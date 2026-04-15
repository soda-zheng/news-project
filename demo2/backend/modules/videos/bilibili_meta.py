"""
B 站视频元数据（公开接口，无需 Cookie）：
- 用于校正 videos.json 里营销标题与真实稿件不一致的问题
- 用于判断稿件是否仍存在（下架则站内 iframe 常失败）

接口：GET https://api.bilibili.com/x/web-interface/view?bvid=BV...
"""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_BILI_VIEW_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_S = 1800.0  # 半小时内同一 BV 不重复打 API

# 注意：不能用 re.I + (BV...)+，否则会把 query 里的参数名「bvid」误当成 BV 号。
# B 站 BV 号一般为 BV + 10 位左右 base58 字符，至少要求 BV 后 ≥10 位字母数字。
_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10,})")


def extract_bvid(url: str | None) -> str | None:
    if not url:
        return None
    m = _BVID_RE.search(str(url))
    return m.group(1) if m else None


def normalize_bilibili_player_url(url: str | None) -> str | None:
    """为第三方页面嵌入补充参数，减少「有声音无画面 / 拒绝嵌入」概率。"""
    if not url:
        return url
    try:
        p = urlparse(str(url).strip())
        if "player.bilibili.com" not in (p.netloc or ""):
            return url
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q["autoplay"] = "0"
        q["high_quality"] = "1"
        q["danmaku"] = "0"
        q["isOutside"] = "true"
        new_query = urlencode(q)
        return urlunparse((p.scheme or "https", p.netloc, p.path or "/", p.params, new_query, p.fragment))
    except Exception:
        return url


def fetch_bilibili_view_meta(session, bvid: str) -> dict:
    """
    返回 dict:
      ok: bool | None  — True 稿件存在；False 明确失败/下架；None 网络异常未判定
      title, pic: str | None
    """
    bvid = (bvid or "").strip()
    if not bvid:
        return {"ok": None, "title": None, "pic": None}

    now = time.time()
    hit = _BILI_VIEW_CACHE.get(bvid)
    if hit and now - hit[0] < _CACHE_TTL_S:
        return hit[1]

    meta = {"ok": None, "title": None, "pic": None}
    try:
        r = session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=3.5,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/",
            },
        )
        r.raise_for_status()
        j = r.json()
        code = int(j.get("code", -1))
        if code == 0:
            d = j.get("data") or {}
            title = str(d.get("title") or "").strip() or None
            pic = str(d.get("pic") or "").strip() or None
            meta = {"ok": True, "title": title, "pic": pic}
        else:
            # 常见：稿件不存在、下架等
            meta = {"ok": False, "title": None, "pic": None}
    except Exception:
        meta = {"ok": None, "title": None, "pic": None}

    _BILI_VIEW_CACHE[bvid] = (now, meta)
    return meta


def enrich_video_item(session, item: dict) -> dict:
    """在单条配置上合并 B 站真实标题/封面，并规范化 embed_url。"""
    if not isinstance(item, dict):
        return item

    out = dict(item)
    t = str(out.get("type") or "").strip().lower()
    if t != "embed":
        return out

    embed_raw = str(out.get("embed_url") or "").strip()
    open_u = str(out.get("open_url") or "").strip()
    bvid = extract_bvid(embed_raw) or extract_bvid(open_u)
    if not bvid:
        return out

    meta = fetch_bilibili_view_meta(session, bvid)

    if meta.get("ok") is True:
        if meta.get("title"):
            out["title_original"] = out.get("title")
            out["title"] = meta["title"]
        if meta.get("pic"):
            out["cover"] = meta["pic"]
        out["bvid"] = bvid
        out["embed_ok"] = True
    elif meta.get("ok") is False:
        out["bvid"] = bvid
        out["embed_ok"] = False
    else:
        out["bvid"] = bvid
        out["embed_ok"] = None

    norm = normalize_bilibili_player_url(embed_raw)
    if norm:
        out["embed_url"] = norm

    return out


def enrich_videos_list(session, items: list) -> list:
    if not items:
        return items
    return [enrich_video_item(session, x) if isinstance(x, dict) else x for x in items]
