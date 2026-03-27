"""
智能投研（Research）服务（重构版）

目标：
1) 尽量不空结果：无论用户输入什么“相关内容”，都返回可读分析；
2) 数据多源：优先本地行情/热点，其次联网抓取公开资料（新闻 RSS / 搜索摘要）；
3) 三层兜底：LLM 失败 -> 模板分析；联网失败 -> 仅本地模板；全部失败 -> 最终应急模板。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable
from urllib.parse import quote_plus
from xml.etree import ElementTree

from modules.news.llm import env_get, llm_chat, parse_llm_json_obj
from modules.stooq_csv import parse_stooq_ohlcv_csv


def _clip(s: str, n: int) -> str:
    t = str(s or "").strip()
    return t[:n] if len(t) > n else t


def _polish_text(s: str) -> str:
    t = str(s or "")
    # 弱化“系统提示口吻”，避免回答显得生硬
    replacements = {
        "待验证": "可继续跟踪确认",
        "证据不足": "当前线索仍在变化",
        "无数据": "公开信息有限",
        "未抓取到": "暂未形成更多公开线索",
        "模板": "分析",
    }
    for old, new in replacements.items():
        t = t.replace(old, new)
    return t.strip()


def _bullet_item_to_text(x: Any) -> str:
    """
    将大模型可能返回的 bullets/items/risk 元素统一成“可读文本”。
    避免把对象（如 {name, change}）直接 str() 后原样展示成 JSON 字面量。
    """
    if x is None:
        return ""
    if isinstance(x, str):
        return _polish_text(x)
    if isinstance(x, dict):
        name = x.get("name") or x.get("title") or x.get("symbol") or ""
        # 常见字段组合：{name, change} / {name, pct_chg} / {title, summary}
        change = x.get("change")
        if change is None:
            change = x.get("pct_chg") or x.get("pct") or x.get("percent")
        if name and change is not None and str(change).strip():
            return _polish_text(f"{name}：{change}")
        title = x.get("title")
        summary = x.get("summary") or x.get("snippet")
        if title and summary:
            return _polish_text(f"{title}：{summary}")
        return _polish_text(json.dumps(x, ensure_ascii=False))
    return _polish_text(str(x))


def _enhance_risk_lines(
    question: str,
    keyword: str,
    category: str,
    stock: dict | None,
    risk_lines: list[str] | None,
) -> list[str]:
    """
    风险提示增强：让风险内容与当前问题更贴合，而不是泛化表达。
    """
    lines = [_bullet_item_to_text(x) for x in (risk_lines or []) if _bullet_item_to_text(x)]
    text = f"{question} {keyword} {category}".lower()

    def _add(line: str):
        if line and line not in lines:
            lines.append(line)

    # 基金类问题
    if any(k in text for k in ["基金", "etf", "联接", "lof"]):
        _add("基金净值与场内价格可能存在时滞或折溢价差异，短线判断需同时观察成交与申赎数据。")
        _add("若遇非交易时段或海外市场波动，基金展示收益与最终确认净值可能存在偏差。")

    # 贵金属与大宗
    if any(k in text for k in ["白银", "silver", "xag", "黄金", "gold", "xau", "原油", "oil", "wti", "brent"]):
        _add("大宗商品受美元、利率预期与地缘事件影响明显，日内波动放大时需控制仓位。")
        _add("若标的是相关基金/ETF，还需关注跟踪误差与换月结构对净值表现的影响。")

    # 个股/板块
    if any(k in text for k in ["个股", "股票", "板块", "题材"]) or stock:
        _add("题材交易阶段若成交额无法持续放大，强势方向可能快速切换。")
        _add("公告、业绩预告与监管信息可能改变短期交易逻辑，需及时复核。")

    # 宏观/利率
    if any(k in text for k in ["宏观", "加息", "降息", "cpi", "非农", "美联储"]):
        _add("宏观事件落地前后常出现预期差交易，需区分“预期兑现”与“超预期冲击”。")

    # 保底
    if not lines:
        lines = ["市场波动受多因素共同驱动，建议结合自身风险承受能力审慎判断。"]

    return lines[:4]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        s = str(v).strip().replace("%", "")
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _topics_llm_allow(state: dict, env_limit_name: str = "RESEARCH_LLM_DAILY_LIMIT", default_limit: int = 60) -> bool:
    day = time.strftime("%Y%m%d", time.localtime())
    if day != state.get("day"):
        state["day"] = day
        state["used"] = 0
    try:
        limit = int(float(env_get(env_limit_name, str(default_limit)) or default_limit))
    except Exception:
        limit = default_limit
    return state.get("used", 0) < max(0, limit)


def _topics_llm_mark_used(state: dict) -> None:
    state["used"] = int(state.get("used", 0)) + 1


def _llm_configured() -> bool:
    return bool(env_get("LLM_API_BASE") and env_get("LLM_API_KEY") and env_get("LLM_MODEL"))


_MEMO: dict[str, tuple[float, dict]] = {}
_MEMO_TTL = 120.0


def _memo_get(key: str) -> dict | None:
    hit = _MEMO.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > _MEMO_TTL:
        _MEMO.pop(key, None)
        return None
    return val


def _memo_set(key: str, val: dict) -> None:
    _MEMO[key] = (time.time(), val)


def _hash_key(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:32]


def _extract_query_candidates(question: str, keyword: str, category: str, stock_symbol: str) -> list[str]:
    cands: list[str] = []
    for t in [stock_symbol, keyword, question, category]:
        v = _clip(t, 80)
        if v and v not in cands:
            cands.append(v)

    # 从中文问题里抽取 2~8 字片段，作为备选搜索词
    for frag in re.findall(r"[\u4e00-\u9fff]{2,8}", f"{question} {keyword}"):
        if frag and frag not in cands:
            cands.append(frag)
        if len(cands) >= 8:
            break
    return cands[:8]


def _fetch_google_news_rss(session, q: str, limit: int = 20, timeout_s: int = 8) -> list[dict]:
    if not q:
        return []
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(q)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    try:
        r = session.get(url, timeout=timeout_s)
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        out: list[dict] = []
        for item in root.findall(".//item")[:limit]:
            title = _clip(item.findtext("title", default=""), 120)
            link = _clip(item.findtext("link", default=""), 220)
            pub = _clip(item.findtext("pubDate", default=""), 64)
            if not title:
                continue
            out.append({"title": title, "link": link, "pub_date": pub, "source": "google_news_rss"})
        return out
    except Exception:
        return []


def _fetch_duckduckgo_instant(session, q: str, timeout_s: int = 4) -> list[dict]:
    if not q:
        return []
    url = "https://api.duckduckgo.com/"
    try:
        r = session.get(
            url,
            params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=timeout_s,
        )
        r.raise_for_status()
        j = r.json()
        out: list[dict] = []
        abstract = _clip(j.get("AbstractText") or "", 240)
        abs_url = _clip(j.get("AbstractURL") or "", 220)
        if abstract:
            out.append({"title": f"{q} 概览", "snippet": abstract, "link": abs_url, "source": "duckduckgo"})

        related = j.get("RelatedTopics") or []
        for it in related[:4]:
            if isinstance(it, dict):
                text = _clip(it.get("Text") or "", 200)
                link = _clip(it.get("FirstURL") or "", 220)
                if text:
                    out.append({"title": f"{q} 相关", "snippet": text, "link": link, "source": "duckduckgo"})
        return out[:5]
    except Exception:
        return []


def _collect_external_context(session, q_candidates: list[str], budget_s: float = 14.0) -> dict:
    news_items: list[dict] = []
    search_items: list[dict] = []
    stooq_items: list[dict] = []
    t0 = time.time()
    # 多关键词拉取 RSS，去重后喂给 LLM；条数受 budget_s 与各请求超时约束
    for q in q_candidates[:5]:
        if time.time() - t0 > budget_s:
            break
        news_items.extend(_fetch_google_news_rss(session, q, limit=20, timeout_s=8))
        if time.time() - t0 > budget_s:
            break
        search_items.extend(_fetch_duckduckgo_instant(session, q, timeout_s=4))

    # 可访问时用 Stooq 兜底提供“实时数字锚点”
    if time.time() - t0 <= budget_s:
        stooq_items = _fetch_stooq_context(session, q_candidates, timeout_s=3)

    # 去重
    dedup_news: list[dict] = []
    seen_n = set()
    for n in news_items:
        k = (n.get("title") or "", n.get("link") or "")
        if k in seen_n:
            continue
        seen_n.add(k)
        dedup_news.append(n)

    dedup_search: list[dict] = []
    seen_s = set()
    for s in search_items:
        k = (s.get("title") or "", s.get("snippet") or "")
        if k in seen_s:
            continue
        seen_s.add(k)
        dedup_search.append(s)

    return {"news": dedup_news[:10], "search": dedup_search[:8], "stooq": stooq_items[:6]}


def _fetch_stooq_quote(session, symbol: str, timeout_s: int = 3) -> dict | None:
    try:
        url = "https://stooq.com/q/l/"
        params = {"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        r = session.get(url, params=params, timeout=timeout_s)
        r.raise_for_status()
        row = parse_stooq_ohlcv_csv(r.text)
        if not row:
            return None
        c = row.get("close")
        return {
            "symbol": row.get("symbol") or symbol.upper(),
            "date": row.get("date") or "",
            "time": row.get("time") or "",
            "open": "" if row.get("open") is None else str(row["open"]),
            "high": "" if row.get("high") is None else str(row["high"]),
            "low": "" if row.get("low") is None else str(row["low"]),
            "close": str(c),
            "volume": "",
            "source": "stooq",
        }
    except Exception:
        return None


def _fetch_stooq_context(session, q_candidates: list[str], timeout_s: int = 3) -> list[dict]:
    text = " ".join(q_candidates).lower()
    symbols: list[str] = []
    # 按主题自动选符号
    if any(k in text for k in ["白银", "silver", "xag"]):
        symbols.append("xagusd")
    if any(k in text for k in ["黄金", "gold", "xau"]):
        symbols.append("xauusd")
    if any(k in text for k in ["原油", "oil", "wti", "brent"]):
        symbols.append("cl.f")
    # 默认加常用大宗，保证“任何输入”至少有可用数字
    for s in ("xauusd", "xagusd", "cl.f"):
        if s not in symbols:
            symbols.append(s)

    out: list[dict] = []
    for sym in symbols[:3]:
        q = _fetch_stooq_quote(session, sym, timeout_s=timeout_s)
        if q:
            out.append(q)
    return out


def _seed_external_context(question: str, keyword: str, category: str, hot: list[dict], external_ctx: dict) -> dict:
    """
    兜底补全：当联网资料抓取失败时，仍构造“可引用的主题上下文”，避免前端出现“没有任何资料”体验。
    """
    news = list(external_ctx.get("news") or [])
    search = list(external_ctx.get("search") or [])
    stooq = list(external_ctx.get("stooq") or [])
    if news or search or stooq:
        return {"news": news, "search": search, "stooq": stooq}

    topic = _clip(keyword or question or category or "当前市场", 36)
    hot_names = [str(x.get("name") or "") for x in (hot or [])[:4] if x.get("name")]
    hot_desc = "、".join(hot_names) if hot_names else "热点样本不足"

    seeded = {
        "news": [
            {
                "title": f"{topic} 今日跟踪（系统补全上下文）",
                "link": "",
                "pub_date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "source": "seeded_context",
            }
        ],
        "search": [
            {
                "title": f"{topic} 主题线索",
                "snippet": f"当前可用盘面样本：{hot_desc}。建议结合当日新闻流与公告验证主题强弱持续性。",
                "link": "",
                "source": "seeded_context",
            }
        ],
        "stooq": stooq,
    }
    return seeded


def _template_research(
    question: str,
    keyword: str,
    category: str,
    stock: dict | None,
    hot: list[dict],
    external_ctx: dict,
) -> dict:
    title = "智能投研 · 多源分析"
    if stock and stock.get("name"):
        title = f"{stock.get('name')} · 多源投研研判"

    bullets: list[str] = []
    risks: list[str] = []

    if stock:
        stock_name = str(stock.get("name") or "标的")
        pct = _safe_float(stock.get("pct_chg"))
        chg = _safe_float(stock.get("chg"))
        price = stock.get("price")
        bullets.append(
            f"行情锚点：{stock_name} 最新价 {price if price is not None else '—'}，较昨收 {chg:+.2f}，涨跌幅 {pct:+.2f}%（{stock.get('update_time') or '时间未知'}）。"
        )
        bullets.append(
            f"日内区间：开盘 {stock.get('open', '—')}，最高 {stock.get('high', '—')}，最低 {stock.get('low', '—')}；建议结合量能确认趋势有效性。"
        )
    else:
        bullets.append("本次按主题视角分析，结合盘面与外部公开信息提炼市场方向。")

    hot_names = [str(x.get("name") or "") for x in hot[:6] if x.get("name")]
    if hot_names:
        bullets.append(f"盘面线索：当前热点样本包括 { '、'.join(hot_names) }，短线情绪仍围绕强势方向交易。")

    news = external_ctx.get("news") or []
    search = external_ctx.get("search") or []
    stooq = external_ctx.get("stooq") or []
    if news:
        top_news = "；".join([_clip(str(x.get("title") or ""), 32) for x in news[:3]])
        bullets.append(f"联网补充（新闻）：{top_news}。建议以多来源交叉验证事件持续性。")
    elif search:
        top_snip = "；".join([_clip(str(x.get("snippet") or ""), 40) for x in search[:2]])
        bullets.append(f"联网补充（主题摘要）：{top_snip}")
    elif stooq:
        snap = "；".join(
            [
                f"{x.get('symbol')} 收 {x.get('close')}（{x.get('date')} {x.get('time')}）"
                for x in stooq[:2]
                if x.get("symbol")
            ]
        )
        if snap:
            bullets.append(f"联网补充（Stooq）：{snap}。可作为跨市场风险偏好与商品方向的实时锚点。")
    else:
        bullets.append("外部公开线索仍在更新中，当前先结合盘面样本给出阶段性判断。")

    if question:
        bullets.append(f"问题聚焦：{_clip(question, 72)}")
    if keyword or category:
        bullets.append(f"关注主题：{_clip(keyword or category, 36)}")

    risks.append("外部资讯可能存在时滞或噪音，需以交易所公告、公司公告与权威数据终端复核。")
    risks.append("若量价背离或热点扩散失败，短线交易拥挤可能引发波动放大。")
    risks.append("本分析仅供研究讨论，不构成任何投资建议。")

    return {
        "title": _clip(title, 50),
        "summary": "已整合行情、热点与公开资讯，以下给出与你问题直接相关的结论与关注方向。",
        "bullets": bullets[:6] if bullets else ["当前可用数据较少，建议补充更具体标的或主题后重试。"],
        "risk": risks[:3],
        "disclaimer": "免责声明：以上内容基于公开信息自动整理，不构成投资建议。市场有风险，决策需独立判断并自行承担责任。",
        "source": "template",
    }


def _build_llm_context(
    question: str,
    keyword: str,
    category: str,
    stock_symbol: str,
    history: list[dict],
    stock: dict | None,
    hot: list[dict],
    external_ctx: dict,
) -> dict:
    return {
        "input": {
            "question": _clip(question, 240),
            "keyword": _clip(keyword, 80),
            "category": _clip(category, 40),
            "stock_symbol": _clip(stock_symbol, 32),
        },
        "conversation_history": history[-6:],
        "local_data": {"stock_snapshot": stock, "hot_topics_sample": hot[:15]},
        "external_data": external_ctx,
        "constraints": [
            "只能基于上下文输出，不得虚构",
            "措辞要自然专业，避免出现系统提示词口吻",
            "输出必须是 JSON：title/summary/bullets/risk/disclaimer/source",
        ],
    }


def _normalize_history(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for x in raw[:12]:
        if not isinstance(x, dict):
            continue
        role = str(x.get("role") or "").strip().lower()
        content = _clip(x.get("content") or "", 220)
        if role not in ("user", "assistant") or not content:
            continue
        out.append({"role": role, "content": content})
    return out


def _history_digest(history: list[dict]) -> str:
    parts: list[str] = []
    for x in history[-6:]:
        parts.append(f"{x.get('role')}:{x.get('content')}")
    return "\n".join(parts)


def _sanitize_llm_output(obj: dict, fallback: dict) -> dict:
    blocks_raw = obj.get("blocks")
    blocks: list[dict] = []
    if isinstance(blocks_raw, list):
        for b in blocks_raw[:5]:
            if not isinstance(b, dict):
                continue
            mode = str(b.get("mode") or "").strip().lower()
            title = _clip(_polish_text(str(b.get("title") or "")), 20)
            if mode == "list":
                items = b.get("items")
                if isinstance(items, list):
                    clean_items: list[str] = []
                    for x in items[:6]:
                        t = _clip(_bullet_item_to_text(x), 160)
                        if t:
                            clean_items.append(t)
                    if clean_items:
                        blocks.append({"title": title or "分析要点", "mode": "list", "items": clean_items})
            else:
                text = _clip(_polish_text(str(b.get("text") or "")), 220)
                if text:
                    blocks.append({"title": title, "mode": "paragraph", "text": text})

    # 兼容旧格式（bullets/risk）自动转 blocks
    if not blocks:
        bullets = obj.get("bullets")
        risk = obj.get("risk")
        if isinstance(bullets, list):
            clean_bullets: list[str] = []
            for x in bullets[:6]:
                t = _clip(_bullet_item_to_text(x), 140)
                if t:
                    clean_bullets.append(t)
            if clean_bullets:
                blocks.append({"title": "分析要点", "mode": "list", "items": clean_bullets})
        if isinstance(risk, list):
            clean_risk: list[str] = []
            for x in risk[:4]:
                t = _clip(_bullet_item_to_text(x), 160)
                if t:
                    clean_risk.append(t)
            if clean_risk:
                blocks.append({"title": "风险提示", "mode": "list", "items": clean_risk})

    if not blocks:
        return fallback

    # 给旧前端字段做兼容映射
    bullets_compat: list[str] = []
    risk_compat: list[str] = []
    for b in blocks:
        if b.get("mode") == "list":
            items = b.get("items") or []
            if "风险" in str(b.get("title") or ""):
                risk_compat.extend(items)
            else:
                bullets_compat.extend(items)

    if not bullets_compat:
        # 没有列表型要点时，给一个兼容字段避免旧 UI 为空
        para = next((x.get("text") for x in blocks if x.get("mode") == "paragraph" and x.get("text")), "")
        if para:
            bullets_compat = [para]
    if not risk_compat:
        risk_compat = ["请结合自身风险承受能力审慎判断。"]

    return {
        "title": _clip(_polish_text(obj.get("title") or fallback.get("title") or "智能投研分析"), 50),
        "summary": _clip(_polish_text(obj.get("summary") or fallback.get("summary") or ""), 180),
        "blocks": blocks,
        "bullets": bullets_compat[:6],
        "risk": risk_compat[:4],
        "disclaimer": _clip(
            obj.get("disclaimer")
            or fallback.get("disclaimer")
            or "免责声明：以上内容不构成投资建议。",
            220,
        ),
        "source": "llm",
    }


def research_analyze(
    session,
    state: dict,
    payload: dict[str, Any],
    fetch_stock_snapshot: Callable[[str], dict | None] | None,
    fetch_hot_items: Callable[[], list[dict]],
) -> dict:
    question = str(payload.get("question") or "").strip()
    keyword = str(payload.get("keyword") or "").strip()
    category = str(payload.get("category") or "").strip()
    stock_symbol = str(payload.get("stockSymbol") or "").strip()
    history = _normalize_history(payload.get("history"))

    # 输入过短也继续分析，保证“永不空”
    if not (question or keyword or stock_symbol):
        question = "请给出当前市场局势的通用研判框架。"

    hot = fetch_hot_items() or []

    stock: dict | None = None
    if fetch_stock_snapshot:
        # 优先显式代码
        if stock_symbol:
            try:
                stock = fetch_stock_snapshot(stock_symbol)
            except Exception:
                stock = None

        # 通用主题模式：仅在“像标的”的输入下再做自动识别，避免任意问题都触发行情探测造成慢请求
        auto_stock_hint = bool(
            re.search(
                r"(sh\d{6}|sz\d{6}|bj\d{6}|黄金|白银|原油|xau|xag|wti|brent|纳指|标普|道琼斯)",
                f"{question} {keyword}",
                flags=re.IGNORECASE,
            )
        )
        if not stock and auto_stock_hint:
            t_stock = time.time()
            for cand in _extract_query_candidates(question, keyword, category, stock_symbol)[:2]:
                if time.time() - t_stock > 5.0:
                    break
                try:
                    st = fetch_stock_snapshot(cand)
                except Exception:
                    st = None
                if st and st.get("name"):
                    stock = st
                    break

    query_candidates = _extract_query_candidates(question, keyword, category, stock_symbol)
    external_ctx = _collect_external_context(session, query_candidates, budget_s=14.0)
    external_ctx = _seed_external_context(question, keyword, category, hot, external_ctx)

    template_out = _template_research(question, keyword, category, stock, hot, external_ctx)

    memo_key = _hash_key(
        [
            question,
            keyword,
            category,
            stock_symbol,
            _history_digest(history),
            json.dumps(stock or {}, ensure_ascii=False, sort_keys=True),
            json.dumps(hot[:10], ensure_ascii=False, sort_keys=True),
            json.dumps(external_ctx, ensure_ascii=False, sort_keys=True),
        ]
    )
    cached = _memo_get(memo_key)
    if cached:
        cached["_debug"] = {
            "cached": True,
            "stock_used": bool(stock),
            "hot_count": len(hot),
            "ext_news_count": len(external_ctx.get("news") or []),
            "ext_search_count": len(external_ctx.get("search") or []),
        }
        return cached

    # LLM 不可用：明确返回“未配置模型”而非伪装模板分析
    if not _llm_configured():
        out = {
            "title": "未启用大模型，无法生成定制投研回答",
            "summary": "当前后端未配置 LLM_API_BASE / LLM_API_KEY / LLM_MODEL。请先配置大模型后再进行问答式投研。",
            "bullets": [
                "你当前看到的“模板化结论”问题，根因是未接入可用大模型。",
                "已采集到的市场与外部信息仍可用，但需要模型进行问题导向的归纳与推理。",
                "配置完成后，系统会按你的问题直接回答，而不是固定模板。"
            ],
            "risk": [
                "未启用大模型时，无法提供你要求的“针对问题的动态分析”。"
            ],
            "disclaimer": "免责声明：以上为系统状态说明，不构成投资建议。",
            "source": "no_llm",
        }
        out["_debug"] = {
            "cached": False,
            "reason": "llm_not_configured",
            "stock_used": bool(stock),
            "hot_count": len(hot),
            "ext_news_count": len(external_ctx.get("news") or []),
            "ext_search_count": len(external_ctx.get("search") or []),
        }
        _memo_set(memo_key, out)
        return out

    if not _topics_llm_allow(state):
        out = dict(template_out)
        out["_debug"] = {
            "cached": False,
            "reason": "llm_daily_limit_reached",
            "stock_used": bool(stock),
            "hot_count": len(hot),
            "ext_news_count": len(external_ctx.get("news") or []),
            "ext_search_count": len(external_ctx.get("search") or []),
        }
        _memo_set(memo_key, out)
        return out

    context = _build_llm_context(question, keyword, category, stock_symbol, history, stock, hot, external_ctx)
    sys = (
        "你是专业的中文投研分析师。"
        "请先直接回答用户问题，再给出支撑依据与风险。"
        "若 conversation_history 存在，需要与当前问题保持连续语义，不要忽略用户前文。"
        "你必须基于 local_data 和 external_data 输出，禁止编造。"
        "结果必须是 JSON 对象，字段为 {title,summary,blocks,disclaimer,source}。"
        "要求："
        "1) summary 必须是针对用户问题的直接结论（不是模板话术）；"
        "2) blocks 为 2~4 个区块，每个区块可选 mode=list 或 mode=paragraph："
        "   - list 区块字段：{title,mode:'list',items:[...]}"
        "   - paragraph 区块字段：{title,mode:'paragraph',text:'...'}"
        "3) 区块形式必须根据问题灵活变化：有时多分点，有时短段落，不要固定模板；"
        "4) 语气像真实研究纪要，避免“待验证/无数据/模板”等表达；"
        "5) source 必须写 'llm'；禁止买卖指令与收益承诺。"
    )
    user = json.dumps(context, ensure_ascii=False)

    try:
        txt = llm_chat(session, [{"role": "system", "content": sys}, {"role": "user", "content": user}], timeout_s=18)
        obj = parse_llm_json_obj(txt) or {}
        out = _sanitize_llm_output(obj, template_out)
        _topics_llm_mark_used(state)
    except Exception as e:
        out = {
            "title": "大模型调用失败，暂时无法生成问答式分析",
            "summary": "已获取到部分市场信息，但当前模型接口不可用（超时/鉴权/网络）。请修复模型连接后重试。",
            "bullets": [
                "你的需求是“基于实时信息的定制问答”，这依赖可用的大模型接口。",
                "当前数据采集链路已运行，但模型层失败，无法完成你期望的深度归纳。",
                "请检查 LLM_API_BASE、LLM_API_KEY、LLM_MODEL 与目标接口网络连通性。"
            ],
            "risk": [
                "模型不可用时继续输出模板结论会误导体验，因此已改为明确报错态。"
            ],
            "disclaimer": "免责声明：以上为系统状态说明，不构成投资建议。",
            "source": "llm_error",
        }
        out["_debug"] = {
            "cached": False,
            "reason": f"llm_call_failed: {str(e)[:180]}",
            "stock_used": bool(stock),
            "hot_count": len(hot),
            "ext_news_count": len(external_ctx.get("news") or []),
            "ext_search_count": len(external_ctx.get("search") or []),
            "query_candidates": query_candidates[:5],
        }
        _memo_set(memo_key, out)
        return out

    # 最终兜底（理论上不会触发）
    if not isinstance(out, dict) or not out.get("bullets"):
        out = {
            "title": "智能投研研判（应急兜底）",
            "summary": "当前外部数据波动较大，已返回最小可用研判框架。",
            "bullets": [
                "先确认你关注的是个股、板块还是宏观主题，并补充时间范围（日内/周内）。",
                "优先观察价格趋势、量能变化和热点扩散路径，再判断持续性。",
                "任何结论都需要用公告和权威数据做二次验证。",
            ],
            "risk": ["信息滞后与样本偏差可能造成误判。", "高波动阶段应控制仓位与回撤阈值。"],
            "disclaimer": "免责声明：以上内容不构成投资建议。",
            "source": "template",
        }

    out["title"] = _polish_text(out.get("title") or "")
    out["summary"] = _polish_text(out.get("summary") or "")
    out["bullets"] = [_bullet_item_to_text(x) for x in (out.get("bullets") or [])]
    out["risk"] = _enhance_risk_lines(question, keyword, category, stock, out.get("risk") or [])

    out["_debug"] = {
        "cached": False,
        "stock_used": bool(stock),
        "hot_count": len(hot),
        "ext_news_count": len(external_ctx.get("news") or []),
        "ext_search_count": len(external_ctx.get("search") or []),
        "query_candidates": query_candidates[:5],
    }
    _memo_set(memo_key, out)
    return out

