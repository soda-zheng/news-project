import time
import uuid
import os
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from utils.helpers import _now_str, _parse_symbol, _is_a_share_6digit, _to_float
from services.stock_service import _fetch_a_share_quote, _get_stock_daily_bars, _fetch_hot_node
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
OUNCE_TO_GRAM = 31.1035

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


def _fetch_yahoo_quote(symbol: str) -> dict | None:
    s = str(symbol or "").strip()
    if not s:
        return None
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        obj = r.json() if r.content else {}
        chart = obj.get("chart") if isinstance(obj, dict) else {}
        result = chart.get("result") if isinstance(chart, dict) else []
        if not isinstance(result, list) or not result:
            return None
        meta = result[0].get("meta") if isinstance(result[0], dict) else {}
        if not isinstance(meta, dict):
            return None
        px = meta.get("regularMarketPrice")
        if px is None:
            px = meta.get("previousClose")
        if px is None:
            return None
        ts = meta.get("regularMarketTime") or 0
        ccy = str(meta.get("currency") or "").strip()
        return {"price": float(px), "currency": ccy, "ts": int(ts) if ts else 0}
    except Exception:
        return None


def _fetch_usdcny_rate() -> tuple[float | None, str]:
    """返回 (汇率, 来源)。优先实时，其次兜底。"""
    y1 = _fetch_yahoo_quote("USDCNY=X")
    if y1 and float(y1.get("price") or 0) > 0:
        return float(y1.get("price")), "USDCNY=X"
    y2 = _fetch_yahoo_quote("USDCNH=X")
    if y2 and float(y2.get("price") or 0) > 0:
        return float(y2.get("price")), "USDCNH=X"
    # 新浪美元兑人民币即期（fx_susdcny）
    try:
        resp = requests.get(
            "https://hq.sinajs.cn/list=fx_susdcny",
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if resp.status_code == 200:
            resp.encoding = "gbk"
            txt = str(resp.text or "")
            if '"' in txt:
                body = txt.split('"', 2)[1]
                parts = [x.strip() for x in body.split(",") if str(x).strip()]
                for p in parts:
                    try:
                        v = float(p)
                        if 5.0 <= v <= 10.0:
                            return v, "fx_susdcny"
                    except Exception:
                        continue
    except Exception:
        pass
    return None, ""


def _fetch_macro_price_answer(question: str) -> dict | None:
    q = str(question or "").strip()
    if not q:
        return None
    ql = q.lower()
    ask_price = any(k in q for k in ["多少钱", "多少点", "价格", "报价", "现价", "实时", "最新"]) or any(
        k in ql for k in ["price", "quote", "realtime"]
    )
    # 用户可能直接回答“看国际现货金/沪金”，也应继续尝试报价
    mention_gold = any(k in q for k in ["黄金", "金价", "伦敦金", "沪金", "现货金", "xauusd", "au主力", "au"])
    mention_silver = any(k in q for k in ["白银", "银价", "伦敦银", "沪银", "现货银", "xagusd", "ag主力", "ag"])
    mention_fx = any(k in q for k in ["汇率", "美元", "离岸", "在岸", "人民币", "usdcny", "usdcnh"])
    mention_oil = any(k in q for k in ["原油", "油价", "布伦特", "wti"])
    if not ask_price and not (mention_gold or mention_silver or mention_fx or mention_oil):
        return None

    want_cny = any(k in q for k in ["元", "人民币", "rmb", "cny"])
    explicit_usd = any(k in ql for k in ["usd", "xauusd", "xagusd", "美元"])

    # 优先匹配用户最常见提问：黄金/汇率/原油
    if mention_gold:
        hit = _fetch_yahoo_quote("GC=F")
        if not hit:
            # Yahoo 不稳定时，用新浪外盘黄金兜底
            try:
                resp = requests.get(
                    "https://hq.sinajs.cn/list=hf_GC",
                    headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                    timeout=8,
                )
                if resp.status_code == 200:
                    resp.encoding = "gbk"
                    txt = str(resp.text or "")
                    if '"' in txt:
                        body = txt.split('"', 2)[1]
                        for x in body.split(","):
                            x = str(x or "").strip()
                            try:
                                v = float(x)
                                if v > 0:
                                    hit = {"price": v, "currency": "USD", "ts": int(time.time())}
                                    break
                            except Exception:
                                continue
            except Exception:
                pass
        if not hit:
            return None
        px = float(hit.get("price") or 0.0)
        ts = int(hit.get("ts") or 0)
        tm = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts > 0 else "刚刚"
        if want_cny or (ask_price and not explicit_usd):
            usdcny, fx_src = _fetch_usdcny_rate()
            if usdcny and usdcny > 0:
                cny_px_oz = px * usdcny
                cny_px_g = cny_px_oz / OUNCE_TO_GRAM
                summary = (
                    f"黄金当前约 {cny_px_g:.2f} 元/克（按国际期金主力 GC=F {px:.2f} USD/盎司、"
                    f"USD/CNY≈{usdcny:.4f}（{fx_src}）换算，更新时间：{tm}）。\n"
                    f"注：国际金价常用美元/盎司，国内常用人民币/克（1盎司≈{OUNCE_TO_GRAM}克）。"
                )
            else:
                est = 7.20
                cny_px_oz = px * est
                cny_px_g = cny_px_oz / OUNCE_TO_GRAM
                summary = (
                    f"黄金当前约 {cny_px_g:.2f} 元/克（按国际期金主力 GC=F {px:.2f} USD/盎司、"
                    f"估算汇率 USD/CNY≈{est:.2f} 换算，更新时间：{tm}）。\n"
                    f"注：实时汇率源短时不可用，以上为近似换算值；1盎司≈{OUNCE_TO_GRAM}克。"
                )
        else:
            summary = (
                f"黄金（国际期金主力，GC=F）当前约 {px:.2f} {hit.get('currency') or 'USD'}（更新时间：{tm}）。\n"
                "若你要看“现货金 XAUUSD”或“沪金主力（人民币）”，我可以按对应口径继续给你。"
            )
        return {
            "summary": summary,
            "followUps": ["查看现货金 XAUUSD", "查看沪金 AU（人民币/克）"],
            "session_id": uuid.uuid4().hex,
        }

    if mention_silver:
        hit = _fetch_yahoo_quote("SI=F")
        if not hit:
            # Yahoo 不稳定时，用新浪外盘白银兜底
            try:
                resp = requests.get(
                    "https://hq.sinajs.cn/list=hf_SI",
                    headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                    timeout=8,
                )
                if resp.status_code == 200:
                    resp.encoding = "gbk"
                    txt = str(resp.text or "")
                    if '"' in txt:
                        body = txt.split('"', 2)[1]
                        for x in body.split(","):
                            x = str(x or "").strip()
                            try:
                                v = float(x)
                                if v > 0:
                                    hit = {"price": v, "currency": "USD", "ts": int(time.time())}
                                    break
                            except Exception:
                                continue
            except Exception:
                pass
        if not hit:
            return None
        px = float(hit.get("price") or 0.0)
        ts = int(hit.get("ts") or 0)
        tm = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts > 0 else "刚刚"
        if want_cny or (ask_price and not explicit_usd):
            usdcny, fx_src = _fetch_usdcny_rate()
            if usdcny and usdcny > 0:
                cny_px_oz = px * usdcny
                cny_px_g = cny_px_oz / OUNCE_TO_GRAM
                summary = (
                    f"白银当前约 {cny_px_g:.2f} 元/克（按国际期银主力 SI=F {px:.2f} USD/盎司、"
                    f"USD/CNY≈{usdcny:.4f}（{fx_src}）换算，更新时间：{tm}）。\n"
                    f"注：国际银价常用美元/盎司，国内常用人民币/克（1盎司≈{OUNCE_TO_GRAM}克）。"
                )
            else:
                est = 7.20
                cny_px_oz = px * est
                cny_px_g = cny_px_oz / OUNCE_TO_GRAM
                summary = (
                    f"白银当前约 {cny_px_g:.2f} 元/克（按国际期银主力 SI=F {px:.2f} USD/盎司、"
                    f"估算汇率 USD/CNY≈{est:.2f} 换算，更新时间：{tm}）。\n"
                    f"注：实时汇率源短时不可用，以上为近似换算值；1盎司≈{OUNCE_TO_GRAM}克。"
                )
        else:
            summary = (
                f"白银（国际期银主力，SI=F）当前约 {px:.2f} {hit.get('currency') or 'USD'}（更新时间：{tm}）。\n"
                "若你要看“现货银 XAGUSD”或“沪银主力（人民币）”，我可以按对应口径继续给你。"
            )
        return {
            "summary": summary,
            "followUps": ["查看现货银 XAGUSD", "查看沪银 AG（人民币/克）"],
            "session_id": uuid.uuid4().hex,
        }

    if any(k in q for k in ["汇率", "美元", "离岸", "在岸", "人民币"]):
        pair = "USDCNH=X" if ("离岸" in q or "CNH" in q.upper()) else "USDCNY=X"
        hit = _fetch_yahoo_quote(pair)
        if not hit:
            return None
        px = float(hit.get("price") or 0.0)
        ts = int(hit.get("ts") or 0)
        tm = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts > 0 else "刚刚"
        label = "美元兑离岸人民币" if pair == "USDCNH=X" else "美元兑在岸人民币"
        summary = f"{label}（{pair}）当前约 {px:.4f}（更新时间：{tm}）。"
        return {
            "summary": summary,
            "followUps": ["要看在岸/离岸价差吗？", "需要我按1个月维度看趋势吗？"],
            "session_id": uuid.uuid4().hex,
        }

    if any(k in q for k in ["原油", "油价", "布伦特", "wti"]):
        sym = "BZ=F" if ("布伦特" in q or "brent" in ql) else "CL=F"
        hit = _fetch_yahoo_quote(sym)
        if not hit:
            return None
        px = float(hit.get("price") or 0.0)
        ts = int(hit.get("ts") or 0)
        tm = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts > 0 else "刚刚"
        label = "布伦特原油主力" if sym == "BZ=F" else "WTI 原油主力"
        summary = f"{label}（{sym}）当前约 {px:.2f} {hit.get('currency') or 'USD'}（更新时间：{tm}）。"
        return {
            "summary": summary,
            "followUps": ["要看布伦特和WTI价差吗？", "要补库存/地缘因素对油价的影响吗？"],
            "session_id": uuid.uuid4().hex,
        }

    return None


def _fetch_cn_index_answer(question: str) -> dict | None:
    q = str(question or "").strip()
    if not q:
        return None
    ql = q.lower()
    mapping = [
        (["创业板指", "创业板指数", "399006"], "399006.SZ", "创业板指"),
        (["沪深300", "hs300", "000300"], "000300.SS", "沪深300"),
        (["上证指数", "上证综指", "上证", "000001"], "000001.SS", "上证指数"),
        (["深证成指", "深成指", "399001"], "399001.SZ", "深证成指"),
        (["中证500", "000905"], "000905.SS", "中证500"),
        (["科创50", "000688"], "000688.SS", "科创50"),
    ]
    picked = None
    for keys, y_symbol, cname in mapping:
        if any(k.lower() in ql for k in keys):
            picked = (y_symbol, cname)
            break
    if not picked:
        if "指数" in q or "大盘" in q:
            picked = ("000300.SS", "沪深300")
        else:
            return None

    y_symbol, cname = picked
    hit = _fetch_yahoo_quote(y_symbol)
    if not hit:
        return None
    px = float(hit.get("price") or 0.0)
    ts = int(hit.get("ts") or 0)
    ccy = str(hit.get("currency") or "CNY").strip() or "CNY"
    tm = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts > 0 else "刚刚"
    summary = f"{cname}当前约 {px:.2f} 点（{ccy}，更新时间：{tm}）。若你要，我可以继续给你短线/中线的指数节奏解读。"
    return {
        "summary": summary,
        "followUps": [f"{cname}短线怎么看？", "再看上证和沪深300对比", "给我一个指数观察清单"],
        "session_id": uuid.uuid4().hex,
    }


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

    # 对话状态承接：若本轮输入是“AI追问按钮文本”，回溯上一条真实用户问题拼接为上下文
    raw_q = str(question or "").strip()
    raw_q_norm = raw_q.replace("（", "(").replace("）", ")").replace(" ", "")
    cycle_choice = None  # "short" | "mid"
    if raw_q_norm in ("短线(1-5天)", "短线(1-5)", "短线", "按短线给我具体进出场"):
        cycle_choice = "short"
    elif raw_q_norm in ("中线(1-3个月)", "中线(1-3)", "中线", "按中线给我关键验证点", "按中线给我建仓/止损/目标"):
        cycle_choice = "mid"

    option_like = any(
        k in raw_q
        for k in [
            "最大可承受回撤",
            "短线交易还是中线持有",
            "是否需要我分别给出短线和中线两套判断",
            "你希望结论偏保守还是偏进攻",
            "短线（1-5天）",
            "中线（1-3个月）",
            "短线(1-5天)",
            "中线(1-3个月)",
        ]
    )
    effective_q = raw_q
    if option_like:
        prev_user = ""
        for h in reversed(history[:-1]):
            if h.get("role") != "user":
                continue
            t = str(h.get("text") or "").strip()
            if not t or t == raw_q:
                continue
            prev_user = t
            break
        if prev_user:
            effective_q = f"{prev_user}；参数：{raw_q}"

    # 若本轮是“周期选择按钮”，把意图显式改写为“请按该周期给可执行策略”，避免落回追问周期/复读行情
    if cycle_choice == "short":
        effective_q = "按短线（1-5天）给出可执行交易策略：结论前置，包含关键位、止损、仓位与触发条件。"
    elif cycle_choice == "mid":
        effective_q = "按中线（1-3个月）给出可执行交易策略：结论前置，包含关键位、止损、仓位与验证点。"

    # 通用问答优先尝试“可直接报价”能力（黄金/汇率/原油）
    direct = _fetch_macro_price_answer(effective_q)
    if isinstance(direct, dict) and str(direct.get("summary") or "").strip():
        return direct

    # 指数问答优先：命中指数时强制脱离个股绑定上下文
    idx = _fetch_cn_index_answer(effective_q)
    if isinstance(idx, dict) and str(idx.get("summary") or "").strip():
        return idx

    q_for_intent = str(effective_q or "").strip()
    non_stock_intent = any(
        k in q_for_intent
        for k in [
            "指数", "大盘", "创业板", "沪深300", "上证", "深成指", "中证500", "科创50",
            "黄金", "白银", "原油", "汇率", "美元", "人民币", "xau", "xag", "wti", "brent",
        ]
    )
    use_stock_context = _is_a_share_6digit(symbol) and not non_stock_intent

    # -------------------------
    # 【核心兜底】A股个股绑定优先（不依赖 LLM）
    # 只要传入了 6 位 A 股代码，就必须优先用该标的的行情/分位/高低点回答，避免落到“通用黄金/通用框架”。
    # -------------------------
    if use_stock_context:
        live = {}
        daily = {}
        try:
            x = _fetch_a_share_quote(symbol)
            if isinstance(x, dict):
                live = x
        except Exception:
            live = {}
        try:
            x = _get_stock_daily_bars(symbol)
            if isinstance(x, dict):
                daily = x
        except Exception:
            daily = {}

        name = str(live.get("name") or symbol).strip() or symbol
        price = _to_float(live.get("price"), 0.0) or _to_float(daily.get("last_close"), 0.0) or 0.0
        pct_chg = _to_float(live.get("pct_chg"), 0.0) or 0.0
        percentile = _to_float(daily.get("percentile"), 0.0) or 0.0
        o = live.get("open")
        hi = live.get("high")
        lo = live.get("low")
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

        q = str(effective_q or "").strip()
        q_low = q.lower()
        ask_buy = any(
            k in q
            for k in [
                "买不买",
                "能不能买",
                "建议买",
                "要不要买",
                "值不值得买",
                "适合买",
                "可以买",
                "能买",
                "能入",
                "能上车",
                "值得入手",
            ]
        )
        ask_cycle_short = cycle_choice == "short" or any(k in q for k in ["短线", "1-5天", "1~5天", "1—5天"])
        ask_cycle_mid = cycle_choice == "mid" or any(k in q for k in ["中线", "1-3个月", "1~3个月", "1—3个月"])
        ask_trend = any(k in q for k in ["走势", "偏哪边", "偏强", "偏弱", "动量", "趋势", "更偏"]) or any(
            k in q_low for k in ["trend", "momentum"]
        )
        ask_risk = any(k in q for k in ["回撤", "风控", "止损", "支撑", "压力", "仓位", "未持仓"])

        base = f"{name}（{symbol}）现价约 {price:.2f} 元，涨跌幅 {pct_chg:+.2f}%，近1年价格分位 {percentile:.2f}%（{PERCENTILE_DEFINITION_CN}）。"
        today = []
        try:
            if o is not None:
                today.append(f"今开 {float(o):.2f}")
        except Exception:
            pass
        try:
            if hi is not None:
                today.append(f"最高 {float(hi):.2f}")
        except Exception:
            pass
        try:
            if lo is not None:
                today.append(f"最低 {float(lo):.2f}")
        except Exception:
            pass
        today_line = ("今日 " + "，".join(today) + "。") if today else ""

        # 周期选择：必须直接给对应周期策略（不复读行情、不再追问周期）
        if cycle_choice in ("short", "mid") or ask_cycle_short or ask_cycle_mid:
            sup = None
            res = None
            try:
                if lo is not None:
                    sup = float(lo)
            except Exception:
                sup = None
            try:
                if hi is not None:
                    res = float(hi)
            except Exception:
                res = None
            sup_s = f"{sup:.2f}" if isinstance(sup, (int, float)) else ""
            res_s = f"{res:.2f}" if isinstance(res, (int, float)) else ""

            # 简化版策略：用今日高低点作“触发位”，动量/涨跌作“追高风险提示”
            if cycle_choice == "short" or ask_cycle_short:
                bias = "偏强" if (pct_chg >= 0 and (change_10 >= 0 or change_20 >= 0)) else "偏弱/震荡"
                chase = "不建议追高，优先等回踩确认" if pct_chg >= 7 else "可关注回踩/突破的触发条件"
                summary = (
                    f"✅【短线（1-5天）策略】结论：{bias}，{chase}。\n"
                    f"关键位：支撑 {sup_s or '今日低点'}，压力 {res_s or '今日高点'}。\n"
                    f"执行：回踩支撑附近企稳再试探；有效突破压力再顺势；跌破支撑严格止损/减仓。\n"
                    f"仓位：短线波动大，单标的建议不超过总资金 20%。\n"
                    f"参考数据：现价 {price:.2f} 元，涨跌幅 {pct_chg:+.2f}%，10/20日动量 {change_10:+.2f}% / {change_20:+.2f}%。"
                )
                return {
                    "summary": summary,
                    "followUps": ["止损怎么设更稳？", "压力位突破后怎么加仓？", "我最大回撤 8%"],
                    "session_id": uuid.uuid4().hex,
                }
            else:
                # 中线更强调“验证点/分批/风控”，但仍给可执行触发条件
                mid_tone = "可等待回调企稳后分批" if (percentile >= 60 or pct_chg >= 7) else "可逢回调分批，但更重风控"
                summary = (
                    f"⚠️【中线（1-3个月）策略】结论：{mid_tone}。\n"
                    f"验证点：不破 {sup_s or '关键支撑'} 且回升站稳后再加仓；上破 {res_s or '关键压力'} 视为趋势确认。\n"
                    f"风控：跌破支撑要收缩仓位；分批建仓、分批止盈，避免一次性满仓。\n"
                    f"参考数据：现价 {price:.2f} 元，近1年价格分位 {percentile:.2f}%，10/20日动量 {change_10:+.2f}% / {change_20:+.2f}%。"
                )
                return {
                    "summary": summary,
                    "followUps": ["给我中线建仓分批方案", "目标位怎么定？", "我最大回撤 8%"],
                    "session_id": uuid.uuid4().hex,
                }

        # 买入建议：必须直接回答“买不买”，并分短线/中线给明确结论 + 理由 + 风控，不再先反问周期
        if ask_buy:
            sup = None
            res = None
            try:
                if lo is not None:
                    sup = float(lo)
            except Exception:
                sup = None
            try:
                if hi is not None:
                    res = float(hi)
            except Exception:
                res = None
            sup_s = f"{sup:.2f}" if isinstance(sup, (int, float)) else None
            res_s = f"{res:.2f}" if isinstance(res, (int, float)) else None

            short_hint = "不建议追高" if pct_chg >= 7 else "可小仓位试错/等待确认"
            mid_hint = "等待回调企稳再分批" if percentile >= 60 or pct_chg >= 7 else "可逢回调分批布局（更重风控）"

            # 买入建议只保留关键数据，避免“行情复读”
            key_line = f"{name}（{symbol}）现价约 {price:.2f} 元，近1年价格分位 {percentile:.2f}%，10/20日动量 {change_10:+.2f}% / {change_20:+.2f}%。"
            hl_line = ""
            if sup_s or res_s:
                parts = []
                if sup_s:
                    parts.append(f"支撑 {sup_s}")
                if res_s:
                    parts.append(f"压力 {res_s}")
                hl_line = "关键位：" + "，".join(parts) + "。"

            summary = (
                f"✅ 短线（1-5天）：{short_hint}。{('若跌破 ' + sup_s + ' 建议止损/减仓。') if sup_s else '若回落失守关键支撑，建议止损/减仓。'}\n"
                f"⚠️ 中线（1-3个月）：{mid_hint}。{('回调到 ' + sup_s + ' 附近企稳再考虑分批。') if sup_s else '等待回调企稳再考虑分批。'}\n"
                f"{key_line}{today_line}\n"
                f"{hl_line}\n"
                "以上仅供参考，不构成投资依据；投资有风险，入市需谨慎。"
            )
            return {
                "summary": summary,
                "followUps": ["按短线给我具体进出场", "按中线给我建仓/止损/目标", "我最大回撤 8%"],
                "session_id": uuid.uuid4().hex,
            }

        if ask_risk:
            sup = None
            res = None
            try:
                if lo is not None:
                    sup = float(lo)
            except Exception:
                sup = None
            try:
                if hi is not None:
                    res = float(hi)
            except Exception:
                res = None
            sup_s = f"{sup:.2f}（今日低点）" if isinstance(sup, (int, float)) else "今日低点"
            res_s = f"{res:.2f}（今日高点）" if isinstance(res, (int, float)) else "今日高点"
            summary = (
                f"{base}{today_line}\n"
                f"风控抓手：支撑先看 {sup_s}，压力先看 {res_s}；跌破支撑要收缩风险敞口，突破压力再做趋势确认。\n"
                "如果你告诉我持有周期（短线/中线）与最大可承受回撤（5%/8%/10%），我可以把止损触发与仓位节奏写成可执行规则。"
            )
            return {
                "summary": summary,
                "followUps": ["最大回撤 5%", "最大回撤 8%", "短线交易", "中线持有"],
                "session_id": uuid.uuid4().hex,
            }

        if ask_trend:
            tilt = "短线偏强" if (pct_chg >= 0 and (change_10 >= 0 or change_20 >= 0)) else "短线偏弱/震荡"
            summary = (
                f"{base}{today_line}\n"
                f"10/20日动量约 {change_10:+.2f}% / {change_20:+.2f}%。结论：{tilt}。"
                "短线先盯今日高低点的突破/跌破；中线更看分位从低位回升的持续性。"
            )
            return {
                "summary": summary,
                "followUps": ["按短线给我具体进出场", "按中线给我关键验证点"],
                "session_id": uuid.uuid4().hex,
            }

        summary = f"{base}{today_line}\n你更关注短线（1-5天）还是中线（1-3个月）？我会按对应周期给你策略。"
        return {
            "summary": summary,
            "followUps": ["短线（1-5天）", "中线（1-3个月）"],
            "session_id": uuid.uuid4().hex,
        }

    stock = {}
    try:
        if use_stock_context:
            live = _fetch_a_share_quote(symbol)
        else:
            live = None
        if isinstance(live, dict):
            stock = live
    except Exception:
        stock = {}

    llm_env = _get_llm_env()
    llm_ready = bool(llm_env.get("api_base") and llm_env.get("model") and llm_env.get("api_key"))
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
    if llm_ready and use_stock_context:
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
                "question": effective_q,
                "chat_history": history,
                "dialog_state": {
                    "cycle": "短线(1-5天)" if cycle_choice == "short" else ("中线(1-3个月)" if cycle_choice == "mid" else ""),
                },
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
                "你是「财懂了」专业金融AI助手，专注A股个股分析。核心铁律："
                "1) 100%匹配用户问题，禁止答非所问；"
                "2) 禁止复述用户问题/原句（如“你问的是...”或“直接回答你的问题：...”），直接给结论；"
                "3) 若用户问“买不买/建议买吗”，必须直接给出短线(1-5天)/中线(1-3个月)的明确建议+理由+风控，不要先反问周期；"
                "4) 必须优先使用输入中的绑定标的行情/历史数据，禁止按通用逻辑回答。"
                "这是多轮对话，必须先理解 chat_history 的上下文，再回答本轮 question。"
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
            pulse_titles = [
                str(x.get("title") or "").strip()
                for x in global_news
                if isinstance(x, dict) and str(x.get("title") or "").strip()
            ][:6]
            user_msg = {
                "question": effective_q,
                "chat_history": history,
                "market_pulse": {
                    "hot_topics": hot,
                    "global_news_titles": pulse_titles,
                },
                "style": "口语化、连续对话风格，先回答问题，再给1个可执行关注点",
            }
            system_msg = (
                "你是金融研究助理。根据用户问题与市场快讯/热点，给出通用的“全面分析”。"
                "这是多轮对话，必须结合 chat_history 理解用户追问对象（例如“那最近一个月呢”要承接上一问）。"
                "语气自然，避免固定模板句式。"
                "禁止复述用户原句（如“你问的是...”），直接给结论。"
                "优先直接回答本轮问题，不要照搬或复述输入 JSON 字段。"
                "若用户问的是具体价格/点位（如黄金、汇率、油价），先明确口径（现货/期货、美元/人民币）并给可执行查询方式；"
                "没有实时数值时，明确说明“当前会话未连接该品种实时行情”，不要编造具体价格。"
                "必须只输出合法 JSON 对象，包含 key: summary（字符串）与 followUps（字符串数组，2-3条）。禁止 Markdown。"
                "如果问题没有明确资产/品种，请先用 1 句澄清默认口径。"
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

    # 3) 没配 LLM：规则化兜底（按问题类型回答，避免机械拼接“样本热点”）
    q = effective_q
    q_low = q.lower()
    ask_price = any(k in q for k in ["多少钱", "多少点", "价格", "报价", "现价", "实时"]) or any(
        k in q_low for k in ["price", "quote", "realtime"]
    )
    ask_gold = any(k in q for k in ["黄金", "金价", "伦敦金", "沪金"])
    ask_fx = any(k in q for k in ["汇率", "美元", "离岸", "在岸", "人民币"])
    ask_oil = any(k in q for k in ["原油", "油价", "布伦特", "wti"])

    if ask_price and ask_gold:
        summary = (
            "当前会话未连接黄金实时行情，无法直接给出精确现价。\n"
            "若按通用口径，建议先确认你要看的是：国际现货金（XAUUSD）还是国内沪金主力（AU）。\n"
            "可执行做法：在行情终端搜索 XAUUSD/AU 主力查看最新价，再结合近1日波动与美元指数判断短线节奏。"
        )
        followups = [
            "你要看国际现货金（美元）还是沪金（人民币）？",
            "按1天还是1个月维度看波动？"
        ]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if ask_price and ask_fx:
        summary = (
            "当前会话未连接外汇实时行情，不能直接给出精确报价。\n"
            "请先确认口径：美元兑人民币（USDCNY 在岸）或 USDCNH（离岸）。\n"
            "拿到现价后，建议结合近期政策预期与中美利差变化评估短期方向。"
        )
        followups = [
            "你要看在岸 USDCNY 还是离岸 USDCNH？",
            "需要我按短线（日内）还是中线（1个月）给你分析框架？"
        ]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if ask_price and ask_oil:
        summary = (
            "当前会话未连接原油实时行情，无法直接给出精确现价。\n"
            "请先确认口径：布伦特（Brent）还是 WTI。\n"
            "拿到现价后，建议结合库存数据、地缘事件与美元走势判断短线强弱。"
        )
        followups = [
            "你关注布伦特还是 WTI？",
            "更想看短线交易节奏还是中期供需逻辑？"
        ]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if not q:
        summary = "我可以直接按你的问题回答。你可以告诉我具体资产与时间维度，例如：黄金（1天/1个月）或某只A股的短线观点。"
        return {"summary": summary, "followUps": DEFAULT_CHAT_FOLLOWUPS[:2], "session_id": uuid.uuid4().hex}

    ask_trend = any(k in q for k in ["走势", "看涨", "看跌", "方向", "涨还是跌", "趋势"])
    ask_risk = any(k in q for k in ["风险", "回撤", "止损", "仓位", "波动"])
    ask_time = any(k in q for k in ["今天", "本周", "这个月", "一个月", "短线", "中线", "日内"])
    ask_compare = any(k in q for k in ["对比", "比较", "哪个好", "A还是B", "vs", "PK"])

    if ask_compare:
        summary = "比较两个标的时，建议用同一口径对齐三件事：当前价格位置（分位）、近1个月动量、风险暴露（回撤与波动）。"
        followups = ["请告诉我要比较的两个标的全称", "你更看重收益潜力还是回撤控制？"]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if ask_trend:
        summary = "先看短周期动量，再看关键支撑/压力位，最后用仓位纪律控制回撤；这是当前未绑定单一标的时最稳妥的执行框架。"
        followups = ["你要按1天、1周还是1个月来判断趋势？", "要不要我给你一个更具体的进出场模板？"]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if ask_risk:
        summary = "为了给你可执行的风控方案，请先确认两个参数：最大可承受回撤（5%/8%/10%）和交易周期（短线/中线）。"
        followups = ["最大回撤 5%", "最大回撤 8%", "短线交易", "中线持有"]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    if ask_time:
        summary = "时间维度会显著影响结论：短线看情绪与动量，中线看基本面与资金风格。"
        followups = ["是否需要我分别给出短线和中线两套判断？", "你希望结论偏保守还是偏进攻？"]
        return {"summary": summary, "followUps": followups, "session_id": uuid.uuid4().hex}

    summary = (
        "当前是通用模式（未绑定单一股票）。若提供具体资产（代码/品种）和时间维度，我会给更精确、可执行的结论。"
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


def generate_home_news_enhanced(limit: int = 10, region: str = "all"):
    """
    增强版首页新闻：获取聚合新闻 + 对每条生成AI摘要/相关股票/关注度
    返回格式与前端 HOME_NEWS_SEED 一致；region: all | domestic | global
    """
    from services.news_service import get_news_summary, normalize_news_region_param

    region = normalize_news_region_param(region)
    if region == "all":
        # 「全部」要在合并前列表里混入国际稿，pool 略大
        pool_limit = min(max(limit * 4, 28), 50)
    else:
        pool_limit = min(max(limit * 8, 40), 100)

    raw = get_news_summary(limit=pool_limit, region=region)
    items = raw.get("items") or []
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

    enhanced = []
    for i, item in enumerate(items[:limit]):
        title = item.get("title", "")
        summary = item.get("summary", "")
        url = item.get("url", "")
        source = item.get("source", "")
        reg = str(item.get("region") or "domestic")

        analysis = None
        if llm_ready and i < max_ai_items:
            try:
                analysis = ai_analyze_news(
                    title,
                    summary,
                    url,
                    source,
                    item.get("metaTime") or item.get("pub_time") or "",
                    item.get("ctime"),
                )
            except Exception:
                analysis = None

        if analysis:
            enhanced.append({
                "id": item.get("id", f"news_{i}"),
                "title": title,
                "summary": analysis.get("ai_summary", summary),
                "metaTime": analysis.get("metaTime", ""),
                "metaSource": analysis.get("metaSource", source),
                "chips": analysis.get("chips", []),
                "heatPercentile": analysis.get("heat_percentile", 60),
                "region": reg,
                "url": item.get("url", ""),
                "_analysis": analysis,
            })
        else:
            enhanced.append({
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
            })

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
