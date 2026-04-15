import json
import re
import threading
import time


def env_get(name: str, default: str | None = None) -> str | None:
    import os
    v = os.environ.get(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s != "" else default


def parse_llm_json_obj(text: str) -> dict | None:
    s = (text or "").strip()
    if not s:
        return None
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s*```$", "", s).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        s = m.group(0)
    try:
        return json.loads(s)
    except Exception:
        return None


def llm_chat(session, messages: list[dict], timeout_s: int = 25) -> str:
    base = env_get("LLM_API_BASE")
    api_key = env_get("LLM_API_KEY")
    model = env_get("LLM_MODEL")
    if not base or not api_key or not model:
        raise RuntimeError("缺少环境变量 LLM_API_BASE/LLM_API_KEY/LLM_MODEL")
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": 0.4}
    last_err = None
    for i in range(3):
        try:
            r = session.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout_s)
            r.raise_for_status()
            j = r.json()
            txt = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if not txt:
                raise RuntimeError("LLM 返回空内容")
            return txt
        except Exception as e:
            last_err = e
            if i < 2:
                time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"LLM 调用失败（重试后仍失败）：{last_err}")


def news_llm_allow(state: dict) -> bool:
    day = time.strftime("%Y%m%d", time.localtime())
    if day != state.get("day"):
        state["day"] = day
        state["used"] = 0
    try:
        limit = int(float(env_get("NEWS_LLM_DAILY_LIMIT", "50") or "50"))
    except Exception:
        limit = 50
    return state.get("used", 0) < max(0, limit)


def news_llm_mark_used(state: dict):
    state["used"] = int(state.get("used", 0)) + 1


def llm_summarize_and_score(session, state: dict, item: dict, news_keyword_hits, fallback_summary, fallback_category):
    title = str(item.get("title") or "").strip()
    source = item.get("source")
    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(item.get("ctime") or 0)))
    kw_hits = news_keyword_hits(title)
    sys = (
        "你是财经新闻编辑。请对输入新闻生成中文摘要与重要性评分。"
        "输出必须是 JSON 对象，字段：summary（约100字，客观中性，不要添加无根据内容），importance（0-100整数），micro_title（4-6个汉字，必须体现“对金融市场的影响/线索”）。"
        "不要输出除 JSON 之外的任何文字。"
    )
    user = f"标题：{title}\n来源：{source or ''}\n发布时间：{dt}\n提示关键词：{', '.join(kw_hits) if kw_hits else ''}"
    if not news_llm_allow(state):
        item["_category"] = fallback_category(title)
        return fallback_summary(title, source), 50, kw_hits
    txt = llm_chat(session, [{"role": "system", "content": sys}, {"role": "user", "content": user}])
    news_llm_mark_used(state)
    obj = parse_llm_json_obj(txt) or {}
    summary = str(obj.get("summary") or "").strip()
    imp = obj.get("importance")
    category = str(obj.get("micro_title") or "").strip()
    try:
        importance = int(float(imp))
    except Exception:
        importance = 50
    importance = max(0, min(100, importance))
    if not summary:
        summary = fallback_summary(title, source)
    if not category:
        category = fallback_category(title)
    if len(category) > 6:
        category = category[:6]
    if len(summary) > 140:
        summary = summary[:140].rstrip() + "…"
    item["_category"] = category
    return summary, importance, kw_hits


def start_news_worker(state: dict, lock: threading.Lock, queue: list, pending: set, worker_started: dict, process_item):
    with lock:
        if worker_started.get("started"):
            return
        worker_started["started"] = True

    def _loop():
        while True:
            item = None
            with lock:
                if queue:
                    item = queue.pop(0)
            if not item:
                time.sleep(0.3)
                continue
            try:
                process_item(item)
            finally:
                with lock:
                    pending.discard(str(item.get("id") or ""))

    threading.Thread(target=_loop, daemon=True).start()

