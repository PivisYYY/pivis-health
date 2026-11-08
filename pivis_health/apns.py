"""APNs（Apple Push Notification service）客户端。

纯标准库实现：ES256 JWT 通过 openssl 子进程签名（python3 无 cryptography），
发送用 curl（带 nghttp2，支持 HTTP/2，APNs 必需）。

未配置密钥（config.apns 缺 key_id/key_path）时一切静默 no-op，
守护进程与 web 服务可在无密钥状态下先行部署。
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path
from typing import Any

TEAM_ID_DEFAULT = ""   # 团队 ID 放 config.local.json 的 apns.team_id
BUNDLE_ID_DEFAULT = "com.pivis.health"
JWT_TTL = 3000          # 45 分钟内复用同一 token（APNs 上限 1 小时）
_SANDBOX_HOST = "https://api.development.push.apple.com"
_PROD_HOST = "https://api.push.apple.com"


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class APNS:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.key_id = str(cfg.get("key_id") or "")
        self.key_path = Path(str(cfg.get("key_path") or "")) if cfg.get("key_path") else None
        self.team_id = str(cfg.get("team_id") or TEAM_ID_DEFAULT)
        self.bundle_id = str(cfg.get("bundle_id") or BUNDLE_ID_DEFAULT)
        self.env = str(cfg.get("env") or "development")
        self._token: str | None = None
        self._token_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.team_id and self.key_path and self.key_path.exists())

    def _sign(self, signing_input: bytes) -> bytes:
        """openssl dgst -sha256 -sign 输出 DER 格式 ECDSA 签名，即 APNs 所需格式。"""
        r = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(self.key_path)],
            input=signing_input, capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            raise RuntimeError(f"openssl sign failed: {r.stderr.decode(errors='replace')}")
        return r.stdout

    def jwt(self) -> str:
        now = int(time.time())
        if self._token and now - self._token_at < JWT_TTL:
            return self._token
        header = _b64u(json.dumps({"alg": "ES256", "kid": self.key_id}, separators=(",", ":")).encode())
        claims = _b64u(json.dumps(
            {"iss": self.team_id, "iat": now, "exp": now + 3500},
            separators=(",", ":")).encode())
        signing_input = f"{header}.{claims}".encode()
        sig = _b64u(self._sign(signing_input))
        self._token = f"{signing_input.decode()}.{sig}"
        self._token_at = now
        return self._token

    def send(self, device_token: str, title: str, body: str,
             data: dict[str, Any] | None = None, badge: int | None = None,
             env: str | None = None, aps_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """发一条 alert 推送。返回 {ok, status, reason}。未配置密钥时 ok=False reason=not_configured。"""
        if not self.configured:
            return {"ok": False, "status": 0, "reason": "not_configured"}
        payload: dict[str, Any] = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
        if badge is not None:
            payload["aps"]["badge"] = badge
        if aps_extra:                      # thread-id：同一个对话 / 同一张卡的通知在锁屏上叠成一组
            payload["aps"].update(aps_extra)
        if data:
            for k, v in data.items():
                payload.setdefault(k, v)
        # 令牌是哪个环境就发哪个环境：安装页装的开发签名是 development，TestFlight 装的是 production
        host = _PROD_HOST if (env or self.env) == "production" else _SANDBOX_HOST
        url = f"{host}/3/device/{device_token}"
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        r = subprocess.run(
            [
                "curl", "--http2", "-sS", "-o", "-", "-w", "\n%{http_code}",
                "-X", "POST", url,
                "-H", f"authorization: bearer {self.jwt()}",
                "-H", f"apns-topic: {self.bundle_id}",
                "-H", "apns-push-type: alert",
                "-H", "apns-priority: 10",
                "--data-binary", "@-",
            ],
            input=body_bytes, capture_output=True, timeout=20,
        )
        out = r.stdout.decode(errors="replace")
        status = 0
        try:
            status = int(out.rsplit("\n", 1)[-1].strip())
        except ValueError:
            pass
        resp = out.rsplit("\n", 1)[0].strip()
        reason = ""
        if resp:
            try:
                reason = json.loads(resp).get("reason", "")
            except json.JSONDecodeError:
                reason = resp[:200]
        return {"ok": 200 <= status < 300, "status": status, "reason": reason}
