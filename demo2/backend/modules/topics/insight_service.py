"""
涨幅榜相关的大模型解读（与新闻 LLM 共用 LLM_API_BASE / KEY / MODEL）。
无配置或超限时回退到规则模板，仍返回 200。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from modules.news.llm import env_get, llm_chat, parse_llm_json_obj


def _clip(s: str, n: int = 80) -> str:
    t = str(s or "").replace("\r", " ").replace("\n", " ").strip()
    return t[:n] if len(t) > n else t


def topics_llm_allow(state: dict, env_limit_name: str = "TOPICS_LLM_DAILY_LIMIT", default_limit: int = 40) -> bool:
    day = time.strftime("%Y%m%d", time.localtime())
    if day != state.get("day"):
        state["day"] = day
        state["used"] = 0
    try:
        limit = int(float(env_get(env_limit_name, str(default_limit)) or default_limit))
    except Exception:
        limit = default_limit
    return state.get("used", 0) < max(0, limit)


def topics_llm_mark_used(state: dict) -> None:
    state["used"] = int(state.get("used", 0)) + 1


def llm_configured() -> bool:
    return bool(env_get("LLM_API_BASE") and env_get("LLM_API_KEY") and env_get("LLM_MODEL"))


_INSIGHT_MEMO: dict[str, tuple[float, dict]] = {}
_MEMO_TTL_STOCK = 120.0
_MEMO_TTL_BOARD = 240.0


def _memo_get(key: str, ttl: float) -> dict | None:
    hit = _INSIGHT_MEMO.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > ttl:
        _INSIGHT_MEMO.pop(key, None)
        return None
    return val


def _memo_set(key: str, val: dict) -> None:
    _INSIGHT_MEMO[key] = (time.time(), val)


def _hash_key(parts: list[str]) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:32]
    return h


def fallback_stock_lines(
    name: str,
    code: str,
    pct_chg: float,
    rank: int,
    avg_pct: float,
    quote: dict | None = None,
) -> list[str]:
    p = float(pct_chg)
    d = p - float(avg_pct)
    abs_d = abs(d)
    if p >= 12:
        l1 = "该股涨幅处于榜单前列，短线波动往往放大，需留意分时承接与量能变化。"
    elif p >= 8:
        l1 = "该股今日偏强，可关注是否具备板块联动与换手配合。"
    elif p >= 5:
        l1 = "该股涨幅高于中性水平，注意分化行情下后排跟风风险。"
    else:
        l1 = "该股涨幅相对温和，可结合大盘与所属板块强弱综合判断。"

    if d >= 0.5:
        l2 = f"当前涨幅高于本榜均值约 {abs_d:.2f} 个百分点，相对榜单整体更强势。"
    elif d <= -0.5:
        l2 = f"当前涨幅低于本榜均值约 {abs_d:.2f} 个百分点，在强势股中偏跟随。"
    else:
        l2 = "与榜单平均涨幅接近，属于同日强势股中的中等强度。"

    lines = [l1, l2]
    if quote and quote.get("price") is not None:
        lines.append(
            "【行情事实】现价 {price}，今开 {open}，高 {high} 低 {low}，昨收 {prev_close}；"
            "较昨收涨跌 {pct}%（行情时间 {tm}）。以上数值来自行情接口，非推测。".format(
                price=quote.get("price"),
                open=quote.get("open"),
                high=quote.get("high"),
                low=quote.get("low"),
                prev_close=quote.get("prev_close"),
                pct=quote.get("pct_chg"),
                tm=_clip(str(quote.get("update_time") or ""), 24),
            )
        )

    nm = _clip(name, 20)
    cd = _clip(code, 16)
    lines.append(f"以上为基于公开数据的统计性描述（{nm} {cd}），不构成投资建议。")
    return lines


def fallback_board_bullets(items: list[dict]) -> list[str]:
    arr = []
    for x in items:
        if not isinstance(x, dict):
            continue
        try:
            pc = float(x.get("pct_chg"))
        except (TypeError, ValueError):
            continue
        arr.append({**x, "pct_chg": pc})
    if not arr:
        return ["暂无可分析数据，请稍后刷新榜单。"]
    pcts = [float(x["pct_chg"]) for x in arr]
    avg = sum(pcts) / len(pcts)
    top3 = pcts[:3]
    top3_avg = sum(top3) / len(top3) if top3 else 0
    strong = sum(1 for v in pcts if v >= 7)
    weak = sum(1 for v in pcts if v < 4)
    spread = pcts[0] - pcts[-1] if len(pcts) >= 2 else 0
    leader = _clip(str(arr[0].get("name") or ""), 24) or "榜首"
    heat = "情绪偏强，追高需控制节奏与仓位。" if avg >= 6 else ("强势扩散中，优先观察量价与板块共振。" if avg >= 4.5 else "分化较明显，宜聚焦前排辨识度更高的标的。")
    return [
        f"榜首「{leader}」领衔，前三平均涨幅约 {top3_avg:.2f}%。",
        f"本批样本平均涨幅 {avg:.2f}%，涨停梯队附近（≥7%）约 {strong} 只，偏弱（<4%）约 {weak} 只。",
        f"首尾涨幅差约 {spread:.2f} 个百分点；{heat}",
    ]


def stock_insight(
    session,
    state: dict,
    payload: dict[str, Any],
    fetch_quote: Callable[[str], dict | None] | None = None,
) -> dict:
    name = _clip(payload.get("name") or "", 40)
    code = _clip(payload.get("leader") or payload.get("code") or "", 24)
    try:
        pct_chg = float(payload.get("pct_chg"))
    except Exception:
        pct_chg = 0.0
    try:
        rank = int(payload.get("rank") or 0)
    except Exception:
        rank = 0
    try:
        avg_pct = float(payload.get("avg_pct"))
    except Exception:
        avg_pct = 0.0

    quote: dict | None = None
    if fetch_quote and code:
        try:
            quote = fetch_quote(code)
        except Exception:
            quote = None

    board_top = payload.get("board_top")
    if not isinstance(board_top, list):
        board_top = []
    top_lines = []
    for i, row in enumerate(board_top[:12]):
        if not isinstance(row, dict):
            continue
        nm = _clip(row.get("name"), 16)
        try:
            pc = float(row.get("pct_chg"))
        except Exception:
            continue
        top_lines.append(f"{i + 1}.{nm} {pc:+.2f}%")
    board_text = "；".join(top_lines) if top_lines else "（未提供榜面前列明细）"

    q_sig = ""
    if quote:
        q_sig = json.dumps(
            {"p": quote.get("price"), "pct": quote.get("pct_chg"), "t": quote.get("update_time")},
            sort_keys=True,
            ensure_ascii=False,
        )
    memo_key = _hash_key([code, str(rank), f"{pct_chg:.2f}", board_text[:200], q_sig])
    cached = _memo_get(memo_key, _MEMO_TTL_STOCK)
    if cached:
        return {**cached, "cached": True}

    def _pack(result: dict) -> dict:
        out = dict(result)
        out["quote_snapshot"] = quote
        out["quote_used"] = bool(quote)
        return out

    base = {
        "lines": fallback_stock_lines(name, code, pct_chg, rank, avg_pct, quote),
        "source": "template",
        "disclaimer": "基于涨幅榜统计"
        + ("与新浪实时行情快照" if quote else "")
        + "的模板说明，非投资建议。",
    }
    base = _pack(base)

    if not llm_configured() or not topics_llm_allow(state):
        _memo_set(memo_key, dict(base))
        return base

    sys_prompt = (
        "你是 A 股市场的「数据解读助手」。用户将提供 JSON：含涨幅榜上的排名/涨跌幅/榜前列摘要，"
        "以及可选的「新浪实时行情快照」（现价、开高低收、较昨收涨跌幅、行情时间）。"
        "你的任务：仅根据这些字段做 2～3 段中文「观察与风险提示」，每段不超过 90 字。"
        "必须遵守："
        "（1）严禁补充、猜测或捏造任何 JSON 中未出现的消息（新闻、公告、业绩、政策、主力、题材、目标价等一律禁止）；"
        "（2）若仅有榜单数据而无行情快照，不得编造 OHLC 或成交价；"
        "（3）可讨论当日价格相对昨收、开盘区间、高低点关系等，但只能基于快照中的数字；"
        "（4）禁止给出具体买卖价、禁止承诺收益、禁止写成确定性交易指令；"
        "（5）语气中性、教育性，结尾倾向「需自行核实、注意波动与流动性」。"
        "输出仅为 JSON：{\"lines\":[\"段落1\",\"段落2\",\"段落3可选\"]}"
    )
    user_obj: dict[str, Any] = {
        "股票名称_榜单": name,
        "代码": code,
        "榜单排名": rank,
        "榜单中的涨幅百分比": round(pct_chg, 2),
        "本榜平均涨幅": round(avg_pct, 2),
        "榜前列摘要": board_text,
    }
    if quote:
        user_obj["新浪实时行情快照_仅可引用其中数字"] = quote
    else:
        user_obj["新浪实时行情快照"] = "本次未获取到，不得编造开高低收现价。"
    user_prompt = json.dumps(user_obj, ensure_ascii=False)

    try:
        txt = llm_chat(session, [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], timeout_s=28)
        topics_llm_mark_used(state)
        obj = parse_llm_json_obj(txt) or {}
        lines = obj.get("lines")
        if isinstance(lines, list):
            cleaned = []
            for x in lines[:4]:
                s = _clip(str(x), 120)
                if s:
                    cleaned.append(s)
            if len(cleaned) >= 2:
                out = {
                    "lines": cleaned,
                    "source": "llm",
                    "disclaimer": (
                        "由大模型仅根据上述公开行情快照与榜单统计整理，不保证完整准确，"
                        "不得视为研报或投资建议；决策请自行核实行情与公告。"
                    ),
                }
                out = _pack(out)
                _memo_set(memo_key, dict(out))
                return out
    except Exception:
        pass

    _memo_set(memo_key, dict(base))
    return base


def board_insight(session, state: dict, items: list[dict]) -> dict:
    clean: list[dict] = []
    for x in items[:40]:
        if not isinstance(x, dict):
            continue
        nm = _clip(x.get("name"), 24)
        if not nm:
            continue
        try:
            pc = float(x.get("pct_chg"))
        except Exception:
            continue
        clean.append({"name": nm, "pct_chg": round(pc, 2)})

    memo_key = _hash_key([json.dumps(clean[:15], ensure_ascii=False, sort_keys=True)])
    cached = _memo_get(memo_key, _MEMO_TTL_BOARD)
    if cached:
        return {**cached, "cached": True}

    fb = {"bullets": fallback_board_bullets(clean), "source": "template"}
    if len(clean) < 3:
        _memo_set(memo_key, {k: v for k, v in fb.items()})
        return fb

    if not llm_configured() or not topics_llm_allow(state):
        _memo_set(memo_key, {k: v for k, v in fb.items()})
        return fb

    sys_prompt = (
        "你是 A 股市场复盘助手。下面是一组当日涨幅榜股票（仅名称与涨跌幅百分比，样本可能不完整）。"
        "请输出 3 条中文要点（每条不超过 100 字）：概括龙头与梯队、整体强弱与分化、以及短线观察风险（中性表述，不给买卖指令）。"
        "严禁编造未提供的新闻、公告、题材、资金动向；不得出现具体买卖价或收益承诺。"
        "输出仅为 JSON：{\"bullets\":[\"要点1\",\"要点2\",\"要点3\"]}"
    )
    user_prompt = json.dumps({"样本": clean[:25]}, ensure_ascii=False)

    try:
        txt = llm_chat(session, [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}], timeout_s=32)
        topics_llm_mark_used(state)
        obj = parse_llm_json_obj(txt) or {}
        bullets = obj.get("bullets")
        if isinstance(bullets, list):
            b2 = [_clip(str(b), 140) for b in bullets[:5] if _clip(str(b), 140)]
            if len(b2) >= 2:
                out = {"bullets": b2, "source": "llm"}
                _memo_set(memo_key, {k: v for k, v in out.items()})
                return out
    except Exception:
        pass

    _memo_set(memo_key, {k: v for k, v in fb.items()})
    return fb
