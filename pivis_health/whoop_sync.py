"""WHOOP 官方 API v2 同步：OAuth2（刷新令牌轮换）→ 14 天滚动快照。

快照格式与旧 Hermes 同步一致（whoop.py 只读解析，字段不变）：
  schema_version, source, window_start_utc, window_end_utc, pagination_complete,
  coverage_warning, collections{recovery, sleep, cycle, workout}

纪律：
- 应用凭据（client id/secret）和令牌只放 cfg.whoop_auth_dir（默认 ~/.config/pivis-health/whoop，
  目录 0700、文件 0600），永不进仓库；client secret 只从环境变量或本机终端隐藏输入读取，不走命令行参数。
- 老大自己在浏览器里登录 WHOOP；本模块只在 127.0.0.1 上等回调。
- 刷新令牌一用就作废（轮换）：整个同步持文件锁，新令牌先落盘再拉数据。
- 任何一类拉取失败都不写快照（旧快照原样保留），并把失败写进状态文件 —— 不允许假 PASS。
- launchd 每 15 分钟一次，夜里也拉（同步不发消息）；超过 1 小时没成功即 stale。
- 有新的已评分恢复 / 睡眠 / 训练：马上重排页面（v3.republish_async）。
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import getpass
import json
import os
import secrets
import socket
import string
import sys
import tempfile
import time as _time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
SOURCE = "whoop"
COVERAGE_WARNING = "API分页完整不等于每天有数据；缺失不代表正常或没有运动。"
SCOPES = "offline read:recovery read:cycles read:workout read:sleep"
DEFAULT_REDIRECT = "http://127.0.0.1:8765/callback"
WINDOW_DAYS = 14
# 不再有静默时段：同步不发任何消息，夜里照常拉，醒来那一刻的恢复 / 睡眠才能最快进页面。
# （以前 02:00–09:00 不同步，是因为老的 Hermes 任务每次同步都往飞书群发消息。）
QUIET_HOURS: tuple[int, int] | None = None
STALE_HOURS = 1.0  # launchd 每 15 分钟一次；超过 1 小时没成功就是断了
PAGE_LIMIT = 25  # WHOOP v2 上限
MAX_PAGES = 200
USER_AGENT = "pivis-health-whoop-sync/1"
# 读取顺序与旧快照无关；whoop.py 按 key 取
COLLECTIONS: dict[str, str] = {
    "recovery": "/developer/v2/recovery",
    "sleep": "/developer/v2/activity/sleep",
    "cycle": "/developer/v2/cycle",
    "workout": "/developer/v2/activity/workout",
}
STATUS_FILE = "whoop_sync_status.json"


@dataclass(frozen=True)
class Endpoints:
    api_base: str = "https://api.prod.whoop.com"

    @property
    def auth_url(self) -> str:
        return self.api_base + "/oauth/oauth2/auth"

    @property
    def token_url(self) -> str:
        return self.api_base + "/oauth/oauth2/token"


class WhoopError(RuntimeError):
    code = "whoop_error"
    exit_code = 1


class NotAuthorised(WhoopError):
    """没有可用令牌，或刷新令牌被 WHOOP 拒绝：需要老大重新跑 whoop-auth。"""
    code = "not_authorised"
    exit_code = 3


class ApiError(WhoopError):
    code = "api_error"


# ---------------------------------------------------------------------------
# 私有文件
# ---------------------------------------------------------------------------

def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def write_private_json(path: Path, obj: Any) -> None:
    """原子写入（同目录临时文件 → fsync → rename），文件权限 0600。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _client_path(auth_dir: Path) -> Path:
    return Path(auth_dir) / "client.json"


def _tokens_path(auth_dir: Path) -> Path:
    return Path(auth_dir) / "tokens.json"


@contextlib.contextmanager
def _locked(auth_dir: Path, wait_s: float = 120.0) -> Iterator[None]:
    """同一时刻只允许一个进程碰令牌：刷新令牌是一次性的，并发刷新会把授权弄丢。"""
    _private_dir(Path(auth_dir))
    lock_path = Path(auth_dir) / "sync.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    deadline = _time.monotonic() + wait_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _time.monotonic() > deadline:
                    raise WhoopError("另一个 WHOOP 同步正在进行（锁等待超时）")
                _time.sleep(0.5)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http(method: str, url: str, *, data: bytes | None = None,
          headers: dict | None = None, timeout: float = 30.0) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        body = b""
        with contextlib.suppress(Exception):
            body = exc.read() or b""
        hdrs = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        return exc.code, hdrs, body


def _json_body(raw: bytes) -> dict:
    try:
        out = json.loads(raw.decode("utf-8") or "{}")
        return out if isinstance(out, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _short(raw: bytes, n: int = 160) -> str:
    return raw.decode("utf-8", "replace").strip().replace("\n", " ")[:n]


def _api_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class WhoopClient:
    def __init__(self, auth_dir: Path, endpoints: Endpoints = Endpoints(), *,
                 sleep: Callable[[float], None] = _time.sleep,
                 clock: Callable[[], float] = _time.time, max_retries: int = 4) -> None:
        self.auth_dir = Path(auth_dir)
        self.ep = endpoints
        self.sleep = sleep
        self.clock = clock
        self.max_retries = max_retries
        self.refreshed = 0

    # -- 凭据 ---------------------------------------------------------------
    def client(self) -> dict:
        c = _read_json(_client_path(self.auth_dir))
        if not c or not c.get("client_id") or not c.get("client_secret"):
            raise NotAuthorised("还没有 WHOOP 应用凭据：请老大在终端运行 ./pivis-health whoop-auth")
        return c

    def tokens(self) -> dict:
        t = _read_json(_tokens_path(self.auth_dir))
        if not t or not t.get("refresh_token"):
            raise NotAuthorised("还没有 WHOOP 授权令牌：请老大在终端运行 ./pivis-health whoop-auth")
        return t

    def _token_request(self, form: dict) -> dict:
        """POST token 端点。默认 client_secret_post；WHOOP 若回 invalid_client 再试一次 HTTP Basic。"""
        c = self.client()
        attempts = [
            ({**form, "client_id": c["client_id"], "client_secret": c["client_secret"]}, {}),
            (form, {"Authorization": "Basic " + base64.b64encode(
                f"{urllib.parse.quote(c['client_id'])}:{urllib.parse.quote(c['client_secret'])}".encode()).decode()}),
        ]
        last = ""
        for body, extra in attempts:
            for retry in range(3):
                try:
                    status, _h, raw = _http("POST", self.ep.token_url,
                                            data=urllib.parse.urlencode(body).encode(),
                                            headers={"Content-Type": "application/x-www-form-urlencoded", **extra})
                except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
                    last = f"网络错误：{exc}"
                    self.sleep(2 ** retry)
                    continue
                if status >= 500:
                    last = f"HTTP {status}: {_short(raw)}"
                    self.sleep(2 ** retry)
                    continue
                payload = _json_body(raw)
                if status == 200 and payload.get("access_token"):
                    return payload
                err = str(payload.get("error") or "")
                if status == 401 and err == "invalid_client":
                    last = "invalid_client"
                    break  # 换 Basic 认证再试
                if err in ("invalid_grant", "invalid_client", "unauthorized_client") or status in (400, 401, 403):
                    raise NotAuthorised(
                        f"WHOOP 拒绝令牌请求（{err or status}）：请老大在终端重新运行 ./pivis-health whoop-auth")
                raise ApiError(f"令牌请求失败 HTTP {status}: {_short(raw)}")
            else:
                raise ApiError(f"令牌请求失败：{last}")
        raise NotAuthorised(f"WHOOP 不认这组应用凭据（{last}）：检查 client id/secret 后重新运行 whoop-auth")

    def save_tokens(self, payload: dict, prev: dict | None = None) -> dict:
        now = self.clock()
        refresh = payload.get("refresh_token") or (prev or {}).get("refresh_token")
        if not refresh:
            raise NotAuthorised("WHOOP 没有返回 refresh token（授权时必须包含 offline 权限）")
        tok = {
            "access_token": payload["access_token"],
            "refresh_token": refresh,
            "token_type": payload.get("token_type") or "bearer",
            "scope": payload.get("scope"),
            "expires_at": now + int(payload.get("expires_in") or 3600),
            "obtained_at": (prev or {}).get("obtained_at") or now,
            "refreshed_at": now,
        }
        write_private_json(_tokens_path(self.auth_dir), tok)
        return tok

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        payload = self._token_request({"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": redirect_uri})
        return self.save_tokens(payload)

    def refresh(self) -> dict:
        prev = self.tokens()
        payload = self._token_request({"grant_type": "refresh_token",
                                       "refresh_token": prev["refresh_token"], "scope": "offline"})
        self.refreshed += 1
        return self.save_tokens(payload, prev)  # 轮换：新 refresh token 立刻落盘

    def access_token(self) -> str:
        t = self.tokens()
        if not t.get("access_token") or float(t.get("expires_at") or 0) - self.clock() < 300:
            t = self.refresh()
        return t["access_token"]

    # -- 数据 ---------------------------------------------------------------
    def get(self, path: str, params: dict) -> dict:
        url = self.ep.api_base + path + "?" + urllib.parse.urlencode(params)
        refreshed_here = False
        last = ""
        for attempt in range(self.max_retries + 1):
            token = self.access_token()
            try:
                status, headers, raw = _http("GET", url, headers={"Authorization": f"Bearer {token}"})
            except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
                last = f"网络错误：{exc}"
                self.sleep(min(2 ** attempt, 30))
                continue
            if status == 200:
                return _json_body(raw)
            if status == 401 and not refreshed_here:
                refreshed_here = True
                self.refresh()
                continue
            if status == 429:
                try:
                    wait = float(headers.get("retry-after") or 0)
                except ValueError:
                    wait = 0.0
                last = "HTTP 429（限流）"
                self.sleep(min(max(wait, 2 ** attempt), 60))
                continue
            if status >= 500:
                last = f"HTTP {status}: {_short(raw)}"
                self.sleep(min(2 ** attempt, 30))
                continue
            if status in (401, 403):
                raise NotAuthorised(f"WHOOP 拒绝访问 {path}（HTTP {status}）：请老大重新运行 whoop-auth")
            raise ApiError(f"GET {path} 失败 HTTP {status}: {_short(raw)}")
        raise ApiError(f"GET {path} 重试 {self.max_retries} 次仍失败：{last}")

    def fetch_collection(self, name: str, start: datetime, end: datetime) -> tuple[list[dict], bool]:
        """完整分页；返回（记录，分页是否完整）。按 id（recovery 用 cycle_id）去重。"""
        path = COLLECTIONS[name]
        params: dict[str, Any] = {"limit": PAGE_LIMIT, "start": _api_ts(start), "end": _api_ts(end)}
        out: list[dict] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        for _ in range(MAX_PAGES):
            page = self.get(path, params)
            records = page.get("records")
            if not isinstance(records, list):
                raise ApiError(f"{name} 返回格式不对（没有 records）")
            for rec in records:
                key = str(rec.get("id") if rec.get("id") is not None else rec.get("cycle_id"))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                out.append(rec)
            nxt = page.get("next_token") or page.get("nextToken")
            if not nxt:
                return out, True
            if nxt in seen_tokens:
                return out, False  # 分页回环：数据可能不全，照实标记
            seen_tokens.add(nxt)
            params = {**params, "nextToken": nxt}
        return out, False


# ---------------------------------------------------------------------------
# 静默时段与新鲜度
# ---------------------------------------------------------------------------

def in_quiet_hours(now: datetime, tz_name: str) -> bool:
    if not QUIET_HOURS:
        return False
    h = now.astimezone(ZoneInfo(tz_name)).hour
    return QUIET_HOURS[0] <= h < QUIET_HOURS[1]


def eligible_hours(since: datetime, until: datetime, tz_name: str) -> float:
    """since→until 之间扣掉静默时段后的小时数（新鲜度只按"本该同步"的时间算）。"""
    if until <= since:
        return 0.0
    total = (until - since).total_seconds()
    if total > 400 * 86400 or not QUIET_HOURS:
        return total / 3600
    tz = ZoneInfo(tz_name)
    d: date = since.astimezone(tz).date() - timedelta(days=1)
    last: date = until.astimezone(tz).date()
    while d <= last:
        qs = datetime.combine(d, time(QUIET_HOURS[0]), tzinfo=tz)
        qe = datetime.combine(d, time(QUIET_HOURS[1]), tzinfo=tz)
        overlap = (min(until, qe) - max(since, qs)).total_seconds()
        if overlap > 0:
            total -= overlap
        d += timedelta(days=1)
    return max(total, 0.0) / 3600


def _parse_utc(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness(cfg, now: datetime | None = None) -> dict:
    """快照新鲜度（不联网、不碰令牌）。stale = 超过 STALE_HOURS 没成功同步。"""
    now = now or datetime.now(timezone.utc)
    path = Path(cfg.whoop_snapshot)
    snap = None
    with contextlib.suppress(Exception):
        snap = _read_json(path)
    end = _parse_utc((snap or {}).get("window_end_utc"))
    age = eligible = None
    if end:
        age = round((now - end).total_seconds() / 3600, 2)
        eligible = round(eligible_hours(end, now, cfg.timezone), 2)
    status = _read_json(Path(cfg.data_dir) / STATUS_FILE) or {}
    auth_dir = Path(getattr(cfg, "whoop_auth_dir", "") or "")
    return {
        "snapshot": str(path),
        "present": snap is not None,
        "window_end_utc": (snap or {}).get("window_end_utc"),
        "age_hours": age,
        "age_hours_outside_quiet": eligible,
        "stale_after_hours": STALE_HOURS,
        "stale": eligible is None or eligible > STALE_HOURS,
        "quiet_hours_now": in_quiet_hours(now, cfg.timezone),
        "authorised": bool(auth_dir and _tokens_path(auth_dir).exists()),
        "last_attempt": {k: status.get(k) for k in ("at_utc", "ok", "error", "error_code") if k in status} or None,
        "last_success_utc": status.get("last_success_utc"),
    }


def _write_status(cfg, **fields: Any) -> None:
    path = Path(cfg.data_dir) / STATUS_FILE
    prev = _read_json(path) or {}
    if fields.get("ok"):
        fields["last_success_utc"] = fields.get("at_utc")
    else:
        fields["last_success_utc"] = prev.get("last_success_utc")
    with contextlib.suppress(OSError):
        write_private_json(path, fields)


def _latest_summary(snap: dict, tz_name: str) -> dict:
    """同步结果里带上最近一晚的恢复数据（只是回显 WHOOP 原值，方便核对）。"""
    from . import whoop as whoop_mod

    rec = whoop_mod.recovery_by_day(snap.get("collections") or {}, tz_name)
    if not rec:
        return {"latest_recovery_date": None}
    day = max(rec)
    r = rec[day]
    return {"latest_recovery_date": day.isoformat(), "recovery_score": r.get("recovery_score"),
            "hrv_rmssd_ms": r.get("hrv_rmssd"), "resting_heart_rate": r.get("resting_heart_rate"),
            "score_state": r.get("score_state")}


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

def sync(cfg, *, endpoints: Endpoints = Endpoints(), now: datetime | None = None,
         days: int = WINDOW_DAYS, force: bool = False, republish: bool = False,
         sleep: Callable[[float], None] = _time.sleep) -> dict:
    now = now or datetime.now(timezone.utc)
    if not force and in_quiet_hours(now, cfg.timezone):
        return {"ok": True, "skipped": "quiet_hours", **_fresh_brief(cfg, now)}
    at = now.isoformat()
    before = _record_sigs(_read_json(Path(cfg.whoop_snapshot)))
    try:
        with _locked(cfg.whoop_auth_dir):
            client = WhoopClient(cfg.whoop_auth_dir, endpoints, sleep=sleep)
            start = now - timedelta(days=days)
            cols: dict[str, list] = {}
            complete = True
            for name in COLLECTIONS:
                recs, ok = client.fetch_collection(name, start, now)
                cols[name] = recs
                complete = complete and ok
            snap = {
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE,
                "window_start_utc": start.isoformat(),
                "window_end_utc": now.isoformat(),
                "pagination_complete": complete,
                "coverage_warning": COVERAGE_WARNING,
                "collections": {"recovery": cols["recovery"], "sleep": cols["sleep"],
                                "cycle": cols["cycle"], "workout": cols["workout"]},
            }
            write_private_json(Path(cfg.whoop_snapshot), snap)
    except WhoopError as exc:
        _write_status(cfg, at_utc=at, ok=False, error=str(exc), error_code=exc.code)
        raise
    except Exception as exc:  # noqa: BLE001 —— 任何意外都必须落进状态文件，不能静默
        _write_status(cfg, at_utc=at, ok=False, error=f"{type(exc).__name__}: {exc}", error_code="unexpected")
        raise
    counts = {k: len(v) for k, v in cols.items()}
    _write_status(cfg, at_utc=at, ok=True, counts=counts, pagination_complete=complete)
    out = {"ok": True, "snapshot": str(cfg.whoop_snapshot), "window_start_utc": snap["window_start_utc"],
           "window_end_utc": snap["window_end_utc"], "pagination_complete": complete, "counts": counts,
           "token_refreshed": client.refreshed > 0}
    with contextlib.suppress(Exception):
        out.update(_latest_summary(snap, cfg.timezone))
    if not complete:
        out["warning"] = "分页不完整：数据可能缺页"
    changed = sorted(_record_sigs(snap) - before)
    out["new_records"] = len(changed)
    if changed and republish:
        # 新的恢复 / 睡眠 / 训练进来了：马上重排页面，不等下一个整点节拍（重排自带单实例锁、节流和退避）
        with contextlib.suppress(Exception):
            from . import v3
            out["republish"] = v3.republish_async(cfg)
    return out


def _record_sigs(snap: Optional[dict]) -> set[tuple]:
    """快照里「已评分」的恢复 / 睡眠 / 训练记录的指纹。当天还在进行的周期（strain 每次都在涨）不算，
    免得每 15 分钟都重排一次页面。"""
    cols = (snap or {}).get("collections") or {}
    out: set[tuple] = set()
    for name in ("recovery", "sleep", "workout"):
        for r in cols.get(name) or []:
            if r.get("score_state") != "SCORED":
                continue
            rid = r.get("id") or r.get("sleep_id") or r.get("cycle_id")
            out.add((name, str(rid), str(r.get("updated_at") or "")))
    return out


def _fresh_brief(cfg, now: datetime) -> dict:
    f = freshness(cfg, now)
    return {k: f[k] for k in ("window_end_utc", "age_hours", "age_hours_outside_quiet", "stale")}


# ---------------------------------------------------------------------------
# 一次性授权（老大自己在浏览器登录）
# ---------------------------------------------------------------------------

_DONE_HTML = ("<!doctype html><meta charset='utf-8'><title>P-Health</title>"
              "<body style='font:16px -apple-system;background:#000;color:#fff;padding:48px'>"
              "<p>{msg}</p></body>")


def _make_state() -> str:
    # WHOOP 文档：自己生成的 state 须为 8 个字符
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def build_auth_url(endpoints: Endpoints, client_id: str, redirect_uri: str, state: str) -> str:
    return endpoints.auth_url + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": SCOPES, "state": state})


def _parse_callback(url_or_query: str) -> dict:
    parsed = urllib.parse.urlparse(url_or_query.strip())
    query = parsed.query or (url_or_query.strip().lstrip("?") if "=" in url_or_query and not parsed.scheme else "")
    return {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}


def _wait_for_callback(server: HTTPServer, expected_path: str, timeout: float) -> dict:
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            result.update(params)
            ok = "code" in params
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "WHOOP 授权完成，可以关掉这个页面。" if ok else "WHOOP 授权没有完成，请回到终端看提示。"
            self.wfile.write(_DONE_HTML.format(msg=msg).encode("utf-8"))

        def log_message(self, *_a):  # 不把回调参数打进日志
            return

    server.RequestHandlerClass = Handler
    server.timeout = 1.0
    deadline = _time.monotonic() + timeout
    while not result and _time.monotonic() < deadline:
        server.handle_request()
    return result


def authorise(cfg, *, client_id: str | None = None, client_secret: str | None = None,
              redirect_uri: str | None = None, reset_client: bool = False, paste: bool = False,
              open_browser: Callable[[str], Any] = webbrowser.open, timeout: float = 300.0,
              endpoints: Endpoints = Endpoints(), ask: Callable[[str], str] = input,
              ask_secret: Callable[[str], str] = getpass.getpass,
              say: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True),
              first_sync: bool = True, sync_kwargs: dict | None = None) -> dict:
    auth_dir = _private_dir(Path(cfg.whoop_auth_dir))
    stored = (None if reset_client else _read_json(_client_path(auth_dir))) or {}
    cid = client_id or os.environ.get("WHOOP_CLIENT_ID") or stored.get("client_id")
    if not cid:
        cid = ask("WHOOP 应用 Client ID：").strip()
    secret = client_secret or os.environ.get("WHOOP_CLIENT_SECRET") or stored.get("client_secret")
    if not secret:
        secret = ask_secret("WHOOP 应用 Client Secret（输入不显示）：").strip()
    redirect = redirect_uri or stored.get("redirect_uri") or DEFAULT_REDIRECT
    if not cid or not secret:
        raise NotAuthorised("没有拿到 client id / secret，授权取消")
    target = urllib.parse.urlparse(redirect)
    loopback = target.scheme == "http" and target.hostname in ("127.0.0.1", "localhost")
    if not loopback and not paste:
        raise WhoopError("回调地址不是本机 http://127.0.0.1，请改用 --paste 模式")
    write_private_json(_client_path(auth_dir), {"client_id": cid, "client_secret": secret, "redirect_uri": redirect})

    state = _make_state()
    url = build_auth_url(endpoints, cid, redirect, state)
    say("请在浏览器里登录 WHOOP 并同意授权（这个地址只含应用 id，不含密钥）：")
    say(url)
    if paste:
        with contextlib.suppress(Exception):
            open_browser(url)
        params = _parse_callback(ask("授权后浏览器跳到的完整地址（地址栏里，页面打不开也没关系）："))
    else:
        server = HTTPServer((target.hostname if target.hostname != "localhost" else "127.0.0.1",
                             target.port or 80), BaseHTTPRequestHandler)
        try:
            with contextlib.suppress(Exception):
                open_browser(url)
            say(f"正在 {redirect} 等 WHOOP 回调（最多 {int(timeout)} 秒）…")
            params = _wait_for_callback(server, target.path or "/", timeout)
        finally:
            server.server_close()
    if not params:
        raise NotAuthorised("等待 WHOOP 回调超时；可以用 --paste 模式重试")
    if params.get("error"):
        raise NotAuthorised(f"WHOOP 返回授权错误：{params.get('error')} {params.get('error_description', '')}".strip())
    if params.get("state") != state:
        raise NotAuthorised("state 不匹配，回调可能不是这次授权发起的，已拒绝")
    if not params.get("code"):
        raise NotAuthorised("回调里没有授权码")
    with _locked(auth_dir):
        client = WhoopClient(auth_dir, endpoints)
        tok = client.exchange_code(params["code"], redirect)
    out: dict[str, Any] = {"ok": True, "authorised": True, "auth_dir": str(auth_dir),
                           "scope": tok.get("scope"), "redirect_uri": redirect}
    if first_sync:
        out["first_sync"] = sync(cfg, endpoints=endpoints, force=True, **(sync_kwargs or {}))
    return out


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def run_cli(cfg, args) -> tuple[dict, int]:
    """返回（JSON 结果，退出码）。0=正常；1=失败；2=快照过期；3=需要老大重新授权。"""
    try:
        if args.cmd == "whoop-auth":
            out = authorise(cfg, client_id=args.client_id, redirect_uri=args.redirect_uri,
                            reset_client=args.reset_client, paste=args.paste,
                            open_browser=(lambda _u: None) if args.no_browser else webbrowser.open,
                            timeout=args.timeout)
            return out, 0
        if args.cmd == "whoop-sync":
            out = sync(cfg, days=args.days, force=args.force, republish=True)   # 只有真同步（CLI / launchd）才触发重排
            return out, 0
        if args.cmd == "whoop-status":
            out = freshness(cfg)
            return out, 2 if out["stale"] else 0
    except WhoopError as exc:
        return {"ok": False, "error": exc.code, "message": str(exc), **_fresh_brief(cfg, datetime.now(timezone.utc))}, exc.exit_code
    raise ValueError(args.cmd)
