from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.utils import now_str, parse_symbol, to_float
from services import topics_service as topics_svc

bp = Blueprint("topics", __name__, url_prefix="/api/topics")


@bp.route("/hot", methods=["GET"])
def topics_hot():
    try:
        limit = int(request.args.get("limit", "10") or "10")
    except Exception:
        limit = 10
    limit = max(1, min(100, limit))
    try:
        rows = topics_svc.fetch_hot_node("sh_a", 45) + topics_svc.fetch_hot_node("sz_a", 45)
        seen = set()
        uniq = []
        for x in rows:
            key = str(x.get("leader") or "")
            if key in seen:
                continue
            seen.add(key)
            uniq.append(x)
        uniq.sort(key=lambda x: to_float(x.get("pct_chg"), -9999) or -9999, reverse=True)
        return jsonify({"code": 200, "msg": "success", "data": {"items": uniq[:limit], "update_time": now_str()}})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取热点失败：{e}", "data": None})


@bp.route("/stock-insight", methods=["POST", "OPTIONS"])
def stock_insight():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "该标的")
    code = parse_symbol(body.get("leader") or body.get("code") or "")
    pct_chg = float(body.get("pct_chg") or 0.0)
    direction = "偏强" if pct_chg >= 0 else "偏弱"
    lines = [
        f"{name}（{code or 'N/A'}）当日表现{direction}，当前涨跌幅 {pct_chg:+.2f}%。",
        "短线观察建议优先看量价配合与板块联动，不建议单一信号决策。",
        "若你补充持仓成本、风险偏好和计划周期，可生成更细化场景建议。",
    ]
    return jsonify({"code": 200, "msg": "success", "data": {"lines": lines, "source": "template"}})
