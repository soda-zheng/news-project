import time
import urllib.parse as urlparse
from flask import jsonify, request, Response, redirect


def news_image_route(session, news_fallback_pic_url):
    src = (request.args.get("src") or "").strip()
    seed = (request.args.get("seed") or "news").strip()
    if not src:
        return redirect(news_fallback_pic_url(seed), code=302)
    try:
        r = session.get(src, timeout=8, headers={"Referer": "https://finance.sina.com.cn"})
        if r.status_code != 200 or not (r.headers.get("Content-Type", "").startswith("image/")):
            return redirect(news_fallback_pic_url(seed), code=302)
        return Response(r.content, status=200, content_type=r.headers.get("Content-Type", "image/jpeg"))
    except Exception:
        return redirect(news_fallback_pic_url(seed), code=302)


def news_home_route(deps):
    deps["news_db_init"]()
    try:
        page = int(request.args.get("page", "1") or "1")
        num = int(request.args.get("num", "20") or "20")
        page = max(1, min(50, page))
        num = max(1, min(20, num))
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：page/num", "data": None})

    try:
        cache_get = deps["cache_get"]
        cache_set = deps["cache_set"]
        cached = cache_get(f"news:home:{page}:{num}", ttl_s=120)
        if cached is None:
            try:
                items = deps["news_fetch_juhe"](page=page, num=num)
                source_tag = "juhe"
            except Exception:
                items = deps["news_fetch_tianapi"](page=page, num=num)
                source_tag = "tianapi"
            cache_set(f"news:home:{page}:{num}", {"items": items, "source": source_tag})
        else:
            items = (cached or {}).get("items") or []

        ids = [it["id"] for it in items]
        cached_map = deps["news_cache_get_many"](ids)
        out, need_llm = [], []

        for it in items:
            c = cached_map.get(it["id"]) or {}
            summary = c.get("summary")
            importance = c.get("importance")
            category = c.get("category")
            if category in deps["news_old_category_set"]:
                category = None
            kw_hits = deps["news_keyword_hits"](it["title"])
            it2 = dict(it)
            it2["summary"] = summary
            it2["importance"] = importance
            it2["category"] = category or deps["fallback_category"](it.get("title") or "")
            it2["_kw_hits"] = kw_hits
            it2["score"] = round(deps["news_compute_score"](it2), 6)
            out.append(it2)
            if not summary:
                need_llm.append(it2)

        if need_llm:
            deps["enqueue_news_for_llm"](need_llm)
        out.sort(key=lambda x: (x.get("score") is not None, x.get("score") or -1), reverse=True)

        featured = []
        for x in out:
            if len(featured) >= 3:
                break
            x2 = dict(x)
            if x2.get("picUrl"):
                x2["picUrl"] = f"/api/news/image?src={urlparse.quote(str(x2.get('picUrl')))}&seed={urlparse.quote(str(x2.get('id') or 'news'))}"
            else:
                x2["picUrl"] = f"/api/news/image?seed={urlparse.quote(str(x2.get('id') or 'news'))}"
            featured.append(x2)

        featured_ids = {str(x.get("id")) for x in featured if x.get("id")}
        out_no_featured = [x for x in out if str(x.get("id")) not in featured_ids]

        def _pub(x: dict):
            summary = x.get("summary") or deps["fallback_summary"](x.get("title"), x.get("source"))
            return {
                "id": x.get("id"),
                "title": x.get("title"),
                "summary": summary,
                "source": x.get("source"),
                "category": x.get("category") or deps["fallback_category"](x.get("title") or ""),
                "ctime": int(x.get("ctime") or 0),
                "picUrl": x.get("picUrl"),
                "url": x.get("url"),
                "importance": x.get("importance") if x.get("importance") is not None else 50,
                "score": x.get("score"),
            }

        return jsonify(
            {
                "code": 200,
                "msg": "success",
                "data": {
                    "page": page,
                    "num": num,
                    "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "source": ((cached or {}).get("source") if cached else source_tag) or "unknown",
                    "featured": [_pub(x) for x in featured],
                    "items": [_pub(x) for x in out_no_featured],
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取首页新闻失败：{e}", "data": None})

