from __future__ import annotations

import os
import threading
import time
import traceback

# 本地开发：backend/.env 中可配置 LLM_API_BASE / LLM_MODEL / LLM_API_KEY
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from flask import Flask, jsonify, request

# 导入服务模块
from services.news_service import (
    fetch_baidu_finance_news,
    fetch_akshare_stock_news,
    fetch_akshare_caixin_news,
    get_news_summary,
    normalize_news_region_param,
    _fetch_sina_global_flash,
    _fetch_news_live
)
from services.stock_service import (
    _fetch_a_share_quote,
    _get_stock_daily_bars,
    _get_a_share_search_index,
    _fetch_market_a_share_overview,
    fetch_a_share_hot_topics_sina_merged,
)
from services.market_service import (
    get_stock_llm_insight,
    research_analyze as research_analyze_service,
    ai_analyze_news,
    generate_home_news_enhanced,
    start_warmup_thread,
)
from services.report_service import upload_file, create_task, get_task, regen_page
from utils.helpers import (
    _now_str,
    _parse_symbol,
    _is_a_share_6digit,
    _cn_a_share_use_last_close_hot_snapshot,
)
from utils.hot_close_snapshot import (
    load_hot_close_snapshot,
    save_hot_close_snapshot,
    snapshot_has_meaningful_pct,
)

app = Flask(__name__)
app.json.ensure_ascii = False


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = str(os.environ.get(name, str(default)) or str(default)).strip()
    try:
        v = int(raw)
    except Exception:
        v = int(default)
    return max(lo, min(hi, v))


# 与 demo2 一致：内存缓存 + 后台定时刷新（仅 A 股 sh_a + sz_a 合并榜）
_TOPICS_HOT_REFRESH_SEC = float(os.environ.get("TOPICS_HOT_REFRESH_SEC", "300"))
_HOME_NEWS_LIMIT = _env_int("HOME_NEWS_LIMIT", 10, 1, 20)
_HOT_MEM_LOCK = threading.Lock()
_HOT_MEM: dict[str, tuple[float, object]] = {}
_TOPICS_SCHED_STARTED = False


def _hot_mem_get(key: str, ttl_s: float):
    with _HOT_MEM_LOCK:
        hit = _HOT_MEM.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - float(ts) <= float(ttl_s):
        return val
    return None


def _hot_mem_set(key: str, val) -> None:
    with _HOT_MEM_LOCK:
        _HOT_MEM[key] = (time.time(), val)


def _hot_mem_peek(key: str):
    with _HOT_MEM_LOCK:
        hit = _HOT_MEM.get(key)
    return None if not hit else hit[1]


def _topics_hot_refresh_once() -> bool:
    """刷新 A 股涨幅榜：仅新浪 sh_a+sz_a（demo2）。"""
    try:
        items = fetch_a_share_hot_topics_sina_merged(45, 45)
        board_source = "sina_merged"
        if not items:
            base_items, _ = _get_a_share_search_index()
            items = [
                {"name": it.get("name"), "leader": it.get("code"), "pct_chg": 0.0}
                for it in (base_items or [])[:120]
            ]
            board_source = "code_list"
        payload = {
            "code": 200,
            "msg": "success",
            "data": {
                "items": items,
                "update_time": _now_str(),
                "quote_mode": "live",
                "board_source": board_source,
            },
        }
        _hot_mem_set("topics_hot", payload)
        _hot_mem_set("topics_hot_last_ok", payload)
        if not _cn_a_share_use_last_close_hot_snapshot() and snapshot_has_meaningful_pct(items):
            save_hot_close_snapshot(items[:80])
        return True
    except Exception as e:
        _hot_mem_set(
            "topics_hot_error",
            {"ts": time.time(), "msg": str(e), "trace": traceback.format_exc()[:1200]},
        )
        return False


def _start_topics_hot_scheduler() -> None:
    global _TOPICS_SCHED_STARTED
    if _TOPICS_SCHED_STARTED:
        return
    _TOPICS_SCHED_STARTED = True

    def _loop():
        _topics_hot_refresh_once()
        while True:
            time.sleep(_TOPICS_HOT_REFRESH_SEC)
            _topics_hot_refresh_once()

    threading.Thread(target=_loop, daemon=True).start()


def _build_hot_topics_payload(limit: int) -> dict:
    cached = _hot_mem_get("topics_hot", _TOPICS_HOT_REFRESH_SEC)
    last_ok = _hot_mem_get("topics_hot_last_ok", 6 * 60 * 60)
    src = None
    if cached and cached.get("code") == 200:
        src = cached
    elif last_ok and last_ok.get("code") == 200:
        src = last_ok
    else:
        return {
            "code": 202,
            "msg": "热门榜数据准备中（首次加载可能稍慢）",
            "data": {
                "items": [],
                "update_time": _now_str(),
                "quote_mode": "live",
                "board_source": "pending",
            },
        }
    items = list((src.get("data") or {}).get("items") or [])
    if limit > len(items):
        _topics_hot_refresh_once()
        cached2 = _hot_mem_get("topics_hot", _TOPICS_HOT_REFRESH_SEC)
        if cached2 and cached2.get("code") == 200:
            items = list((cached2.get("data") or {}).get("items") or items)
        else:
            last2 = _hot_mem_get("topics_hot_last_ok", 6 * 60 * 60)
            if last2 and last2.get("code") == 200:
                items = list((last2.get("data") or {}).get("items") or items)
    d = dict(src.get("data") or {})
    d["items"] = items[:limit]
    return {"code": 200, "msg": str(src.get("msg") or "success"), "data": d}


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
    # 非连续竞价时段：返回磁盘快照（与此前逻辑一致）
    if _cn_a_share_use_last_close_hot_snapshot():
        snap = load_hot_close_snapshot()
        snap_items = snap.get("items") if isinstance(snap, dict) else None
        if isinstance(snap_items, list) and snap_items:
            return jsonify(
                {
                    "code": 200,
                    "msg": "success(close-snapshot)",
                    "data": {
                        "items": snap_items[:limit],
                        "update_time": str(snap.get("saved_at") or _now_str()),
                        "quote_mode": "last_close",
                        "board_source": "last_close",
                    },
                }
            )

    _start_topics_hot_scheduler()
    if _hot_mem_peek("topics_hot") is None and _hot_mem_peek("topics_hot_last_ok") is None:
        _topics_hot_refresh_once()

    payload = _build_hot_topics_payload(limit)
    if payload.get("code") == 200:
        return jsonify(payload)

    # 仍无缓存时：同步拉一次新浪合并榜；再不行仅用 A 股代码列表兜底
    try:
        rows = fetch_a_share_hot_topics_sina_merged(45, 45) or []
        board_src = "sina_merged_sync" if rows else "code_list"
        if not rows:
            base_items, _ = _get_a_share_search_index()
            rows = [
                {"name": it.get("name"), "leader": it.get("code"), "pct_chg": 0.0}
                for it in (base_items or [])[:limit]
            ]
        return jsonify(
            {
                "code": 200,
                "msg": "success(sync-fallback)",
                "data": {
                    "items": rows[:limit],
                    "update_time": _now_str(),
                    "quote_mode": "live",
                    "board_source": board_src,
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取热点失败：{e}", "data": None})


@app.route("/api/news/home", methods=["GET"])
def news_home():
    try:
        page = int(request.args.get("page", "1") or "1")
        num_raw = str(request.args.get("num", "") or "").strip()
        num = int(num_raw) if num_raw else _HOME_NEWS_LIMIT
    except Exception:
        return jsonify({"code": 400, "msg": "参数错误：page/num", "data": None})
    page = max(1, page)
    num = max(1, min(20, num))
    try:
        # 优先：新浪财经全球财经快讯
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
    out = []
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


@app.route("/api/stock/daily-bars", methods=["GET"])
def stock_daily_bars():
    raw_in = str(request.args.get("symbol", "") or "").strip()
    symbol = _parse_symbol(raw_in)
    if not _is_a_share_6digit(symbol):
        return jsonify({"code": 400, "msg": "仅支持沪深京 A 股 6 位代码", "data": None})

    try:
        data = _get_stock_daily_bars(symbol)
        if not data:
            return jsonify({"code": 500, "msg": "K线抓取失败", "data": None})
        return jsonify({"code": 200, "msg": "success", "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"K线抓取失败：{e}", "data": None})


@app.route("/api/market/a-overview", methods=["GET"])
def market_a_share_overview():
    try:
        data = _fetch_market_a_share_overview()
        if not data:
            return jsonify({"code": 503, "msg": "未安装 akshare，请 pip install -r requirements.txt", "data": None})
        return jsonify({"code": 200, "msg": "success", "data": data})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e), "data": None})


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


@app.route("/api/research/stock-llm-insight", methods=["POST", "OPTIONS"])
def stock_llm_insight():
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True) or {}
    raw_symbol = str(body.get("symbol") or body.get("leader") or body.get("code") or "").strip()
    symbol = _parse_symbol(raw_symbol)
    if not _is_a_share_6digit(symbol):
        return jsonify({"code": 400, "msg": "仅支持沪深京 A 股 6 位代码", "data": None})

    try:
        payload = get_stock_llm_insight(symbol)
        if not payload:
            return jsonify({"code": 500, "msg": "无法获取历史K线数据（已尝试新浪兜底）", "data": None})
        return jsonify({"code": 200, "msg": "success(llm)", "data": payload})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e), "data": None})


@app.route("/api/research/analyze", methods=["POST", "OPTIONS"])
def research_analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    symbol = _parse_symbol(body.get("symbol") or body.get("leader") or "")
    q = str(body.get("question") or "").strip()
    chat_history = body.get("chatHistory")
    try:
        result = research_analyze_service(symbol, q, chat_history)
        return jsonify({"code": 200, "msg": "success(llm)", "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e), "data": None})


@app.route("/api/upload", methods=["POST", "OPTIONS"])
def upload():
    if request.method == "OPTIONS":
        return ("", 204)
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required"}), 400
    result = upload_file(file)
    if not result:
        return jsonify({"error": "Only .pdf is supported"}), 400
    return jsonify(result)


@app.route("/api/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("sessionId") or "").strip()
    result = create_task(session_id)
    if not result:
        return jsonify({"error": "session not found"}), 404
    return jsonify(result)


@app.route("/api/tasks/<task_id>", methods=["GET", "OPTIONS"])
def task(task_id: str):
    if request.method == "OPTIONS":
        return ("", 204)
    t = get_task(task_id)
    if not t:
        return jsonify({"error": "task not found"}), 404
    return jsonify(t)


@app.route("/api/regen", methods=["POST", "OPTIONS"])
def regen():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    session_id = str(body.get("sessionId") or "").strip()
    page_index = body.get("pageIndex")
    custom_q = str(body.get("customQuestion") or "").strip()
    choice = str(body.get("choice") or "").strip()
    if not session_id or page_index is None:
        return jsonify({"error": "sessionId and pageIndex are required"}), 400
    try:
        idx = int(page_index)
    except Exception:
        return jsonify({"error": "pageIndex must be int"}), 400
    try:
        out = regen_page(session_id, idx, custom_question=custom_q, choice=choice)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/news/baidu", methods=["GET"])
def news_baidu():
    try:
        limit = int(request.args.get("limit", "20") or "20")
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))
    try:
        items = fetch_baidu_finance_news(limit=limit)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "update_time": _now_str(),
                "source": "baidu-finance-rss",
                "items": items,
            },
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取百度财经新闻失败：{e}", "data": None})


@app.route("/api/news/caixin", methods=["GET"])
def news_caixin():
    try:
        limit = int(request.args.get("limit", "20") or "20")
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))
    try:
        items = fetch_akshare_caixin_news(limit=limit)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "update_time": _now_str(),
                "source": "akshare-stock_news_main_cx",
                "items": items,
            },
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取财新网新闻失败：{e}", "data": None})


@app.route("/api/news/stock", methods=["GET"])
def news_stock():
    symbol = str(request.args.get("symbol", "") or "").strip()
    if not symbol:
        return jsonify({"code": 400, "msg": "缺少symbol参数", "data": None})
    try:
        limit = int(request.args.get("limit", "10") or "10")
    except Exception:
        limit = 10
    limit = max(1, min(30, limit))
    try:
        items = fetch_akshare_stock_news(symbol=symbol, limit=limit)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "update_time": _now_str(),
                "source": "akshare-stock_news_em",
                "symbol": symbol,
                "items": items,
            },
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取个股新闻失败：{e}", "data": None})


@app.route("/api/news/aggregate", methods=["GET"])
def news_aggregate():
    try:
        limit = int(request.args.get("limit", "30") or "30")
    except Exception:
        limit = 30
    limit = max(1, min(50, limit))
    category = str(request.args.get("category", "") or "").strip()
    region = normalize_news_region_param(request.args.get("region"))
    try:
        result = get_news_summary(category=category if category else None, limit=limit, region=region)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": result,
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取聚合新闻失败：{e}", "data": None})


@app.route("/api/news/ai-analyze", methods=["POST", "OPTIONS"])
def news_ai_analyze():
    """
    对单条新闻做AI深度分析，返回完整的话题详情
    包含：AI摘要、相关股票、关注度、驱动事件、投资逻辑、因果链、反向风险、时间轴
    """
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    title = str(body.get("title") or "").strip()
    summary = str(body.get("summary") or "").strip()
    url = str(body.get("url") or "").strip()
    source = str(body.get("source") or "").strip()
    publish_time = body.get("publishTime") or body.get("metaTime") or body.get("publishedAt") or ""
    publish_ts = body.get("ctime") or body.get("publishedTs")

    if not title:
        return jsonify({"code": 400, "msg": "缺少title参数", "data": None})

    try:
        result = ai_analyze_news(title, summary, url, source, publish_time, publish_ts)
        if not result:
            return jsonify({"code": 500, "msg": "AI分析失败", "data": None})
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": result,
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"新闻AI分析失败：{e}", "data": None})


@app.route("/api/news/home-enhanced", methods=["GET"])
def news_home_enhanced():
    """
    增强版首页新闻：从3源聚合真实新闻 + AI生成摘要/相关股票/关注度
    返回格式与前端 HOME_NEWS_SEED 一致
    """
    try:
        limit_raw = str(request.args.get("limit", "") or "").strip()
        limit = int(limit_raw) if limit_raw else _HOME_NEWS_LIMIT
    except Exception:
        limit = _HOME_NEWS_LIMIT
    limit = max(1, min(20, limit))
    region = normalize_news_region_param(request.args.get("region"))
    try:
        items = generate_home_news_enhanced(limit=limit, region=region)
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "update_time": _now_str(),
                "items": items,
                "source_count": len(items),
                "region": region,
            },
        })
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取增强首页新闻失败：{e}", "data": None})


if __name__ == "__main__":
    # 启动预热线程
    start_warmup_thread()
    
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
