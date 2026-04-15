import time
from flask import jsonify, request


def quote_route(deps):
    try:
        raw_symbol = request.args.get("symbol", "") or ""
        candidates = deps["normalize_symbol_candidates"](raw_symbol)
        if not candidates:
            return jsonify({"code": 400, "msg": "缺少参数：symbol", "data": None})

        for sym in candidates:
            try:
                used, fields = deps["sina_quote"](sym)
                if not fields:
                    continue
                if used.startswith("gb_"):
                    name, price, open_p, prev_close, high, low, update_time = deps["parse_us"](used, fields)
                elif used.startswith("hk"):
                    name, price, open_p, prev_close, high, low, update_time = deps["parse_hk"](used, fields)
                elif used.startswith("hf_"):
                    name, price, open_p, prev_close, high, low, update_time = deps["parse_futures"](used, fields)
                else:
                    name, price, open_p, prev_close, high, low, update_time = deps["parse_a_share"](used, fields)

                chg = round(price - prev_close, 4) if prev_close else 0.0
                pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
                return jsonify(
                    {
                        "code": 200,
                        "msg": "success",
                        "data": {
                            "input_symbol": raw_symbol,
                            "symbol": used,
                            "name": name,
                            "price": round(price, 4),
                            "chg": round(chg, 4),
                            "pct_chg": pct,
                            "open": round(open_p, 4),
                            "prev_close": round(prev_close, 4),
                            "high": round(high, 4),
                            "low": round(low, 4),
                            "update_time": update_time,
                        },
                    }
                )
            except Exception:
                continue
        return jsonify({"code": 404, "msg": f"未找到该标的（尝试：{', '.join(candidates)}）", "data": None})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询失败：{e}", "data": None})


def core_quotes_route(deps):
    quotes = []
    for name, symbol in (
        (deps["NAME_SSE"], "sh000001"),
        (deps["NAME_SZSE"], "sz399001"),
        (deps["NAME_CHINEXT"], "sz399006"),
    ):
        try:
            quotes.append(deps["get_index_quote"](name, symbol))
        except Exception as e:
            print(f"获取指数失败：{symbol} {e}")
    extra_getters = [deps["get_usdcny"], deps["get_gold"]]
    if deps.get("get_silver"):
        extra_getters.append(deps["get_silver"])
    extra_getters.append(deps["get_crude_oil"])
    for getter in extra_getters:
        try:
            quotes.append(getter())
        except Exception as e:
            print(f"获取行情失败：{e}")
    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {"update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), "quotes": [q for q in quotes if q is not None]},
        }
    )


def usdcny_route(get_usdcny):
    data = get_usdcny()
    if data:
        return jsonify({"code": 200, "msg": "success", "data": data})
    return jsonify({"code": 500, "msg": "获取人民币/美元汇率失败", "data": None})


def stock_route(deps):
    try:
        raw_symbol = request.args.get("symbol", "") or ""
        candidates = deps["normalize_symbol_candidates"](raw_symbol)
        if not candidates:
            return jsonify({"code": 400, "msg": "缺少参数：symbol", "data": None})
        for sym in candidates:
            used, fields = deps["sina_quote"](sym)
            if not fields:
                continue
            name, price, open_p, prev_close, high, low, update_time = deps["parse_a_share"](used, fields)
            chg = round(price - prev_close, 4) if prev_close else 0.0
            pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
            return jsonify(
                {
                    "code": 200,
                    "msg": "success",
                    "data": {
                        "symbol": used,
                        "input_symbol": raw_symbol,
                        "name": name,
                        "price": round(price, 2),
                        "chg": round(chg, 2),
                        "pct_chg": pct,
                        "open": round(open_p, 2),
                        "prev_close": round(prev_close, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "update_time": update_time,
                    },
                }
            )
        return jsonify({"code": 404, "msg": "未找到该股票/代码不支持", "data": None})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询失败：{e}", "data": None})

