from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False


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


STOCKS = {
    "300750": {
        "symbol": "sz300750",
        "name": "宁德时代",
        "price": 156.82,
        "open": 154.10,
        "prev_close": 153.28,
        "high": 157.50,
        "low": 152.60,
        "pct_chg": 2.31,
        "chg": 3.54,
    },
    "600519": {
        "symbol": "sh600519",
        "name": "贵州茅台",
        "price": 1720.00,
        "open": 1699.00,
        "prev_close": 1695.42,
        "high": 1728.00,
        "low": 1695.00,
        "pct_chg": 1.45,
        "chg": 24.58,
    },
    "002594": {
        "symbol": "sz002594",
        "name": "比亚迪",
        "price": 238.50,
        "open": 241.20,
        "prev_close": 240.24,
        "high": 242.30,
        "low": 237.10,
        "pct_chg": -0.72,
        "chg": -1.74,
    },
}

HOT_ITEMS = [
    {"name": "动力电池", "leader": "300750", "pct_chg": 9.8},
    {"name": "汽车零部件", "leader": "002594", "pct_chg": 8.91},
    {"name": "白酒龙头", "leader": "600519", "pct_chg": 6.42},
    {"name": "AI算力", "leader": "300308", "pct_chg": 5.88},
    {"name": "机器人", "leader": "300024", "pct_chg": 5.41},
    {"name": "半导体", "leader": "688981", "pct_chg": 4.99},
    {"name": "储能", "leader": "300274", "pct_chg": 4.72},
    {"name": "消费电子", "leader": "300136", "pct_chg": 4.37},
    {"name": "高端制造", "leader": "600031", "pct_chg": 4.06},
    {"name": "中特估", "leader": "601668", "pct_chg": 3.84},
]

NEWS_ITEMS = [
    {
        "id": "n1",
        "title": "新能源产业链景气延续，机构关注盈利修复",
        "summary": "关注上游原材料波动与下游需求弹性。",
        "source": "市场快讯",
        "category": "市场快讯",
        "ctime": 0,
        "picUrl": "",
        "url": "",
        "importance": 62,
        "score": 0.82,
    },
    {
        "id": "n2",
        "title": "白酒板块出现修复，龙头成交额提升",
        "summary": "旺季预期与估值修复共同驱动。",
        "source": "财联观察",
        "category": "财联观察",
        "ctime": 0,
        "picUrl": "",
        "url": "",
        "importance": 58,
        "score": 0.76,
    },
    {
        "id": "n3",
        "title": "政策端再提科技创新，硬科技方向活跃",
        "summary": "聚焦业绩与订单兑现，避免纯概念。",
        "source": "投研日报",
        "category": "投研日报",
        "ctime": 0,
        "picUrl": "",
        "url": "",
        "importance": 64,
        "score": 0.78,
    },
]

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
    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {"items": HOT_ITEMS[:limit], "update_time": _now_str()},
        }
    )


@app.route("/api/news/home", methods=["GET"])
def news_home():
    try:
        page = int(request.args.get("page", "1") or "1")
        num = int(request.args.get("num", "20") or "20")
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：page/num", "data": None})
    page = max(1, page)
    num = max(1, min(20, num))
    featured = NEWS_ITEMS[:3]
    items = (NEWS_ITEMS * 8)[:num]
    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {
                "page": page,
                "num": num,
                "update_time": _now_str(),
                "source": "finance-local",
                "featured": featured,
                "items": items,
            },
        }
    )


@app.route("/api/stock", methods=["GET"])
def stock():
    symbol = _parse_symbol(request.args.get("symbol", ""))
    item = STOCKS.get(symbol)
    if not item:
        return jsonify({"code": 404, "msg": "未找到该股票/代码不支持", "data": None})
    return jsonify({"code": 200, "msg": "success", "data": {**item, "input_symbol": symbol, "update_time": _now_str()}})


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
    stock = STOCKS.get(symbol, {})
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
