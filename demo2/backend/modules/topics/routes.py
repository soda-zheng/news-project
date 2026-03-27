from flask import jsonify, request
from modules.topics.service import build_topics_hot_response
from modules.topics.insight_service import board_insight, stock_insight


def boards_industry_route(deps):
    cached = deps["cache_get"]("boards_industry", ttl_s=deps["TOPICS_REFRESH_SECONDS"])
    if cached:
        return jsonify(cached)
    try:
        rows = deps["sina_hq_node_data"]("hs_hy", num=80)
        items = []
        for r in rows:
            pct = deps["to_float"](r.get("changepercent"), None)
            if pct is None:
                continue
            items.append({"kind": "industry", "name": str(r.get("name") or r.get("symbol") or ""), "pct_chg": round(float(pct), 2), "leader": r.get("symbol")})
        result = {"code": 200, "msg": "success", "data": {"items": items[:20], "update_time": deps["now_str"]()}}
        deps["cache_set"]("boards_industry", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取行业板块失败：{e}", "data": None})


def boards_concept_route(deps):
    cached = deps["cache_get"]("boards_concept", ttl_s=deps["TOPICS_REFRESH_SECONDS"])
    if cached:
        return jsonify(cached)
    try:
        rows = deps["sina_hq_node_data"]("hs_gn", num=80)
        items = []
        for r in rows:
            pct = deps["to_float"](r.get("changepercent"), None)
            if pct is None:
                continue
            items.append({"kind": "concept", "name": str(r.get("name") or r.get("symbol") or ""), "pct_chg": round(float(pct), 2), "leader": r.get("symbol")})
        result = {"code": 200, "msg": "success", "data": {"items": items[:20], "update_time": deps["now_str"]()}}
        deps["cache_set"]("boards_concept", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取概念板块失败：{e}", "data": None})


def topics_hot_route(deps):
    deps["start_topics_hot_scheduler"]()
    try:
        limit = int(request.args.get("limit", "10") or "10")
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：limit", "data": None})
    limit = max(1, min(100, limit))
    cached = deps["cache_get"]("topics_hot", ttl_s=deps["TOPICS_REFRESH_SECONDS"])
    last_ok = deps["cache_get"]("topics_hot_last_ok", ttl_s=6 * 60 * 60)
    return jsonify(build_topics_hot_response(limit, cached, last_ok, deps["topics_hot_refresh_once"]))


def topics_stock_insight_route(deps):
    if request.method != "POST":
        return jsonify({"code": 405, "msg": "Method Not Allowed", "data": None})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    try:
        data = stock_insight(
            deps["session"],
            deps["topics_llm_state"],
            body,
            fetch_quote=deps.get("fetch_quote"),
        )
        return jsonify({"code": 200, "msg": "success", "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"分析失败：{e}", "data": None})


def topics_board_insight_route(deps):
    if request.method != "POST":
        return jsonify({"code": 405, "msg": "Method Not Allowed", "data": None})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    items = body.get("items")
    if not isinstance(items, list):
        items = []
    try:
        data = board_insight(deps["session"], deps["topics_llm_state"], items)
        return jsonify({"code": 200, "msg": "success", "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"分析失败：{e}", "data": None})

