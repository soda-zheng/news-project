from __future__ import annotations

import json
import os
import re

# 本地开发：backend/.env 中可配置 LLM_API_BASE / LLM_MODEL / LLM_API_KEY
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass
import threading
import time
import uuid
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request
import requests

app = Flask(__name__)
app.json.ensure_ascii = False
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


def _get_llm_env():
    # 兼容用户在环境变量中提供 LLM_* 配置（不在代码里写 key）
    return {
        "provider": str(os.environ.get("LLM_PROVIDER") or "openai_compat"),
        "use_local": str(os.environ.get("LLM_USE_LOCAL") or "0"),
        "api_base": str(os.environ.get("LLM_API_BASE") or ""),
        "model": str(os.environ.get("LLM_MODEL") or ""),
        "api_key": str(os.environ.get("LLM_API_KEY") or ""),
    }


def _openai_compat_chat(
    messages: list[dict],
    max_tokens: int = 420,
    temperature: float = 0.4,
    *,
    json_mode: bool = False,
    timeout_sec: int = 60,
) -> str:
    env = _get_llm_env()
    api_base = env.get("api_base") or ""
    model = env.get("model") or ""
    api_key = env.get("api_key") or ""
    if not api_base or not model or not api_key:
        raise RuntimeError("LLM env not configured (LLM_API_BASE/LLM_MODEL/LLM_API_KEY)")

    url = api_base.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        # 通义 compatible-mode 与 OpenAI 对齐时支持 json_object，可显著减少「非 JSON」截断
        payload["response_format"] = {"type": "json_object"}

    r = SESSION.post(url, headers=headers, json=payload, timeout=timeout_sec)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        hint = ""
        try:
            hint = (r.text or "")[:400]
        except Exception:
            pass
        raise RuntimeError(f"LLM HTTP {r.status_code}: {hint or e}") from e

    data = r.json()
    err = data.get("error")
    if err:
        raise RuntimeError(str(err))
    # OpenAI compatible
    content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content")
    if not content:
        raise RuntimeError(f"LLM empty content: {str(data)[:200]}")
    return str(content)


def _strip_markdown_json_fence(text: str) -> str:
    """去掉 ```json ... ``` 等包裹，保留内部文本。"""
    s = str(text or "").strip()
    if not s:
        return s
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    s = _strip_markdown_json_fence(text)
    start = s.find("{")
    if start < 0:
        return None
    # 先尝试从首个 { 起解析完整对象（避免串里再含 } 时截断错误）
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    try:
        last = s.rfind("}")
        if last > start:
            obj = json.loads(s[start : last + 1])
            return obj if isinstance(obj, dict) else None
    except Exception:
        return None
    return None


def _llm_repair_insight_json(bad_text: str) -> dict | None:
    """二次调用：把模型输出的杂乱文本压成严格 JSON（仍失败则 None）。"""
    try:
        snippet = str(bad_text or "").strip()
        if len(snippet) > 6000:
            snippet = snippet[:6000] + "…"
        messages = [
            {
                "role": "system",
                "content": "你只输出一个 JSON 对象，键必须为 aiInsightList、suggestionList 和 quickQuestionList，值均为中文字符串数组。"
                "不要 Markdown、不要代码块、不要解释。",
            },
            {
                "role": "user",
                "content": "将以下内容整理成上述 JSON（若能直接解析则抽取数组）：\n\n" + snippet,
            },
        ]
        try:
            out = _openai_compat_chat(
                messages, max_tokens=900, temperature=0.05, json_mode=True, timeout_sec=70
            )
        except RuntimeError:
            out = _openai_compat_chat(
                messages, max_tokens=900, temperature=0.05, json_mode=False, timeout_sec=70
            )
        return _extract_json_object(out)
    except Exception:
        return None


def _invoke_llm_for_insight(messages: list[dict]) -> str:
    """优先 json_object；若接口不支持则自动降级为非 JSON 模式。"""
    try:
        return _openai_compat_chat(
            messages, max_tokens=1024, temperature=0.35, json_mode=True, timeout_sec=65
        )
    except RuntimeError as e:
        err_txt = str(e).lower()
        if "http 400" in err_txt or "response_format" in err_txt or "not support" in err_txt:
            return _openai_compat_chat(
                messages, max_tokens=1024, temperature=0.35, json_mode=False, timeout_sec=65
            )
        raise


def _safe_bullets(items, max_items: int = 5):
    out = []
    if isinstance(items, list):
        for x in items:
            s = str(x).strip()
            if s:
                out.append(s[:80])
            if len(out) >= max_items:
                break
    return out


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _parse_symbol(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    if len(s) == 8 and (s.startswith("sh") or s.startswith("sz") or s.startswith("bj")) and s[2:].isdigit():
        return s[2:]
    if len(s) == 6 and s.isdigit():
        return s
    return s


def _sina_symbol(code: str) -> str:
    c = _parse_symbol(code)
    if len(c) != 6 or not c.isdigit():
        return c
    if c.startswith(("6", "9")):
        return f"sh{c}"
    if c.startswith("8"):
        return f"bj{c}"
    return f"sz{c}"


def _to_float(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace("%", "")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _parse_sina_var(payload: str) -> list[str]:
    if not payload or "=" not in payload:
        return []
    right = payload.split("=", 1)[1].strip().strip(";").strip()
    right = right.strip('"')
    if not right:
        return []
    return right.split(",")


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


def _is_a_share_6digit(code: str) -> bool:
    c = _parse_symbol(code)
    return bool(c) and len(c) == 6 and c.isdigit()


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
    """AKShare 备用：东财买卖盘/盘口（含最新、涨跌幅、开高低、昨收）。"""
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
    """
    A 股实时：新浪 hq.sinajs.cn 优先；无数据或价格为 0 时用东财 bid_ask 兜底。
    """
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


def _parse_sina_json_v2(raw: str):
    s = str(raw or "").strip()
    if not s:
        return []
    fixed = re.sub(r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
    try:
        out = json.loads(fixed)
        return out if isinstance(out, list) else []
    except Exception:
        return []


def _fetch_hot_node(node: str, num: int = 40):
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    resp = SESSION.get(
        url,
        params={"page": 1, "num": num, "sort": "changepercent", "asc": 0, "node": node, "_s_r_a": "init"},
        timeout=10,
    )
    rows = _parse_sina_json_v2(resp.text)
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


def _parse_sina_flash_time(ts: str) -> int:
    """新浪财经全球快讯时间 -> unix 秒，解析失败则 0。"""
    s = str(ts or "").strip()
    if not s:
        return 0
    try:
        return int(time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S")))
    except Exception:
        pass
    try:
        return int(time.mktime(time.strptime(s[:16], "%Y-%m-%d %H:%M")))
    except Exception:
        return 0


def _fetch_sina_global_flash(limit: int = 20):
    """
    新浪财经-全球财经快讯（AkShare: stock_info_global_sina）
    限量：默认取最近 limit 条（数据源本身约 20 条）。
    目标页: https://finance.sina.com.cn/7x24
    """
    limit = max(1, min(50, int(limit or 20)))
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_info_global_sina()
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    cols = list(df.columns)
    if len(cols) < 2:
        return None
    tcol = "时间" if "时间" in cols else cols[0]
    ccol = "内容" if "内容" in cols else cols[1]
    base_url = "https://finance.sina.com.cn/7x24"
    out = []
    for j, (_, row) in enumerate(df.head(limit).iterrows()):
        tstr = str(row.get(tcol) or "").strip()
        content = str(row.get(ccol) or "").strip()
        if not content:
            continue
        ctime = _parse_sina_flash_time(tstr)
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"sina-global|{tstr}|{content[:120]}").hex[:16]
        title = content[:80] + ("…" if len(content) > 80 else "")
        out.append(
            {
                "id": nid,
                "title": title,
                "summary": content,
                "source": "新浪财经",
                "category": "全球财经快讯",
                "ctime": ctime,
                "picUrl": "",
                "url": base_url,
                "importance": 90,
                "score": 100.0 - j * 0.01,
            }
        )
    return out


def _fetch_news_live(page: int = 1, num: int = 20):
    """
    新浪滚动新闻开放接口（无需 key）：
    pageid=155 财经页，lid=1686 财经要闻
    """
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    resp = SESSION.get(
        url,
        params={"pageid": 155, "lid": 1686, "num": num, "page": page},
        timeout=10,
    )
    data = resp.json() if resp.text else {}
    lst = ((data or {}).get("result") or {}).get("data") or []
    ashare_keywords = [
        "a股",
        "沪深",
        "上证",
        "深证",
        "创业板",
        "北交所",
        "证监会",
        "ipo",
        "并购",
        "回购",
        "分红",
        "财报",
        "业绩",
        "券商",
        "银行",
        "半导体",
        "新能源",
        "ai",
        "算力",
        "机器人",
        "医药",
        "白酒",
        "地产",
        "出口",
    ]
    intl_keywords = ["美联储", "非农", "cpi", "pmi", "美元", "美债", "纳指", "道指", "原油", "黄金", "地缘", "关税"]
    domestic_keywords = ["国务院", "央行", "财政部", "发改委", "工信部", "住建部", "政策", "国常会", "稳增长", "消费", "制造业"]
    items = []
    for x in lst:
        if not isinstance(x, dict):
            continue
        nid = str(x.get("oid") or x.get("docid") or x.get("id") or uuid.uuid4().hex[:8])
        title = str(x.get("title") or "").strip()
        if not title:
            continue
        summary = str(x.get("intro") or x.get("description") or title[:80]).strip()
        ctime = int(_to_float(x.get("ctime"), 0) or 0)
        url = str(x.get("url") or "").strip()
        if not url:
            url = f"https://search.sina.com.cn/?q={requests.utils.quote(title)}"
        pic = ""
        pics = x.get("images") or []
        if isinstance(pics, list) and pics:
            first = pics[0]
            if isinstance(first, dict):
                pic = str(first.get("u") or first.get("url") or "").strip()
        source = str(x.get("source") or "新浪财经")
        content = f"{title} {summary}".lower()
        score = 0.0
        score += sum(1.0 for k in ashare_keywords if k in content) * 2.5
        score += sum(1.0 for k in domestic_keywords if k.lower() in content) * 1.8
        score += sum(1.0 for k in intl_keywords if k.lower() in content) * 1.6
        if "人民日报" in source or "新华社" in source or "央视" in source:
            score += 2.2
        elif "新浪" in source or "证券时报" in source or "财联社" in source:
            score += 1.2
        age_hours = max(0, (time.time() - ctime) / 3600.0) if ctime else 24
        freshness = max(0.0, 3.0 - age_hours / 8.0)
        score += freshness
        if score < 2.5:
            continue
        category = "A股相关"
        if any(k.lower() in content for k in intl_keywords):
            category = "国际市场"
        if any(k.lower() in content for k in domestic_keywords):
            category = "国内宏观"
        items.append(
            {
                "id": nid,
                "title": title,
                "summary": summary,
                "source": source,
                "category": category,
                "ctime": ctime,
                "picUrl": pic,
                "url": url,
                "importance": int(min(95, 45 + score * 5)),
                "score": round(score, 3),
            }
        )
    items.sort(key=lambda x: (x.get("score") or 0, x.get("ctime") or 0), reverse=True)
    return items


_SESSIONS: dict[str, dict] = {}
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2)

# 全市场 A 股代码+名称（用于 /api/stock/search），短时缓存减轻 AKShare 请求压力
_STOCK_A_NAME_LOCK = threading.Lock()
_STOCK_A_NAME_CACHE: dict[str, object] = {"ts": 0.0, "items": []}
_STOCK_A_NAME_TTL = float(os.environ.get("STOCK_A_NAME_CACHE_SEC", "600"))


def _normalize_a_code(raw: object) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 6:
        return digits[-6:]
    if len(s) == 6 and s.isdigit():
        return s
    return ""


def _df_to_code_name_items(df) -> list[dict[str, str]]:
    if df is None or getattr(df, "empty", True):
        return []
    col_code = col_name = None
    for c in df.columns:
        cs = str(c).lower()
        if col_code is None and ("代码" in str(c) or cs == "code"):
            col_code = c
        if col_name is None and ("名称" in str(c) or "name" == cs):
            col_name = c
    if col_code is None or col_name is None:
        return []
    codes = df[col_code].astype(str).str.strip()
    names = df[col_name].astype(str).str.strip()
    out: list[dict[str, str]] = []
    for c, n in zip(codes, names):
        c6 = _normalize_a_code(c)
        if len(c6) == 6 and c6.isdigit() and n:
            out.append({"code": c6, "name": n})
    return out


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
    """返回 [{code, name}, ...]，必要时刷新缓存。"""
    now = time.time()
    with _STOCK_A_NAME_LOCK:
        cached = _STOCK_A_NAME_CACHE["items"]
        ts = float(_STOCK_A_NAME_CACHE["ts"] or 0)
        if isinstance(cached, list) and cached and (now - ts) < _STOCK_A_NAME_TTL:
            return cached, None
    items_new, err = _download_a_share_code_name_list()
    with _STOCK_A_NAME_LOCK:
        if items_new:
            _STOCK_A_NAME_CACHE["items"] = items_new
            _STOCK_A_NAME_CACHE["ts"] = time.time()
            return items_new, None
        stale = _STOCK_A_NAME_CACHE["items"]
        if isinstance(stale, list) and stale:
            return stale, err
        return [], err or "暂无股票列表"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"code": 200, "msg": "finance-backend", "data": {"time": _now_str()}})


@app.route("/api/topics/hot", methods=["GET"])
def topics_hot():
    try:
        limit = int(request.args.get("limit", "10") or "10")
    except Exception:
        limit = 10
    limit = max(1, min(100, limit))
    try:
        rows = _fetch_hot_node("sh_a", 45) + _fetch_hot_node("sz_a", 45)
        seen = set()
        uniq = []
        for x in rows:
            key = str(x.get("leader") or "")
            if key in seen:
                continue
            seen.add(key)
            uniq.append(x)
        uniq.sort(key=lambda x: _to_float(x.get("pct_chg"), -9999) or -9999, reverse=True)
        return jsonify({"code": 200, "msg": "success", "data": {"items": uniq[:limit], "update_time": _now_str()}})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取热点失败：{e}", "data": None})


@app.route("/api/news/home", methods=["GET"])
def news_home():
    try:
        page = int(request.args.get("page", "1") or "1")
        num = int(request.args.get("num", "20") or "20")
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：page/num", "data": None})
    page = max(1, page)
    num = max(1, min(20, num))
    try:
        # 优先：新浪财经全球财经快讯（AkShare stock_info_global_sina，约 20 条）
        sina_global = _fetch_sina_global_flash(limit=20)
        if sina_global:
            featured = sina_global[:3]
            remain = sina_global[3:] if len(sina_global) > 3 else []
            return jsonify(
                {
                    "code": 200,
                    "msg": "success",
                    "data": {
                        "page": page,
                        "num": num,
                        "update_time": _now_str(),
                        "source": "akshare-stock_info_global_sina",
                        "source_page": "https://finance.sina.com.cn/7x24",
                        "featured": featured,
                        "items": remain,
                    },
                }
            )
        items = _fetch_news_live(page=page, num=num)
        featured = items[:3]
        remain = items[3:] if len(items) > 3 else []
        return jsonify(
            {
                "code": 200,
                "msg": "success",
                "data": {
                    "page": page,
                    "num": num,
                    "update_time": _now_str(),
                    "source": "sina-roll",
                    "featured": featured,
                    "items": remain,
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取新闻失败：{e}", "data": None})


@app.route("/api/news/sina-global", methods=["GET"])
def news_sina_global():
    """新浪财经全球快讯原始通道（方便单独联调）。"""
    try:
        limit = int(request.args.get("limit", "20") or "20")
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))
    try:
        items = _fetch_sina_global_flash(limit=limit)
        if not items:
            return jsonify(
                {
                    "code": 503,
                    "msg": "未获取到数据（请确认已安装 akshare：pip install -r requirements.txt，且网络可访问新浪）",
                    "data": None,
                }
            )
        return jsonify(
            {
                "code": 200,
                "msg": "success",
                "data": {
                    "update_time": _now_str(),
                    "source": "akshare-stock_info_global_sina",
                    "source_page": "https://finance.sina.com.cn/7x24",
                    "items": items,
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e), "data": None})


def _df_to_records(df):
    if df is None or getattr(df, "empty", True):
        return []
    import pandas as pd

    def _clean(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        return float(v) if isinstance(v, (int, float)) else v

    rows = []
    for _, row in df.iterrows():
        rows.append({str(k): _clean(row[k]) for k in df.columns})
    return rows


@app.route("/api/stock", methods=["GET"])
def stock():
    raw_in = str(request.args.get("symbol", "") or "").strip()
    symbol = _parse_symbol(raw_in)
    if not _is_a_share_6digit(symbol):
        return jsonify({"code": 400, "msg": "当前仅支持沪深京 A 股 6 位数字代码", "data": None})
    try:
        item = _fetch_a_share_quote(symbol)
        if not item:
            return jsonify({"code": 404, "msg": "未找到该股票或数据源暂不可用", "data": None})
        return jsonify({"code": 200, "msg": "success", "data": {**item, "input_symbol": raw_in}})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询失败：{e}", "data": None})


@app.route("/api/stock/search", methods=["GET"])
def stock_search():
    """按代码或简称子串搜索沪深京 A 股（全市场列表来自 AKShare，带服务端缓存）。"""
    q = str(request.args.get("q", "") or "").strip()
    try:
        limit = int(request.args.get("limit", "30") or "30")
    except Exception:
        limit = 30
    limit = max(1, min(80, limit))
    if not q:
        return jsonify({"code": 200, "msg": "success", "data": {"items": [], "update_time": _now_str()}})
    items, err = _get_a_share_search_index()
    if not items:
        return jsonify({"code": 503, "msg": err or "股票列表暂不可用", "data": {"items": [], "update_time": _now_str()}})
    ql = q.lower()
    out: list[dict[str, str]] = []
    for it in items:
        name = str(it.get("name") or "")
        code = str(it.get("code") or "")
        if q in name or q in code or (name and ql in name.lower()):
            out.append({"code": code, "name": name})
            if len(out) >= limit:
                break
    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {"items": out, "q": q, "limit": limit, "update_time": _now_str()},
        }
    )


def _df_pick_col(df, *names: str):
    cols = list(df.columns)
    for want in names:
        for c in cols:
            sc = str(c)
            if sc == want or want in sc:
                return c
    return None


def _sina_symbol_prefix(code6: str) -> str:
    # 新浪日线/分钟 K 接口通常需要 sh/sz 前缀
    c = str(code6).strip()
    return ("sh" if c.startswith(("6", "9")) else "sz") + c


def _parse_maybe_timestamp_to_ymd(day: object) -> str:
    """
    尝试把新浪返回的 day 字段解析成 YYYY-MM-DD。
    新浪接口实际返回可能是：日期字符串 / Unix 秒 / Unix 毫秒 / 带数字包装字符串。
    """
    if day is None:
        return ""
    if isinstance(day, (int, float)):
        ts = int(day)
        # 10位通常是秒；13位通常是毫秒
        if ts > 10_000_000_000:
            ts = ts // 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return ""

    s = str(day).strip()
    if not s:
        return ""
    # 常见 YYYY-MM-DD 或 YYYY-MM-DD HH:mm
    if "-" in s:
        return s[:10]
    # YYYYMMDD
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    # 兜底：提取 10/13 位数字当作时间戳
    m = re.search(r"(\d{10,13})", s)
    if m:
        ts = int(m.group(1))
        if ts > 10_000_000_000:
            ts = ts // 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return ""
    return s[:10]


def _fetch_daily_bars_sina(symbol: str) -> dict | None:
    """
    AKShare 挂掉时的兜底：使用新浪 quotes.sina.cn 的公开 K 线接口抓取日线。
    返回结构与当前前端期望一致：
      { dates: [...], candle: [[open, close, low, high], ...], volume: [...], high_52w, low_52w, percentile, last_close, trade_days }
    """
    code6 = _parse_symbol(symbol)  # 保险：调用方可能传了带前缀
    if not _is_a_share_6digit(code6):
        return None

    prefix = _sina_symbol_prefix(code6)  # sh600519 / sz000001
    url = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    def pick_arrays(container: object) -> dict | None:
        if not isinstance(container, dict):
            return None
        need = ["day", "open", "high", "low", "close"]
        if all(k in container for k in need):
            return container
        # 可能包在 data 里
        if "data" in container and isinstance(container["data"], dict):
            d = container["data"]
            if all(k in d for k in need):
                return d
        return None

    # 兜底：不同资料里日K的 scale 写法不完全一致，做多候选重试更稳
    # 实测优先使用 240（返回 list 且 day 为 YYYY-MM-DD，适合直接当日线）。
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

        # 有些情况下返回可能带非 JSON 前缀；尽量抓取 JSON 段
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

        # 情况 1：obj 是 list（scale=240 的实测返回）
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

        # 情况 2：obj 是 dict（数组式返回）
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

        # 统一按日期从旧到新排序
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

    # 全部候选失败
    _fetch_daily_bars_sina.last_err = last_err
    return None


@app.route("/api/stock/daily-bars", methods=["GET"])
def stock_daily_bars():
    """A 股近一年高低点与日线收盘价序列（用于网页 K 线与分位）。"""
    raw_in = str(request.args.get("symbol", "") or "").strip()
    symbol = _parse_symbol(raw_in)
    if not _is_a_share_6digit(symbol):
        return jsonify({"code": 400, "msg": "仅支持沪深京 A 股 6 位代码", "data": None})

    # 频繁切换/刷新会导致 akshare 拉取被限流：做一层简单内存缓存。
    now_ts = time.time()
    cached = _STOCK_DAILY_BARS_CACHE.get(symbol)
    if cached and (now_ts - cached.get("ts", 0)) < _STOCK_DAILY_BARS_TTL_SEC:
        return jsonify({"code": 200, "msg": "success(cached)", "data": cached.get("data")})
    try:
        import akshare as ak
    except ImportError:
        return jsonify({"code": 503, "msg": "未安装 akshare", "data": None})
    def _tx_symbol(code6: str) -> str:
        # stock_zh_a_hist_tx 需要类似 sh600519 / sz000001 的前缀
        return ("sh" if str(code6).startswith(("6", "9")) else "sz") + str(code6)

    df = None
    fetch_err = None
    fetch_errors: list[str] = []
    end_d = datetime.now().strftime("%Y%m%d")
    # 缩短回溯区间以降低 akshare 拉取耗时（但足够覆盖尾部 ~250 个交易日）
    start_d = (datetime.now() - timedelta(days=380)).strftime("%Y%m%d")
    # AKShare 的复权参数在不同版本/股票上容错差异较大：
    # 先尝试前复权/不复权/后复权，尽量拿到可用数据。
    adjust_values = ["qfq", "bfq", "hfq"]

    # 尽量做“多源兜底”：不同 akshare 版本 / 不同网络条件，函数可用性不同。
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
        # stock_zh_a_hist 在你的环境里可能会 Connection aborted，因此也作为备选
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
        # AKShare 失败：尝试新浪公开接口兜底
        sina = _fetch_daily_bars_sina(symbol)
        if sina:
            _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": sina}
            return jsonify({"code": 200, "msg": "success(sina)", "data": sina})

        msg = fetch_err or "no data"
        if fetch_errors:
            msg = msg + " | " + " ; ".join(fetch_errors[:3])
        sina_err = getattr(_fetch_daily_bars_sina, "last_err", None)
        if sina_err:
            msg = msg + f" | sina: {sina_err}"
        return jsonify({"code": 500, "msg": f"K线抓取失败：{msg}", "data": None})
    dc = _df_pick_col(df, "日期")
    oc = _df_pick_col(df, "开盘")
    cc = _df_pick_col(df, "收盘")
    hc = _df_pick_col(df, "最高")
    lc = _df_pick_col(df, "最低")
    vc = _df_pick_col(df, "成交量")
    # 有些环境下 akshare 返回的列名会出现编码乱码，
    # 导致字符串匹配不到（例如不再包含“日期/开盘/收盘”这些子串）。
    # stock_zh_a_hist 的列结构通常为：
    # [日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, ...]，
    # 因此这里做列序号回退兜底。
    if not dc or not oc or not cc or not hc or not lc or not vc:
        # 如果是 stock_zh_a_hist_tx，列名通常是英文：date/open/close/high/low/amount
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
            # 兜底：按常见顺序回退到“列序号”
            # stock_zh_a_hist 由于编码乱码列名匹配失败，列序通常仍是：
            # [日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, ...]
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
            return jsonify({"code": 200, "msg": "success(sina)", "data": sina})
        sina_err = getattr(_fetch_daily_bars_sina, "last_err", None)
        msg = "无法识别K线列"
        if sina_err:
            msg = msg + f" | sina: {sina_err}"
        return jsonify({"code": 500, "msg": msg, "data": None})
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
            return jsonify({"code": 200, "msg": "success(sina)", "data": sina})
        sina_err = getattr(_fetch_daily_bars_sina, "last_err", None)
        msg = "K线解析失败"
        if sina_err:
            msg = msg + f" | sina: {sina_err}"
        return jsonify({"code": 500, "msg": msg, "data": None})
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

    # 写入缓存：减少频繁拉取导致的网络错误 / 超时
    _STOCK_DAILY_BARS_CACHE[symbol] = {"ts": now_ts, "data": data_payload}

    return jsonify({"code": 200, "msg": "success", "data": data_payload})


@app.route("/api/market/a-overview", methods=["GET"])
def market_a_share_overview():
    """
    创新/扩展：A 股市场总貌（上交所 stock_sse_summary + 深交所 stock_szse_summary）。
    深交所需交易日 date，自动尝试今日与昨日。
    """
    try:
        import akshare as ak
    except ImportError:
        return jsonify({"code": 503, "msg": "未安装 akshare，请 pip install -r requirements.txt", "data": None})
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
    return jsonify({"code": 200, "msg": "success", "data": data})


@app.route("/api/topics/stock-insight", methods=["POST", "OPTIONS"])
def stock_insight():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "该标的")
    code = _parse_symbol(body.get("leader") or body.get("code") or "")
    pct_chg = float(body.get("pct_chg") or 0.0)
    direction = "偏强" if pct_chg >= 0 else "偏弱"
    lines = [
        f"{name}（{code or 'N/A'}）当日表现{direction}，当前涨跌幅 {pct_chg:+.2f}%。",
        "短线观察建议优先看量价配合与板块联动，不建议单一信号决策。",
        "若你补充持仓成本、风险偏好和计划周期，可生成更细化场景建议。",
    ]
    return jsonify({"code": 200, "msg": "success", "data": {"lines": lines, "source": "template"}})


PERCENTILE_DEFINITION_CN = (
    "近约250个交易日（约一年）窗口：取区间最低价与最高价，用最新收盘价在区间上的相对位置（百分比）；"
    "非市盈率或估值分位。"
)


def _headlines_for_symbol(symbol: str, name: str, global_news: list, hot_rows: list) -> list[dict]:
    """从全市场快讯里筛出标题/摘要疑似与本股相关的条目，供 LLM 做事件层输入；匹配失败不代表市场上真无新闻。"""
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


def _insight_response_meta(symbol_hit_count: int) -> dict:
    return {
        "percentileDefinition": PERCENTILE_DEFINITION_CN,
        "symbolHeadlineCount": symbol_hit_count,
    }


@app.route("/api/research/stock-llm-insight", methods=["POST", "OPTIONS"])
def stock_llm_insight():
    """
    基于 LLM 生成：AI 智能研判（3-5条）+ 未持仓操作建议（3条）。
    输入：{ symbol }，symbol 为沪深京 6 位代码（如 600519）
    """
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True) or {}
    raw_symbol = str(body.get("symbol") or body.get("leader") or body.get("code") or "").strip()
    symbol = _parse_symbol(raw_symbol)
    if not _is_a_share_6digit(symbol):
        return jsonify({"code": 400, "msg": "仅支持沪深京 A 股 6 位代码", "data": None})

    # 1) 行情（实时/近实时）
    try:
        quote = _fetch_a_share_quote(symbol) or {}
    except Exception as e:
        quote = {}

    # 2) 历史（K 线）：优先与 /api/stock/daily-bars 共用内存缓存，保证分位/一年高低与 K 线图一致
    daily = None
    now_bar_ts = time.time()
    cached_bar = _STOCK_DAILY_BARS_CACHE.get(symbol)
    if cached_bar and (now_bar_ts - cached_bar.get("ts", 0)) < _STOCK_DAILY_BARS_TTL_SEC:
        daily = cached_bar.get("data")
    if not daily or not isinstance(daily, dict) or not daily.get("dates") or not daily.get("candle"):
        try:
            daily = _fetch_daily_bars_sina(symbol)
        except Exception:
            daily = None

    # 3) 新闻趋势（用热点与快讯做近似输入）
    hot = []
    try:
        rows = _fetch_hot_node("sh_a", 30) + _fetch_hot_node("sz_a", 30)
        # 去重并按涨幅降序
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

    # 如果新浪快讯获取失败也没关系，LLM 仍可基于行情+历史输出（多取几条以提高个股命中）
    global_news = []
    try:
        items = _fetch_news_live(page=1, num=22) or []
        global_news = items[:18]
    except Exception:
        global_news = []

    if not daily or not isinstance(daily, dict) or not daily.get("dates") or not daily.get("candle"):
        return jsonify({"code": 500, "msg": "无法获取历史K线数据（已尝试新浪兜底）", "data": None})

    name = str(quote.get("name") or symbol or "").strip() or symbol
    pct_chg = float(quote.get("pct_chg") or 0.0)
    price = quote.get("price") or daily.get("last_close") or 0.0

    closes = daily.get("closes") or []
    # 计算简单趋势特征：近 10/20（如果长度足够）
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

    symbol_headlines = _headlines_for_symbol(symbol, name, global_news, hot)
    insight_meta = _insight_response_meta(len(symbol_headlines))

    # LLM 提示（要求输出 JSON）
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
        },
        "recent_headlines_for_symbol": symbol_headlines,
        "news_trend": {
            "hot_topics": hot,
            "global_news_tail": [
                {"title": x.get("title"), "summary": x.get("summary")} for x in global_news if isinstance(x, dict)
            ],
        },
        "task": {
            "aiInsightList": "生成 3-5条简短研判：把行情/趋势/历史分位/10/20日动量串起来；若 recent_headlines_for_symbol 非空可点到为止提事件，每条不超过60字",
            "suggestionList": "生成 3条未持仓操作建议：包含观察要点与风控口径，每条不超过60字；不构成投资建议",
            "quickQuestionList": "再生成 3个更聚焦该股票的追问问题（不构成投资建议）；每个问题不超过30字。每个问题必须与该股票的近一年分位/10/20日动量/52周回撤或关键支撑压力相关；并优先包含该股票简称(name)或至少包含“该股”。不要套用固定模板词（如“财报不及预期/同业对比/最大风险情景”）；若 recent_headlines_for_symbol 中不包含“财报/业绩/公告/年报/一季报/利润”等关键词，则禁止出现财报类措辞。禁止出现连续6位数字。"
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
        "禁止 Markdown、禁止代码围栏、禁止输出 JSON 以外的任何字符。"
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": json.dumps(user_msg, ensure_ascii=False)},
    ]

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
        }
        return jsonify({"code": 200, "msg": "success(llm)", "data": payload_out})
    except Exception as e:
        # LLM 不可用时退回模板：仍返回 code=200，便于前端展示；具体原因放在 msg 便于排查
        lines = [
            f"{name} 当前涨跌幅 {pct_chg:+.2f}%，结合历史分位与近10/20日动量，短期以结构性波动为主。",
            f"当前处于近一年收盘价区间相对分位 {percentile:.2f}%（非估值分位），上行需看趋势延续，下行需关注回撤承接。",
            "新闻面以热点/快讯为参考；未在给定快讯列表中检索到该股相关标题时，不宜断言「无热点」。"
        ]
        suggestions = [
            "未持仓：等待关键位附近的放量/承接确认，再分批参与。",
            "设置明确的止损/止盈规则，避免单次波动影响整体计划。",
            "若走势与量能背离，提高观望权重并减少追涨。"
        ]
        quick_list = [
            "结合当前分位与10/20日动量，下一步走势更偏哪边？",
            "52周回撤下，最该盯的支撑/压力信号是什么？",
            "若继续偏弱，未持仓者如何控风险与等信号？"
        ]
        err_hint = str(e).replace("\n", " ").strip()
        if len(err_hint) > 180:
            err_hint = err_hint[:180] + "…"
        return jsonify(
            {
                "code": 200,
                "msg": f"success(template_llm_err: {err_hint})",
                "data": {
                    "aiInsightList": lines[:5],
                    "suggestionList": suggestions[:3],
                    "quickQuestionList": quick_list,
                    "meta": insight_meta,
                },
            }
        )


@app.route("/api/research/analyze", methods=["POST", "OPTIONS"])
def research_analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    symbol = _parse_symbol(body.get("symbol") or body.get("leader") or "")
    q = str(body.get("question") or "").strip()
    stock = {}
    try:
        if _is_a_share_6digit(symbol):
            live = _fetch_a_share_quote(symbol)
        else:
            live = _fetch_stock_live(symbol)
        if isinstance(live, dict):
            stock = live
    except Exception:
        stock = {}

    # 若 LLM 配置存在：用你的模型基于行情/历史/新闻回答；否则回退模板
    llm_env = _get_llm_env()
    llm_ready = bool(llm_env.get("api_base") and llm_env.get("model") and llm_env.get("api_key"))
    if llm_ready and _is_a_share_6digit(symbol):
        try:
            daily = _fetch_daily_bars_sina(symbol)  # 尽量用新浪兜底，减少依赖 akshare
            if not daily:
                daily = {}
            # 热点/快讯：给模型参考情绪与主题
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
                items = _fetch_news_live(page=1, num=6) or []
                global_news = items[:4]
            except Exception:
                global_news = []

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
                "question": q,
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
                "output_requirements": {
                    "must_include": ["行情简述", "趋势/历史含义", "与新闻主题的关联", "风控口径（非投资建议）"],
                    "max_chars": 380,
                },
            }

            system_msg = (
                "你是金融研究助理。根据输入的行情/历史/新闻趋势回答用户问题。"
                "必须只输出合法 JSON 对象，包含 key: summary（字符串）。禁止 Markdown。"
            )
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(user_msg, ensure_ascii=False)},
            ]
            content = _openai_compat_chat(messages, max_tokens=380, temperature=0.35)
            obj = _extract_json_object(content) or {}
            summary = str(obj.get("summary") or "").strip()
            if summary:
                return jsonify({"code": 200, "msg": "success(llm)", "data": {"summary": summary, "session_id": uuid.uuid4().hex}})
        except Exception:
            pass

    # 回退模板（LLM 不可用/配置缺失/解析失败）
    summary = (
        f"基于当前样本，{stock.get('name', symbol or '该标的')}短期以结构性波动为主。"
        "建议优先关注回撤承接与板块强度变化，控制追涨节奏。"
    )
    if q:
        summary += f" 你的问题是“{q}”，建议结合仓位与周期再细化执行策略。"
    return jsonify({"code": 200, "msg": "success", "data": {"summary": summary, "session_id": uuid.uuid4().hex}})


@app.route("/api/upload", methods=["POST", "OPTIONS"])
def upload():
    if request.method == "OPTIONS":
        return ("", 204)
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required"}), 400
    name = str(file.filename or "").strip()
    if not name.lower().endswith(".pdf"):
        return jsonify({"error": "Only .pdf is supported"}), 400
    session_id = uuid.uuid4().hex
    out_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    file.save(out_path)
    size = os.path.getsize(out_path)
    with _LOCK:
        _SESSIONS[session_id] = {"pdf_path": out_path, "name": name, "size": int(size)}
    return jsonify({"sessionId": session_id, "fileInfo": {"name": name, "size": int(size)}})


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


@app.route("/api/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("sessionId") or "").strip()
    with _LOCK:
        if session_id not in _SESSIONS:
            return jsonify({"error": "session not found"}), 404
    task_id = uuid.uuid4().hex
    with _LOCK:
        _TASKS[task_id] = {"status": "queued", "stage": "排队中", "error": "", "result": None}
    _POOL.submit(_run_task, task_id, session_id)
    return jsonify({"taskId": task_id, "engine": "finance-local", "module": "fin_report_mock"})


@app.route("/api/tasks/<task_id>", methods=["GET", "OPTIONS"])
def task(task_id: str):
    if request.method == "OPTIONS":
        return ("", 204)
    with _LOCK:
        t = _TASKS.get(task_id)
    if not t:
        return jsonify({"error": "task not found"}), 404
    return jsonify(t)


def _warm_a_share_search_cache():
    """后台预热全市场名称列表，避免首个搜索请求长时间无响应。"""
    time.sleep(1.5)
    try:
        _get_a_share_search_index()
    except Exception:
        pass


threading.Thread(target=_warm_a_share_search_cache, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
