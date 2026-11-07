"""公网隧道只开放安装页：从 Cloudflare 隧道进来的请求，安装页以外一律 404；Tailscale / 本机直连不受影响。"""
from __future__ import annotations

from email.message import Message

from pivis_health.web import tunnel_blocked


def _h(**kv):
    m = Message()
    for k, v in kv.items():
        m[k.replace("_", "-")] = v
    return m


TUNNEL = dict(Host="abc-def.trycloudflare.com", Cf_Ray="8f1a2b3c4d5e6f70-SJC", Cf_Connecting_Ip="203.0.113.7")
TAILNET = dict(Host="100.64.0.1:8943")


def test_tunnel_only_install():
    h = _h(**TUNNEL)
    for ok in ("/install", "/install/", "/install/manifest.plist", "/install/PivisHealth.ipa", "/install/?x=1"):
        assert not tunnel_blocked(h, ok), ok
    for bad in ("/api/chat?limit=20", "/api/v3/status", "/api/v3/todo/t1", "/v2", "/", "/media/a.m4a",
                "/installer", "/api/v3/app-version", "/api/v3/widget"):
        assert tunnel_blocked(h, bad), bad


def test_header_only_or_host_only_still_counts_as_tunnel():
    assert tunnel_blocked(_h(Host="example.org", Cf_Ray="x"), "/api/chat")
    assert tunnel_blocked(_h(Host="abc.trycloudflare.com"), "/api/chat")


def test_direct_access_unchanged():
    h = _h(**TAILNET)
    for p in ("/api/chat", "/api/v3/status", "/install/", "/"):
        assert not tunnel_blocked(h, p)


# ---- DSH 令牌只给本机和带设备密钥的 App
from dataclasses import replace  # noqa: E402

from pivis_health.config import Config  # noqa: E402
from pivis_health.web import app_trusted  # noqa: E402


def test_dsh_token_needs_loopback_or_app_key():
    keyed = replace(Config(), app_key="k-123")
    assert app_trusted(keyed, "127.0.0.1", {}) and app_trusted(keyed, "::1", {})
    assert app_trusted(keyed, "100.64.0.9", {"X-Pivis-Key": "k-123"})
    assert not app_trusted(keyed, "100.64.0.9", {})
    assert not app_trusted(keyed, "100.64.0.9", {"X-Pivis-Key": "wrong"})
    unkeyed = Config()
    assert not app_trusted(unkeyed, "100.64.0.9", {"X-Pivis-Key": ""})
    assert app_trusted(unkeyed, "127.0.0.1", {})


def test_app_key_never_in_repr():
    assert "k-123" not in repr(replace(Config(), app_key="k-123"))
