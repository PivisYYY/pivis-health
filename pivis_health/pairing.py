"""手机配对（build 55）：P-Health 跑在用户自己的电脑上，App 扫这台电脑出的二维码连过来。

二维码里是一条链接：phealth://pair?v=1&n=<电脑名>&h=<地址1,地址2,…>&p=<P-Health 端口>&d=<DSH 端口>&k=<设备密钥>
- 地址按优先顺序：局域网 IPv4、Tailscale（100.64/10）、Bonjour 名（XXX.local）。App 逐个试 /api/v3/hello，先通的用。
- 设备密钥就是服务器的 app_key（所有接口都要它），所以二维码只在本机显示：终端里打印，或只允许本机打开的 /pair 页面。
"""
from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.parse import urlparse

from .vendor.qrcodegen import QrCode

TAILNET = ipaddress.ip_network("100.64.0.0/10")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def computer_name() -> str:
    name = _run(["scutil", "--get", "ComputerName"])
    if not name:
        import socket
        name = socket.gethostname().split(".")[0]
    return name[:40] or "我的电脑"


def hosts() -> list[str]:
    """这台电脑能被手机连到的地址：局域网 IPv4 在前，Tailscale 其次，最后是 Bonjour 名。"""
    lan, tail = [], []
    iface = ""
    for line in _run(["ifconfig"]).splitlines():
        head = re.match(r"^([A-Za-z0-9]+):", line)
        if head:
            iface = head.group(1)
            continue
        m = re.match(r"^\s*inet (\d+\.\d+\.\d+\.\d+)", line)
        if not m:
            continue
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local:
            continue
        if ip in TAILNET:
            tail.append(str(ip))                        # Tailscale（utun 网卡）
        elif ip.is_private and iface.startswith("en"):
            lan.append(str(ip))                         # 只要真实网卡（Wi-Fi / 网线）；虚拟机、容器的网桥手机连不到
    out = lan + tail
    local = _run(["scutil", "--get", "LocalHostName"])
    if local:
        out.append(f"{local}.local")
    seen, uniq = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def dsh_port(cfg) -> int:
    try:
        return int(urlparse(cfg.dsh_web).port or 8960)
    except (ValueError, AttributeError):
        return 8960


def api_port(cfg) -> int:
    return int(getattr(cfg, "api_port", 0) or 8943)


def pair_url(cfg, host_list: list[str] | None = None) -> str:
    if not cfg.app_key:
        raise ValueError("服务器还没有设备密钥（app_key）：先跑 ./pivis-health setup")
    q = {"v": "1", "n": computer_name(), "h": ",".join(host_list if host_list is not None else hosts()),
         "p": str(api_port(cfg)), "d": str(dsh_port(cfg)), "k": cfg.app_key}
    return "phealth://pair?" + urlencode(q, quote_via=quote, safe=",")


def qr(text: str) -> QrCode:
    return QrCode.encode_text(text, QrCode.Ecc.MEDIUM)


def terminal(text: str) -> str:
    """终端里能扫的二维码：两行像素合成一行（▀ ▄ █），白底黑块，留 2 格白边。"""
    q = qr(text)
    n, border = q.get_size(), 2
    rng = range(-border, n + border)

    def dark(x: int, y: int) -> bool:
        return 0 <= x < n and 0 <= y < n and q.get_module(x, y)

    lines = []
    for y in range(-border, n + border, 2):
        row = []
        for x in rng:
            top, bot = dark(x, y), dark(x, y + 1)
            # 终端是深色背景时也要能扫：画「亮」的部分（白块），暗的留空
            row.append(" " if top and bot else "▄" if top else "▀" if bot else "█")
        lines.append("".join(row))
    return "\n".join(lines)


def svg(text: str, scale: int = 8, border: int = 4) -> str:
    q = qr(text)
    n = q.get_size()
    parts = [f"M{x + border},{y + border}h1v1h-1z" for y in range(n) for x in range(n) if q.get_module(x, y)]
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size * scale}" height="{size * scale}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{" ".join(parts)}" fill="#000"/></svg>')


def page(cfg) -> str:
    """只给本机看的配对页（/pair）：二维码 + 三步说明。"""
    url = pair_url(cfg)
    hs = hosts()
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>P-Health 配对</title><style>
body{{margin:0;background:#000;color:#fff;font-family:-apple-system,"PingFang SC",sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}}
main{{text-align:center;max-width:420px;padding:32px}} h1{{font-weight:300;font-size:28px;letter-spacing:2px;margin:0 0 8px}}
p{{color:#aaa;font-size:14px;line-height:1.7;margin:6px 0}} .qr{{background:#fff;display:inline-block;padding:12px;border-radius:12px;margin:24px 0}}
.qr svg{{width:280px;height:280px;display:block}} ol{{text-align:left;color:#ccc;font-size:14px;line-height:2;padding-left:22px}}
code{{color:#777;font-size:11px;word-break:break-all}}
</style></head><body><main>
<h1>P-Health</h1><p>{computer_name()}</p>
<div class="qr">{svg(url)}</div>
<ol><li>iPhone 上装好 P-Health（TestFlight）</li><li>用相机或 App 里的「扫码配对」扫这个码</li><li>手机和这台电脑在同一个 Wi-Fi（出门在外用 Tailscale）</li></ol>
<p>手机会依次试：{"、".join(hs) or "（没找到局域网地址）"}</p>
<p><code>这个码里有这台电脑的访问密钥，只在本机显示，不要截图发给别人。</code></p>
</main></body></html>"""


def write_files(cfg) -> dict:
    """配对文件写到数据目录：pair.html（本机打开）和 pair.txt（链接，手机上直接点也行）。"""
    d = Path(cfg.data_dir)
    d.mkdir(parents=True, exist_ok=True)
    html, txt = d / "pair.html", d / "pair.txt"
    html.write_text(page(cfg), encoding="utf-8")
    txt.write_text(pair_url(cfg) + "\n", encoding="utf-8")
    for f in (html, txt):
        f.chmod(0o600)
    return {"html": str(html), "txt": str(txt)}
