import time

from modules.stooq_csv import parse_stooq_ohlcv_csv


def _safe_float(val, default=None):
    """新浪字段偶发非数字（或列位移），避免 float() 抛错导致整条行情被丢弃。"""
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def _stooq_ohlc_row(session, symbol: str) -> dict | None:
    """
    Stooq 免费 CSV：XAUUSD/XAGUSD 等与主流「伦敦金/现货」更接近。
    注意：Stooq 常返回单行无表头 CSV，不可用「首行当列名」方式解析。
    """
    try:
        url = "https://stooq.com/q/l/"
        r = session.get(url, params={"s": symbol, "f": "sd2t2ohlcv", "e": "csv"}, timeout=8)
        r.raise_for_status()
        row = parse_stooq_ohlcv_csv(r.text)
        if not row:
            return None
        return {
            "close": float(row["close"]),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
        }
    except Exception:
        return None


def sina_get(session, headers, symbol: str) -> str:
    url = f"https://hq.sinajs.cn/list={symbol}"
    res = session.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    res.encoding = "gbk"
    return res.text.strip()


def parse_sina_var(payload: str) -> list[str]:
    if '"' not in payload:
        return []
    try:
        inner = payload.split('"', 1)[1].rsplit('"', 1)[0]
    except Exception:
        return []
    if not inner:
        return []
    return inner.split(",")


def sina_quote(session, headers, symbol: str) -> tuple[str, list[str]]:
    raw = sina_get(session, headers, symbol)
    fields = parse_sina_var(raw)
    return symbol, fields


def normalize_symbol_candidates(raw_symbol: str) -> list[str]:
    s_raw = (raw_symbol or "").strip().strip('"').strip("'").strip()
    if not s_raw:
        return []
    s_lower = s_raw.lower()
    candidates = [s_raw, s_lower]
    if s_lower.startswith("hf_") and len(s_lower) > 3:
        suffix = s_raw[3:] if s_raw.lower().startswith("hf_") else s_lower[3:]
        if suffix:
            candidates.insert(0, f"hf_{suffix.upper()}")
    if s_lower.isdigit() and len(s_lower) == 6:
        # 北交所常见 92xxxx；勿误判为沪市（此前 920028 会走 sh920028 导致行情拉取失败）
        if s_lower.startswith("92"):
            candidates.insert(0, f"bj{s_lower}")
        elif s_lower.startswith(("6", "9")):
            candidates.insert(0, f"sh{s_lower}")
        elif s_lower.startswith(("0", "2", "3")):
            candidates.insert(0, f"sz{s_lower}")
        elif s_lower.startswith(("4", "8")):
            candidates.insert(0, f"bj{s_lower}")
        else:
            candidates.insert(0, f"sh{s_lower}")
    if s_lower.isdigit() and len(s_lower) == 5:
        candidates.insert(0, f"hk{s_lower}")
    if s_lower.isalpha() and 1 <= len(s_lower) <= 10:
        candidates.insert(0, f"gb_{s_lower}")
    seen, out = set(), []
    for c in candidates:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out


def parse_a_share(fields: list[str]):
    """
    新浪 A 股/指数常见字段顺序：
    0 名称 1 开盘 2 昨收 3 现价 4 最高 5 最低 …（后续为成交量等）
    休市或暂未撮合时「现价」常为 0，此时用昨收展示，避免前端全显示 0。
    """
    name = fields[0] if fields else ""
    open_p = _safe_float(fields[1] if len(fields) > 1 else None, 0.0) or 0.0
    prev_close = _safe_float(fields[2] if len(fields) > 2 else None, 0.0) or 0.0
    high = _safe_float(fields[4] if len(fields) > 4 else None, 0.0) or 0.0
    low = _safe_float(fields[5] if len(fields) > 5 else None, 0.0) or 0.0
    price = _safe_float(fields[3] if len(fields) > 3 else None, 0.0) or 0.0
    if not price and prev_close:
        price = float(prev_close)
    date = fields[-3] if len(fields) >= 3 else ""
    tm = fields[-2] if len(fields) >= 2 else ""
    update_time = f"{date} {tm}".strip() or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return name, price, open_p, prev_close, high, low, update_time


def parse_hk(fields: list[str]):
    name = fields[1] if len(fields) > 1 and fields[1] else fields[0]
    open_p = float(fields[2]) if len(fields) > 2 and fields[2] else 0.0
    price = float(fields[3]) if len(fields) > 3 and fields[3] else 0.0
    high = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
    low = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
    prev_close = float(fields[9]) if len(fields) > 9 and fields[9] else 0.0
    date = fields[-2] if len(fields) >= 2 else ""
    tm = fields[-1] if len(fields) >= 1 else ""
    update_time = f"{date} {tm}".strip() or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return name, price, open_p, prev_close, high, low, update_time


def parse_us(fields: list[str]):
    name = fields[0]
    price = float(fields[1]) if len(fields) > 1 and fields[1] else 0.0
    open_p = float(fields[5]) if len(fields) > 5 and fields[5] else 0.0
    high = float(fields[6]) if len(fields) > 6 and fields[6] else 0.0
    low = float(fields[7]) if len(fields) > 7 and fields[7] else 0.0
    chg = float(fields[2]) if len(fields) > 2 and fields[2] else 0.0
    prev_close = round(price - chg, 4) if price and chg else 0.0
    update_time = fields[3] if len(fields) > 3 else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return name, price, open_p, prev_close, high, low, update_time


def parse_futures(symbol: str, fields: list[str]):
    name = fields[13] if len(fields) > 13 and fields[13] else symbol
    price = float(fields[0]) if len(fields) > 0 and fields[0] else 0.0
    open_p = float(fields[2]) if len(fields) > 2 and fields[2] else 0.0
    high = float(fields[3]) if len(fields) > 3 and fields[3] else 0.0
    low = float(fields[4]) if len(fields) > 4 and fields[4] else 0.0
    prev_close = float(fields[7]) if len(fields) > 7 and fields[7] else 0.0
    date = fields[12] if len(fields) > 12 else ""
    tm = fields[6] if len(fields) > 6 else ""
    update_time = f"{date} {tm}".strip() or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return name, price, open_p, prev_close, high, low, update_time


def get_usdcny(deps):
    cached = deps["cache_get"]("usdcny", ttl_s=2)
    if cached:
        return cached
    raw = sina_get(deps["session"], deps["headers"], "USDCNY")
    fields = parse_sina_var(raw)
    # 新浪 USDCNY：字段1 为最新价/中间参考，字段2 多为昨收/基准；此前误用字段3（常为当日区间价）导致与主流站不一致
    price = _safe_float(fields[1] if len(fields) > 1 else None, None)
    if price is None:
        price = _safe_float(fields[3] if len(fields) > 3 else None, 0.0) or 0.0
    prev_close = _safe_float(fields[2] if len(fields) > 2 else None, None)
    if prev_close is not None and prev_close != 0:
        chg = round(float(price) - float(prev_close), 4)
        pct_chg = round((chg / float(prev_close)) * 100, 2)
        deps["cache_raw"][f"prev:{deps['NAME_USDCNY']}"] = (deps["now_ts"](), float(price))
    else:
        chg, pct_chg = deps["with_prev_change"](deps["NAME_USDCNY"], float(price), digits=4)
    result = {
        "name": deps["NAME_USDCNY"],
        "price": round(float(price), 4),
        "chg": chg,
        "pct_chg": pct_chg,
        "source_note": "新浪 USDCNY（字段1 最新价相对字段2 参考价；各行口径可能略有差异）",
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    deps["cache_set"]("usdcny", result)
    return result


def get_gold(deps):
    cached = deps["cache_get"]("gold", ttl_s=2)
    if cached:
        # 升级展示名后，内存里可能仍是旧缓存「COMEX黄金」，统一成当前 NAME_GOLD 以免前端对不上
        if isinstance(cached, dict) and cached.get("name") != deps["NAME_GOLD"]:
            merged = {**cached, "name": deps["NAME_GOLD"]}
            merged.pop("unit", None)
            return merged
        return cached

    # 优先：国际现货 XAU/USD（Stooq）。网络偶发抖动失败时若立刻改拉 COMEX 期货 hf_GC，会高出约 20～40 美元，
    # 配合前端高频刷新会像「跳变」。故：短时重试 Stooq；仍失败则在一段时间内沿用最近一次成功现货快照，最后再期货兜底。
    row = None
    for _attempt in range(2):
        row = _stooq_ohlc_row(deps["session"], "xauusd")
        if row and row.get("close"):
            break
        time.sleep(0.2)

    if row and row.get("close"):
        price = float(row["close"])
        o = row.get("open")
        if o is not None and o > 0:
            chg = round(price - o, 2)
            pct_chg = round((chg / o) * 100, 2)
            deps["cache_raw"][f"prev:{deps['NAME_GOLD']}"] = (deps["now_ts"](), float(price))
        else:
            chg, pct_chg = deps["with_prev_change"](deps["NAME_GOLD"], price, digits=2)
        result = {
            "name": deps["NAME_GOLD"],
            "price": round(price, 2),
            "chg": chg,
            "pct_chg": pct_chg,
            "source_note": "XAU/USD 现货参考（Stooq 最新价/Close），与 COMEX 期货主力报价可能不同",
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        deps["cache_set"]("gold_stooq_snapshot", {**result})
        deps["cache_set"]("gold", result)
        return result

    snap = deps["cache_get"]("gold_stooq_snapshot", ttl_s=120)
    if isinstance(snap, dict) and snap.get("price") is not None:
        delayed = {
            **snap,
            "name": deps["NAME_GOLD"],
            "source_note": "沿用最近一次现货价（本次未能从 Stooq 更新，已避免切换为期货价导致跳变）",
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        delayed.pop("unit", None)
        deps["cache_set"]("gold", delayed)
        return delayed

    fields = []
    for sym in ("hf_GC", "hf_gc"):
        try:
            raw = sina_get(deps["session"], deps["headers"], sym)
            fields = parse_sina_var(raw)
            if fields and fields[0]:
                break
        except Exception:
            fields = []
            continue

    if not fields:
        return None

    price = _safe_float(fields[0], 0.0) or 0.0
    prev_settle = _safe_float(fields[7] if len(fields) > 7 else None)
    if prev_settle is not None and prev_settle != 0:
        chg = round(price - prev_settle, 2)
        pct_chg = round((chg / prev_settle) * 100, 2)
        deps["cache_raw"][f"prev:{deps['NAME_GOLD']}"] = (deps["now_ts"](), float(price))
    else:
        chg, pct_chg = deps["with_prev_change"](deps["NAME_GOLD"], price, digits=2)
    result = {
        "name": deps["NAME_GOLD"],
        "price": round(price, 2),
        "chg": chg,
        "pct_chg": pct_chg,
        "source_note": "新浪 hf_GC（COMEX 黄金期货主连，备用；与现货 XAU 价差较大）",
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    deps["cache_set"]("gold", result)
    return result


def get_silver(deps):
    cached = deps["cache_get"]("silver", ttl_s=2)
    if cached:
        if isinstance(cached, dict) and cached.get("name") != deps["NAME_SILVER"]:
            merged = {**cached, "name": deps["NAME_SILVER"]}
            merged.pop("unit", None)
            return merged
        return cached

    fields = []
    for sym in ("hf_SI", "hf_si"):
        try:
            raw = sina_get(deps["session"], deps["headers"], sym)
            fields = parse_sina_var(raw)
            if fields and fields[0]:
                break
        except Exception:
            fields = []
            continue

    if not fields:
        return None

    price = _safe_float(fields[0] if len(fields) > 0 else None, 0.0) or 0.0
    prev_settle = _safe_float(fields[7] if len(fields) > 7 else None)
    if prev_settle is not None and prev_settle != 0:
        chg = round(price - prev_settle, 2)
        pct_chg = round((chg / prev_settle) * 100, 2)
        deps["cache_raw"][f"prev:{deps['NAME_SILVER']}"] = (deps["now_ts"](), float(price))
    else:
        chg, pct_chg = deps["with_prev_change"](deps["NAME_SILVER"], price, digits=2)
    result = {
        "name": deps["NAME_SILVER"],
        "price": round(price, 2),
        "chg": chg,
        "pct_chg": pct_chg,
        "source_note": "新浪 hf_SI（COMEX 白银期货主连参考价，可能与现货/XAG 口径存在差异）",
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    deps["cache_set"]("silver", result)
    return result


def get_crude_oil(deps):
    cached = deps["cache_get"]("wti", ttl_s=2)
    if cached:
        return cached
    raw = sina_get(deps["session"], deps["headers"], "hf_CL")
    fields = parse_sina_var(raw)
    price = _safe_float(fields[0] if len(fields) > 0 else None, 0.0) or 0.0
    prev_settle = _safe_float(fields[7] if len(fields) > 7 else None)
    if prev_settle and prev_settle != 0:
        chg = round(price - prev_settle, 2)
        pct_chg = round((chg / prev_settle) * 100, 2)
        deps["cache_raw"][f"prev:{deps['NAME_WTI']}"] = (deps["now_ts"](), float(price))
    else:
        chg, pct_chg = deps["with_prev_change"](deps["NAME_WTI"], price, digits=2)
    result = {"name": deps["NAME_WTI"], "price": round(price, 2), "chg": chg, "pct_chg": pct_chg, "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
    deps["cache_set"]("wti", result)
    return result


def get_index_quote(deps, name: str, symbol: str):
    cached = deps["cache_get"](f"idx:{symbol}", ttl_s=2)
    if cached:
        return cached
    _, fields = sina_quote(deps["session"], deps["headers"], symbol)
    if not fields:
        raise RuntimeError(f"指数行情为空：{symbol}")
    try:
        prev_close = _safe_float(fields[2] if len(fields) > 2 else None, 0.0) or 0.0
        raw_now = _safe_float(fields[3] if len(fields) > 3 else None, 0.0) or 0.0
        update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        # 与主流财经端一致：有最新价则算涨跌；无最新价（休市/盘前）用昨收展示点位，涨跌记 0 / 0%
        if raw_now and prev_close:
            price = float(raw_now)
            chg = round(price - prev_close, 4)
            pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
        elif prev_close:
            price = float(prev_close)
            chg = 0.0
            pct = 0.0
        else:
            price = 0.0
            chg = 0.0
            pct = 0.0
    except Exception:
        price = 0.0
        chg = 0.0
        pct = 0.0
        update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    result = {
        "name": name,
        "price": round(price, 2),
        "chg": round(chg, 2),
        "pct_chg": pct,
        "update_time": update_time,
    }
    deps["cache_set"](f"idx:{symbol}", result)
    return result

