import os
import time
import json
import requests
from datetime import datetime, timedelta
from utils.helpers import (
    _now_str, _parse_symbol, _sina_symbol, _to_float, _parse_sina_var,
    _is_a_share_6digit, _sina_symbol_prefix, _parse_maybe_timestamp_to_ymd,
    _df_pick_col, _df_to_records, _df_to_code_name_items,
    _parse_sina_json_v2,
)


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn",
    }
)

_STOCK_DAILY_BARS_CACHE: dict[str, dict] = {}
_STOCK_DAILY_BARS_TTL_SEC = 60 * 60  # 1 小时

_STOCK_A_NAME_LOCK = time.time()
_STOCK_A_NAME_CACHE: dict[str, object] = {"ts": 0.0, "items": []}
_STOCK_A_NAME_TTL = float(os.environ.get("STOCK_A_NAME_CACHE_SEC", "600"))


def _fetch_stock_live(symbol_input: str):
    symbol = _sina_symbol(symbol_input)
    if not symbol:
        return None
    url = f"https://hq.sinajs.cn/list={symbol}"
    resp = SESSION.get(url, timeout=8)
    resp.encoding = "gbk"
    text = resp.text
    fields = _parse_sina_var(text)
    if len(fields) < 6:
        return None
    name = str(fields[0] or "").strip()
    open_p = _to_float(fields[1], 0.0) or 0.0
    prev_close = _to_float(fields[2], 0.0) or 0.0
    price = _to_float(fields[3], 0.0) or 0.0
    high = _to_float(fields[4], 0.0) or 0.0
    low = _to_float(fields[5], 0.0) or 0.0
    chg = round(price - prev_close, 4) if prev_close else 0.0
    pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
    update_time = _now_str()
    if len(fields) >= 32:
        update_time = f"{fields[30]} {fields[31]}".strip()
    code6 = _parse_symbol(symbol_input) or symbol.replace("sh", "").replace("sz", "").replace("bj", "")
    return {
        "symbol": code6,
        "code": code6,
        "name": name or code6,
        "price": round(price, 2),
        "chg": round(chg, 2),
        "pct_chg": pct,
        "open": round(open_p, 2),
        "prev_close": round(prev_close, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "update_time": update_time,
        "source": "sina",
    }


def _akshare_em_stock_name(code6: str) -> str:
    try:
        import akshare as ak
    except ImportError:
        return ""
    try:
        df = ak.stock_individual_info_em(symbol=code6)
    except Exception:
        return ""
    if df is None or getattr(df, "empty", True):
        return ""
    cols = list(df.columns)
    if len(cols) < 2:
        return ""
    ic, vc = cols[0], cols[1]
    for _, row in df.iterrows():
        if str(row[ic]).strip() in ("股票简称", "证券简称"):
            return str(row[vc]).strip()
    return ""


def _fetch_quote_ak_bid_ask(code6: str) -> dict | None:
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_bid_ask_em(symbol=code6)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True) or len(df.columns) < 2:
        return None
    c0, c1 = df.columns[0], df.columns[1]
    kv: dict[str, float | str] = {}
    for _, row in df.iterrows():
        k = str(row[c0]).strip()
        kv[k] = row[c1]

    def pick(*names: str):
        for n in names:
            if n in kv:
                return kv[n]
        return None

    price = _to_float(pick("最新"), None)
    if price is None or price <= 0:
        return None
    pct = _to_float(pick("涨幅"), 0.0) or 0.0
    chg = _to_float(pick("涨跌"), 0.0) or 0.0
    open_p = _to_float(pick("今开"), 0.0) or 0.0
    high = _to_float(pick("最高"), 0.0) or 0.0
    low = _to_float(pick("最低"), 0.0) or 0.0
    prev_close = _to_float(pick("昨收"), 0.0) or 0.0
    name = _akshare_em_stock_name(code6) or code6
    return {
        "symbol": code6,
        "code": code6,
        "name": name,
        "price": round(float(price), 2),
        "chg": round(float(chg), 2),
        "pct_chg": round(float(pct), 2),
        "open": round(float(open_p or 0), 2),
        "prev_close": round(float(prev_close or 0), 2),
        "high": round(float(high or 0), 2),
        "low": round(float(low or 0), 2),
        "update_time": _now_str(),
        "source": "akshare-stock_bid_ask_em",
    }


def _quote_price_ok(q: dict | None) -> bool:
    if not q:
        return False
    p = _to_float(q.get("price"), 0.0)
    return p is not None and float(p) > 0


def _fetch_a_share_quote(code6: str) -> dict | None:
    sina = None
    try:
        sina = _fetch_stock_live(code6)
    except Exception:
        sina = None
    if _quote_price_ok(sina):
        return sina
    akq = _fetch_quote_ak_bid_ask(code6)
    if _quote_price_ok(akq):
        return akq
    if sina:
        sina["source"] = "sina-incomplete"
        return sina
    return None


def _fetch_sina_hq_node_raw(node: str, num: int = 40) -> list:
    """新浪 Market_Center.getHQNodeData 原始行列表（与 demo2 一致）。"""
    params = {"page": 1, "num": num, "sort": "changepercent", "asc": 0, "node": node, "_s_r_a": "init"}
    urls = [
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
    ]
    rows: list = []
    for _ in range(2):
        if rows:
            break
        for url in urls:
            try:
                resp = SESSION.get(url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                parsed = _parse_sina_json_v2(resp.text)
                if isinstance(parsed, list) and parsed:
                    rows = parsed
                    break
            except Exception:
                continue
    return rows if isinstance(rows, list) else []


def _sina_stock_row_pct_chg(r: dict) -> float:
    """
    新浪 getHQNodeData 单行涨跌幅：优先 (现价-昨收)/昨收；否则 changepercent；否则 0（demo2 同逻辑）。
    """
    trade = _to_float(r.get("trade"), 0.0) or 0.0
    settlement = _to_float(r.get("settlement"), None)
    api_pct = _to_float(r.get("changepercent"), None)
    if trade > 0 and settlement is not None and float(settlement) > 0:
        return round((trade - float(settlement)) / float(settlement) * 100, 2)
    if api_pct is not None:
        return round(float(api_pct), 2)
    return 0.0


def _symbol_exchange_prio(sym: str) -> int:
    s = str(sym or "").lower()
    if s.startswith("sh"):
        return 0
    if s.startswith("sz"):
        return 1
    if s.startswith("bj"):
        return 2
    return 3


def _normalize_sina_symbol_to_code6(symbol: str) -> str:
    s = str(symbol or "").strip().lower()
    if len(s) == 8 and (s.startswith("sh") or s.startswith("sz") or s.startswith("bj")) and s[2:].isdigit():
        return s[2:]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return ""


def fetch_a_share_hot_topics_sina_merged(num_sh: int = 45, num_sz: int = 45) -> list[dict]:
    """
    A 股涨幅榜（demo2 逻辑）：合并上证 A + 深证 A 节点，去重后按涨跌幅/交易所/成交量排序。
    仅含沪深 A 股池（sh_a、sz_a），北交所不在此两节点则不会出现。
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_sh = pool.submit(_fetch_sina_hq_node_raw, "sh_a", num_sh)
        fut_sz = pool.submit(_fetch_sina_hq_node_raw, "sz_a", num_sz)
        rows_sh = fut_sh.result(timeout=50) or []
        rows_sz = fut_sz.result(timeout=50) or []

    seen: set[str] = set()
    rows: list[dict] = []
    for chunk in (rows_sh, rows_sz):
        for r in chunk:
            if not isinstance(r, dict):
                continue
            sym = str((r.get("symbol") or "")).strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            rows.append(r)

    items: list[dict] = []
    for r in rows:
        name = r.get("name") or r.get("symbol") or ""
        if not name:
            continue
        pct = _sina_stock_row_pct_chg(r)
        leader_sym = r.get("symbol") or ""
        code6 = _normalize_sina_symbol_to_code6(str(leader_sym))
        if len(code6) != 6 or not code6.isdigit():
            continue
        vol = int(_to_float(r.get("volume"), 0.0) or 0.0)
        prio = _symbol_exchange_prio(str(leader_sym or ""))
        items.append(
            {
                "name": str(name),
                "leader": code6,
                "pct_chg": pct,
                "_vol": vol,
                "_prio": prio,
            }
        )
    items.sort(
        key=lambda x: (
            -(_to_float(x.get("pct_chg"), 0.0) or 0.0),
            x["_prio"],
            -x["_vol"],
        )
    )
    for it in items:
        it.pop("_vol", None)
        it.pop("_prio", None)
    return items


def _fetch_hot_node(node: str, num: int = 40):
    rows = _fetch_sina_hq_node_raw(node, num)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        leader = str(r.get("symbol") or "").strip().lower()
        if not name or not leader:
            continue
        pct = _to_float(r.get("changepercent"), None)
        trade = _to_float(r.get("trade"), 0.0) or 0.0
        settle = _to_float(r.get("settlement"), None)
        if trade > 0 and settle and settle > 0:
            pct = round((trade - settle) / settle * 100, 2)
        if pct is None:
            continue
        out.append({"name": name, "leader": leader[2:] if len(leader) == 8 else leader, "pct_chg": round(float(pct), 2)})
    return out


def _fetch_hot_rank_em(limit: int = 20):
    """
    东方财富 A股人气榜（更接近“热门股”语义）。
    """
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_hot_rank_em()
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []

    rc = _df_pick_col(df, "当前排名", "排名")
    cc = _df_pick_col(df, "代码")
    nc = _df_pick_col(df, "股票名称", "名称")
    pc = _df_pick_col(df, "涨跌幅")
    if not cc or not nc:
        return []

    out = []
    for _, row in df.iterrows():
        code = str(row.get(cc) or "").strip()
        name = str(row.get(nc) or "").strip()
        if not code or not name:
            continue
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) != 6:
            continue
        pct = _to_float(row.get(pc), 0.0) if pc else 0.0
        rank = int(_to_float(row.get(rc), 999999) or 999999) if rc else 999999
        out.append({
            "name": name,
            "leader": digits,
            "pct_chg": round(float(pct or 0.0), 2),
            "rank": rank,
        })
    out.sort(key=lambda x: int(x.get("rank") or 999999))
    return out[: max(1, min(200, int(limit or 20)))]


def _fetch_hot_follow_xq(limit: int = 20):
    """
    雪球热门关注榜：在部分网络环境下比东方财富更稳定。
    返回与热点接口一致结构：name / leader / pct_chg
    """
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_hot_follow_xq(symbol="最热门")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []

    cols = list(df.columns)
    if len(cols) < 2:
        return []
    code_col = cols[0]
    name_col = cols[1]
    out = []
    for _, row in df.head(max(1, min(200, int(limit or 20)))).iterrows():
        raw_code = str(row.get(code_col) or "").strip().upper()
        name = str(row.get(name_col) or "").strip()
        if not raw_code or not name:
            continue
        # SH600519 / SZ000001 -> 600519
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if len(digits) != 6:
            continue
        # 这里不再逐只请求实时行情（会显著拖慢接口并导致前端超时）
        out.append({"name": name, "leader": digits, "pct_chg": 0.0})
    return out


def _fetch_hot_tweet_xq(limit: int = 20):
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_hot_tweet_xq(symbol="最热门")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    cols = list(df.columns)
    if len(cols) < 2:
        return []
    code_col, name_col = cols[0], cols[1]
    out = []
    for _, row in df.head(max(1, min(200, int(limit or 20)))).iterrows():
        raw_code = str(row.get(code_col) or "").strip().upper()
        name = str(row.get(name_col) or "").strip()
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if len(digits) != 6 or not name:
            continue
        out.append({"name": name, "leader": digits, "pct_chg": 0.0})
    return out


def _fetch_hot_deal_xq(limit: int = 20):
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_hot_deal_xq(symbol="最热门")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    cols = list(df.columns)
    if len(cols) < 2:
        return []
    code_col, name_col = cols[0], cols[1]
    out = []
    for _, row in df.head(max(1, min(200, int(limit or 20)))).iterrows():
        raw_code = str(row.get(code_col) or "").strip().upper()
        name = str(row.get(name_col) or "").strip()
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if len(digits) != 6 or not name:
            continue
        out.append({"name": name, "leader": digits, "pct_chg": 0.0})
    return out


def _fetch_a_share_spot_gainers_em(limit: int = 20):
    """
    A 股涨幅榜（与常见 demo 一致）：AkShare stock_zh_a_spot_em，东方财富 A 股全市场快照，按涨跌幅排序。
    覆盖沪/深/北交所 A 股，数据源为东财网页接口封装，不是新浪节点。
    """
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []

    cc = _df_pick_col(df, "代码")
    nc = _df_pick_col(df, "名称")
    pc = _df_pick_col(df, "涨跌幅")
    if not cc or not nc or not pc:
        return []

    rows = []
    for _, row in df.iterrows():
        code = str(row.get(cc) or "").strip()
        name = str(row.get(nc) or "").strip()
        pct = _to_float(row.get(pc), None)
        if not (code and name and pct is not None):
            continue
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) != 6:
            continue
        rows.append({"name": name, "leader": digits, "pct_chg": round(float(pct), 2)})
    rows.sort(key=lambda x: float(x.get("pct_chg") or -9999), reverse=True)
    return rows[: max(1, min(200, int(limit or 20)))]


def _fetch_hot_rank_fallback(limit: int = 20):
    """兼容旧名：等同东财 A 股涨幅榜。"""
    return _fetch_a_share_spot_gainers_em(limit)


def _download_a_share_code_name_list() -> tuple[list[dict[str, str]], str | None]:
    try:
        import akshare as ak
    except ImportError:
        return [], "未安装 akshare，请 pip install -r requirements.txt"
    err_notes: list[str] = []
    for fn_name, fn in (
        ("stock_info_a_code_name", getattr(ak, "stock_info_a_code_name", None)),
        ("stock_zh_a_spot_em", getattr(ak, "stock_zh_a_spot_em", None)),
    ):
        if fn is None:
            continue
        try:
            df = fn()
            items = _df_to_code_name_items(df)
            if items:
                return items, None
            err_notes.append(f"{fn_name}: 无有效行")
        except Exception as e:
            err_notes.append(f"{fn_name}: {e}")
    return [], "；".join(err_notes) if err_notes else "无法获取 A 股列表"


def _get_a_share_search_index() -> tuple[list[dict[str, str]], str | None]:
    now = time.time()
    cached = _STOCK_A_NAME_CACHE["items"]
    ts = float(_STOCK_A_NAME_CACHE["ts"] or 0)
    if isinstance(cached, list) and cached and (now - ts) < _STOCK_A_NAME_TTL:
        return cached, None
    items_new, err = _download_a_share_code_name_list()
    if items_new:
        _STOCK_A_NAME_CACHE["items"] = items_new
        _STOCK_A_NAME_CACHE["ts"] = time.time()
        return items_new, None
    stale = _STOCK_A_NAME_CACHE["items"]
    if isinstance(stale, list) and stale:
        return stale, err
    return [], err or "暂无股票列表"


def _fetch_daily_bars_sina(symbol: str) -> dict | None:
    code6 = _parse_symbol(symbol)
    if not _is_a_share_6digit(code6):
        return None

    prefix = _sina_symbol_prefix(code6)
    url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    def pick_arrays(container: object) -> dict | None:
        if not isinstance(container, dict):
            return None
        need = ["day", "open", "high", "low", "close"]
        if all(k in container for k in need):
            return container
        if "data" in container and isinstance(container["data"], dict):
            d = container["data"]
            if all(k in d for k in need):
                return d
        return None

    scale_candidates = ["240", "D", "1"]
    last_err = None

    for sc in scale_candidates:
        params = {"symbol": prefix, "scale": sc, "ma": "no", "datalen": "1023"}
        try:
            resp = SESSION.get(url, params=params, timeout=20)
            text = resp.text
        except Exception as e:
            last_err = str(e)
            continue

        try:
            obj = resp.json()
        except Exception:
            try:
                first = text.find("{")
                last = text.rfind("}")
                if first >= 0 and last > first:
                    obj = json.loads(text[first : last + 1])
                else:
                    last_err = "no json object"
                    continue
            except Exception as e:
                last_err = str(e)
                continue

        rows: list[dict[str, object]] = []

        if isinstance(obj, list):
            for item in obj:
                if not isinstance(item, dict):
                    continue
                dstr = _parse_maybe_timestamp_to_ymd(item.get("day"))
                if not dstr:
                    continue
                try:
                    o = float(item.get("open"))
                    c = float(item.get("close"))
                    lo = float(item.get("low"))
                    hi_ = float(item.get("high"))
                    v_raw = item.get("volume")
                    v = float(v_raw) if v_raw is not None else 0.0
                except Exception:
                    continue
                rows.append({"date": dstr, "o": o, "c": c, "lo": lo, "hi": hi_, "v": v})

        else:
            arrays = pick_arrays(obj)
            if not arrays:
                continue

            days = arrays.get("day") or []
            opens = arrays.get("open") or []
            highs = arrays.get("high") or []
            lows = arrays.get("low") or []
            closes = arrays.get("close") or []
            vols = arrays.get("volume") or [0] * len(days)

            n = min(len(days), len(opens), len(highs), len(lows), len(closes), len(vols))
            if n <= 10:
                continue

            for i in range(n):
                dstr = _parse_maybe_timestamp_to_ymd(days[i])
                if not dstr:
                    continue
                try:
                    o = float(opens[i])
                    c = float(closes[i])
                    lo = float(lows[i])
                    hi_ = float(highs[i])
                    v = float(vols[i])
                except Exception:
                    continue
                rows.append({"date": dstr, "o": o, "c": c, "lo": lo, "hi": hi_, "v": v})

        if len(rows) <= 10:
            continue

        rows.sort(key=lambda r: r["date"])

        closes_all = [float(r["c"]) for r in rows]
        volumes_all = [float(r["v"]) for r in rows]
        dates_all = [str(r["date"]) for r in rows]
        candle_all = [
            [round(float(r["o"]), 4), round(float(r["c"]), 4), round(float(r["lo"]), 4), round(float(r["hi"]), 4)]
            for r in rows
        ]

        win = rows[-250:] if len(rows) >= 250 else rows
        try:
            hi = float(max(r["hi"] for r in win))
            lo = float(min(r["lo"] for r in win))
            last_close = float(closes_all[-1])
            pct = round((last_close - lo) / (hi - lo) * 100, 2) if hi > lo else 50.0
            pct = max(0.0, min(100.0, pct))
        except Exception:
            continue

        chart_n = min(90, len(closes_all))
        chart_closes = [round(x, 3) for x in closes_all[-chart_n:]]

        return {
            "symbol": code6,
            "closes": chart_closes,
            "dates": dates_all,
            "candle": candle_all,
            "volume": volumes_all,
            "high_52w": round(hi, 2),
            "low_52w": round(lo, 2),
            "percentile": pct,
            "last_close": round(last_close, 2),
            "trade_days": int(len(rows)),
            "update_time": _now_str(),
        }

    _fetch_daily_bars_sina.last_err = last_err
    return None


def _get_stock_daily_bars(symbol: str) -> dict | None:
    now_ts = time.time()
    cached = _STOCK_DAILY_BARS_CACHE.get(symbol)
    if cached and (now_ts - cached.get("ts", 0)) < _STOCK_DAILY_BARS_TTL_SEC:
        return cached.get("data")
    try:
        import akshare as ak
    except ImportError:
        return None
    def _tx_symbol(code6: str) -> str:
        return ("sh" if str(code6).startswith(("6", "9")) else "sz") + str(code6)

    df = None
    fetch_err = None
    fetch_errors: list[str] = []
    end_d = datetime.now().strftime("%Y%m%d")
    start_d = (datetime.now() - timedelta(days=380)).strftime("%Y%m%d")
    adjust_values = ["qfq", "bfq", "hfq"]

    for adjust in adjust_values:
        candidates: list[tuple[str, callable]] = []
        if hasattr(ak, "stock_zh_a_hist_em"):
            candidates.append((
                f"stock_zh_a_hist_em(adjust={adjust})",
                lambda adjust=adjust: ak.stock_zh_a_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=start_d,
                    end_date=end_d,
                    adjust=adjust,
                    timeout=20,
                ),
            ))
        if hasattr(ak, "stock_zh_a_hist"):
            candidates.append((
                f"stock_zh_a_hist(adjust={adjust})",
                lambda adjust=adjust: ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_d,
                    end_date=end_d,
                    adjust=adjust,
                    timeout=20,
                ),
            ))
        if hasattr(ak, "stock_zh_a_hist_tx"):
            candidates.append((
                f"stock_zh_a_hist_tx(adjust={adjust})",
                lambda adjust=adjust: ak.stock_zh_a_hist_tx(
                    symbol=_tx_symbol(symbol),
                    start_date=start_d,
                    end_date=end_d,
                    adjust=adjust,
                    timeout=20,
                ),
            ))

        for name, fn in candidates:
            try:
                df = fn()
                if df is not None and not getattr(df, "empty", True):
                    break
            except Exception as e:
                fetch_err = str(e)
                fetch_errors.append(f"{name}: {fetch_err}")
                df = None

        if df is not None and not getattr(df, "empty", True):
            break

    if df is None or getattr(df, "empty", True):
        sina = _fetch_daily_bars_sina(symbol)
        if sina:
            _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": sina}
            return sina
        return None

    dc = _df_pick_col(df, "日期")
    oc = _df_pick_col(df, "开盘")
    cc = _df_pick_col(df, "收盘")
    hc = _df_pick_col(df, "最高")
    lc = _df_pick_col(df, "最低")
    vc = _df_pick_col(df, "成交量")

    if not dc or not oc or not cc or not hc or not lc or not vc:
        cols = list(df.columns)
        lower = {str(c).lower(): c for c in cols}
        dc_en = lower.get("date")
        oc_en = lower.get("open")
        cc_en = lower.get("close")
        hc_en = lower.get("high")
        lc_en = lower.get("low")
        vc_en = lower.get("volume") or lower.get("amount")
        if dc_en and oc_en and cc_en and hc_en and lc_en and vc_en:
            dc, oc, cc, hc, lc, vc = dc_en, oc_en, cc_en, hc_en, lc_en, vc_en
        else:
            if len(cols) >= 7:
                dc = dc or cols[0]
                oc = oc or cols[2]
                cc = cc or cols[3]
                hc = hc or cols[4]
                lc = lc or cols[5]
                vc = vc or cols[6]

    if not dc or not oc or not cc or not hc or not lc or not vc:
        sina = _fetch_daily_bars_sina(symbol)
        if sina:
            _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": sina}
            return sina
        return None

    df = df.sort_values(dc).reset_index(drop=True)
    win = df.tail(250)
    try:
        hi = float(win[hc].astype(float).max())
        lo = float(win[lc].astype(float).min())
        closes_all = [float(x) for x in df[cc].astype(float).tolist()]
        last_close = closes_all[-1]
        pct = round((last_close - lo) / (hi - lo) * 100, 2) if hi > lo else 50.0
        pct = max(0.0, min(100.0, pct))
    except Exception:
        sina = _fetch_daily_bars_sina(symbol)
        if sina:
            _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": sina}
            return sina
        return None

    chart_n = min(90, len(closes_all))
    chart_closes = [round(x, 3) for x in closes_all[-chart_n:]]
    dates: list[str] = []
    candle: list[list[float]] = []
    volumes: list[float] = []
    try:
        for _, row in df.iterrows():
            ds = row[dc]
            dstr = str(ds)[:10] if ds is not None else ""
            dates.append(dstr)
            o = float(row[oc])
            c = float(row[cc])
            hi_ = float(row[hc])
            lo_ = float(row[lc])
            candle.append([round(o, 4), round(c, 4), round(lo_, 4), round(hi_, 4)])
            if vc:
                volumes.append(round(float(row[vc]), 2))
            else:
                volumes.append(0.0)
    except Exception:
        dates = []
        candle = []
        volumes = []

    data_payload = {
        "symbol": symbol,
        "closes": chart_closes,
        "dates": dates,
        "candle": candle,
        "volume": volumes,
        "high_52w": round(hi, 2),
        "low_52w": round(lo, 2),
        "percentile": pct,
        "last_close": round(last_close, 2),
        "trade_days": int(len(df)),
        "update_time": _now_str(),
    }

    _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": data_payload}
    return data_payload


def _fetch_market_a_share_overview():
    try:
        import akshare as ak
    except ImportError:
        return None
    data = {"update_time": _now_str(), "sse": None, "szse": None, "szse_trade_date": None}
    try:
        df = ak.stock_sse_summary()
        data["sse"] = _df_to_records(df)
    except Exception as e:
        data["sse_error"] = str(e)
    dates = [time.strftime("%Y%m%d"), (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")]
    for d in dates:
        try:
            df2 = ak.stock_szse_summary(date=d)
            rec = _df_to_records(df2)
            if rec:
                data["szse"] = rec
                data["szse_trade_date"] = d
                break
        except Exception as e:
            data["szse_error"] = str(e)
    return data
