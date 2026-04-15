import time
from urllib.parse import urlparse

from flask import Response, jsonify, redirect, request

from modules.videos.bilibili_meta import enrich_videos_list
from modules.videos.service import load_videos


def _cover_host_allowed(netloc: str) -> bool:
    h = (netloc or "").lower().strip()
    if not h:
        return False
    if h.endswith(".hdslb.com") or h == "hdslb.com":
        return True
    if h.endswith(".bilibili.com") or h == "bilibili.com":
        return True
    if "picsum.photos" in h:
        return True
    return False


def video_cover_route(session):
    """
    代理视频封面图：B 站 CDN 常校验 Referer，浏览器直连易裂图。
    GET /api/video-cover?src=https%3A%2F%2Fi0.hdslb.com%2F...
    """
    src = (request.args.get("src") or "").strip()
    if not src:
        return redirect("https://picsum.photos/seed/vcover/640/360", code=302)

    try:
        parsed = urlparse(src)
    except Exception:
        return ("", 400)

    if parsed.scheme not in ("http", "https"):
        return ("", 400)
    if not _cover_host_allowed(parsed.netloc):
        return ("", 403)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if "hdslb.com" in (parsed.netloc or "").lower():
        headers["Referer"] = "https://www.bilibili.com/"

    try:
        r = session.get(src, timeout=10, headers=headers, allow_redirects=True)
        if r.status_code != 200:
            return redirect("https://picsum.photos/seed/vcover-fail/640/360", code=302)
        ct = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            return redirect("https://picsum.photos/seed/vcover-type/640/360", code=302)
        return Response(r.content, status=200, content_type=ct)
    except Exception:
        return redirect("https://picsum.photos/seed/vcover-err/640/360", code=302)


def videos_route(base_dir: str, session=None):
    items = load_videos(base_dir)
    if session is not None:
        try:
            items = enrich_videos_list(session, list(items))
        except Exception:
            pass
    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {"items": items, "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())},
        }
    )

