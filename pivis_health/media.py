"""媒体链接的唯一规则（待办、对话卡片、主卡零件、素材库都用这里）：
能不能用、是什么类型、是不是 follow 出的片、有没有封面。"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class MediaError(ValueError):
    pass


# 公开网盘 / 临时文件站 / 图床：用户和博主的视频绝不能传到这些地方
FILE_HOSTS = ("uguu.se", "catbox.moe", "litterbox", "gofile.io", "tmpfiles.org", "0x0.st", "pixeldrain", "bashupload",
              "envs.sh", "transfer.sh", "file.io", "wetransfer", "filebin", "temp.sh", "anonfiles", "mega.nz", "dropbox",
              "drive.google", "pan.baidu", "aliyundrive", "alipan", "lanzou", "123pan", "cowtransfer", "imgur", "sm.ms")


def check_url(url: str) -> None:
    if url.startswith("/media/"):
        return
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise MediaError(f"媒体链接必须是公网 http(s) 地址或 /media/ 下的文件: {url}")
    host = p.hostname
    if host in ("localhost",) or host.endswith(".local"):
        raise MediaError(f"媒体链接不能用本地地址: {url}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:  # 域名，不是 IP
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")):
        raise MediaError(f"媒体链接不能用内网地址: {url}")
    if "youtube.com" in host or "youtu.be" in host:
        raise MediaError("不使用 YouTube，国内平台优先 B 站")
    if any(h in host for h in FILE_HOSTS):
        raise MediaError("不能用网盘 / 临时文件站 / 图床的链接（用户和博主的视频不能传到公开网站）；"
                        "自己做的跟练视频用 follow 命令出片后给的 /media/follow/... 地址")



def path_only(url: str) -> str:
    return (url or "").split("?")[0].lower()


def is_follow_video(url: str) -> bool:
    """follow 出的片：/media/follow/<ssid>/out.mp4（可带 ?v=）"""
    return path_only(url).startswith("/media/follow/") and path_only(url).endswith(".mp4")


def kind_of(url: str) -> str:
    """video：视频文件或 B 站视频页；audio：音频文件；embed：其他网页"""
    p = path_only(url)
    if p.endswith((".mp4", ".m4v", ".mov")) or "bilibili.com/video/" in p:
        return "video"
    if p.endswith((".m4a", ".mp3", ".aac", ".wav")):
        return "audio"
    return "embed"


def poster_for(cfg, url: str) -> str | None:
    """follow 出的片有封面就给封面地址（App 不用再按路径猜）"""
    if not is_follow_video(url):
        return None
    from .follow import media_path
    poster = path_only(url).rsplit("/", 1)[0] + "/poster.jpg"
    return poster if media_path(cfg, poster) is not None else None
