from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
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
    return {
        "symbol": symbol,
        "name": name or symbol,
        "price": round(price, 2),
        "chg": round(chg, 2),
        "pct_chg": pct,
        "open": round(open_p, 2),
        "prev_close": round(prev_close, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "update_time": update_time,
    }


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


@app.route("/api/stock", methods=["GET"])
def stock():
    symbol = _parse_symbol(request.args.get("symbol", ""))
    try:
        item = _fetch_stock_live(symbol)
        if not item:
            return jsonify({"code": 404, "msg": "未找到该股票/代码不支持", "data": None})
        return jsonify({"code": 200, "msg": "success", "data": {**item, "input_symbol": symbol}})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询失败：{e}", "data": None})


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


@app.route("/api/research/analyze", methods=["POST", "OPTIONS"])
def research_analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    symbol = _parse_symbol(body.get("symbol") or body.get("leader") or "")
    q = str(body.get("question") or "").strip()
    stock = {}
    try:
        live = _fetch_stock_live(symbol)
        if isinstance(live, dict):
            stock = live
    except Exception:
        stock = {}
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
