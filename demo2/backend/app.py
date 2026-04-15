from flask import Flask, jsonify, request
import time
import requests
import threading
import traceback
import json
import re
import ast
import os
import sqlite3
from datetime import datetime
from core.env import bootstrap_env
from modules.quotes.routes import quote_route, core_quotes_route, usdcny_route, stock_route
from modules.quotes.service import (
    sina_get as module_sina_get,
    parse_sina_var as module_parse_sina_var,
    sina_quote as module_sina_quote,
    normalize_symbol_candidates as module_normalize_symbol_candidates,
    parse_a_share as module_parse_a_share,
    parse_hk as module_parse_hk,
    parse_us as module_parse_us,
    parse_futures as module_parse_futures,
    get_usdcny as module_get_usdcny,
    get_gold as module_get_gold,
    get_silver as module_get_silver,
    get_crude_oil as module_get_crude_oil,
    get_index_quote as module_get_index_quote,
)
from modules.fx.routes import convert_route, fx_currencies_route
from modules.videos.routes import video_cover_route, videos_route
from modules.topics.routes import (
    topics_hot_route,
    boards_industry_route,
    boards_concept_route,
    topics_stock_insight_route,
    topics_board_insight_route,
)
from modules.research.routes import (
    research_analyze_route,
    research_chat_session_delete_route,
    research_chat_session_messages_route,
    research_chat_sessions_route,
    research_task_status_route,
    research_tasks_stream_route,
)
from modules.news.routes import news_image_route, news_home_route
from modules.news.service import (
    news_fetch_juhe,
    news_fetch_tianapi,
    news_fallback_pic_url,
    fallback_summary,
    fallback_category,
)
from modules.news.repo import news_db_init as repo_news_db_init, news_cache_get_many as repo_news_cache_get_many, news_cache_upsert as repo_news_cache_upsert
from modules.news.llm import (
    env_get as llm_env_get,
    llm_chat as module_llm_chat,
    llm_summarize_and_score as module_llm_summarize_and_score,
    start_news_worker as module_start_news_worker,
)
from modules.research.service import research_analyze as module_research_analyze
_financial_report_import_error = ""
try:
    from modules.financial_report.routes import register_financial_report_routes
except Exception as e:
    register_financial_report_routes = None
    _financial_report_import_error = str(e)

app = Flask(__name__)

# JSON 返回中文不转义
app.json.ensure_ascii = False

# 调试期优先读取本地密钥文件（不要提交到 git）
bootstrap_env(os.path.dirname(__file__))

# 解决跨域问题（前端调用必备）
@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'  # 允许所有域名访问
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


# 财报分析（可选模块，缺少外部依赖时降级跳过，避免主服务无法启动）
if register_financial_report_routes is not None:
    register_financial_report_routes(app)
else:
    print(f"[warn] financial_report disabled: {_financial_report_import_error}")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
)

# 简单内存缓存：减少外部请求频率、提升稳定性
_CACHE = {}  # key -> (ts, value)

NAME_USDCNY = "\u4eba\u6c11\u5e01/\u7f8e\u5143"
NAME_GOLD = "\u73b0\u8d27\u9ec4\u91d1"  # 展示名：国际现货黄金（数据源优先 XAU/USD，失败再 COMEX 期货）
NAME_SILVER = "COMEX\u767d\u94f6"
NAME_WTI = "WTI\u539f\u6cb9"
NAME_SSE = "\u4e0a\u8bc1\u6307\u6570"
NAME_SZSE = "\u6df1\u8bc1\u6210\u6307"
NAME_CHINEXT = "\u521b\u4e1a\u677f\u6307"


def _now_ts() -> float:
    return time.time()


def _cache_get(key: str, ttl_s: int):
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, val = hit
    if _now_ts() - ts <= ttl_s:
        return val
    return None


def _cache_set(key: str, val):
    _CACHE[key] = (_now_ts(), val)


def _with_prev_change(name: str, price: float, digits: int = 2):
    prev = _CACHE.get(f"prev:{name}")
    if prev:
        _, prev_price = prev
        chg = round(price - float(prev_price), digits)
        pct = round((chg / float(prev_price)) * 100, 2) if float(prev_price) else 0.0
    else:
        chg, pct = 0.0, 0.0
    _CACHE[f"prev:{name}"] = (_now_ts(), float(price))
    return chg, pct


# ===================== 核心行情获取函数（稳定数据源） =====================
# 统一使用新浪财经行情源（你当前网络可访问，且无需 key）
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": SESSION.headers.get("User-Agent"),
}


def _sina_get(symbol: str) -> str:
    return module_sina_get(SESSION, SINA_HEADERS, symbol)


def _parse_sina_var(payload: str) -> list[str]:
    return module_parse_sina_var(payload)

def _sina_quote(symbol: str) -> tuple[str, list[str]]:
    return module_sina_quote(SESSION, SINA_HEADERS, symbol)

def _normalize_symbol_candidates(raw_symbol: str) -> list[str]:
    out = module_normalize_symbol_candidates(raw_symbol)
    raw = (raw_symbol or "").strip()
    if not raw:
        return []
    raw_lower = raw.lower()

    # 行情查询优先语义：
    # 输入“黄金/白银/原油”等泛关键词时，优先返回对应大宗品种，避免被中文模糊匹配到某只个股（如“山东黄金”）。
    if raw_lower in ("gold", "comexgold", "comex黄金", "黄金", "xau", "xau/usd", "xauusd") or "黄金" in raw:
        merged = ["hf_GC"]
        for s in out:
            if s not in merged:
                merged.append(s)
        return merged
    if raw_lower in ("silver", "comexsilver", "comex白银", "白银", "xag", "xag/usd", "xagusd") or "白银" in raw:
        merged = ["hf_SI", "hf_si"]
        for s in out:
            if s not in merged:
                merged.append(s)
        return merged
    if raw_lower in ("wti", "oil", "crude", "原油", "wti原油") or "原油" in raw:
        merged = ["hf_CL"]
        for s in out:
            if s not in merged:
                merged.append(s)
        return merged

    # 支持中文股票名 => 用 suggest(type=11) 查到 sh/sz/bj + 6 位候选代码
    # 仅在输入包含中文字符时触发，避免对标准代码/英文 ticker 增加网络开销。
    try:
        if re.search(r"[\u4e00-\u9fff]", raw):
            r = SESSION.get(
                "https://suggest3.sinajs.cn/suggest/type=11",
                params={"key": raw},
                timeout=8,
                headers={"Referer": "https://finance.sina.com.cn"},
            )
            txt = r.text or ""
            symbols = re.findall(r"\b(?:sh|sz|bj)\d{6}\b", txt)
            if symbols:
                merged: list[str] = []
                seen: set[str] = set()
                for s in symbols + out:
                    if s and s not in seen:
                        seen.add(s)
                        merged.append(s)
                return merged
    except Exception:
        # 失败则退化为原有逻辑
        pass

    return out

def _parse_a_share(symbol: str, fields: list[str]):
    return module_parse_a_share(fields)

def _parse_hk(symbol: str, fields: list[str]):
    return module_parse_hk(fields)

def _parse_us(symbol: str, fields: list[str]):
    return module_parse_us(fields)

def _parse_futures(symbol: str, fields: list[str]):
    return module_parse_futures(symbol, fields)

@app.route("/api/quote", methods=["GET"])
def quote():
    return quote_route(
        {
            "normalize_symbol_candidates": _normalize_symbol_candidates,
            "sina_quote": _sina_quote,
            "parse_us": _parse_us,
            "parse_hk": _parse_hk,
            "parse_futures": _parse_futures,
            "parse_a_share": _parse_a_share,
        }
    )


@app.route("/api/quote-candidates", methods=["GET"])
def quote_candidates():
    """
    行情候选查询：
    - 用于前端输入中文/关键词时展示多候选，避免默认命中第一条（如“黄金”=>山东黄金）。
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"code": 200, "msg": "success", "data": {"items": []}})

    q_lower = q.lower()
    symbols: list[str] = []
    seen: set[str] = set()

    def _push(sym: str):
        s = str(sym or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        symbols.append(s)

    # 大宗关键词优先放前面
    if q_lower in ("gold", "comexgold", "comex黄金", "黄金", "xau", "xau/usd", "xauusd") or "黄金" in q:
        _push("hf_GC")
    if q_lower in ("silver", "comexsilver", "comex白银", "白银", "xag", "xag/usd", "xagusd") or "白银" in q:
        _push("hf_SI")
    if q_lower in ("wti", "oil", "crude", "原油", "wti原油") or "原油" in q:
        _push("hf_CL")

    # 代码规范化候选
    for s in _normalize_symbol_candidates(q):
        _push(s)

    # 中文名称候选（新浪 suggest）
    try:
        if re.search(r"[\u4e00-\u9fff]", q):
            r = SESSION.get(
                "https://suggest3.sinajs.cn/suggest/type=11",
                params={"key": q},
                timeout=8,
                headers={"Referer": "https://finance.sina.com.cn"},
            )
            txt = r.text or ""
            for s in re.findall(r"\b(?:sh|sz|bj)\d{6}\b", txt):
                _push(s)
    except Exception:
        pass

    items = []
    for sym in symbols[:24]:
        try:
            used, fields = _sina_quote(sym)
            if not fields:
                items.append({"symbol": sym, "name": sym})
                continue
            if used.startswith("hf_"):
                # 期货：名称在字段[13]
                name = str(fields[13]).strip() if len(fields) > 13 else sym
                items.append({"symbol": used, "name": name or used})
            else:
                name, *_ = _parse_a_share(used, fields)
                items.append({"symbol": used, "name": str(name or used).strip()})
        except Exception:
            items.append({"symbol": sym, "name": sym})

    return jsonify({"code": 200, "msg": "success", "data": {"items": items}})


# 1) 人民币/美元（USDCNY）
def get_usdcny():
    return module_get_usdcny(
        {
            "session": SESSION,
            "headers": SINA_HEADERS,
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "cache_raw": _CACHE,
            "now_ts": _now_ts,
            "with_prev_change": _with_prev_change,
            "NAME_USDCNY": NAME_USDCNY,
        }
    )


# 2) 国际金价：优先 Stooq XAU/USD 现货，失败则新浪 hf_GC（COMEX 期货主连）
def get_gold():
    return module_get_gold(
        {
            "session": SESSION,
            "headers": SINA_HEADERS,
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "cache_raw": _CACHE,
            "now_ts": _now_ts,
            "with_prev_change": _with_prev_change,
            "NAME_GOLD": NAME_GOLD,
        }
    )


def get_silver():
    return module_get_silver(
        {
            "session": SESSION,
            "headers": SINA_HEADERS,
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "cache_raw": _CACHE,
            "now_ts": _now_ts,
            "with_prev_change": _with_prev_change,
            "NAME_SILVER": NAME_SILVER,
        }
    )


# 3) WTI 原油（纽约原油：hf_CL）
def get_crude_oil():
    return module_get_crude_oil(
        {
            "session": SESSION,
            "headers": SINA_HEADERS,
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "cache_raw": _CACHE,
            "now_ts": _now_ts,
            "with_prev_change": _with_prev_change,
            "NAME_WTI": NAME_WTI,
        }
    )


def get_index_quote(name: str, symbol: str):
    return module_get_index_quote(
        {"session": SESSION, "headers": SINA_HEADERS, "cache_get": _cache_get, "cache_set": _cache_set},
        name,
        symbol,
    )


# ===================== 对外API接口 =====================
@app.route("/api/core-quotes", methods=["GET"])
def core_quotes():
    return core_quotes_route(
        {
            "NAME_SSE": NAME_SSE,
            "NAME_SZSE": NAME_SZSE,
            "NAME_CHINEXT": NAME_CHINEXT,
            "get_index_quote": get_index_quote,
            "get_usdcny": get_usdcny,
            "get_gold": get_gold,
            "get_silver": get_silver,
            "get_crude_oil": get_crude_oil,
        }
    )


# 单独获取人民币/美元汇率
@app.route("/api/usdcny", methods=["GET"])
def usdcny():
    return usdcny_route(get_usdcny)


# 货币换算
@app.route("/api/convert", methods=["GET"])
def convert():
    return convert_route(SESSION)

@app.route("/api/fx/currencies", methods=["GET"])
def fx_currencies():
    return fx_currencies_route(SESSION, _cache_get, _cache_set)

# -------------------- AkShare：板块/概念（用于“热门话题”替代） --------------------
def _pick(row: dict, keys: list[str], default=None):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _to_float(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace("%", "")
        return float(s)
    except Exception:
        return default


NEWS_SOURCE_WEIGHTS = {
    "新华社": 1.0,
    "人民日报": 0.9,
    "央视新闻": 0.9,
    "央行": 1.0,
    "证监会": 0.9,
    "财联社": 0.75,
    "第一财经": 0.65,
    "澎湃新闻": 0.55,
}

NEWS_KEYWORDS = [
    "央行",
    "美联储",
    "降息",
    "加息",
    "通胀",
    "CPI",
    "PPI",
    "人民币",
    "汇率",
    "黄金",
    "原油",
    "AI",
    "芯片",
    "地产",
    "银行",
    "券商",
    "债券",
    "国债",
]

NEWS_SCORE_W = {
    "recency": 0.42,
    "source": 0.12,
    "keyword": 0.10,
    "importance": 0.32,
    "image": 0.04,
}

_NEWS_OLD_CATEGORY_SET = {
    "美国政经",
    "宏观政策",
    "科技产业",
    "金融市场",
    "地产行业",
    "公司动态",
    "大宗商品",
    "要闻",
    "市场关注",
}


def _parse_juhe_ctime(s: str) -> int:
    # "2025-12-24 17:28:14"
    try:
        dt = datetime.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception:
        return int(_now_ts())


def _news_db_path() -> str:
    return os.path.join(os.path.dirname(__file__), "news_cache.sqlite3")


def _news_db_conn():
    conn = sqlite3.connect(_news_db_path(), timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _news_db_init():
    return repo_news_db_init(os.path.dirname(__file__))


def _news_cache_get_many(ids: list[str]) -> dict[str, dict]:
    return repo_news_cache_get_many(os.path.dirname(__file__), ids)


def _news_cache_upsert(item: dict, summary: str, importance: int, keywords: list[str] | None = None, category: str | None = None):
    return repo_news_cache_upsert(os.path.dirname(__file__), _now_ts, item, summary, importance, keywords, category)


def _news_fetch_juhe(page: int = 1, num: int = 30) -> list[dict]:
    return news_fetch_juhe(SESSION, _parse_juhe_ctime, page=page, num=num)


def _news_fetch_tianapi(page: int = 1, num: int = 30) -> list[dict]:
    return news_fetch_tianapi(SESSION, page=page, num=num)


def _news_fallback_pic_url(news_id: str) -> str:
    return news_fallback_pic_url(news_id)


@app.route("/api/news/image", methods=["GET"])
def news_image():
    return news_image_route(SESSION, _news_fallback_pic_url)


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s != "" else default


_NEWS_WORKER_LOCK = threading.Lock()
_NEWS_WORKER_STARTED = {"started": False}
_NEWS_PENDING = set()  # news_id
_NEWS_QUEUE = []  # list[dict]
_NEWS_LLM_STATE = {"day": "", "used": 0}
_TOPICS_LLM_STATE = {"day": "", "used": 0}
_RESEARCH_LLM_STATE = {"day": "", "used": 0}


def _llm_chat(messages: list[dict], timeout_s: int = 25) -> str:
    from modules.news.llm import llm_chat
    return llm_chat(SESSION, messages, timeout_s=timeout_s)


def _news_llm_allow() -> bool:
    from modules.news.llm import news_llm_allow
    return news_llm_allow(_NEWS_LLM_STATE)


def _news_llm_mark_used():
    from modules.news.llm import news_llm_mark_used
    news_llm_mark_used(_NEWS_LLM_STATE)


def _parse_llm_json_obj(text: str) -> dict | None:
    from modules.news.llm import parse_llm_json_obj
    return parse_llm_json_obj(text)


def _fallback_summary(title: str, source: str | None) -> str:
    return fallback_summary(title, source)


def _fallback_category(title: str) -> str:
    return fallback_category(title)


def _llm_summarize_and_score(item: dict) -> tuple[str, int, list[str]]:
    return module_llm_summarize_and_score(
        SESSION,
        _NEWS_LLM_STATE,
        item,
        _news_keyword_hits,
        _fallback_summary,
        _fallback_category,
    )


def _start_news_worker():
    def _process_item(item):
        try:
            summary, importance, kw_hits = _llm_summarize_and_score(item)
            category = item.get("_category") or _fallback_category(item.get("title") or "")
            _news_cache_upsert(item, summary=summary, importance=importance, keywords=kw_hits, category=category)
        except Exception:
            try:
                summary = _fallback_summary(item.get("title"), item.get("source"))
                _news_cache_upsert(
                    item,
                    summary=summary,
                    importance=50,
                    keywords=_news_keyword_hits(item.get("title") or ""),
                    category=_fallback_category(item.get("title") or ""),
                )
            except Exception:
                pass

    return module_start_news_worker(
        _NEWS_LLM_STATE,
        _NEWS_WORKER_LOCK,
        _NEWS_QUEUE,
        _NEWS_PENDING,
        _NEWS_WORKER_STARTED,
        _process_item,
    )


def _enqueue_news_for_llm(items: list[dict]):
    _start_news_worker()
    with _NEWS_WORKER_LOCK:
        # 调试阶段每次最多排队 2 条，避免很快打满每日 50 次
        for it in items[:2]:
            nid = str(it.get("id") or "")
            if not nid or nid in _NEWS_PENDING:
                continue
            _NEWS_PENDING.add(nid)
            _NEWS_QUEUE.append(it)


def _news_source_weight(source: str | None) -> float:
    if not source:
        return 0.2
    s = str(source).strip()
    for k, w in NEWS_SOURCE_WEIGHTS.items():
        if k in s:
            return float(w)
    return 0.35


def _news_keyword_hits(title: str) -> list[str]:
    t = str(title or "")
    hits = [kw for kw in NEWS_KEYWORDS if kw and kw in t]
    seen = set()
    out = []
    for h in hits:
        if h not in seen:
            out.append(h)
            seen.add(h)
    return out


def _news_recency_score(ts: int) -> float:
    age_s = max(0.0, _now_ts() - float(ts or 0))
    age_h = age_s / 3600.0
    return max(0.0, 1.0 - (age_h / 48.0))


def _news_compute_score(item: dict) -> float:
    rec = _news_recency_score(int(item.get("ctime") or 0))
    src = _news_source_weight(item.get("source"))
    kw_hits = item.get("_kw_hits") or []
    kw = min(1.0, 0.15 * len(kw_hits))
    imp = float(item.get("importance") or 50) / 100.0
    img = 1.0 if item.get("picUrl") else 0.0
    w = NEWS_SCORE_W
    return (
        w["recency"] * rec
        + w["source"] * src
        + w["keyword"] * kw
        + w["importance"] * imp
        + w["image"] * img
    )


def _ak_df_to_items(df, kind: str):
    # 兼容不同 AkShare 版本的列名
    records = df.to_dict("records")
    items = []
    for r in records:
        name = _pick(r, ["板块名称", "行业名称", "概念名称", "名称", "板块", "name"])
        if not name:
            continue
        pct_raw = _pick(
            r,
            [
                "涨跌幅",
                "涨跌幅(%)",
                "涨跌幅%",
                "涨跌幅（%）",
                "涨跌幅(%) ",
                "pct_chg",
                "changepercent",
                "涨跌幅比例",
            ],
        )
        pct = _to_float(pct_raw, None)
        leader = _pick(r, ["领涨股", "领涨股票", "领涨股名称", "领涨"])
        items.append(
            {
                "kind": kind,
                "name": str(name),
                "pct_chg": round(float(pct), 2) if pct is not None else None,
                "leader": str(leader) if leader else None,
            }
        )
    # 按涨跌幅排序
    items.sort(key=lambda x: (x.get("pct_chg") is not None, x.get("pct_chg") or -10_000), reverse=True)
    return items


def _ak_try_first(ak, fn_names: list[str]):
    """按顺序尝试 ak 的多个函数名，返回 df。全部失败则抛出最后一个异常。"""
    last = None
    for name in fn_names:
        fn = getattr(ak, name, None)
        if not callable(fn):
            continue
        try:
            return fn()
        except Exception as e:
            last = e
            continue
    if last:
        raise last
    raise RuntimeError("AkShare 缺少可用函数")

TOPICS_REFRESH_SECONDS = 5 * 60  # 5分钟刷新一次

EASTMONEY_HEADERS = {
    "User-Agent": SESSION.headers.get("User-Agent"),
    "Referer": "https://quote.eastmoney.com/",
}


def _eastmoney_clist_get(fs: str, pz: int = 50):
    """
    东方财富板块列表（免费）:
    - 行业：fs=m:90+t:2
    - 概念：fs=m:90+t:3
    fields:
      f12: 代码, f14: 名称, f3: 涨跌幅, f2: 最新价, f62: 主力净流入(可选)
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": int(pz),
        "po": 1,  # desc
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": fs,
        "fields": "f12,f14,f2,f3,f62",
        "_": int(time.time() * 1000),
    }
    last = None
    for _ in range(3):
        try:
            r = SESSION.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=10)
            r.raise_for_status()
            j = r.json()
            diff = ((j.get("data") or {}).get("diff") or [])
            items = []
            for d in diff:
                name = d.get("f14")
                if not name:
                    continue
                items.append(
                    {
                        "kind": "concept" if "t:3" in fs else "industry",
                        "name": str(name),
                        "pct_chg": round(float(d.get("f3") or 0.0), 2),
                        "leader": None,
                    }
                )
            return items
        except Exception as e:
            last = e
            time.sleep(0.8)
    raise last or RuntimeError("东方财富 clist/get 失败")

def _parse_sina_json_v2(raw: str):
    """
    新浪 quotes_service 的 json_v2.php 返回的不是严格 JSON（key 未加引号）。
    这里做一个保守解析：先把 key 变成 "key":，再 json.loads；失败则退回 ast.literal_eval。
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    # 常见返回: [{symbol:"sh600000",name:"xxx",trade:"10.1",changepercent:"-0.12",...}, ...]
    fixed = re.sub(r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', raw)
    try:
        return json.loads(fixed)
    except Exception:
        try:
            return ast.literal_eval(fixed)
        except Exception:
            return None


def _sina_hq_node_data(node: str, num: int = 20):
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        "page": 1,
        "num": int(num),
        "sort": "changepercent",
        "asc": 0,
        "node": node,
        "_s_r_a": "init",
    }
    last = None
    for _ in range(3):
        try:
            r = SESSION.get(url, params=params, headers=SINA_HEADERS, timeout=10)
            r.raise_for_status()
            data = _parse_sina_json_v2(r.text)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            last = e
            time.sleep(0.6)
    raise last or RuntimeError("新浪 getHQNodeData 失败")


def _sina_stock_row_pct_chg(r: dict):
    """
    新浪 getHQNodeData：有成交价时用 (trade-settlement)/settlement；
    否则采用 API 的 changepercent；均无则 0.0（与第一财经等站点休市时展示 0.00% 一致）。
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


def _topics_hot_refresh_once():
    """
    刷新热门榜缓存：
    - 合并上证 A + 深证 A 涨幅榜节点（避免 hs_a 在盘前全 0 时北交所 bj 因排序挤满 Top10）
    - 涨跌幅：优先用成交价相对昨结算 settlement 计算；盘前无成交则 pct_chg 为 0.0
    失败时不覆盖 last_ok。
    """
    try:
        rows_sh = _sina_hq_node_data("sh_a", num=45)
        rows_sz = _sina_hq_node_data("sz_a", num=45)
        seen = set()
        rows = []
        for chunk in (rows_sh, rows_sz):
            for r in chunk:
                sym = str((r.get("symbol") or "")).strip()
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                rows.append(r)

        items = []
        for r in rows:
            name = r.get("name") or r.get("symbol") or ""
            if not name:
                continue
            pct = _sina_stock_row_pct_chg(r)
            leader = r.get("symbol") or None
            vol = int(_to_float(r.get("volume"), 0.0) or 0.0)
            prio = _symbol_exchange_prio(str(leader or ""))
            items.append(
                {
                    "kind": "topic",
                    "name": str(name),
                    "pct_chg": pct,
                    "leader": leader,
                    "_vol": vol,
                    "_prio": prio,
                }
            )
        items.sort(
            key=lambda x: (
                -(_to_float(x["pct_chg"], 0.0) or 0.0),
                x["_prio"],
                -x["_vol"],
            )
        )
        for it in items:
            it.pop("_vol", None)
            it.pop("_prio", None)
        payload = {
            "code": 200,
            "msg": "success",
            "data": {
                "items": items,
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            },
        }
        _cache_set("topics_hot", payload)
        _cache_set("topics_hot_last_ok", payload)
        return True
    except Exception as e:
        _cache_set(
            "topics_hot_error",
            {
                "code": 500,
                "msg": f"热门榜刷新失败：{e}",
                "data": {"items": [], "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())},
                "trace": traceback.format_exc()[:2000],
            },
        )
        return False


def _start_topics_hot_scheduler():
    if _CACHE.get("_topics_scheduler_started"):
        return
    _CACHE["_topics_scheduler_started"] = (_now_ts(), True)

    def _loop():
        # 启动后先尝试预热一次（不阻塞主线程）
        _topics_hot_refresh_once()
        while True:
            time.sleep(TOPICS_REFRESH_SECONDS)
            _topics_hot_refresh_once()

    threading.Thread(target=_loop, daemon=True).start()


@app.route("/api/boards/industry", methods=["GET"])
def boards_industry():
    return boards_industry_route(
        {
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "TOPICS_REFRESH_SECONDS": TOPICS_REFRESH_SECONDS,
            "sina_hq_node_data": _sina_hq_node_data,
            "to_float": _to_float,
            "now_str": lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
    )


@app.route("/api/boards/concept", methods=["GET"])
def boards_concept():
    return boards_concept_route(
        {
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "TOPICS_REFRESH_SECONDS": TOPICS_REFRESH_SECONDS,
            "sina_hq_node_data": _sina_hq_node_data,
            "to_float": _to_float,
            "now_str": lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
    )


@app.route("/api/topics/hot", methods=["GET"])
def topics_hot():
    return topics_hot_route(
        {
            "start_topics_hot_scheduler": _start_topics_hot_scheduler,
            "cache_get": _cache_get,
            "TOPICS_REFRESH_SECONDS": TOPICS_REFRESH_SECONDS,
            "topics_hot_refresh_once": _topics_hot_refresh_once,
        }
    )


def _stock_snapshot_for_insight(raw_symbol: str) -> dict | None:
    """新浪 A 股快照，供个股 AI 解读绑定真实 OHLC，避免仅依据榜单字段空泛发挥。"""
    try:
        raw = (raw_symbol or "").strip()
        if not raw:
            return None

        def _search_stock_symbol_by_name(name: str) -> list[str]:
            """
            新浪 suggest(type=11) 根据中文公司名/证券名返回候选 symbol。
            返回：如 ['sh600519','sz000001']。
            """
            try:
                r = SESSION.get(
                    "https://suggest3.sinajs.cn/suggest/type=11",
                    params={"key": name},
                    timeout=8,
                    headers={"Referer": "https://finance.sina.com.cn"},
                )
                txt = r.text or ""
                # 直接抽取 sh/sz/bj + 6 位数字（规避中文编码干扰）
                symbols = re.findall(r"\b(?:sh|sz|bj)\d{6}\b", txt)
                out: list[str] = []
                seen: set[str] = set()
                for s in symbols:
                    if s not in seen:
                        seen.add(s)
                        out.append(s)
                return out
            except Exception:
                return []

        raw_lower = raw.lower()
        # 若输入不是标准代码（sh/sz/bj + 6位），尝试按“中文名”做 suggest 搜索
        if not re.match(r"^(sh|sz|bj)\d{6}$", raw_lower):
            candidates = _search_stock_symbol_by_name(raw)
            if candidates:
                for sym in candidates:
                    used, fields = _sina_quote(sym)
                    if not fields:
                        continue
                    name, price, open_p, prev_close, high, low, update_time = _parse_a_share(used, fields)
                    chg = round(price - prev_close, 4) if prev_close else 0.0
                    pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
                    return {
                        "symbol": used,
                        "name": str(name).strip()[:40],
                        "price": round(float(price), 2),
                        "chg": round(float(chg), 2),
                        "pct_chg": float(pct),
                        "open": round(float(open_p), 2),
                        "prev_close": round(float(prev_close), 2),
                        "high": round(float(high), 2),
                        "low": round(float(low), 2),
                        "update_time": str(update_time)[:32],
                    }
        # 允许“黄金/白银”类输入直接返回 COMEX 期货快照（用于智能投研）
        if raw_lower in ("gold", "comexgold", "comex黄金", "黄金", "xau", "xau/usd", "xauusd"):
            return get_gold()
        if "comex" in raw_lower and "gold" in raw_lower:
            return get_gold()
        if "黄金" in raw:
            return get_gold()
        if raw_lower in ("silver", "comexsilver", "comex白银", "白银", "xag", "xag/usd", "xagusd"):
            return get_silver()
        if "comex" in raw_lower and "silver" in raw_lower:
            return get_silver()
        if "白银" in raw:
            return get_silver()
        for sym in _normalize_symbol_candidates(raw):
            used, fields = _sina_quote(sym)
            if not fields:
                continue
            name, price, open_p, prev_close, high, low, update_time = _parse_a_share(used, fields)
            chg = round(price - prev_close, 4) if prev_close else 0.0
            pct = round((chg / prev_close) * 100, 2) if prev_close else 0.0
            return {
                "symbol": used,
                "name": str(name).strip()[:40],
                "price": round(float(price), 2),
                "chg": round(float(chg), 2),
                "pct_chg": float(pct),
                "open": round(float(open_p), 2),
                "prev_close": round(float(prev_close), 2),
                "high": round(float(high), 2),
                "low": round(float(low), 2),
                "update_time": str(update_time)[:32],
            }
    except Exception:
        return None
    return None


@app.route("/api/topics/stock-insight", methods=["GET", "POST", "OPTIONS"])
def topics_stock_insight():
    if request.method == "GET":
        return jsonify(
            {
                "code": 200,
                "msg": "ok",
                "data": {
                    "endpoint": "/api/topics/stock-insight",
                    "hint": "个股解读请使用 POST，Content-Type: application/json",
                },
            }
        )
    if request.method == "OPTIONS":
        return ("", 204)
    return topics_stock_insight_route(
        {
            "session": SESSION,
            "topics_llm_state": _TOPICS_LLM_STATE,
            "fetch_quote": _stock_snapshot_for_insight,
        }
    )


@app.route("/api/topics/board-insight", methods=["GET", "POST", "OPTIONS"])
def topics_board_insight():
    if request.method == "GET":
        return jsonify(
            {
                "code": 200,
                "msg": "ok",
                "data": {
                    "endpoint": "/api/topics/board-insight",
                    "hint": "盘面要点请使用 POST，Content-Type: application/json",
                },
            }
        )
    if request.method == "OPTIONS":
        return ("", 204)
    return topics_board_insight_route({"session": SESSION, "topics_llm_state": _TOPICS_LLM_STATE})


def _fetch_hot_items_for_research(limit: int = 20) -> list[dict]:
    """
    给智能投研提供“热点涨幅榜样本”，尽量走缓存；失败则返回空列表。
    """
    try:
        cached = _cache_get("topics_hot", ttl_s=TOPICS_REFRESH_SECONDS)
        if not cached or cached.get("code") != 200:
            _topics_hot_refresh_once()
            cached = _cache_get("topics_hot", ttl_s=TOPICS_REFRESH_SECONDS)
        if cached and cached.get("code") == 200:
            items = ((cached.get("data") or {}).get("items") or [])[:limit]
            return items
    except Exception:
        pass
    return []


@app.route("/api/research/analyze", methods=["GET", "POST", "OPTIONS"])
def research_analyze():
    # 前端只需要一个接口；GET 提示，POST 才会做实际研判
    return research_analyze_route(
        {
            "research_analyze": module_research_analyze,
            "session": SESSION,
            "research_llm_state": _RESEARCH_LLM_STATE,
            "fetch_stock_snapshot": _stock_snapshot_for_insight,
            "fetch_hot_items": _fetch_hot_items_for_research,
        }
    )


@app.route("/api/research/tasks/<task_id>", methods=["GET"])
def research_task_status(task_id):
    return research_task_status_route(task_id)


@app.route("/api/research/tasks/stream", methods=["GET"])
def research_tasks_stream():
    return research_tasks_stream_route()


@app.route("/api/research/chat/sessions", methods=["GET"])
def research_chat_sessions():
    return research_chat_sessions_route()


@app.route("/api/research/chat/sessions/<session_id>", methods=["GET", "DELETE"])
def research_chat_session_detail(session_id):
    if request.method == "DELETE":
        return research_chat_session_delete_route(session_id)
    return research_chat_session_messages_route(session_id)


@app.route("/api/news/home", methods=["GET"])
def news_home():
    return news_home_route(
        {
            "news_db_init": _news_db_init,
            "cache_get": _cache_get,
            "cache_set": _cache_set,
            "news_fetch_juhe": _news_fetch_juhe,
            "news_fetch_tianapi": _news_fetch_tianapi,
            "news_cache_get_many": _news_cache_get_many,
            "news_old_category_set": _NEWS_OLD_CATEGORY_SET,
            "news_keyword_hits": _news_keyword_hits,
            "fallback_category": _fallback_category,
            "news_compute_score": _news_compute_score,
            "enqueue_news_for_llm": _enqueue_news_for_llm,
            "fallback_summary": _fallback_summary,
        }
    )


@app.route("/api/videos", methods=["GET"])
def videos():
    return videos_route(os.path.dirname(__file__), SESSION)


@app.route("/api/video-cover", methods=["GET"])
def video_cover():
    return video_cover_route(SESSION)


@app.route("/api/ping", methods=["GET"])
def api_ping():
    """用于确认你启动的是本仓库 backend（含涨幅榜 AI 等接口），避免 5000 端口被其它程序占用。"""
    return jsonify(
        {
            "code": 200,
            "msg": "caidong-backend",
            "data": {
                "stock_insight_get": "/api/topics/stock-insight",
                "board_insight_get": "/api/topics/board-insight",
                "research_analyze_get": "/api/research/analyze",
            },
        }
    )


@app.route("/api/llm/ping", methods=["GET"])
def api_llm_ping():
    """
    大模型连通性自检：
    - 未配置：返回 code=503, status=not_configured
    - 已配置但调用失败：返回 code=502, status=error（含简要错误）
    - 调用成功：返回 code=200, status=ok
    """
    base = (llm_env_get("LLM_API_BASE") or "").strip()
    key = (llm_env_get("LLM_API_KEY") or "").strip()
    model = (llm_env_get("LLM_MODEL") or "").strip()
    configured = bool(base and key and model)
    masked_key = f"{key[:6]}***{key[-4:]}" if len(key) >= 12 else ("***" if key else "")

    if not configured:
        return (
            jsonify(
                {
                    "code": 503,
                    "msg": "llm not configured",
                    "data": {
                        "status": "not_configured",
                        "configured": False,
                        "checks": {
                            "LLM_API_BASE": bool(base),
                            "LLM_API_KEY": bool(key),
                            "LLM_MODEL": bool(model),
                        },
                    },
                }
            ),
            503,
        )

    try:
        txt = module_llm_chat(
            SESSION,
            [
                {"role": "system", "content": "你是连通性检测助手。只回复 pong。"},
                {"role": "user", "content": "ping"},
            ],
            timeout_s=12,
        )
        return jsonify(
            {
                "code": 200,
                "msg": "llm ok",
                "data": {
                    "status": "ok",
                    "configured": True,
                    "base": base.rstrip("/"),
                    "model": model,
                    "api_key_masked": masked_key,
                    "response_preview": str(txt)[:80],
                },
            }
        )
    except Exception as e:
        err = str(e)
        hint = "unknown"
        lerr = err.lower()
        if "401" in lerr or "403" in lerr or "unauthorized" in lerr or "forbidden" in lerr:
            hint = "auth_failed"
        elif "timeout" in lerr or "timed out" in lerr:
            hint = "network_timeout"
        elif "404" in lerr or "model" in lerr:
            hint = "model_or_endpoint_error"
        elif "max retries exceeded" in lerr:
            hint = "network_unreachable"
        return (
            jsonify(
                {
                    "code": 502,
                    "msg": "llm ping failed",
                    "data": {
                        "status": "error",
                        "configured": True,
                        "base": base.rstrip("/"),
                        "model": model,
                        "api_key_masked": masked_key,
                        "hint": hint,
                        "error": err[:500],
                    },
                }
            ),
            502,
        )


# 股票查询（新浪行情）
@app.route("/api/stock", methods=["GET"])
def stock():
    return stock_route(
        {
            "normalize_symbol_candidates": _normalize_symbol_candidates,
            "sina_quote": _sina_quote,
            "parse_a_share": _parse_a_share,
        }
    )


# ===================== 启动服务 =====================
if __name__ == "__main__":
    print("\n" + "=" * 56)
    print("  财懂了 backend（Flask）")
    print("  必须先在本目录启动：  cd d:\\demo2\\backend   再  python app.py")
    print("  自检: http://127.0.0.1:5000/api/ping  应返回 JSON 含 caidong-backend")
    print("  解读: http://127.0.0.1:5000/api/topics/stock-insight (GET 应返回 JSON)")
    print("  若仍为 Not Found，说明 5000 端口不是本进程，请结束占用后重试。")
    print("=" * 56 + "\n")
    dev_reload = str(os.environ.get("DEV_RELOAD", "0")).strip().lower()
    if dev_reload in ("1", "true", "yes", "y"):
        # 开发自动重载：修改后端代码后自动重启（会有一个 reloader 进程）
        app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
    else:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

