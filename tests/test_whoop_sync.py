"""WHOOP 同步：假 WHOOP API（本机 HTTP 服务，合成数据），不联网、不碰真实令牌。"""
from __future__ import annotations

import json
import socket
import stat
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from pivis_health import whoop as whoop_mod
from pivis_health import whoop_sync as ws

NOW = datetime(2026, 11, 5, 13, 30, tzinfo=timezone.utc)  # 北京 21:30，非静默时段
CID, SECRET = "test-client-id", "test-client-secret"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _records(now: datetime, days: int = 30) -> dict[str, list[dict]]:
    """合成 30 天数据（多于 14 天窗口），每天 1 次睡眠/恢复/周期 + 每天 2 次运动 → 触发分页。"""
    out: dict[str, list[dict]] = {"recovery": [], "sleep": [], "cycle": [], "workout": []}
    for back in range(days):
        night = (now - timedelta(days=back + 1)).replace(hour=15, minute=20, second=0, microsecond=0)  # 北京 23:20
        sid = f"sleep-{back}"
        end = night + timedelta(hours=7, minutes=40)
        out["sleep"].append({"id": sid, "cycle_id": 1000 + back, "start": _iso(night), "end": _iso(end),
                             "timezone_offset": "+08:00", "nap": False, "score_state": "SCORED",
                             "created_at": _iso(end), "updated_at": _iso(end),
                             "score": {"stage_summary": {"total_light_sleep_time_milli": 3 * 3_600_000,
                                                         "total_slow_wave_sleep_time_milli": 3_600_000,
                                                         "total_rem_sleep_time_milli": 2 * 3_600_000},
                                       "sleep_needed": {"baseline_milli": 8 * 3_600_000}}})
        out["recovery"].append({"cycle_id": 1000 + back, "sleep_id": sid, "score_state": "SCORED",
                                "created_at": _iso(end + timedelta(minutes=20)),
                                "updated_at": _iso(end + timedelta(minutes=20)),
                                "score": {"recovery_score": 50.0 + back, "hrv_rmssd_milli": 40.0 + back,
                                          "resting_heart_rate": 55.0, "user_calibrating": False}})
        out["cycle"].append({"id": 1000 + back, "start": _iso(end), "end": _iso(end + timedelta(days=1)),
                             "timezone_offset": "+08:00", "score_state": "SCORED", "step_count": 5000,
                             "created_at": _iso(end), "updated_at": _iso(end),
                             "score": {"strain": 9.5, "kilojoule": 8000.0}})
        for k in range(2):
            ws_start = end + timedelta(hours=10 + k)
            out["workout"].append({"id": f"w-{back}-{k}", "start": _iso(ws_start),
                                   "end": _iso(ws_start + timedelta(minutes=30)), "score_state": "SCORED",
                                   "created_at": _iso(ws_start), "updated_at": _iso(ws_start),
                                   "sport_name": "walking", "score": {"strain": 4.0}})
    return out


class FakeWhoop:
    """最小 WHOOP v2：/oauth/oauth2/{auth,token} + 四个集合，含分页、刷新令牌轮换、可注入 429/401/500。"""

    def __init__(self, now: datetime) -> None:
        self.data = _records(now)
        self.access: set[str] = set()
        self.refresh: set[str] = set()
        self.codes: dict[str, str] = {}  # code -> redirect_uri
        self.n = 0
        self.log: list[tuple[str, str]] = []
        self.token_forms: list[dict] = []
        self.fail_once: dict[str, int] = {}  # path -> status（429/401）
        self.fail_always: dict[str, int] = {}
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                return

            def _send(self, status: int, body: dict | None = None, headers: dict | None = None):
                raw = json.dumps(body or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                fake.log.append(("GET", u.path))
                if u.path == "/oauth/oauth2/auth":
                    # 模拟老大在浏览器里登录并同意 → 302 回本机回调
                    assert q["client_id"] == CID and "offline" in q["scope"].split()
                    code = fake._new("code")
                    fake.codes[code] = q["redirect_uri"]
                    loc = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})
                    self.send_response(302)
                    self.send_header("Location", loc)
                    self.end_headers()
                    return
                name = {v: k for k, v in ws.COLLECTIONS.items()}.get(u.path)
                if not name:
                    return self._send(404, {"error": "not found"})
                token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                if token not in fake.access:
                    return self._send(401, {"error": "unauthorized"})
                if u.path in fake.fail_always:
                    return self._send(fake.fail_always[u.path], {"error": "boom"})
                if u.path in fake.fail_once:
                    status = fake.fail_once.pop(u.path)
                    if status == 401:
                        fake.access.discard(token)
                    return self._send(status, {"error": "injected"}, {"Retry-After": "7"} if status == 429 else None)
                limit = int(q.get("limit", 10))
                assert limit <= 25
                start = datetime.fromisoformat(q["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(q["end"].replace("Z", "+00:00"))
                key = "created_at" if name == "recovery" else "start"
                rows = [r for r in fake.data[name]
                        if start <= datetime.fromisoformat(r[key].replace("Z", "+00:00")) < end]
                rows.sort(key=lambda r: r[key], reverse=True)  # WHOOP：新的在前
                off = int(q.get("nextToken") or 0)
                page = rows[off:off + limit]
                nxt = str(off + limit) if off + limit < len(rows) else None
                return self._send(200, {"records": page, "next_token": nxt})

            def do_POST(self):  # noqa: N802
                u = urllib.parse.urlparse(self.path)
                fake.log.append(("POST", u.path))
                if u.path != "/oauth/oauth2/token":
                    return self._send(404)
                length = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                fake.token_forms.append(form)
                if form.get("client_id") != CID or form.get("client_secret") != SECRET:
                    return self._send(401, {"error": "invalid_client"})
                with fake.lock:
                    if form.get("grant_type") == "authorization_code":
                        if fake.codes.pop(form.get("code"), None) != form.get("redirect_uri"):
                            return self._send(400, {"error": "invalid_grant"})
                    elif form.get("grant_type") == "refresh_token":
                        if form.get("refresh_token") not in fake.refresh:
                            return self._send(400, {"error": "invalid_grant"})
                        fake.refresh.discard(form["refresh_token"])  # 轮换：旧的立即作废
                        fake.access.clear()
                    else:
                        return self._send(400, {"error": "unsupported_grant_type"})
                    acc, ref = fake._new("acc"), fake._new("ref")
                    fake.access.add(acc)
                    fake.refresh.add(ref)
                return self._send(200, {"access_token": acc, "refresh_token": ref, "expires_in": 3600,
                                        "scope": ws.SCOPES, "token_type": "bearer"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _new(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}-{self.n}"

    def gets(self, path: str) -> int:
        return sum(1 for m, p in self.log if m == "GET" and p == path)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fake():
    f = FakeWhoop(NOW)
    yield f
    f.close()


@pytest.fixture()
def cfg(tmp_path):
    return SimpleNamespace(whoop_snapshot=tmp_path / "snap" / "whoop-snapshot.json",
                           whoop_auth_dir=tmp_path / "auth", data_dir=tmp_path / "runtime",
                           timezone="Asia/Shanghai")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _browser(url: str) -> None:
    """代替老大的浏览器：后台线程打开授权页，跟随 302 到本机回调。"""
    threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=10).read(), daemon=True).start()


def _authorise(cfg, fake, **kw):
    redirect = f"http://127.0.0.1:{_free_port()}/callback"
    return ws.authorise(cfg, client_id=CID, client_secret=SECRET, redirect_uri=redirect,
                        open_browser=_browser, timeout=15, endpoints=ws.Endpoints(fake.base),
                        say=lambda _m: None, sync_kwargs={"now": NOW, "sleep": lambda _s: None}, **kw)


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _seed_tokens(cfg, fake, *, expired: bool = False) -> None:
    acc, ref = "acc-seed", "ref-seed"
    fake.access.add(acc)
    fake.refresh.add(ref)
    ws.write_private_json(Path(cfg.whoop_auth_dir) / "client.json",
                          {"client_id": CID, "client_secret": SECRET, "redirect_uri": ws.DEFAULT_REDIRECT})
    ws.write_private_json(Path(cfg.whoop_auth_dir) / "tokens.json",
                          {"access_token": acc, "refresh_token": ref,
                           "expires_at": (0 if expired else 4_000_000_000)})


# ---------------------------------------------------------------------------


def test_authorise_loopback_then_first_sync(cfg, fake):
    out = _authorise(cfg, fake)
    assert out["ok"] and out["authorised"]
    auth = Path(cfg.whoop_auth_dir)
    assert _mode(auth) == 0o700
    assert _mode(auth / "client.json") == 0o600 and _mode(auth / "tokens.json") == 0o600
    tok = json.loads((auth / "tokens.json").read_text())
    assert tok["refresh_token"] in fake.refresh and tok["access_token"] in fake.access
    # 授权结果里不能带任何密钥或令牌
    blob = json.dumps(out)
    assert SECRET not in blob and tok["refresh_token"] not in blob and tok["access_token"] not in blob
    first = out["first_sync"]
    assert first["ok"] and first["pagination_complete"]
    assert first["counts"] == {"recovery": 14, "sleep": 14, "cycle": 14, "workout": 28}


def test_snapshot_schema_and_reader_roundtrip(cfg, fake):
    _seed_tokens(cfg, fake)
    out = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    snap_path = Path(cfg.whoop_snapshot)
    assert _mode(snap_path) == 0o600
    snap = json.loads(snap_path.read_text())
    assert list(snap) == ["schema_version", "source", "window_start_utc", "window_end_utc",
                          "pagination_complete", "coverage_warning", "collections"]
    assert snap["schema_version"] == 1 and snap["source"] == "whoop"
    assert set(snap["collections"]) == {"recovery", "sleep", "cycle", "workout"}
    assert datetime.fromisoformat(snap["window_end_utc"]) == NOW
    assert datetime.fromisoformat(snap["window_start_utc"]) == NOW - timedelta(days=14)
    # 28 条运动 > 25 → 至少两页；记录不重复
    assert fake.gets("/developer/v2/activity/workout") == 2
    ids = [w["id"] for w in snap["collections"]["workout"]]
    assert len(ids) == len(set(ids)) == 28
    # whoop.py 原样能读：最近一晚的 HRV 是合成数据里 back=0 那晚
    view = whoop_mod.load_snapshot(snap_path)
    rec = whoop_mod.recovery_by_night(view, "Asia/Shanghai")
    last = max(rec)
    assert last.isoformat() == "2026-11-04" and rec[last]["hrv_rmssd"] == 40.0
    assert out["latest_recovery_date"] == "2026-11-05" and out["hrv_rmssd_ms"] == 40.0   # 11-04 那晚 → 11-05 早上的恢复
    assert not list(snap_path.parent.glob(".*.tmp"))  # 原子写，没有残留临时文件


def test_expired_access_token_refreshes_and_rotates(cfg, fake):
    _seed_tokens(cfg, fake, expired=True)
    out = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert out["ok"] and out["token_refreshed"]
    tok = json.loads((Path(cfg.whoop_auth_dir) / "tokens.json").read_text())
    assert tok["refresh_token"] != "ref-seed" and "ref-seed" not in fake.refresh  # 旧的已作废
    assert tok["refresh_token"] in fake.refresh
    refresh_forms = [f for f in fake.token_forms if f["grant_type"] == "refresh_token"]
    assert len(refresh_forms) == 1 and refresh_forms[0]["scope"] == "offline"
    # 第二次：令牌还新，不应再刷新
    out2 = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert out2["ok"] and not out2["token_refreshed"]


def test_401_mid_sync_refreshes_once(cfg, fake):
    _seed_tokens(cfg, fake)
    fake.fail_once["/developer/v2/activity/sleep"] = 401
    out = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert out["ok"] and out["token_refreshed"] and out["counts"]["sleep"] == 14


def test_429_waits_retry_after(cfg, fake):
    _seed_tokens(cfg, fake)
    fake.fail_once["/developer/v2/cycle"] = 429
    waits: list[float] = []
    out = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=waits.append)
    assert out["ok"] and out["counts"]["cycle"] == 14
    assert 7.0 in waits


def test_api_failure_keeps_old_snapshot_and_records_error(cfg, fake):
    _seed_tokens(cfg, fake)
    old = {"schema_version": 1, "window_end_utc": "2026-11-01T00:00:00+00:00", "collections": {}}
    ws.write_private_json(Path(cfg.whoop_snapshot), old)
    fake.fail_always["/developer/v2/activity/workout"] = 500
    with pytest.raises(ws.ApiError):
        ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert json.loads(Path(cfg.whoop_snapshot).read_text()) == old
    status = json.loads((Path(cfg.data_dir) / ws.STATUS_FILE).read_text())
    assert status["ok"] is False and "500" in status["error"]
    f = ws.freshness(cfg, NOW)
    assert f["stale"] and f["last_attempt"]["ok"] is False


def test_revoked_refresh_token_needs_reauth(cfg, fake):
    _seed_tokens(cfg, fake, expired=True)
    fake.refresh.clear()  # WHOOP 那边授权已失效
    with pytest.raises(ws.NotAuthorised) as exc:
        ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert exc.value.exit_code == 3 and "whoop-auth" in str(exc.value)
    assert not Path(cfg.whoop_snapshot).exists()


def test_no_tokens_is_not_authorised(cfg, fake):
    with pytest.raises(ws.NotAuthorised):
        ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW)
    assert fake.log == []


def test_syncs_at_night_too(cfg, fake):
    """以前北京 02:00–09:00 不同步，醒来那一刻的恢复要等到 9 点后才进页面；现在夜里照常拉。"""
    _seed_tokens(cfg, fake)
    night = datetime(2026, 11, 5, 23, 50, tzinfo=timezone.utc)  # 北京 07:50，刚醒
    out = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=night, sleep=lambda _s: None)
    assert out["ok"] and "skipped" not in out and fake.log


@pytest.mark.parametrize("age_min, stale", [(30, False), (59, False), (61, True), (6 * 60, True)])
def test_freshness_one_hour(cfg, age_min, stale):
    now = datetime(2026, 11, 5, 23, 50, tzinfo=timezone.utc)
    end = now - timedelta(minutes=age_min)
    ws.write_private_json(Path(cfg.whoop_snapshot), {"window_end_utc": end.isoformat(), "collections": {}})
    assert ws.freshness(cfg, now)["stale"] is stale


def test_new_scored_records_are_detected(cfg, fake):
    """有新的已评分恢复 / 睡眠 / 训练才算「有新数据」（当天进行中的周期 strain 每次都变，不算）。"""
    _seed_tokens(cfg, fake)
    first = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert first["new_records"] > 0
    again = ws.sync(cfg, endpoints=ws.Endpoints(fake.base), now=NOW, sleep=lambda _s: None)
    assert again["new_records"] == 0 and "republish" not in again


def test_missing_snapshot_is_stale(cfg):
    f = ws.freshness(cfg, NOW)
    assert f["present"] is False and f["stale"] is True


def test_paste_mode_rejects_wrong_state(cfg, fake):
    with pytest.raises(ws.NotAuthorised, match="state"):
        ws.authorise(cfg, client_id=CID, client_secret=SECRET, paste=True, open_browser=lambda _u: None,
                     endpoints=ws.Endpoints(fake.base), say=lambda _m: None,
                     ask=lambda _p: "http://127.0.0.1:8765/callback?code=x&state=WRONGxxx")
    assert not (Path(cfg.whoop_auth_dir) / "tokens.json").exists()


def test_paste_mode_happy_path(cfg, fake):
    seen: dict = {}

    def browser(url: str) -> None:
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        assert len(q["state"]) == 8 and q["response_type"] == "code"
        code = fake._new("code")
        fake.codes[code] = q["redirect_uri"]
        seen["url"] = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})

    out = ws.authorise(cfg, client_id=CID, client_secret=SECRET, paste=True, open_browser=browser,
                       endpoints=ws.Endpoints(fake.base), say=lambda _m: None, ask=lambda _p: seen["url"],
                       sync_kwargs={"now": NOW, "sleep": lambda _s: None})
    assert out["authorised"] and out["first_sync"]["ok"]


def test_wrong_client_secret_is_not_authorised(cfg, fake):
    with pytest.raises(ws.NotAuthorised):
        ws.authorise(cfg, client_id=CID, client_secret="wrong", redirect_uri=f"http://127.0.0.1:{_free_port()}/callback",
                     open_browser=_browser, timeout=15, endpoints=ws.Endpoints(fake.base), say=lambda _m: None)
    assert not (Path(cfg.whoop_auth_dir) / "tokens.json").exists()


def test_non_loopback_redirect_requires_paste(cfg, fake):
    with pytest.raises(ws.WhoopError, match="--paste"):
        ws.authorise(cfg, client_id=CID, client_secret=SECRET, redirect_uri="https://example.org/cb",
                     endpoints=ws.Endpoints(fake.base), say=lambda _m: None)


def test_cli_status_and_sync_exit_codes(tmp_path, monkeypatch, capsys):
    from pivis_health import cli

    monkeypatch.setenv("PIVIS_HEALTH_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setenv("PIVIS_HEALTH_WHOOP_SNAPSHOT", str(tmp_path / "w.json"))
    monkeypatch.setenv("PIVIS_WHOOP_AUTH_DIR", str(tmp_path / "auth"))
    monkeypatch.setenv("PIVIS_HEALTH_DATA_DIR", str(tmp_path / "rt"))
    assert cli.main(["whoop-status"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["stale"] is True and out["authorised"] is False
    assert cli.main(["whoop-sync", "--force"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["error"] == "not_authorised"


def test_long_running_tools_pick_up_new_snapshot(tools_env, tmp_path):
    """serve 进程里的 HealthTools 常驻：同步换了文件，下一次读就要看到新数据。"""
    import dataclasses

    from pivis_health.tools import HealthTools

    snap_path = tmp_path / "live" / "whoop-snapshot.json"
    tools = HealthTools(dataclasses.replace(tools_env.cfg, whoop_snapshot=snap_path))
    assert tools._whoop is None
    base = {"schema_version": 1, "source": "whoop", "window_start_utc": "a", "window_end_utc": "b",
            "pagination_complete": True, "coverage_warning": "", "collections": {}}
    ws.write_private_json(snap_path, {**base, "collections": {"recovery": [{"cycle_id": 1}]}})
    assert len(tools._whoop["recovery"]) == 1
    ws.write_private_json(snap_path, {**base, "collections": {"recovery": [{"cycle_id": 1}, {"cycle_id": 2}]}})
    assert len(tools._whoop["recovery"]) == 2
    snap_path.unlink()
    assert tools._whoop is None
