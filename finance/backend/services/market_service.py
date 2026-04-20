import time
import uuid
import os
import threading
import re
from concurrent.futures import ThreadPoolExecutor
import requests
from utils.helpers import _now_str, _parse_symbol, _is_a_share_6digit, _to_float, _parse_sina_var
from services.stock_service import _fetch_a_share_quote, _get_stock_daily_bars, _fetch_hot_node, _get_a_share_search_index
from services.news_service import _fetch_news_live, fetch_akshare_stock_news
from services.llm_service import _invoke_llm_for_insight, _llm_repair_insight_json, _openai_compat_chat, _get_llm_env
from utils.helpers import _safe_bullets, _extract_json_object


_SESSIONS: dict[str, dict] = {}
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2)
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

PERCENTILE_DEFINITION_CN = (
    "近约250个交易日（约一年）窗口：取区间最低价与最高价，用最新收盘价在区间上的相对位置（百分比）；"
    "非市盈率或估值分位。"
)

DEFAULT_CHAT_FOLLOWUPS = [
    "如果按一个月维度看，关键拐点怎么判断？",
    "现在最该盯的两个风险变量是什么？",
    "给我一个更稳健的观察/应对思路。",
]

_SINA_HQ = requests.Session()
_SINA_HQ.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn",
    }
)

# Stooq 不需要新浪 Referer；部分网络环境带 Referer 反而更容易被拦/返回空
_STOOQ = requests.Session()
_STOOQ.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/plain,*/*",
    }
)


def _env_flag(name: str, default: bool = True) -> bool:
    v = str(os.environ.get(name, "1" if default else "0") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _safe_followups(items, max_items: int = 3):
    out = []
    if isinstance(items, list):
        for x in items:
            s = str(x).strip()
            if s and s not in out:
                out.append(s[:40])
            if len(out) >= max_items:
                break
    return out


def _detect_gold_market(question: str) -> str:
    q = str(question or "").strip().lower()
    if not q:
        return ""
    if not any(k in q for k in ("黄金", "金价", "国际金", "国内金", "xau", "伦敦金", "沪金", "au9999", "现货金")):
        return ""
    # 口径优先：国内关键词优先命中“国内金价”，否则默认“国际现货黄金”
    cn_keys = ("国内", "国内金", "人民币", "沪金", "上金所", "au9999", "上海金", "黄金td")
    intl_keys = ("现货", "伦敦", "国际", "国际金", "xau", "美元", "comex", "纽约金")
    if any(k in q for k in cn_keys):
        return "cn"
    if any(k in q for k in intl_keys):
        return "intl"
    return "intl"


def _is_price_question(question: str) -> bool:
    q = str(question or "").strip()
    if not q:
        return False
    return any(k in q for k in ("多少", "几", "报价", "价格", "点位", "多少钱", "实时", "现在"))


def _first_float(values, idxs):
    for idx in idxs:
        if idx < 0 or idx >= len(values):
            continue
        v = _to_float(values[idx], None)
        if v is not None:
            return float(v)
    return None


def _fetch_sina_hq_line(symbol: str) -> list[str]:
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        resp = _SINA_HQ.get(url, timeout=8)
        resp.encoding = "gbk"
        return _parse_sina_var(resp.text)
    except Exception:
        return []


def _extract_dt_from_fields(fields: list[str]) -> str:
    date_s = ""
    time_s = ""
    for raw in fields:
        s = str(raw or "").strip()
        if not date_s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            date_s = s
        if not time_s and re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", s):
            time_s = s
        if date_s and time_s:
            break
    return f"{date_s} {time_s}".strip()


def _fetch_gold_live_quote(question: str) -> dict | None:
    market = _detect_gold_market(question)
    if not market:
        return None

    ql = str(question or "").strip().lower()
    want_comex = ("comex" in ql) or ("gc" in ql) or ("纽约金" in ql)
    # 新浪公开行情：
    # - 若用户明确问 COMEX：优先 hf_GC（期货主连）
    # - 否则：优先 hf_XAU（更接近现货口径），再用 hf_GC 兜底
    # - 国内：沪金连续 nf_AU0
    if market == "intl":
        candidates = ["hf_GC", "hf_XAU"] if want_comex else ["hf_XAU", "hf_GC"]
    else:
        candidates = ["nf_AU0"]
    unit = "美元/盎司" if market == "intl" else "元/克"
    market_name = ("COMEX黄金期货" if want_comex else "国际现货黄金") if market == "intl" else "国内沪金连续"

    for sym in candidates:
        fields = _fetch_sina_hq_line(sym)
        if not fields:
            continue
        if sym.startswith("hf_"):
            # 示例：hf_XAU => [最新, 买, 卖, 今开, 最高, 最低, 时间, 昨结, ... , 日期, 名称]
            price = _first_float(fields, [0, 3, 1])
            prev_close = _first_float(fields, [7, 1])
            if not price or price <= 0:
                continue
            pct = ((price - prev_close) / prev_close * 100.0) if prev_close and prev_close > 0 else None
            update_time = _extract_dt_from_fields(fields) or _now_str()
            name = str(fields[-1] or "").strip() if fields else market_name
            return {
                "market": market,
                "market_name": market_name,
                "symbol": sym,
                "name": name or market_name,
                "price": round(float(price), 3),
                "pct_chg": round(float(pct), 3) if pct is not None else None,
                "unit": unit,
                "update_time": update_time,
                "source": "sina-hq",
            }
        if sym.startswith("nf_"):
            # 示例：nf_AU0 => [名称, ..., 今开, 最高, 最低, 最新/现价附近字段..., 日期, ...]
            price = _first_float(fields, [8, 6, 5, 2])
            prev_close = _first_float(fields, [6, 7, 2])
            if not price or price <= 0:
                continue
            pct = ((price - prev_close) / prev_close * 100.0) if prev_close and prev_close > 0 else None
            update_time = _extract_dt_from_fields(fields) or _now_str()
            name = str(fields[0] or "").strip() if fields else market_name
            return {
                "market": market,
                "market_name": market_name,
                "symbol": sym,
                "name": name or market_name,
                "price": round(float(price), 3),
                "pct_chg": round(float(pct), 3) if pct is not None else None,
                "unit": unit,
                "update_time": update_time,
                "source": "sina-hq",
            }
    return None


def _build_gold_quote_summary(quote: dict) -> str:
    pct = quote.get("pct_chg")
    pct_txt = f"{float(pct):+.3f}%" if pct is not None else "暂无涨跌幅"
    return (
        f"{quote.get('market_name')}（{quote.get('symbol')}）最新约 {quote.get('price')} {quote.get('unit')}，"
        f"涨跌幅 {pct_txt}。"
        f"数据源：新浪公开行情（{quote.get('source')}），时间：{quote.get('update_time')}。"
    )


_INDEX_SYMBOLS = [
    ("沪深300", "sh000300"),
    ("上证指数", "sh000001"),
    ("深证成指", "sz399001"),
    ("创业板指", "sz399006"),
    ("中证500", "sh000905"),
    ("中证1000", "sh000852"),
    ("中小100", "sz399005"),
    ("国证2000", "sz399303"),
]


def _detect_index_symbol(question: str) -> tuple[str, str] | None:
    q = str(question or "").strip().lower()
    if not q:
        return None
    alias = {
        "沪深300": ("沪深300", "sh000300"),
        "hs300": ("沪深300", "sh000300"),
        "000300": ("沪深300", "sh000300"),
        "上证": ("上证指数", "sh000001"),
        "上证指数": ("上证指数", "sh000001"),
        "上证综指": ("上证指数", "sh000001"),
        "深指": ("深证成指", "sz399001"),
        "深证": ("深证成指", "sz399001"),
        "深证成指": ("深证成指", "sz399001"),
        "创业板": ("创业板指", "sz399006"),
        "创业板指": ("创业板指", "sz399006"),
        "中证500": ("中证500", "sh000905"),
        "000905": ("中证500", "sh000905"),
        "中证1000": ("中证1000", "sh000852"),
        "000852": ("中证1000", "sh000852"),
    }
    for k, v in alias.items():
        if k in q:
            return v
    return None


def _fetch_index_live_quote(question: str) -> dict | None:
    hit = _detect_index_symbol(question)
    if not hit:
        return None
    market_name, sym = hit
    fields = _fetch_sina_hq_line(sym)
    if not fields:
        return None
    price = _first_float(fields, [3, 1, 0])
    open_p = _first_float(fields, [1])
    prev_close = _first_float(fields, [2])
    high = _first_float(fields, [4])
    low = _first_float(fields, [5])
    if not price or price <= 0:
        return None
    pct = ((price - prev_close) / prev_close * 100.0) if prev_close and prev_close > 0 else None
    update_time = _extract_dt_from_fields(fields) or _now_str()
    name = str(fields[0] or "").strip() if fields else market_name
    return {
        "market": "cn_index",
        "market_name": market_name,
        "symbol": sym,
        "name": name or market_name,
        "price": round(float(price), 3),
        "pct_chg": round(float(pct), 3) if pct is not None else None,
        "open": round(float(open_p), 3) if open_p is not None else None,
        "high": round(float(high), 3) if high is not None else None,
        "low": round(float(low), 3) if low is not None else None,
        "unit": "点",
        "update_time": update_time,
        "source": "sina-hq",
    }


def _build_live_quote_summary(quote: dict) -> str:
    pct = quote.get("pct_chg")
    pct_txt = f"{float(pct):+.3f}%" if pct is not None else "暂无涨跌幅"
    unit = str(quote.get("unit") or "").strip()
    unit_txt = f" {unit}" if unit else ""
    return (
        f"{quote.get('market_name')}（{quote.get('symbol')}）最新约 {quote.get('price')}{unit_txt}，"
        f"涨跌幅 {pct_txt}。"
        f"数据源：新浪公开行情（{quote.get('source')}），时间：{quote.get('update_time')}。"
    )


def _llm_enrich_live_quote(quote: dict, question: str, chat_history: list, llm_ready: bool) -> str:
    base = _build_live_quote_summary(quote)
    if not llm_ready:
        return base
    # 防止“看似合理但数字错误”的情况：若 LLM 输出中出现任何非 live_quote 的数字，直接回退 base
    def _allowed_number_tokens(q: dict) -> set[str]:
        out: set[str] = set()
        for k in ("price", "pct_chg"):
            v = q.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
            except Exception:
                continue
            # 常见格式：原样/两位/三位/四位、带符号百分比
            out.add(str(v))
            out.add(f"{fv:.4f}".rstrip("0").rstrip("."))
            out.add(f"{fv:.3f}".rstrip("0").rstrip("."))
            out.add(f"{fv:.2f}".rstrip("0").rstrip("."))
            out.add(f"{fv:.1f}".rstrip("0").rstrip("."))
            out.add(f"{fv:.0f}")
            out.add(f"{fv:+.4f}".rstrip("0").rstrip("."))
            out.add(f"{fv:+.3f}".rstrip("0").rstrip("."))
            out.add(f"{fv:+.2f}".rstrip("0").rstrip("."))
            out.add(f"{fv:+.1f}".rstrip("0").rstrip("."))
            out.add(f"{fv:+.0f}")
        # 时间戳允许出现日期/时间数字（不做数值校验）
        return {x for x in out if x}

    allowed = _allowed_number_tokens(quote)
    try:
        payload = {
            "question": str(question or "").strip(),
            "chat_history": chat_history or [],
            "live_quote": {
                "market_name": quote.get("market_name"),
                "symbol": quote.get("symbol"),
                "price": quote.get("price"),
                "pct_chg": quote.get("pct_chg"),
                "unit": quote.get("unit"),
                "update_time": quote.get("update_time"),
                "source": quote.get("source"),
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是金融研究助理。必须把 live_quote 当作唯一可信数字来源。"
                    "你只能做补充解读，禁止改写价格、涨跌幅、时间、单位。"
                    "若需要复述数字，必须与 live_quote 完全一致。"
                    "严格要求：除 live_quote.price 与 live_quote.pct_chg 外，summary 中禁止出现其它任何数字（包括区间、目标位、历史高低、换算、推算）。"
                    "输出 JSON：summary(字符串) + followUps(2-3条字符串数组)。禁止 Markdown。"
                ),
            },
            {"role": "user", "content": str(payload)},
        ]
        content = _openai_compat_chat(messages, max_tokens=240, temperature=0.2)
        obj = _extract_json_object(content) or {}
        s = str(obj.get("summary") or "").strip()
        if s:
            # 数字一致性校验：如果出现任何“看起来像数字”的片段且不在 allowed 集合里，回退
            tokens = re.findall(r"(?<!\d)(?:\d+\.\d+|\d+)(?!\d)", s)
            bad = []
            for t in tokens:
                # 过滤日期时间（YYYY-MM-DD / HH:MM:SS）中的数字片段：允许出现
                if "-" in s or ":" in s:
                    # 粗过滤：如果该 token 周围 2 个字符内包含 '-' 或 ':'，认为是时间日期的一部分
                    idx = s.find(t)
                    if idx != -1:
                        ctx = s[max(0, idx - 2) : min(len(s), idx + len(t) + 2)]
                        if ("-" in ctx) or (":" in ctx):
                            continue
                if t not in allowed:
                    bad.append(t)
            if bad:
                return base
            return s
    except Exception:
        pass
    return base


def _llm_enrich_history_summary(quote: dict, question: str, verified_summary: str, chat_history: list, llm_ready: bool) -> str:
    if not llm_ready:
        return verified_summary
    try:
        payload = {
            "question": str(question or "").strip(),
            "chat_history": chat_history or [],
            "verified_summary": str(verified_summary or "").strip(),
            "live_quote": {
                "market_name": quote.get("market_name"),
                "symbol": quote.get("symbol"),
                "price": quote.get("price"),
                "pct_chg": quote.get("pct_chg"),
                "unit": quote.get("unit"),
                "update_time": quote.get("update_time"),
                "source": quote.get("source"),
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是金融研究助理。必须基于 verified_summary 与 live_quote 回答。"
                    "可以做趋势解读，但禁止新增任何未在 verified_summary/live_quote 出现的数字。"
                    "输出 JSON：summary(字符串) + followUps(2-3条字符串数组)。禁止 Markdown。"
                ),
            },
            {"role": "user", "content": str(payload)},
        ]
        content = _openai_compat_chat(messages, max_tokens=320, temperature=0.2)
        obj = _extract_json_object(content) or {}
        s = str(obj.get("summary") or "").strip()
        if not s:
            return verified_summary
        # 数字护栏：LLM 输出中的数字必须来自 verified_summary 或 live_quote 两者
        allowed_src = f"{verified_summary} {_build_live_quote_summary(quote)}"
        allowed_nums = set(re.findall(r"(?<!\d)(?:\d+\.\d+|\d+)(?!\d)", allowed_src))
        out_nums = re.findall(r"(?<!\d)(?:\d+\.\d+|\d+)(?!\d)", s)
        for n in out_nums:
            if n not in allowed_nums:
                return verified_summary
        return s
    except Exception:
        return verified_summary


def _is_history_scope_question(question: str) -> bool:
    q = str(question or "").strip()
    if not q:
        return False
    keys = (
        "历史",
        "最高",
        "最低",
        "趋势",
        "走势",
        "区间",
        "最近一周",
        "近一周",
        "近1月",
        "近一个月",
        "近一月",
        "近10日",
        "近20日",
        "过去",
        "此前",
        "之前",
        "去年",
        "今年以来",
        "近半年",
        "近一年",
    )
    return any(k in q for k in keys)


def _build_history_scope_guard(quote: dict) -> str:
    return (
        f"{_build_live_quote_summary(quote)}"
        "你问的是历史/区间口径（如最高位、近1个月涨幅）。"
        "当前问答链路已接实时行情，但本次未能拉取到可用的历史序列数据（可能是数据源超时/被拦/暂不可用）；"
        "为避免误导，我先不给未经验证的历史数字。"
    )


def _fetch_stooq_daily_series(symbol: str, max_rows: int = 500) -> tuple[list[str], list[float]]:
    try:
        r = _STOOQ.get(
            "https://stooq.com/q/d/l/",
            params={"s": str(symbol or "").strip().lower(), "i": "d"},
            timeout=10,
        )
        r.raise_for_status()
        lines = [x.strip() for x in str(r.text or "").splitlines() if x.strip()]
        if len(lines) < 2:
            return [], []
        head = [h.strip().lower() for h in lines[0].split(",")]
        try:
            i_date = head.index("date")
            i_close = head.index("close")
        except ValueError:
            return [], []
        dates: list[str] = []
        closes: list[float] = []
        for ln in lines[1: max_rows + 1]:
            parts = [x.strip() for x in ln.split(",")]
            if len(parts) <= max(i_date, i_close):
                continue
            c = _to_float(parts[i_close], None)
            if c is None:
                continue
            dates.append(parts[i_date])
            closes.append(float(c))
        return dates, closes
    except Exception:
        return [], []


def _pick_window_days_by_question(question: str, series_len: int) -> tuple[int, str]:
    qn = str(question or "")
    n = max(2, int(series_len or 2))
    m = re.search(r"近\s*(\d+)\s*(日|天|周|个月|月|年)", qn)
    if m:
        num = max(1, int(m.group(1)))
        unit = m.group(2)
        if unit in ("日", "天"):
            return min(n - 1, max(1, num)), f"近{num}日"
        if unit == "周":
            return min(n - 1, max(1, num * 5)), f"近{num}周"
        if unit in ("个月", "月"):
            return min(n - 1, max(1, num * 22)), f"近{num}个月"
        if unit == "年":
            return min(n - 1, max(1, num * 250)), f"近{num}年"
    table = [
        (("近一周", "这周", "最近一周"), 5, "近1周"),
        (("近两周", "最近两周"), 10, "近2周"),
        (("近10日", "近十日", "最近10天"), 10, "近10日"),
        (("近20日", "近二十日"), 20, "近20日"),
        (("近1月", "近一个月", "近一月", "一个月", "1个月"), 22, "近1个月"),
        (("近3月", "近三个月", "近季度"), 66, "近3个月"),
        (("近半年", "半年"), 120, "近半年"),
        (("近1年", "近一年", "一年", "今年以来"), 250, "近1年"),
        (("近2年", "近两年"), 500, "近2年"),
    ]
    for keys, days, label in table:
        if any(k in qn for k in keys):
            return min(n - 1, max(1, days)), label
    return min(n - 1, 22), "近1个月"


def _verified_history_summary(question: str, quote: dict) -> str:
    sym = str(quote.get("symbol") or "").strip().lower()
    q = str(question or "").strip()
    dates: list[str] = []
    closes: list[float] = []

    # A 股：直接用现有个股历史接口（已在项目内稳定使用）
    digits = "".join(ch for ch in sym if ch.isdigit())
    if len(digits) >= 6 and digits[-6:].isdigit():
        code6 = digits[-6:]
        try:
            daily = _get_stock_daily_bars(code6) or {}
        except Exception:
            daily = {}
        d = daily.get("dates") or []
        c = daily.get("closes") or []
        if isinstance(d, list) and isinstance(c, list) and len(d) == len(c) and len(c) >= 2:
            dates = [str(x) for x in d]
            closes = [float(_to_float(x, 0.0) or 0.0) for x in c]

    # 商品：用 Stooq 日线做历史区间统计
    if not closes:
        stooq_map = {"hf_xau": "xauusd", "hf_si": "xagusd", "hf_cl": "cl.f"}
        if sym in stooq_map:
            dates, closes = _fetch_stooq_daily_series(stooq_map[sym], max_rows=520)

    if not closes or len(closes) < 2:
        return ""

    pairs = [(d, c) for d, c in zip(dates, closes) if c > 0]
    if len(pairs) < 2:
        return ""
    dates = [x[0] for x in pairs]
    closes = [x[1] for x in pairs]

    last_p = closes[-1]
    last_d = dates[-1]
    window, window_label = _pick_window_days_by_question(q, len(closes))
    base_p = closes[-1 - window]
    win_pct = ((last_p - base_p) / base_p * 100.0) if base_p > 0 else None

    win_slice = closes[-(window + 1):]
    win_dates = dates[-(window + 1):]
    w_max_i = max(range(len(win_slice)), key=lambda i: win_slice[i])
    w_min_i = min(range(len(win_slice)), key=lambda i: win_slice[i])
    w_max_p, w_max_d = win_slice[w_max_i], win_dates[w_max_i]
    w_min_p, w_min_d = win_slice[w_min_i], win_dates[w_min_i]
    max_i = max(range(len(closes)), key=lambda i: closes[i])
    min_i = min(range(len(closes)), key=lambda i: closes[i])
    max_p, max_d = closes[max_i], dates[max_i]
    min_p, min_d = closes[min_i], dates[min_i]

    unit = str(quote.get("unit") or "").strip()
    unit_txt = f" {unit}" if unit else ""
    mkt = str(quote.get("market_name") or quote.get("name") or sym)

    if any(k in q for k in ("最高", "高点", "最高位")):
        return f"{mkt}可验证历史样本最高收盘约为 {max_p:.4f}{unit_txt}（{max_d}），当前最新约 {last_p:.4f}{unit_txt}（{last_d}）。"
    if any(k in q for k in ("最低", "低点", "最低位")):
        return f"{mkt}可验证历史样本最低收盘约为 {min_p:.4f}{unit_txt}（{min_d}），当前最新约 {last_p:.4f}{unit_txt}（{last_d}）。"
    if win_pct is not None:
        return f"{mkt}{window_label}（约{window}个交易日）收盘累计约 {win_pct:+.2f}%，区间最高收盘 {w_max_p:.4f}{unit_txt}（{w_max_d}），最低收盘 {w_min_p:.4f}{unit_txt}（{w_min_d}）。"
    return f"{mkt}当前最新约 {last_p:.4f}{unit_txt}（{last_d}），{window_label}区间最高收盘 {w_max_p:.4f}{unit_txt}（{w_max_d}），最低收盘 {w_min_p:.4f}{unit_txt}（{w_min_d}）。"


def _normalize_query_text(text: str) -> str:
    q = str(text or "").strip().lower()
    if not q:
        return ""
    # 轻量归一化：去语气词/空白，避免“国际金呢”“今天的沪深300行情怎么样”这类漏识别
    q = re.sub(r"\s+", "", q)
    for w in ("呢", "啊", "呀", "吧", "吗", "么", "请问", "帮我", "看看", "一下", "今天", "今日", "现在", "目前", "行情", "报价", "价格", "多少", "几点", "点位"):
        q = q.replace(w, "")
    return q


def _keyword_hit(q_norm: str, key: str) -> bool:
    k = str(key or "").strip().lower()
    if not k:
        return False
    if k in q_norm:
        return True
    # “黄金/国际金/现货金”这类写法做统一兜底，减少手写别名
    if "金" in k and (("国际" in k and ("国际金" in q_norm or "国际黄金" in q_norm)) or ("国内" in k and ("国内金" in q_norm or "国内黄金" in q_norm))):
        return True
    return False


_QUOTE_KEYWORD_LIBRARY = [
    {"keys": ("沪深300", "hs300"), "symbol": "sh000300", "name": "沪深300", "unit": "点"},
    {"keys": ("上证指数", "上证综指", "上证"), "symbol": "sh000001", "name": "上证指数", "unit": "点"},
    {"keys": ("深证成指", "深指", "深证"), "symbol": "sz399001", "name": "深证成指", "unit": "点"},
    {"keys": ("创业板指", "创业板"), "symbol": "sz399006", "name": "创业板指", "unit": "点"},
    {"keys": ("中证500",), "symbol": "sh000905", "name": "中证500", "unit": "点"},
    {"keys": ("中证1000",), "symbol": "sh000852", "name": "中证1000", "unit": "点"},
    {"keys": ("道琼斯", "道指"), "symbol": "gb_dji", "name": "道琼斯指数", "unit": "点"},
    {"keys": ("纳斯达克", "纳指"), "symbol": "gb_ixic", "name": "纳斯达克指数", "unit": "点"},
    {"keys": ("标普500", "标普"), "symbol": "gb_inx", "name": "标普500", "unit": "点"},
    {"keys": ("comex黄金", "comex金", "gc黄金", "纽约金"), "symbol": "hf_GC", "name": "COMEX黄金期货", "unit": "美元/盎司"},
    {"keys": ("现货黄金", "伦敦金", "伦敦现货金", "国际黄金", "国际金", "xau"), "symbol": "hf_XAU", "name": "国际现货黄金", "unit": "美元/盎司"},
    {"keys": ("国内黄金", "国内金", "沪金", "au9999"), "symbol": "nf_AU0", "name": "国内沪金连续", "unit": "元/克"},
    {"keys": ("现货白银", "白银", "xag"), "symbol": "hf_SI", "name": "国际白银", "unit": "美元/盎司"},
    {"keys": ("原油", "wti", "美油"), "symbol": "hf_CL", "name": "WTI原油", "unit": "美元/桶"},
    {"keys": ("美元人民币", "usdcny", "汇率"), "symbol": "USDCNY", "name": "美元兑人民币", "unit": ""},
]


def _normalize_symbol_candidates(raw_symbol: str) -> list[str]:
    s_raw = str(raw_symbol or "").strip().strip('"').strip("'").strip()
    if not s_raw:
        return []
    s_lower = s_raw.lower()
    candidates = [s_raw, s_lower]
    if s_lower.startswith("hf_") and len(s_lower) > 3:
        suffix = s_raw[3:] if s_raw.lower().startswith("hf_") else s_lower[3:]
        if suffix:
            candidates.insert(0, f"hf_{suffix.upper()}")
    if s_lower.startswith("nf_") and len(s_lower) > 3:
        suffix = s_raw[3:] if s_raw.lower().startswith("nf_") else s_lower[3:]
        if suffix:
            candidates.insert(0, f"nf_{suffix.upper()}")
    if len(s_lower) == 6 and s_lower.isdigit():
        if s_lower.startswith("92"):
            candidates.insert(0, f"bj{s_lower}")
        elif s_lower.startswith(("6", "9")):
            candidates.insert(0, f"sh{s_lower}")
        elif s_lower.startswith(("0", "2", "3")):
            candidates.insert(0, f"sz{s_lower}")
        elif s_lower.startswith(("4", "8")):
            candidates.insert(0, f"bj{s_lower}")
    if len(s_lower) == 5 and s_lower.isdigit():
        candidates.insert(0, f"hk{s_lower}")
    if s_lower.isalpha() and 1 <= len(s_lower) <= 12 and not s_lower.startswith(("sh", "sz", "bj", "hk", "gb", "hf", "nf")):
        candidates.insert(0, f"gb_{s_lower}")
    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _parse_sina_realtime_quote(symbol: str, fields: list[str]) -> dict | None:
    if not fields:
        return None
    sym = str(symbol or "").strip().lower()
    now = _now_str()
    update_time = _extract_dt_from_fields(fields) or now
    if sym.startswith("gb_"):
        name = str(fields[0] or symbol).strip()
        price = _first_float(fields, [1, 0])
        open_p = _first_float(fields, [5])
        high = _first_float(fields, [6])
        low = _first_float(fields, [7])
        chg = _first_float(fields, [2])
        prev_close = (float(price) - float(chg)) if (price is not None and chg is not None) else None
    elif sym.startswith("hk"):
        name = str((fields[1] if len(fields) > 1 and fields[1] else fields[0]) or symbol).strip()
        open_p = _first_float(fields, [2])
        price = _first_float(fields, [3, 6, 2])
        high = _first_float(fields, [4])
        low = _first_float(fields, [5])
        prev_close = _first_float(fields, [9, 3, 2])
    elif sym.startswith("hf_") or sym.startswith("nf_"):
        name = str((fields[-1] if sym.startswith("hf_") else fields[0]) or symbol).strip()
        price = _first_float(fields, [0, 8, 6, 5, 2, 1])
        open_p = _first_float(fields, [3, 2])
        high = _first_float(fields, [4, 3])
        low = _first_float(fields, [5, 4])
        prev_close = _first_float(fields, [7, 2, 1])
    else:
        name = str(fields[0] or symbol).strip()
        open_p = _first_float(fields, [1])
        prev_close = _first_float(fields, [2])
        price = _first_float(fields, [3, 2, 1])
        high = _first_float(fields, [4])
        low = _first_float(fields, [5])
    if price is None:
        return None
    if (price <= 0) and (prev_close is not None and prev_close > 0):
        price = float(prev_close)
    if price <= 0:
        return None
    chg = float(price) - float(prev_close) if (prev_close is not None and prev_close > 0) else None
    pct = (chg / float(prev_close) * 100.0) if (chg is not None and prev_close and prev_close > 0) else None
    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": round(float(price), 4),
        "open": round(float(open_p), 4) if open_p is not None else None,
        "high": round(float(high), 4) if high is not None else None,
        "low": round(float(low), 4) if low is not None else None,
        "pct_chg": round(float(pct), 3) if pct is not None else None,
        "update_time": update_time,
        "source": "sina-hq",
    }


def _extract_quote_target(question: str) -> dict | None:
    q = str(question or "").strip()
    if not q:
        return None
    ql = q.lower()
    qn = _normalize_query_text(q)
    m = re.search(r"\b((?:sh|sz|bj)\d{6}|hk\d{5}|(?:hf|nf)_[a-z0-9]+|gb_[a-z0-9]+|usdcny)\b", ql)
    if m:
        sym = m.group(1)
        return {"symbol": sym, "name": sym.upper(), "unit": ""}
    m6 = re.search(r"\b(\d{6})\b", q)
    if m6:
        return {"symbol": m6.group(1), "name": m6.group(1), "unit": ""}
    for item in _QUOTE_KEYWORD_LIBRARY:
        if any(_keyword_hit(qn, k) for k in item["keys"]):
            return {"symbol": item["symbol"], "name": item["name"], "unit": item["unit"]}
    return None


def _build_quote_context_text(question: str, history: list[dict] | None) -> str:
    q = str(question or "").strip()
    if not isinstance(history, list) or not history:
        return q
    recent = []
    for row in history[-6:]:
        if not isinstance(row, dict):
            continue
        # 只用用户输入做上下文承接，避免把助手回答里的股票代码/数字当成新的标的
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        txt = str(row.get("text") or "").strip()
        if txt:
            recent.append(txt[:120])
    if not recent:
        return q
    # 当前问题放最前，后接最近上下文，便于“那国际金呢/那这个最高呢”这类追问承接标的
    return f"{q} | {' | '.join(recent)}"


def _fetch_realtime_quote_by_question(question: str, history: list[dict] | None = None) -> tuple[dict | None, bool]:
    target = _extract_quote_target(question)
    if not target:
        target = _extract_quote_target(_build_quote_context_text(question, history))
    if not target:
        return None, False
    candidates = _normalize_symbol_candidates(str(target.get("symbol") or ""))
    for sym in candidates:
        fields = _fetch_sina_hq_line(sym)
        quote = _parse_sina_realtime_quote(sym, fields)
        if not quote:
            continue
        quote["market_name"] = str(target.get("name") or quote.get("name") or sym)
        quote["unit"] = str(target.get("unit") or "")
        return quote, True
    # 多源兜底：新浪不可用时，按品种回退到 Stooq / AkShare
    fb = _fetch_realtime_quote_fallback(
        symbol=str(target.get("symbol") or ""),
        market_name=str(target.get("name") or ""),
        unit=str(target.get("unit") or ""),
    )
    if fb:
        return fb, True
    return None, True


def _parse_stooq_ohlcv_csv(text: str) -> dict | None:
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    if not lines:
        return None
    if len(lines) >= 2 and "Close" in lines[0]:
        cols = [x.strip() for x in lines[0].split(",")]
        vals = [x.strip() for x in lines[1].split(",")]
        row = dict(zip(cols, vals))
        close = _to_float(row.get("Close"), None)
        if close is None:
            return None
        return {
            "date": str(row.get("Date") or "").strip(),
            "time": str(row.get("Time") or "").strip(),
            "open": _to_float(row.get("Open"), None),
            "high": _to_float(row.get("High"), None),
            "low": _to_float(row.get("Low"), None),
            "close": float(close),
        }
    parts = [x.strip() for x in lines[0].split(",")]
    if len(parts) < 7:
        return None
    close = _to_float(parts[6], None)
    if close is None:
        return None
    return {
        "date": parts[1] or "",
        "time": parts[2] or "",
        "open": _to_float(parts[3], None),
        "high": _to_float(parts[4], None),
        "low": _to_float(parts[5], None),
        "close": float(close),
    }


def _fetch_stooq_ohlc(symbol: str) -> dict | None:
    try:
        r = _STOOQ.get(
            "https://stooq.com/q/l/",
            params={"s": str(symbol or "").strip().lower(), "f": "sd2t2ohlcv", "e": "csv"},
            timeout=8,
        )
        r.raise_for_status()
        return _parse_stooq_ohlcv_csv(r.text)
    except Exception:
        return None


def _fetch_realtime_quote_fallback(symbol: str, market_name: str, unit: str) -> dict | None:
    sym = str(symbol or "").strip().lower()
    # 商品优先 Stooq（demo2 同类来源）
    stooq_map = {
        "hf_xau": ("xauusd", "美元/盎司"),
        "hf_si": ("xagusd", "美元/盎司"),
        "hf_cl": ("cl.f", "美元/桶"),
    }
    if sym in stooq_map:
        stooq_symbol, default_unit = stooq_map[sym]
        row = _fetch_stooq_ohlc(stooq_symbol)
        if row and _to_float(row.get("close"), 0.0):
            price = float(_to_float(row.get("close"), 0.0) or 0.0)
            open_p = _to_float(row.get("open"), None)
            pct = ((price - float(open_p)) / float(open_p) * 100.0) if (open_p is not None and float(open_p) > 0) else None
            return {
                "symbol": symbol,
                "name": market_name or symbol,
                "market_name": market_name or symbol,
                "price": round(price, 4),
                "open": round(float(open_p), 4) if open_p is not None else None,
                "high": round(float(_to_float(row.get("high"), 0.0) or 0.0), 4) if row.get("high") is not None else None,
                "low": round(float(_to_float(row.get("low"), 0.0) or 0.0), 4) if row.get("low") is not None else None,
                "pct_chg": round(float(pct), 3) if pct is not None else None,
                "update_time": f"{row.get('date', '')} {row.get('time', '')}".strip() or _now_str(),
                "source": "stooq-csv",
                "unit": unit or default_unit,
            }

    # A 股代码兜底：沿用已有 AkShare fallback（_fetch_a_share_quote 内部已多源）
    if sym.isdigit() and len(sym) == 6:
        try:
            q = _fetch_a_share_quote(sym)
        except Exception:
            q = None
        if q and _to_float(q.get("price"), 0.0):
            prev_close = _to_float(q.get("prev_close"), None)
            price = float(_to_float(q.get("price"), 0.0) or 0.0)
            pct = _to_float(q.get("pct_chg"), None)
            if pct is None and prev_close and prev_close > 0:
                pct = (price - float(prev_close)) / float(prev_close) * 100.0
            return {
                "symbol": sym,
                "name": str(q.get("name") or market_name or sym),
                "market_name": market_name or str(q.get("name") or sym),
                "price": round(price, 4),
                "open": _to_float(q.get("open"), None),
                "high": _to_float(q.get("high"), None),
                "low": _to_float(q.get("low"), None),
                "pct_chg": round(float(pct), 3) if pct is not None else None,
                "update_time": str(q.get("update_time") or _now_str()),
                "source": str(q.get("source") or "akshare-fallback"),
                "unit": unit or "",
            }
    return None


def _headlines_for_symbol(symbol: str, name: str, global_news: list, hot_rows: list) -> list[dict]:
    sym = str(symbol or "").strip()
    nm = (str(name or "").strip()).replace(" ", "").replace("\u3000", "")
    hits: list[dict] = []
    seen: set[str] = set()

    def push(title: str, source: str) -> None:
        t = (title or "").strip()
        if len(t) < 4 or t in seen:
            return
        seen.add(t)
        hits.append({"title": t[:220], "source": str(source or "快讯")[:32]})

    for r in hot_rows or []:
        if not isinstance(r, dict):
            continue
        ld = str(r.get("leader") or "")
        digits = "".join(ch for ch in ld if ch.isdigit())
        code6 = digits[-6:] if len(digits) >= 6 else digits
        if sym and code6 == sym:
            pc = _to_float(r.get("pct_chg"), 0.0) or 0.0
            hn = str(r.get("name") or nm or sym).strip()
            push(f"热力榜：{hn}（{sym}）涨跌幅约 {pc:+.2f}%", "市场热力")

    for it in global_news or []:
        if not isinstance(it, dict):
            continue
        blob = f"{it.get('title') or ''}{it.get('summary') or ''}"
        hit = bool(sym) and sym in blob
        if not hit and nm and len(nm) >= 2 and nm in blob:
            hit = True
        if hit:
            push(str(it.get("title") or it.get("summary") or "")[:200], str(it.get("source") or "快讯"))

    return hits[:8]


def _insight_response_meta(symbol_hit_count: int, stock_news_count: int = 0) -> dict:
    return {
        "percentileDefinition": PERCENTILE_DEFINITION_CN,
        "symbolHeadlineCount": symbol_hit_count,
        "stockNewsCount": stock_news_count,
    }


def get_stock_llm_insight(symbol: str):
    try:
        quote = _fetch_a_share_quote(symbol) or {}
    except Exception as e:
        quote = {}

    daily = None
    now_bar_ts = time.time()
    try:
        daily = _get_stock_daily_bars(symbol)
    except Exception:
        daily = None

    hot = []
    try:
        rows = _fetch_hot_node("sh_a", 30) + _fetch_hot_node("sz_a", 30)
        seen = set()
        uniq = []
        for x in rows:
            k = str(x.get("leader") or "")
            if not k or k in seen:
                continue
            seen.add(k)
            uniq.append(x)
        uniq.sort(key=lambda x: _to_float(x.get("pct_chg"), -9999) or -9999, reverse=True)
        hot = uniq[:8]
    except Exception:
        hot = []

    global_news = []
    try:
        items = _fetch_news_live(page=1, num=22) or []
        global_news = items[:18]
    except Exception:
        global_news = []

    stock_specific_news = []
    try:
        stock_items = fetch_akshare_stock_news(symbol=symbol, limit=8)
        if stock_items:
            stock_specific_news = [
                {"title": x.get("title"), "summary": x.get("summary"), "source": x.get("source"), "url": x.get("url"), "ctime": x.get("ctime")}
                for x in stock_items
            ]
    except Exception:
        stock_specific_news = []

    if not daily or not isinstance(daily, dict) or not daily.get("dates") or not daily.get("candle"):
        return None

    name = str(quote.get("name") or symbol or "").strip() or symbol
    pct_chg = float(quote.get("pct_chg") or 0.0)
    price = quote.get("price") or daily.get("last_close") or 0.0

    closes = daily.get("closes") or []
    def _pct(a, b):
        try:
            a = float(a)
            b = float(b)
            if b == 0:
                return 0.0
            return (a - b) / b * 100.0
        except Exception:
            return 0.0

    last_close = daily.get("last_close") or 0.0
    change_10 = _pct(closes[-1], closes[-11]) if isinstance(closes, list) and len(closes) >= 12 else 0.0
    change_20 = _pct(closes[-1], closes[-21]) if isinstance(closes, list) and len(closes) >= 22 else 0.0

    hi_52w = daily.get("high_52w") or 0.0
    lo_52w = daily.get("low_52w") or 0.0
    percentile = round(float(daily.get("percentile") or 0.0), 2)

    symbol_headlines = _headlines_for_symbol(symbol, name, global_news + stock_specific_news, hot)
    insight_meta = _insight_response_meta(len(symbol_headlines), len(stock_specific_news))
    stock_ai_enabled = _env_flag("STOCK_LLM_AI_ENABLED", True)

    user_msg = {
        "symbol": symbol,
        "name": name,
        "quote": {
            "price": price,
            "pct_chg": pct_chg,
            "high": quote.get("high"),
            "low": quote.get("low"),
            "open": quote.get("open"),
        },
        "historical": {
            "last_close": last_close,
            "percentile": percentile,
            "high_52w": hi_52w,
            "low_52w": lo_52w,
            "change_10d_pct": round(change_10, 2),
            "change_20d_pct": round(change_20, 2),
            "dates_tail": daily.get("dates", [])[-6:],
        },
        "constraints": {
            "percentile_definition": PERCENTILE_DEFINITION_CN,
            "valuation_fields_missing": True,
            "symbol_headlines_matched": len(symbol_headlines),
            "stock_news_count": len(stock_specific_news),
        },
        "recent_headlines_for_symbol": symbol_headlines,
        "stock_specific_news": stock_specific_news[:6],
        "news_trend": {
            "hot_topics": hot,
            "global_news_tail": [
                {"title": x.get("title"), "summary": x.get("summary")} for x in global_news if isinstance(x, dict)
            ],
        },
        "task": {
            "aiInsightList": "生成 3-5条简短研判：把行情/趋势/历史分位/10/20日动量串起来；若 recent_headlines_for_symbol 或 stock_specific_news 非空，必须引用至少1条具体新闻事件作为依据，每条不超过60字",
            "suggestionList": "生成 3条未持仓操作建议：若 stock_specific_news 非空，需结合新闻事件给出针对性建议；包含观察要点与风控口径，每条不超过60字；不构成投资建议",
            "quickQuestionList": '再生成 3个更聚焦该股票的追问问题（不构成投资建议）；每个问题不超过30字。每个问题必须与该股票的近一年分位/10/20日动量/52周回撤或关键支撑压力相关；并优先包含该股票简称(name)或至少包含"该股"。不要套用固定模板词（如"财报不及预期/同业对比/最大风险情景"）；若 recent_headlines_for_symbol 和 stock_specific_news 中都不包含"财报/业绩/公告/年报/一季报/利润"等关键词，则禁止出现财报类措辞。禁止出现连续6位数字。'
        },
    }

    system_msg = (
        "你是金融研究助理。用户给的是该股客观数据 JSON。"
        "你必须只输出一个 JSON 对象，且仅含键 aiInsightList、suggestionList、quickQuestionList；值均为中文字符串数组。"
        "aiInsightList：3-5 条；suggestionList：3 条「未持仓」建议，须至少一条明确写出股票简称或代码；每条≤60字。"
        "quickQuestionList：3 条；每条≤30字；每条必须包含该股票简称(name)或“该股”，且必须与行情/历史特征相关；禁止使用与该股票无关的泛化问题。"
        "historical.percentile 的含义见 constraints.percentile_definition。引用分位时仅可使用与 historical.percentile 相同的数值（可格式化为两位小数，如 52.35），禁止改用其它分位。"
        "若 constraints.valuation_fields_missing 为 true：禁止使用「估值偏高/偏低/合理/泡沫/中性偏高/市盈率/PE」等字样。"
        "若 recent_headlines_for_symbol 为空数组：禁止断言「无热点新闻」「板块关注度低」「缺乏资金」等；应表述为未在给定快讯列表中检索到该股相关标题，结论以技术面为主。"
        "若 recent_headlines_for_symbol 非空：可简要引用其中事实，勿编造未出现的公告或数据。"
        "若 stock_specific_news 非空：这是从东方财富获取的该股票专属新闻（标题+摘要），你必须在 aiInsightList 中至少引用1条具体新闻事件作为研判依据，并在 suggestionList 中结合这些新闻给出针对性建议。"
        "若 stock_specific_news 为空：则不提及个股新闻，仅基于行情/技术面分析。"
        "禁止 Markdown、禁止代码围栏、禁止输出 JSON 以外的任何字符。"
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": str(user_msg)},
    ]

    # 环境开关：关闭个股页 LLM，避免每次进入页面消耗 token
    if not stock_ai_enabled:
        lines = [
            f"{name} 当前涨跌幅 {pct_chg:+.2f}%，结合历史分位与近 10/20 日动量，短期以结构性波动为主。",
            f"当前处于近一年收盘价区间相对分位 {percentile:.2f}%（非估值分位），上行需看趋势延续，下行需关注回撤承接。",
            "AI 已关闭：当前为规则摘要模式（不消耗大模型 token）。",
        ]
        suggestions = [
            "未持仓：等待关键位附近的放量/承接确认，再分批参与。",
            "设置明确的止损/止盈规则，避免单次波动影响整体计划。",
            "若走势与量能背离，提高观望权重并减少追涨。",
        ]
        quick_list = [
            "结合当前分位与 10/20 日动量，下一步走势更偏哪边？",
            "52 周回撤下，最该盯的支撑/压力信号是什么？",
            "若继续偏弱，未持仓者如何控风险与等信号？",
        ]
        return {
            "aiInsightList": lines[:5],
            "suggestionList": suggestions[:3],
            "quickQuestionList": quick_list,
            "meta": insight_meta,
            "stockNews": stock_specific_news[:8],
        }

    try:
        content = _invoke_llm_for_insight(messages)
        obj = _extract_json_object(content) or {}
        ai_list = _safe_bullets(obj.get("aiInsightList"), max_items=5)
        sug_list = _safe_bullets(obj.get("suggestionList"), max_items=3)
        quick_list = _safe_bullets(obj.get("quickQuestionList"), max_items=3)

        if (not ai_list or not sug_list) and content:
            fixed = _llm_repair_insight_json(content)
            if isinstance(fixed, dict):
                if not ai_list:
                    ai_list = _safe_bullets(fixed.get("aiInsightList"), max_items=5)
                if not sug_list:
                    sug_list = _safe_bullets(fixed.get("suggestionList"), max_items=3)
                if not quick_list:
                    quick_list = _safe_bullets(fixed.get("quickQuestionList"), max_items=3)

        if not ai_list or not sug_list:
            messages_fix = messages + [
                {"role": "assistant", "content": (content or "")[:6500]},
                {
                    "role": "user",
                    "content": (
                        "上一段无法解析为 JSON。请仅输出一个 JSON 对象，键 aiInsightList（3-5条）、suggestionList（3条）与 quickQuestionList（3条）。"
                        f"内容必须针对 {name}（{symbol}），并体现近一年分位{percentile:.2f}%（勿改此分位）、涨跌幅{pct_chg:+.2f}%、"
                        f"10日收益约{change_10:+.2f}%与20日约{change_20:+.2f}%。不要其它文字。"
                    ),
                },
            ]
            content2 = _invoke_llm_for_insight(messages_fix)
            obj2 = _extract_json_object(content2) or {}
            if not ai_list:
                ai_list = _safe_bullets(obj2.get("aiInsightList"), max_items=5)
            if not sug_list:
                sug_list = _safe_bullets(obj2.get("suggestionList"), max_items=3)
            if not quick_list:
                quick_list = _safe_bullets(obj2.get("quickQuestionList"), max_items=3)

        if not ai_list or not sug_list:
            raise RuntimeError("LLM 多次重试后仍无法得到有效的 aiInsightList/suggestionList")

        if not quick_list:
            quick_list = [
                "结合当前分位与10/20日动量，下一步走势更偏哪边？",
                "52周回撤下，最该盯的支撑/压力信号是什么？",
                "若继续偏弱，未持仓者如何控风险与等信号？"
            ]

        payload_out = {
            "aiInsightList": ai_list,
            "suggestionList": sug_list,
            "quickQuestionList": quick_list,
            "meta": insight_meta,
            "stockNews": stock_specific_news[:8],  # 返回最多 8 条个股新闻
        }
        return payload_out
    except Exception as e:
        lines = [
            f"{name} 当前涨跌幅 {pct_chg:+.2f}%，结合历史分位与近 10/20 日动量，短期以结构性波动为主。",
            f"当前处于近一年收盘价区间相对分位 {percentile:.2f}%（非估值分位），上行需看趋势延续，下行需关注回撤承接。",
            "新闻面以热点/快讯为参考；未在给定快讯列表中检索到该股相关标题时，不宜断言「无热点」。"
        ]
        suggestions = [
            "未持仓：等待关键位附近的放量/承接确认，再分批参与。",
            "设置明确的止损/止盈规则，避免单次波动影响整体计划。",
            "若走势与量能背离，提高观望权重并减少追涨。"
        ]
        quick_list = [
            "结合当前分位与 10/20 日动量，下一步走势更偏哪边？",
            "52 周回撤下，最该盯的支撑/压力信号是什么？",
            "若继续偏弱，未持仓者如何控风险与等信号？"
        ]
        payload_out = {
            "aiInsightList": lines[:5],
            "suggestionList": suggestions[:3],
            "quickQuestionList": quick_list,
            "meta": insight_meta,
            "stockNews": stock_specific_news[:8],  # 异常情况下也返回个股新闻
        }
        return payload_out


def research_analyze(symbol: str, question: str, chat_history=None):
    # 仅保留最近几轮，避免 prompt 过长；每条只保留 role/text 关键信息
    history = []
    if isinstance(chat_history, list):
        for row in chat_history[-8:]:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "").strip().lower()
            text = str(row.get("text") or row.get("content") or "").strip()
            if role not in ("user", "assistant", "ai") or not text:
                continue
            history.append({"role": "assistant" if role == "ai" else role, "text": text[:260]})

    stock = {}
    try:
        if _is_a_share_6digit(symbol):
            live = _fetch_a_share_quote(symbol)
        else:
            live = None
        if isinstance(live, dict):
            stock = live
    except Exception:
        stock = {}

    llm_env = _get_llm_env()
    # 保留模型可追溯信息：当前问答模型来自 .env 的 LLM_API_BASE / LLM_MODEL
    llm_ready = bool(llm_env.get("api_base") and llm_env.get("model") and llm_env.get("api_key"))
    q_text = str(question or "").strip()
    q_ctx = _build_quote_context_text(q_text, history)
    gold_market = _detect_gold_market(q_ctx)
    gold_quote = _fetch_gold_live_quote(q_ctx) if gold_market else None
    index_quote = _fetch_index_live_quote(q_ctx)
    generic_quote, has_quote_target = _fetch_realtime_quote_by_question(q_text, history)
    live_quote = gold_quote or index_quote or generic_quote
    # 关键修复：只要已经拿到实时 quote（哪怕 target 解析置信度一般），也必须优先走“先查后答”分支
    # 防止回落到通用 LLM 后出现脱离实时数据的数字（如历史旧价/错误口径）。
    if has_quote_target or live_quote:
        if live_quote:
            if _is_history_scope_question(q_text):
                verified = _verified_history_summary(q_text, live_quote)
                if verified:
                    trend_summary = _llm_enrich_history_summary(live_quote, q_text, verified, history, llm_ready)
                    return {
                        "summary": f"{_build_live_quote_summary(live_quote)} {trend_summary}",
                        "followUps": [
                            "看近3个月/近1年的区间结果",
                            "补充这个区间的波动风险点",
                        ],
                        "session_id": uuid.uuid4().hex,
                    }
                return {
                    "summary": _build_history_scope_guard(live_quote),
                    "followUps": [
                        "先看这个标的的实时价和日内高低",
                        "历史源恢复后再看最高/最低",
                    ],
                    "session_id": uuid.uuid4().hex,
                }
            summary = _llm_enrich_live_quote(live_quote, q_text, history, llm_ready)
            return {
                "summary": summary,
                "followUps": [
                    "看近一周波动区间",
                    "补充这个标的的影响因素",
                ],
                "session_id": uuid.uuid4().hex,
            }
        return {
            "summary": "我当前没拿到可用的实时行情报价（可能是行情源超时或符号不支持），为了避免误导，不给你编造数字。你可以稍后重试，或把标的名称说得更具体。",
            "followUps": [
                "你想查哪个具体标的（如沪深300、上证、现货黄金）？",
                "要不要我改成多数据源兜底（新浪+备用源）？",
            ],
            "session_id": uuid.uuid4().hex,
        }
    # 通用：热点/快讯（无论是否传 symbol 都可用）
    hot = []
    try:
        rows = _fetch_hot_node("sh_a", 22) + _fetch_hot_node("sz_a", 22)
        seen = set()
        uniq = []
        for x in rows:
            k = str(x.get("leader") or "")
            if not k or k in seen:
                continue
            seen.add(k)
            uniq.append(x)
        uniq.sort(key=lambda x: _to_float(x.get("pct_chg"), -9999) or -9999, reverse=True)
        hot = uniq[:6]
    except Exception:
        hot = []

    global_news = []
    try:
        items = _fetch_news_live(page=1, num=10) or []
        global_news = items[:6]
    except Exception:
        global_news = []

    # 1) 传了 A 股代码：用“个股上下文”回答（更细）
    if llm_ready and _is_a_share_6digit(symbol):
        try:
            daily = _get_stock_daily_bars(symbol)
            if not daily:
                daily = {}

            name = stock.get("name") or symbol
            pct_chg = float(stock.get("pct_chg") or 0.0)
            last_close = daily.get("last_close") or 0.0
            closes = daily.get("closes") or []

            def _pct(a, b):
                try:
                    a = float(a)
                    b = float(b)
                    if b == 0:
                        return 0.0
                    return (a - b) / b * 100.0
                except Exception:
                    return 0.0

            change_10 = _pct(closes[-1], closes[-11]) if isinstance(closes, list) and len(closes) >= 12 else 0.0
            change_20 = _pct(closes[-1], closes[-21]) if isinstance(closes, list) and len(closes) >= 22 else 0.0
            percentile = float(daily.get("percentile") or 0.0)

            user_msg = {
                "symbol": symbol,
                "name": name,
                "question": question,
                "chat_history": history,
                "quote": {
                    "price": stock.get("price"),
                    "pct_chg": pct_chg,
                    "open": stock.get("open"),
                    "high": stock.get("high"),
                    "low": stock.get("low"),
                },
                "historical": {
                    "last_close": last_close,
                    "percentile": percentile,
                    "change_10d_pct": round(change_10, 2),
                    "change_20d_pct": round(change_20, 2),
                },
                "news_trend": {
                    "hot_topics": hot,
                    "global_news_tail": [
                        {"title": x.get("title"), "summary": x.get("summary")} for x in global_news if isinstance(x, dict)
                    ],
                },
                "style": "口语化、连续对话风格，先直接回答用户本轮问题，再补1条关键风险提示",
            }

            system_msg = (
                "你是金融研究助理。根据输入的行情/历史/新闻趋势回答用户问题。"
                "这是多轮对话，必须先理解 chat_history 的上下文，再回答本轮 question，避免答非所问。"
                "语气自然，避免固定小标题模板和机械分段。"
                "必须只输出合法 JSON 对象，包含 key: summary（字符串）与 followUps（字符串数组，2-3条）。禁止 Markdown。"
            )
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": str(user_msg)},
            ]
            content = _openai_compat_chat(messages, max_tokens=380, temperature=0.35)
            obj = _extract_json_object(content) or {}
            summary = str(obj.get("summary") or "").strip()
            follow_ups = _safe_followups(obj.get("followUps"))
            if summary:
                return {
                    "summary": summary,
                    "followUps": follow_ups if follow_ups else DEFAULT_CHAT_FOLLOWUPS[:2],
                    "session_id": uuid.uuid4().hex,
                }
        except Exception:
            pass

    # 2) 没传 symbol 或不是 A 股：走“通用全面分析”
    if llm_ready:
        try:
            user_msg = {
                "question": str(question or "").strip(),
                "chat_history": history,
                "market_pulse": {
                    "hot_topics": hot,
                    "global_news_tail": [
                        {"title": x.get("title"), "summary": x.get("summary"), "source": x.get("source"), "url": x.get("url")}
                        for x in global_news
                        if isinstance(x, dict)
                    ],
                },
                "style": "口语化、连续对话风格，先回答问题，再给1个可执行关注点",
                "live_quote": live_quote if live_quote else None,
                "live_quote_status": "ok" if live_quote else ("missing" if has_quote_target else "not_requested"),
            }
            system_msg = (
                "你是金融研究助理。根据用户问题与市场快讯/热点，给出通用的“全面分析”。"
                "这是多轮对话，必须结合 chat_history 理解用户追问对象（例如“那最近一个月呢”要承接上一问）。"
                "语气自然，避免固定模板句式。"
                "必须只输出合法 JSON 对象，包含 key: summary（字符串）与 followUps（字符串数组，2-3条）。禁止 Markdown。"
                "如果问题没有明确资产/品种，请先用 1 句澄清默认口径（如：按国内市场视角/以黄金=国际金价）。"
                "若 user_msg.live_quote_status=ok：必须优先使用 live_quote 的价格/涨跌幅/时间，禁止改写数值。"
                "若 user_msg.live_quote_status=missing 且问题涉及价格：必须明确说明“当前无法获取实时价格”，禁止给任何具体价格数字。"
            )
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": str(user_msg)},
            ]
            content = _openai_compat_chat(messages, max_tokens=520, temperature=0.35)
            obj = _extract_json_object(content) or {}
            summary = str(obj.get("summary") or "").strip()
            follow_ups = _safe_followups(obj.get("followUps"))
            if summary:
                return {
                    "summary": summary,
                    "followUps": follow_ups if follow_ups else DEFAULT_CHAT_FOLLOWUPS[:2],
                    "session_id": uuid.uuid4().hex,
                }
        except Exception:
            pass

    # 3) 没配 LLM：规则化兜底（仍尽量“全面”）
    q = str(question or "").strip()
    top_hot = hot[:3] if isinstance(hot, list) else []
    top_news = global_news[:3] if isinstance(global_news, list) else []
    hot_txt = "、".join([str(x.get("name") or x.get("leader") or "")[:18] for x in top_hot if isinstance(x, dict)]) or "（暂无）"
    news_txt = "；".join([str(x.get("title") or "")[:36] for x in top_news if isinstance(x, dict)]) or "（暂无）"
    if has_quote_target:
        if live_quote:
            summary = _build_live_quote_summary(live_quote) + "（当前为规则直出模式）"
        else:
            summary = "当前未拿到可用的实时行情（规则直出模式），为避免误导不输出具体价格。"
        return {
            "summary": summary,
            "followUps": DEFAULT_CHAT_FOLLOWUPS[:2],
            "session_id": uuid.uuid4().hex,
        }

    summary = (
        "当前为通用模式（未绑定单一股票）。\n"
        f"你的问题：{q or '（未提供问题）'}\n"
        f"市场热点（样本）：{hot_txt}\n"
        f"快讯摘要（样本）：{news_txt}\n"
        "分析口径：短期看情绪与政策/数据节奏，中期看基本面与资金风格切换；注意波动与仓位纪律（不构成投资建议）。"
    )
    return {
        "summary": summary,
        "followUps": DEFAULT_CHAT_FOLLOWUPS[:2],
        "session_id": uuid.uuid4().hex,
    }


def upload_file(file):
    name = str(file.filename or "").strip()
    if not name.lower().endswith(".pdf"):
        return None
    session_id = uuid.uuid4().hex
    out_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    file.save(out_path)
    size = os.path.getsize(out_path)
    with _LOCK:
        _SESSIONS[session_id] = {"pdf_path": out_path, "name": name, "size": int(size)}
    return {"sessionId": session_id, "fileInfo": {"name": name, "size": int(size)}}


def _run_task(task_id: str, session_id: str):
    with _LOCK:
        _TASKS[task_id]["status"] = "running"
        _TASKS[task_id]["stage"] = "解析PDF"
    time.sleep(1.0)
    with _LOCK:
        _TASKS[task_id]["stage"] = "结构化分析"
    time.sleep(1.2)
    result = {
        "summary": "财报解析完成：本期盈利质量中性偏稳，现金流较上期改善，短期风险在需求波动与存货去化节奏。",
        "sessionId": session_id,
    }
    with _LOCK:
        _TASKS[task_id]["status"] = "succeeded"
        _TASKS[task_id]["stage"] = "完成"
        _TASKS[task_id]["result"] = result


def create_task(session_id: str):
    with _LOCK:
        if session_id not in _SESSIONS:
            return None
    task_id = uuid.uuid4().hex
    with _LOCK:
        _TASKS[task_id] = {"status": "queued", "stage": "排队中", "error": "", "result": None}
    _POOL.submit(_run_task, task_id, session_id)
    return {"taskId": task_id, "engine": "finance-local", "module": "fin_report_mock"}

def get_task(task_id: str):
    with _LOCK:
        t = _TASKS.get(task_id)
    return t


def ai_analyze_news(title: str, summary: str = "", url: str = "", source: str = "", published_time=None, published_ts=None):
    """
    对单条新闻做AI深度分析，返回完整的话题详情结构（与前端 topicDataMap 格式一致）
    包含：AI摘要、相关股票、关注度、驱动事件、投资逻辑、因果链、反向风险、时间轴
    """
    import re
    title = str(title or "").strip()
    if not title:
        return None
    summary = str(summary or title[:150]).strip()
    source = str(source or "未知来源").strip()

    system_msg = (
        "你是资深财经研究分析师。用户给的是一条财经新闻的标题和摘要。"
        "你必须只输出一个合法 JSON 对象，禁止 Markdown、禁止代码围栏。"
        "输出JSON必须包含以下所有字段："
        "1. ai_summary: string - AI生成的新闻摘要（100-200字），用'🤖 AI摘要：'开头"
        "2. heat_percentile: number - 叙事关注度(0-100整数)，根据新闻影响力、市场相关性评估"
        "3. drive: string - 驱动事件描述（80-150字），说明触发这条新闻的核心事件"
        "4. logic: string - 投资逻辑（80-150字），从驱动事件推导出的投资逻辑链"
        "5. causal_chain: array - 因果链数组，必须恰好4个对象："
        "   [{label:'事件', text:'...'}, {label:'影响路径', text:'...'}, {label:'可能受益', text:'...'}, {label:'可能承压', text:'...'}]"
        "6. risk_if_wrong: string - 反向风险/可证伪点（60-100字），若情况相反会怎样"
        "7. stocks: array - 相关股票数组，2-4个对象：[{name:'股票名称', code:'代码(如600519.SH)', change:'+1.2%', positive:true/false}]"
        "8. timeline: array - 关键时间轴，2-4个对象：[{date:'YYYY-MM-DD', title:'事件描述', tag:'事件/政策/财报/数据/行业'}]"
        "注意事项："
        "- stocks中的code必须是真实存在的A股代码格式(6位.SH/SZ)或港股(HK)"
        "- change和positive要根据当前市场环境合理估算"
        "- causal_chain每步text不超过80字"
        "- 所有内容基于给定新闻，不要编造未提及的事件"
    )

    user_msg = {
        "news": {
            "title": title,
            "summary": summary,
            "source": source,
            "url": url,
        },
        "task": "生成完整的财经新闻深度分析",
    }

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": str(user_msg)},
    ]

    obj = None
    try:
        content = _openai_compat_chat(messages, max_tokens=1800, temperature=0.35)
        obj = _extract_json_object(content)

        if not obj:
            fixed = _llm_repair_insight_json(content)
            if isinstance(fixed, dict):
                obj = fixed

        if not obj:
            raise RuntimeError("LLM 无法生成有效的新闻分析 JSON")
    except Exception as e:
        # LLM 失败时使用规则生成 fallback
        obj = None
        print(f"⚠️  LLM 分析失败，使用 fallback: {str(e)[:100]}")

    # 约束时间轴日期：优先以新闻发布时间为锚点；只能使用原文中明确出现过的日期表达
    src_text = f"{title}\n{summary}"
    now_year = time.localtime().tm_year

    def _parse_publish_ymd(v, ts_val):
        if ts_val is not None:
            try:
                t = int(float(ts_val))
                if t > 10_000_000_000:
                    t = t // 1000
                if t > 0:
                    return time.strftime("%Y-%m-%d", time.localtime(t))
            except Exception:
                pass
        s = str(v or "").strip()
        if not s:
            return ""
        m = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return ""

    publish_ymd = _parse_publish_ymd(published_time, published_ts)
    anchor_year = int(publish_ymd[:4]) if publish_ymd else now_year
    def _valid_md(mm, dd):
        try:
            mmi = int(mm)
            ddi = int(dd)
            return 1 <= mmi <= 12 and 1 <= ddi <= 31
        except Exception:
            return False

    allowed_dates = set()
    for y, m, d in re.findall(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", src_text):
        if _valid_md(m, d):
            allowed_dates.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    for y, m, d in re.findall(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", src_text):
        if _valid_md(m, d):
            allowed_dates.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    # 原文若只有“4月8日/4-8”这类无年份写法，统一按发布时间年份归一化
    for m, d in re.findall(r"(?<!\d)(\d{1,2})月(\d{1,2})日", src_text):
        if _valid_md(m, d):
            allowed_dates.add(f"{int(anchor_year):04d}-{int(m):02d}-{int(d):02d}")
    for m, d in re.findall(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)", src_text):
        if _valid_md(m, d):
            allowed_dates.add(f"{int(anchor_year):04d}-{int(m):02d}-{int(d):02d}")
    # 发布时间本身也允许作为时间轴日期
    if publish_ymd:
        allowed_dates.add(publish_ymd)

    def _norm_date(v):
        s = str(v or "").strip()
        m = re.match(r"^(20\d{2})[./-](\d{1,2})[./-](\d{1,2})$", s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.match(r"^(20\d{2})年(\d{1,2})月(\d{1,2})日$", s)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
        if m:
            if not _valid_md(m.group(1), m.group(2)):
                return ""
            return f"{int(anchor_year):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        m = re.match(r"^(\d{1,2})[./-](\d{1,2})$", s)
        if m:
            if not _valid_md(m.group(1), m.group(2)):
                return ""
            return f"{int(anchor_year):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        return ""

    if obj:
        timeline_raw = obj.get("timeline") if isinstance(obj.get("timeline"), list) else []
        timeline_clean = []
        for row in timeline_raw:
            if not isinstance(row, dict):
                continue
            dt = _norm_date(row.get("date"))
            if not dt:
                continue
            # 没有可校验日期时，直接丢弃时间轴，宁缺毋滥
            if dt not in allowed_dates:
                continue
            title_txt = str(row.get("title") or "").strip()[:60]
            tag_txt = str(row.get("tag") or "事件").strip()[:12] or "事件"
            if not title_txt:
                continue
            timeline_clean.append({"date": dt, "title": title_txt, "tag": tag_txt})
            if len(timeline_clean) >= 4:
                break
        # 时间轴兜底：有发布时间时至少给一条“发布时间”，避免整块为空
        if not timeline_clean and publish_ymd:
            timeline_clean.append({"date": publish_ymd, "title": "新闻发布", "tag": "事件"})

        result = {
            "title": title,
            "ai_summary": str(obj.get("ai_summary") or f"🤖 AI摘要：{summary[:120]}"),
            "heat_percentile": int(min(100, max(0, obj.get("heat_percentile") or 65))),
            "drive": str(obj.get("drive") or f"驱动事件：{title}"),
            "logic": str(obj.get("logic") or "投资逻辑需结合后续市场数据进一步验证。"),
            "causalChain": obj.get("causalChain") or [
                {"label": "事件", "text": title[:60]},
                {"label": "影响路径", "text": "市场对该事件的初步反应将体现在相关标的价格波动上。"},
                {"label": "可能受益", "text": "与新闻主题直接相关的板块或个股可能获得短期关注。"},
                {"label": "可能承压", "text": "若事件发展不及预期，相关标的可能面临回调压力。"}
            ],
            "counterRisk": {
                "title": "若情况相反会怎样",
                "points": [str(obj.get("risk_if_wrong") or "若事态发展与预期相反，需重新评估投资逻辑。")]
            },
            "riskIfWrong": str(obj.get("risk_if_wrong") or "若事态发展与预期相反，需重新评估投资逻辑。"),
            "stocks": obj.get("stocks") or [],
            "timeline": timeline_clean,
            "originalNews": f"{title}\n{re.sub(r'<[^<]+?>', '', summary)}\n来源：{source}",
            "metaTime": str(published_time or time.strftime("%Y-%m-%d %H:%M", time.localtime())),
            "metaSource": f"来源：{source}",
            "url": url,
        }
    else:
        # Fallback: 基于规则的简单分析
        # 清洗摘要中的 HTML 标签
        import re
        clean_summary = re.sub(r'<[^<]+?>', '', summary)[:120]
        timeline_fallback = [{"date": publish_ymd, "title": "新闻发布", "tag": "事件"}] if publish_ymd else []
        result = {
            "title": title,
            "ai_summary": f"🤖 AI摘要：{clean_summary if len(clean_summary) > 50 else title[:120]}",
            "heat_percentile": 60,
            "drive": f"驱动事件：{title}",
            "logic": "投资逻辑需结合后续市场数据进一步验证。",
            "causalChain": [
                {"label": "事件", "text": title[:60]},
                {"label": "影响路径", "text": "市场对该事件的初步反应将体现在价格波动上。"},
                {"label": "可能受益", "text": "与主题相关的标的可能获得关注。"},
                {"label": "可能承压", "text": "若不及预期则可能回调。"}
            ],
            "counterRisk": {"title": "若情况相反会怎样", "points": ["需重新评估投资逻辑"]},
            "riskIfWrong": "若事态发展与预期相反，需重新评估。",
            "stocks": [],
            "timeline": timeline_fallback,
            "originalNews": f"{title}\n来源：{source}",
            "metaTime": str(published_time or time.strftime("%Y-%m-%d %H:%M", time.localtime())),
            "metaSource": f"来源：{source}",
            "url": url,
        }

    chips = []
    for s in result.get("stocks", []):
        name = s.get("name", "")
        code = s.get("code", "")
        if name and code:
            chips.append(f"{name} {code}")
    result["chips"] = chips
    result["narrativePercent"] = result["heat_percentile"]

    return result


def _parse_watchlist_codes(raw_codes) -> list[str]:
    out = []
    seen = set()
    for x in raw_codes or []:
        s = str(x or "").strip()
        if len(s) == 6 and s.isdigit() and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _personalize_news_items(items: list[dict], watchlist_codes: list[str]) -> list[dict]:
    codes = _parse_watchlist_codes(watchlist_codes)
    if not codes:
        return []
    watch_set = set(codes)
    out = []
    for it in items or []:
        chips = it.get("chips") or []
        chip_codes = set()
        for chip in chips:
            s = str(chip or "")
            m = re.search(r"(\d{6})\.(SH|SZ|BJ)\b", s, flags=re.IGNORECASE)
            if m:
                chip_codes.add(m.group(1))
                continue
            m2 = re.search(r"\b(\d{6})\b", s)
            if m2:
                chip_codes.add(m2.group(1))
        # 直接命中自选，或同条新闻中出现了自选相关股票链（包含竞品/同板块 chips）
        if chip_codes & watch_set:
            row = dict(it)
            row["personalReason"] = "自选相关"
            out.append(row)
    return out


def _personalize_from_raw_news(raw_items: list[dict], watchlist_codes: list[str], limit: int) -> list[dict]:
    codes = _parse_watchlist_codes(watchlist_codes)
    if not codes:
        return []
    code_set = set(codes)
    name_map = {}
    try:
        idx_items, _ = _get_a_share_search_index()
        for it in idx_items or []:
            c = str(it.get("code") or "").strip()
            n = str(it.get("name") or "").strip()
            if c and n and c in code_set:
                name_map[c] = n
    except Exception:
        name_map = {}

    out = []
    seen_ids = set()
    for i, item in enumerate(raw_items or []):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        text = f"{title}\n{summary}"
        matched = []
        for code in codes:
            nm = name_map.get(code, "")
            if code in text or (nm and nm in text):
                matched.append((code, nm or code))
        if not matched:
            continue
        nid = str(item.get("id") or f"personal_{i}").strip() or f"personal_{i}"
        if nid in seen_ids:
            continue
        seen_ids.add(nid)
        chips = [f"{nm} {code}" for code, nm in matched]
        out.append(
            {
                "id": nid,
                "title": title,
                "summary": f"🤖 AI摘要：{summary[:100] if summary else title[:100]}",
                "metaTime": str(item.get("metaTime") or item.get("pub_time") or time.strftime("%Y-%m-%d %H:%M", time.localtime())),
                "metaSource": f"来源：{str(item.get('source') or '').strip()}",
                "chips": chips,
                "heatPercentile": int(_to_float(item.get("importance"), 55) or 55),
                "region": str(item.get("region") or "domestic"),
                "url": str(item.get("url") or "").strip(),
                "_analysis": None,
                "personalReason": "自选直接相关",
            }
        )
        if len(out) >= max(1, int(limit or 10)):
            break
    if out:
        return out

    # 二级兜底：若快讯没命中，改用“个股新闻源”补齐，避免首页个性化直接空白
    try:
        from services.news_service import fetch_akshare_stock_news
    except Exception:
        return out
    for code in codes:
        nm = name_map.get(code, code)
        rows = fetch_akshare_stock_news(code, limit=4) or []
        for j, item in enumerate(rows):
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not title:
                continue
            nid = str(item.get("id") or f"personal_stock_{code}_{j}").strip() or f"personal_stock_{code}_{j}"
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            out.append(
                {
                    "id": nid,
                    "title": title,
                    "summary": f"🤖 AI摘要：{summary[:100] if summary else title[:100]}",
                    "metaTime": str(item.get("metaTime") or item.get("pub_time") or time.strftime("%Y-%m-%d %H:%M", time.localtime())),
                    "metaSource": f"来源：{str(item.get('source') or '').strip()}",
                    "chips": [f"{nm} {code}"],
                    "heatPercentile": int(_to_float(item.get("importance"), 58) or 58),
                    "region": str(item.get("region") or "domestic"),
                    "url": str(item.get("url") or "").strip(),
                    "_analysis": None,
                    "personalReason": "自选个股新闻",
                }
            )
            if len(out) >= max(1, int(limit or 10)):
                return out
    return out


def generate_home_news_enhanced(
    limit: int = 10,
    region: str = "all",
    mode: str = "all",
    watchlist_codes: list[str] | None = None,
):
    """
    增强版首页新闻：获取聚合新闻 + 对每条生成AI摘要/相关股票/关注度
    返回格式与前端 HOME_NEWS_SEED 一致；region: all | domestic | global
    """
    from services.news_service import get_news_summary, normalize_news_region_param

    personal_mode = str(mode or "all").strip().lower() in ("personal", "watchlist", "personalized")
    watchlist_codes = _parse_watchlist_codes(watchlist_codes or [])
    if personal_mode and not watchlist_codes:
        return []

    region = normalize_news_region_param(region)
    if personal_mode:
        # 个性化极速通道：避免先跑多源聚合（耗时高），直接用新浪滚动快讯做匹配
        try:
            from services.news_service import _fetch_news_live
            fast_n = min(max(limit * 10, 40), 120)
            fast_items = _fetch_news_live(page=1, num=fast_n) or []
        except Exception:
            fast_items = []
        return _personalize_from_raw_news(fast_items, watchlist_codes, limit)

    if region == "all":
        # 「全部」要在合并前列表里混入国际稿，pool 略大
        pool_limit = min(max(limit * 4, 28), 50)
    else:
        pool_limit = min(max(limit * 8, 40), 100)

    raw = get_news_summary(limit=pool_limit, region=region)
    items = raw.get("items") or []
    if personal_mode:
        # 防御分支：理论上上方已 return
        return _personalize_from_raw_news(items, watchlist_codes, limit)

    llm_env = _get_llm_env()
    llm_ready = bool(llm_env.get("api_base") and llm_env.get("model") and llm_env.get("api_key"))
    home_ai_enabled = _env_flag("HOME_NEWS_AI_ENABLED", True)
    if not home_ai_enabled:
        llm_ready = False
    try:
        max_ai_items = int(os.environ.get("HOME_NEWS_AI_MAX", str(limit)) or str(limit))
    except Exception:
        max_ai_items = limit
    max_ai_items = max(0, min(limit, max_ai_items))

    # 如果用户希望“没有关联股的剔除”，就只保留 AI 解析后 chips 非空的新闻。
    # 为了让“剔除后还能换新的”，需要把最多分析条数放大一些（否则容易分析完也不够填满）。
    enhanced = []
    ai_used = 0
    if llm_ready:
        if personal_mode:
            # 个性化模式避免“长时间加载中”：限制分析样本，优先尽快返回
            max_ai_items = min(pool_limit, max(max_ai_items, max(limit * 2, 12)))
        else:
            max_ai_items = min(pool_limit, max(max_ai_items, limit * 3))
    for i, item in enumerate(items):
        if len(enhanced) >= limit:
            break
        title = item.get("title", "")
        summary = item.get("summary", "")
        url = item.get("url", "")
        source = item.get("source", "")
        reg = str(item.get("region") or "domestic")

        analysis = None
        if llm_ready and ai_used < max_ai_items:
            try:
                analysis = ai_analyze_news(
                    title,
                    summary,
                    url,
                    source,
                    item.get("metaTime") or item.get("pub_time") or "",
                    item.get("ctime"),
                )
                ai_used += 1
            except Exception:
                analysis = None

        if analysis:
            chips = analysis.get("chips") or []
            # 只保留能识别出关联股票的新闻
            if len(chips) > 0:
                enhanced.append(
                    {
                        "id": item.get("id", f"news_{i}"),
                        "title": title,
                        "summary": analysis.get("ai_summary", summary),
                        "metaTime": analysis.get("metaTime", ""),
                        "metaSource": analysis.get("metaSource", source),
                        "chips": chips,
                        "heatPercentile": analysis.get("heat_percentile", 60),
                        "region": reg,
                        "url": item.get("url", ""),
                        "_analysis": analysis,
                    }
                )
        else:
            # 如果没拿到 analysis：当 llm_ready 打开时直接跳过，避免出现“无关联股”的条目；
            # 否则（AI 关闭）保留原行为（展示基础摘要）。
            if not llm_ready:
                enhanced.append(
                    {
                        "id": item.get("id", f"news_{i}"),
                        "title": title,
                        "summary": f"🤖 AI摘要：{summary[:100]}",
                        "metaTime": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
                        "metaSource": f"来源：{source}",
                        "chips": [],
                        "heatPercentile": 50,
                        "region": reg,
                        "url": item.get("url", ""),
                        "_analysis": None,
                    }
                )

    if personal_mode:
        picked = _personalize_news_items(enhanced, watchlist_codes)
        return picked[:limit]
    return enhanced


def _warm_a_share_search_cache():
    time.sleep(1.5)
    try:
        from services.stock_service import _get_a_share_search_index
        _get_a_share_search_index()
    except Exception:
        pass


def start_warmup_thread():
    threading.Thread(target=_warm_a_share_search_cache, daemon=True).start()
