import time


def build_topics_hot_response(limit: int, cached: dict | None, last_ok: dict | None, refresh_once):
    def _pack(src):
        items = (src.get("data") or {}).get("items") or []
        if limit > len(items):
            refresh_once()
            items = (src.get("data") or {}).get("items") or items
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "items": items[:limit],
                "update_time": (src.get("data") or {}).get("update_time") or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            },
        }

    if cached and cached.get("code") == 200:
        return _pack(cached)
    if last_ok and last_ok.get("code") == 200:
        return _pack(last_ok)
    return {
        "code": 202,
        "msg": "热门榜数据准备中（首次加载可能稍慢）",
        "data": {"items": [], "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())},
    }

