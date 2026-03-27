import time
import urllib.parse as urlparse
from flask import jsonify, request


def convert_route(session):
    try:
        qs_amount = request.args.get("amount", "1")
        qs_from = (request.args.get("from", "USD") or "USD").strip().upper()
        qs_to = (request.args.get("to", "CNY") or "CNY").strip().upper()
        amount = float(qs_amount)
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：amount/from/to", "data": None})
    try:
        api = f"https://api.exchangerate-api.com/v4/latest/{urlparse.quote(qs_from)}"
        r = session.get(api, timeout=10)
        r.raise_for_status()
        data = r.json()
        rate = float(data["rates"][qs_to])
        result = round(amount * float(rate), 6)
        return jsonify(
            {
                "code": 200,
                "msg": "success",
                "data": {
                    "amount": amount,
                    "from": qs_from,
                    "to": qs_to,
                    "rate": round(float(rate), 6),
                    "result": result,
                    "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "msg": f"换算失败：{e}", "data": None})


def fx_currencies_route(session, cache_get, cache_set):
    cached = cache_get("fx_currencies", ttl_s=12 * 60 * 60)
    if cached:
        return jsonify(cached)
    try:
        api = f"https://api.exchangerate-api.com/v4/latest/{urlparse.quote('USD')}"
        r = session.get(api, timeout=10)
        r.raise_for_status()
        data = r.json()
        rates = data.get("rates") or {}
        items = sorted({str(k).upper() for k in rates.keys() if k})
        result = {
            "code": 200,
            "msg": "success",
            "data": {"base": "USD", "items": items, "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())},
        }
        cache_set("fx_currencies", result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取币种列表失败：{e}", "data": None})

