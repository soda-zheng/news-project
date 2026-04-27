from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from functools import partial

import requests
try:
    from opencc import OpenCC
except Exception:  # pragma: no cover
    OpenCC = None  # type: ignore

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_SESSIONS: dict[str, dict] = {}
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2)

_CC_T2S = OpenCC("t2s") if OpenCC else None
_T2S_FALLBACK_MAP = {
    "發": "发", "佈": "布", "變": "变", "動": "动", "況": "况", "與": "与", "對": "对", "應": "应",
    "為": "为", "務": "务", "產": "产", "業": "业", "關": "关", "鍵": "键", "數": "数", "據": "据",
    "風": "风", "險": "险", "體": "体", "質": "质", "營": "营", "銷": "销", "額": "额", "報": "报",
    "總": "总", "級": "级", "壓": "压", "減": "减", "價": "价", "達": "达", "實": "实", "現": "现",
    "續": "续", "邏": "逻", "輯": "辑", "證": "证", "監": "监", "幣": "币", "萬": "万", "億": "亿",
    "臺": "台", "這": "这", "個": "个", "題": "题", "選": "选", "擇": "择", "編": "编", "頁": "页",
    "買": "买", "賣": "卖", "盤": "盘", "錄": "录", "經": "经", "淨": "净", "條": "条", "後": "后",
    "驗": "验", "開": "开", "戰": "战", "略": "略", "顯": "显", "著": "着", "將": "将", "來": "来",
    "滿": "满", "擴": "扩", "張": "张", "節": "节", "點": "点", "組": "组", "織": "织", "綱": "纲",
    "領": "领", "導": "导", "閱": "阅", "讀": "读", "檢": "检", "查": "查", "資": "资", "訊": "讯",
    "佔": "占", "會": "会", "裡": "里", "門": "门", "書": "书", "樣": "样", "勵": "励", "劃": "划",
    "獎": "奖", "歲": "岁", "戶": "户", "網": "网", "區": "区", "雲": "云", "滙": "汇", "國": "国",
    "龍": "龙", "專": "专", "項": "项", "債": "债", "醫": "医", "藥": "药",
    "瑪": "玛", "際": "际", "團": "团", "調": "调", "潤": "润", "術": "术",
    "幹": "干", "雜": "杂", "訊": "讯", "釋": "释", "壹": "壹", "貳": "贰", "參": "叁",
    "肆": "肆", "伍": "伍", "陸": "陆", "柒": "柒", "捌": "捌", "玖": "玖", "拾": "拾",
}


def _get_llm_env():
    return {
        "api_base": str(os.environ.get("LLM_API_BASE") or "").strip(),
        "model": str(os.environ.get("LLM_MODEL") or "").strip(),
        "api_key": str(os.environ.get("LLM_API_KEY") or "").strip(),
    }


def _get_report_llm_env():
    api_base = str(os.environ.get("REPORT_LLM_API_BASE") or "").strip()
    model = str(os.environ.get("REPORT_LLM_MODEL") or "").strip()
    api_key = str(os.environ.get("REPORT_LLM_API_KEY") or "").strip()
    if api_key:
        if not api_base:
            api_base = "https://open.bigmodel.cn/api/paas/v4"
        if not model:
            model = "glm-4-flash"
        return {"api_base": api_base, "model": model, "api_key": api_key}
    return _get_llm_env()


def _env_float(key: str, default: float) -> float:
    try:
        v = os.environ.get(key)
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        v = os.environ.get(key)
        if v is None or str(v).strip() == "":
            return default
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _strip_question_page_markers(q: str) -> str:
    """用户可见问题行不展示 （P5）/ (P5) / （第3页） 等页码标注。"""
    s = str(q or "").strip()
    if not s:
        return s
    s = re.sub(r"\s*[（(]\s*P\d+\s*[）)]\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[（(]\s*第\s*\d+\s*页\s*[）)]\s*$", "", s)
    return s.rstrip()


def _scrub_forbidden_weipilou(s: str) -> str:
    """产品要求全文不出现「未披露」字样（含模型常见套话），统一改为合规表述。"""
    t = str(s or "")
    if not t or "未披露" not in t:
        return t
    t = re.sub(
        r"财报摘录未披露|摘录未披露|文本里未披露|文本未披露|年报未披露|暂未披露|尚未披露|未予披露",
        "需对照年报核实",
        t,
    )
    return t.replace("未披露", "需对照年报核实")


def _to_simplified(s: str) -> str:
    t = str(s or "")
    if not t:
        return t
    try:
        if _CC_T2S:
            return str(_CC_T2S.convert(t))
    except Exception:
        pass
    return "".join([_T2S_FALLBACK_MAP.get(ch, ch) for ch in t])


def _simplify_facts(facts: list[dict]) -> list[dict]:
    out = []
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        out.append(
            {
                "indicator": _to_simplified(str(f.get("indicator") or "")),
                "value": _to_simplified(str(f.get("value") or "")),
                "page": str(f.get("page") or ""),
                "evidence": _to_simplified(str(f.get("evidence") or "")),
            }
        )
    return out


def _simplify_pages_map(pages: dict[int, str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for p, txt in (pages or {}).items():
        try:
            pi = int(p)
        except Exception:
            continue
        out[pi] = _to_simplified(str(txt or ""))
    return out


def _deep_simplify_obj(obj):
    if isinstance(obj, str):
        return _to_simplified(obj)
    if isinstance(obj, list):
        return [_deep_simplify_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_simplify_obj(v) for k, v in obj.items()}
    return obj


def _safe_json_obj(content: str) -> dict:
    obj = _extract_json_object(content) or {}
    return obj if isinstance(obj, dict) else {}


def _looks_like_valid_page_md(s: str) -> bool:
    t = str(s or "").strip()
    if not t or len(t) < 40:
        return False
    if t.startswith("### "):
        return True
    # 兼容审稿器未按 markdown 标题输出，但正文足够完整的情况
    return ("\n" in t and ("核心结论" in t or "细节" in t or "风险" in t))


def _question_from_choice(choice: str) -> str:
    if not choice:
        return ""
    parts = [p.strip() for p in _to_simplified(str(choice)).split("｜") if p.strip()]
    ind = parts[0] if parts else ""
    val = ""
    page = ""
    for p in parts[1:]:
        if re.fullmatch(r"P\d+", p):
            page = p
        elif not val:
            val = p
    if not ind:
        return ""
    suffix = f"（{page}）" if page else "（P1）"
    if val:
        return f"围绕「{ind}」为{val}这一变化，最关键的驱动拆解是什么？对盈利质量与后续指引的影响分别是什么{suffix}？"
    return f"围绕本期「{ind}」披露，最关键的变化与驱动是什么？对盈利质量与风险暴露的含义分别是什么{suffix}？"


def _fact_from_choice(choice: str, facts: list[dict]) -> dict | None:
    if not choice:
        return None
    parts = [p.strip() for p in _to_simplified(str(choice)).split("｜") if p.strip()]
    ind = parts[0] if parts else ""
    val = ""
    page = ""
    for p in parts[1:]:
        if re.fullmatch(r"P\d+", p):
            page = p
        elif not val:
            val = p
    if not ind:
        return None
    best = {"indicator": ind, "value": val, "page": page}
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("indicator") or "").strip() != ind:
            continue
        fp = str(f.get("page") or "").strip()
        if page and fp and fp != page:
            continue
        best["value"] = str(f.get("value") or best.get("value") or "").strip()
        best["page"] = (fp or best.get("page") or "").strip()
        break
    return best


def _strip_markdown_json_fence(text: str) -> str:
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


def _openai_compat_chat(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout_sec: int,
    env_override: dict,
    retry_max_retries: int,
    retry_base_sleep: float,
    retry_sleep_cap: float,
) -> str:
    api_base = str(env_override.get("api_base") or "").strip()
    model = str(env_override.get("model") or "").strip()
    api_key = str(env_override.get("api_key") or "").strip()
    if not api_base or not model or not api_key:
        raise RuntimeError("LLM env not configured (REPORT_LLM_* or LLM_*)")

    url = api_base.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "finance-backend/1.0",
    }
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    ts = float(timeout_sec or 60)
    req_timeout = (min(20.0, max(5.0, ts * 0.2)), ts)

    last_err: Exception | None = None
    for attempt in range(int(retry_max_retries) + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=req_timeout)
        except requests.exceptions.Timeout as e:
            last_err = e
            if attempt >= retry_max_retries:
                raise RuntimeError(f"LLM 请求超时（{timeout_sec}s）: {e}") from e
            sleep_s = retry_base_sleep * (2**attempt) + random.random() * 0.35
            time.sleep(min(retry_sleep_cap, sleep_s))
            continue

        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            last_err = e
            status = int(getattr(r, "status_code", 0) or 0)
            hint = ""
            try:
                hint = (r.text or "")[:600]
            except Exception:
                hint = ""
            is_retryable = status in (408, 409, 425, 429, 500, 502, 503, 504)
            if (not is_retryable) or attempt >= retry_max_retries:
                raise RuntimeError(f"LLM HTTP {status}: {hint or e}") from e
            sleep_s = retry_base_sleep * (2**attempt) + random.random() * 0.35
            if status == 429:
                ra = r.headers.get("Retry-After") if r.headers else None
                if ra:
                    try:
                        sleep_s = max(sleep_s, float(str(ra).strip()))
                    except ValueError:
                        pass
                sleep_s = max(sleep_s, 2.0 + random.random())
            time.sleep(min(retry_sleep_cap, sleep_s))
            continue

        data = r.json()
        err = data.get("error")
        if err:
            raise RuntimeError(str(err))
        content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content")
        if not content:
            raise RuntimeError(f"LLM empty content: {str(data)[:200]}")
        return str(content)

    raise RuntimeError(f"LLM HTTP retry failed: {last_err}") from last_err


def _report_chat(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout_sec: int,
    deadline_sec: float = 0,
) -> str:
    env = _get_report_llm_env()
    jm = bool(json_mode)
    if jm and str(os.environ.get("REPORT_LLM_DISABLE_JSON_OBJECT") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        jm = False

    rep_retries = _env_int("REPORT_LLM_MAX_RETRIES", 10)
    rep_base = _env_float("REPORT_LLM_RETRY_BASE_SLEEP_SEC", 2.0)
    rep_cap = _env_float("REPORT_LLM_RETRY_MAX_SLEEP_SEC", 90.0)

    _do = partial(
        _openai_compat_chat,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=jm,
        timeout_sec=timeout_sec,
        env_override=env,
        retry_max_retries=rep_retries,
        retry_base_sleep=rep_base,
        retry_sleep_cap=rep_cap,
    )

    dl = float(deadline_sec or 0)
    if dl <= 0:
        return _do()

    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_do)
    try:
        return fut.result(timeout=dl)
    except FuturesTimeout as te:
        raise RuntimeError(
            f"财报 LLM 本步骤超过 {dl:.0f}s 仍未结束（常见于接口极慢、网络挂起或大 PDF 一次送太多字）。"
        ) from te
    finally:
        pool.shutdown(wait=False)


def upload_file(file) -> dict | None:
    name = str(getattr(file, "filename", "") or "").strip()
    if not name.lower().endswith(".pdf"):
        return None
    session_id = uuid.uuid4().hex
    out_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    file.save(out_path)
    size = os.path.getsize(out_path)
    with _LOCK:
        _SESSIONS[session_id] = {"pdf_path": out_path, "name": name, "size": int(size)}
    return {"sessionId": session_id, "fileInfo": {"name": name, "size": int(size)}}


def create_session_from_pdf_url(pdf_url: str, name: str = "") -> dict:
    url = str(pdf_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("pdfUrl 非法或为空")
    file_name = str(name or "").strip() or os.path.basename(url.split("?", 1)[0]) or "report.pdf"
    if not file_name.lower().endswith(".pdf"):
        file_name = f"{file_name}.pdf"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    content = r.content or b""
    if not content:
        raise RuntimeError("下载的 PDF 内容为空")
    if not content.startswith(b"%PDF"):
        raise RuntimeError("下载内容不是有效 PDF")

    session_id = uuid.uuid4().hex
    out_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
    with open(out_path, "wb") as f:
        f.write(content)
    size = os.path.getsize(out_path)
    with _LOCK:
        _SESSIONS[session_id] = {"pdf_path": out_path, "name": file_name, "size": int(size)}
    return {"sessionId": session_id, "fileInfo": {"name": file_name, "size": int(size)}}


def create_task(session_id: str, analyze_type: str = "finance") -> dict | None:
    with _LOCK:
        if session_id not in _SESSIONS:
            return None
    a_type = str(analyze_type or "finance").strip().lower()
    if a_type not in ("finance", "research"):
        a_type = "finance"
    task_id = uuid.uuid4().hex
    with _LOCK:
        _TASKS[task_id] = {"status": "queued", "stage": "排队中", "error": "", "result": None, "analyzeType": a_type}
    _POOL.submit(_run_task, task_id, session_id, a_type)
    module = "research_report_deep" if a_type == "research" else "fin_report_real"
    return {"taskId": task_id, "engine": "finance-local", "module": module, "analyzeType": a_type}


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        return _TASKS.get(task_id)


def regen_page(session_id: str, page_index: int, custom_question: str = "", choice: str = "") -> dict:
    # 简化版：复用已生成 pages/questions/facts/tagged
    with _LOCK:
        sess = _SESSIONS.get(session_id) or {}
    pages = sess.get("pages") or []
    if not isinstance(pages, list) or not pages:
        raise RuntimeError("请先完成分析生成 5 问 5 解")
    if page_index < 0 or page_index >= len(pages):
        raise RuntimeError("pageIndex out of range")

    tagged = str(sess.get("tagged") or "").strip()
    if not tagged:
        raise RuntimeError("会话缺少财报文本上下文，请重新上传并开始分析")

    facts = sess.get("facts") or []
    facts = facts if isinstance(facts, list) else []

    q = _to_simplified(str(custom_question or "").strip())
    pinned_fact = None
    if not q and choice:
        q = _question_from_choice(choice)
    if choice:
        pinned_fact = _fact_from_choice(choice, facts)
    if not q:
        # 默认沿用原题
        md = str(pages[page_index] or "")
        m = re.search(r"^###\s+\d+\.\s+(.*)$", md, flags=re.M)
        q = (m.group(1).strip() if m else "").strip()
    q = _scrub_forbidden_weipilou(_strip_question_page_markers(q))
    if not q:
        q = "本期业绩的核心分化点与可持续性如何评估？"

    facts = _simplify_facts(facts)
    facts_ctx = json.dumps(facts[:12], ensure_ascii=False)
    prompt_a = (
        "你是严谨的卖方财报分析师。只依据下方财报文本与数据点作答，拒绝空泛结论。"
        "【强制要求】所有输出内容必须使用简体中文，禁止使用繁体汉字，所有词汇均需转换为大陆通用简体表述。"
        "输出简洁中文，格式必须含 4 段：核心结论、细节1、细节2、关键数字/概念。"
        "每段必须提供新增信息，禁止复述上一段。"
        "全文禁止出现「未披露」三字；证据不足时请写「需对照年报核实」或「摘录中未列示该口径」。"
        "可引用 Pxx 页码辅助定位；勿在【问题】行或用户可见标题里写页码。"
        "细节1：拆解驱动（量/价/结构/成本/一次性）至少 1 条，并给证据页码。"
        "细节2：给出反证/风险与验证动作（需要再核对的表或指标），并给线索页码。"
        "关键数字/概念：必须用 3-6 条列表输出，每条形如“指标｜数值｜Pxx”，不要写成一段话；"
        "每条以 “- ” 开头，行首不要写 1. 2. 等序号。"
    )
    pinned_txt = ""
    if pinned_fact and str(pinned_fact.get("indicator") or "").strip():
        pinned_txt = (
            f"\n【强约束数据点】{pinned_fact.get('indicator')}"
            f"｜{pinned_fact.get('value') or ''}｜{pinned_fact.get('page') or ''}\n"
            "必须围绕该数据点先回答，再展开风险与验证动作。"
        )
    user_a = f"【问题】{q}\n\n【可用数据点】{facts_ctx}{pinned_txt}\n\n【财报文本】\n{tagged[:6000]}"
    deadline = _env_float("REPORT_LLM_ANSWER_DEADLINE_SEC", 240.0)
    ans = _report_chat(
        [{"role": "system", "content": prompt_a}, {"role": "user", "content": user_a}],
        max_tokens=900,
        temperature=0.25,
        json_mode=False,
        timeout_sec=120,
        deadline_sec=deadline,
    )
    ans = _to_simplified(_scrub_forbidden_weipilou(str(ans or "").strip() or "本题暂无可用解析，请稍后重试。"))
    q = _to_simplified(q)
    pages[page_index] = f"### {page_index+1}. {q}\n\n{ans}"
    with _LOCK:
        if session_id in _SESSIONS:
            _SESSIONS[session_id]["pages"] = pages
    return {"pages": pages, "pageIndex": page_index}


def _run_task(task_id: str, session_id: str, analyze_type: str = "finance"):
    def _set_stage(stage: str):
        with _LOCK:
            if task_id in _TASKS:
                _TASKS[task_id]["stage"] = stage

    def _set_failed(err: str):
        with _LOCK:
            if task_id in _TASKS:
                _TASKS[task_id]["status"] = "failed"
                _TASKS[task_id]["stage"] = "失败"
                _TASKS[task_id]["error"] = str(err)
                _TASKS[task_id]["result"] = None

    with _LOCK:
        _TASKS[task_id]["status"] = "running"
        _TASKS[task_id]["stage"] = "解析PDF"
        _TASKS[task_id]["error"] = ""

    def _extract_pdf_pages(pdf_path: str) -> dict[int, str]:
        # 优先 PyMuPDF（更少乱码）；若不可用则回退 pypdf
        def _clean(t: str) -> str:
            t = re.sub(r"[ \t]+\n", "\n", t)
            t = re.sub(r"\n{3,}", "\n\n", t).strip()
            return t

        out: dict[int, str] = {}
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(pdf_path)
            try:
                for i in range(doc.page_count):
                    try:
                        page = doc.load_page(i)
                        t = page.get_text("text") or ""
                    except Exception:
                        t = ""
                    t = _clean(t)
                    if t:
                        out[i + 1] = t
            finally:
                try:
                    doc.close()
                except Exception:
                    pass
            if out:
                return out
        except Exception:
            out = {}

        if PdfReader is None:
            return {}
        reader = PdfReader(pdf_path)
        for i, p in enumerate(reader.pages or []):
            try:
                t = p.extract_text() or ""
            except Exception:
                t = ""
            t = _clean(t)
            if t:
                out[i + 1] = t
        return out

    def _build_page_tagged_text(pages: dict[int, str], max_chars: int = 20000) -> str:
        out = []
        cur = 0
        for p in sorted(pages.keys()):
            txt = str(pages.get(p) or "").strip()
            if not txt:
                continue
            chunk = f"[P{p}]\n{txt}\n"
            if cur + len(chunk) > max_chars:
                chunk = chunk[: max(0, max_chars - cur)]
            if not chunk:
                break
            out.append(chunk)
            cur += len(chunk)
            if cur >= max_chars:
                break
        return "\n".join(out).strip()

    def _sanitize_facts(facts_in: list[dict], max_total: int = 220) -> list[dict]:
        out = []
        seen = set()
        for f in facts_in or []:
            if not isinstance(f, dict):
                continue
            ind = str(f.get("indicator") or "").strip()
            val = str(f.get("value") or "").strip()
            page = str(f.get("page") or "").strip()
            ev = str(f.get("evidence") or "").strip()
            if not ind:
                continue
            key = (ind, val, page)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "indicator": _scrub_forbidden_weipilou(ind),
                    "value": _scrub_forbidden_weipilou(val),
                    "page": page,
                    "evidence": _scrub_forbidden_weipilou(ev),
                }
            )
            if len(out) >= max_total:
                break
        return out

    def _extract_rule_based_facts(pages_text: dict[int, str], max_per_page: int = 28, max_total: int = 200) -> list[dict]:
        facts = []
        re_pct = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
        re_amt = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(亿|万|千|百万|亿元|万美元|港元|美元|人民币|元)")
        keywords = [
            "收入",
            "营收",
            "净利润",
            "毛利率",
            "费用率",
            "研发",
            "经营现金流",
            "应收",
            "存货",
            "产能",
            "利用率",
            "ASP",
        ]
        for p in sorted(pages_text.keys()):
            txt = str(pages_text.get(p) or "")
            if not txt.strip():
                continue
            lines = [x.strip() for x in re.split(r"[。\n]", txt) if x.strip()]
            picked = 0
            for ln in lines:
                if picked >= max_per_page:
                    break
                if not any(k in ln for k in keywords):
                    continue
                if not (re_pct.search(ln) or re_amt.search(ln)):
                    continue
                ind = next((k for k in keywords if k in ln), "")
                if not ind:
                    continue
                facts.append({"indicator": ind, "value": "", "page": f"P{p}", "evidence": ln[:120]})
                picked += 1
                if len(facts) >= max_total:
                    break
            if len(facts) >= max_total:
                break
        return facts

    def _build_questions_from_facts(facts: list[dict], n: int = 5) -> list[str]:
        # 与存档一致：多模板 + 去同质化
        def _norm(s: str) -> str:
            return re.sub(r"\s+", "", str(s or ""))

        def _pick_bucket(indicator: str) -> str:
            s = str(indicator or "")
            if any(k in s for k in ("收入", "营收", "订单", "销售额")):
                return "revenue"
            if any(k in s for k in ("净利润", "利润", "归母")):
                return "profit"
            if any(k in s for k in ("毛利率", "毛利", "ASP", "单价", "售价")):
                return "margin"
            if any(k in s for k in ("费用率", "销售费用", "管理费用", "研发", "研发费用")):
                return "opex"
            if any(k in s for k in ("现金流", "经营现金流")):
                return "cashflow"
            if any(k in s for k in ("应收", "回款")):
                return "ar"
            if any(k in s for k in ("存货", "库存")):
                return "inv"
            if any(k in s for k in ("产能", "利用率", "开工", "稼动")):
                return "capacity"
            if any(k in s for k in ("销量", "出货", "销售量", "数量", "晶圆")):
                return "volume"
            return "general"

        def _templates(bucket: str) -> list[str]:
            m: dict[str, list[str]] = {
                "revenue": [
                    "{ind}的核心增减量来自哪里（量/价/结构/区域）？最该核对哪张表？",
                    "{ind}变化是否来自一次性确认/会计口径变化？如何用财报科目交叉验证？",
                ],
                "margin": [
                    "{ind}变动最可能由哪一项驱动（ASP/成本/产品结构）？证据链怎么串起来？",
                    "{ind}是否具备可持续性？下一季度最该盯的反向指标是什么？",
                ],
                "capacity": [
                    "{ind}提升/下滑背后是需求拉动还是供给释放？对后续毛利与费用摊薄有何含义？",
                    "{ind}对应的新增产能/扩产节奏是什么？是否会带来折旧与现金流压力？",
                ],
                "volume": [
                    "{ind}增长的主要来源是客户拉货还是渠道补库？如何从结构/价格侧验证？",
                    "{ind}与收入/毛利的联动是否一致？若不一致，最可能是哪项口径造成的？",
                ],
                "profit": [
                    "{ind}的改善/走弱主要来自经营性还是非经常性项目？最关键的拆分口径是什么？",
                    "{ind}与现金流是否匹配？若背离，优先排查哪三类科目？",
                ],
                "cashflow": [
                    "{ind}的变动由哪些营运资本科目驱动？哪些项目需要进一步核对附注与表格？",
                    "{ind}是否存在季节性/一次性回款影响？如何用应收/合同负债佐证？",
                ],
                "ar": [
                    "{ind}的变化是否提示回款压力或信用政策变化？最该核对坏账/账龄哪个口径？",
                    "{ind}与收入增速相比是否异常？如何判断是否透支未来增长？",
                ],
                "inv": [
                    "{ind}上升/下降的原因是什么（备货/滞销/在制品）？对减值风险意味着什么？",
                    "{ind}与交付/产能利用率是否一致？若不一致，该如何定位问题环节？",
                ],
                "opex": [
                    "{ind}变动最可能由投放强度还是研发投入驱动？如何评估投入产出？",
                    "{ind}是否存在费用重分类/一次性费用？用哪些科目与附注交叉核对？",
                ],
                "general": [
                    "{ind}这条披露最核心的口径是什么？用同比/环比分别会得到什么不同结论？",
                    "{ind}的关键风险与反证点是什么？下一步验证动作怎么做？",
                ],
            }
            return m.get(bucket, m["general"])

        out: list[str] = []
        used_key: set[tuple[str, str]] = set()
        used_ind_norm: set[str] = set()
        used_template: set[str] = set()
        for f in facts or []:
            if len(out) >= n:
                break
            if not isinstance(f, dict):
                continue
            ind = str(f.get("indicator") or "").strip()
            page = str(f.get("page") or "").strip()
            ev = str(f.get("evidence") or "").strip()
            if not ind or not page:
                continue
            key = (ind, page)
            if key in used_key:
                continue
            indn = _norm(ind)
            if indn in used_ind_norm:
                continue
            bucket = _pick_bucket(ind)
            cand = _templates(bucket)
            if ev and len(ev) >= 10:
                cand = [
                    "{ind}最关键的驱动是什么（量/价/结构/成本/一次性）？对经营质量意味着什么？",
                    "{ind}这条披露背后最可能对应哪个管理口径？如何用财报科目验证？",
                ] + cand
            picked = None
            for t in cand:
                if t in used_template:
                    continue
                picked = t
                used_template.add(t)
                break
            if not picked:
                picked = cand[0]
            out.append(_scrub_forbidden_weipilou(_strip_question_page_markers(picked.format(ind=ind))))
            used_key.add(key)
            used_ind_norm.add(indn)
        fallback = [
            "本期最重要的三条可核对变化分别是什么？各对应哪条披露或附注？",
            "本期业绩的核心分化点是什么？用哪三个数据点可以在财报里直接验证？",
            "有哪些口径/一次性项目可能导致“看上去变好/变差”的错觉？应如何排除？",
            "现金流与利润是否同向？若背离，优先核对哪三项营运资本科目？",
            "下一季度最大的可验证风险点是什么？需要重点核对哪些表格与附注？",
        ]
        for t in fallback:
            if len(out) >= n:
                break
            t2 = _scrub_forbidden_weipilou(_strip_question_page_markers(t))
            if t2 not in out:
                out.append(t2)
        return out[:n]

    def _fallback_report_result(pages_text: dict[int, str]) -> dict:
        full = "\n".join([str(pages_text.get(i) or "") for i in sorted(pages_text.keys())])
        short = (full or "").strip()[:900] or "未能提取到可读文本，可能是扫描件或加密 PDF。"
        pages_out = [
            "### 1. 这份财报最值得先看的三项指标是什么？\n\n核心结论：优先看营收增速、归母净利润增速、经营现金流净额，并与上年同期/上一期对比。\n",
            "### 2. 利润质量是否匹配？\n\n核心结论：利润要看“可持续性”，需要同时核对毛利、费用率、减值与现金流。\n",
            "### 3. 当前主要风险点是什么？\n\n核心结论：优先排查应收、存货、合同负债与减值风险。\n",
        ]
        return {
            "summary": f"财报解析完成（模板模式）。文本摘要：{short}",
            "sessionId": session_id,
            "questions": [{"category": "财务分析", "question": p.split('\n', 1)[0].replace('### ', '')} for p in pages_out],
            "pages": pages_out,
            "facts": [],
        }

    try:
        with _LOCK:
            sess = _SESSIONS.get(session_id)
        if not sess:
            raise RuntimeError("session not found")
        pdf_path = str(sess.get("pdf_path") or "").strip()
        if not pdf_path or not os.path.exists(pdf_path):
            raise RuntimeError("PDF 文件不存在")

        pages_map = _extract_pdf_pages(pdf_path)
        pages_map = _simplify_pages_map(pages_map)
        tagged = _build_page_tagged_text(pages_map, max_chars=20000)
        if not tagged:
            raise RuntimeError("未提取到可读 PDF 文本（可能是扫描件或加密 PDF）")

        is_research = str(analyze_type or "finance").strip().lower() == "research"

        _set_stage("理解研报" if is_research else "理解财报")
        understand_cap = _env_int("REPORT_LLM_UNDERSTAND_INPUT_CHARS", 16000)
        tagged_u = tagged[:understand_cap] if (understand_cap >= 4000 and len(tagged) > understand_cap) else tagged
        u_deadline = _env_float("REPORT_LLM_UNDERSTAND_DEADLINE_SEC", 300.0)
        if is_research:
            prompt_understand = (
                "你是资深卖方研究员。基于下方带页码标注的研报摘录生成结构化结果。\n"
                "【强制要求】所有输出内容必须使用简体中文，禁止使用繁体汉字，所有词汇均需转换为大陆通用简体表述。\n"
                "只输出 JSON 对象，键包括 summary、disclosed_facts。\n"
                "summary: 160-260 字中文，概括机构观点方向、评级变化（若有）、核心假设与主要风险；"
                "全文禁止出现「未披露」三字，可用「需对照原文核实」「摘录中未列示该口径」等表述。\n"
                "disclosed_facts: 最多 24 条，元素形如 {indicator,value,page,evidence}，page 用 Pxx，evidence 为原文极短摘录（尽量含评级/目标价/预测数字）。\n"
                "不要输出 questions。\n"
            )
        else:
            prompt_understand = (
                "你是资深卖方（A/H 股）财报分析师。基于下方带页码标注的财报摘录生成结构化结果。\n"
                "【强制要求】所有输出内容必须使用简体中文，禁止使用繁体汉字，所有词汇均需转换为大陆通用简体表述。\n"
                "只输出 JSON 对象，键包括 summary、disclosed_facts。\n"
                "summary: 140-240 字中文，必须包含：报告期/业务变化一句话 + 1 个关键驱动 + 1 个关键风险/不确定性；"
                "全文禁止出现「未披露」三字，可用「需对照年报核实」「摘录中未列示该口径」等表述。\n"
                "disclosed_facts: 最多 24 条，元素形如 {indicator,value,page,evidence}，page 用 Pxx，evidence 为原文极短摘录（尽量含数字/口径）。\n"
                "不要输出 questions。\n"
            )
        summary = ""
        facts_model = []
        try:
            content_u = _report_chat(
                [{"role": "system", "content": prompt_understand}, {"role": "user", "content": tagged_u}],
                max_tokens=2000,
                temperature=0.25,
                json_mode=True,
                timeout_sec=120,
                deadline_sec=u_deadline,
            )
            obj_u = _extract_json_object(content_u) or {}
            summary = _to_simplified(_scrub_forbidden_weipilou(str(obj_u.get("summary") or "").strip()))
            facts_model = obj_u.get("disclosed_facts") if isinstance(obj_u.get("disclosed_facts"), list) else []
        except Exception as e:
            _set_stage("理解阶段(降级)")
            summary = _to_simplified(_scrub_forbidden_weipilou(f"理解阶段超时/异常，已降级继续解析：{str(e)[:220]}"))
            facts_model = []

        facts_rule = _extract_rule_based_facts(pages_map, max_per_page=28, max_total=200)
        facts = _simplify_facts(_sanitize_facts([*(facts_model or []), *(facts_rule or [])], max_total=220))
        fact_sheet = {}
        if is_research:
            _set_stage("抽取研报事实表")
            fact_prompt = (
                "你是财报/研报事实抽取器。只依据输入文本抽取事实，不允许脑补。"
                "只输出 JSON 对象，键必须包括：company, rating_view, rating_change, "
                "target_price, valuation_method, forecast, drivers, risks, catalysts, evidence_rules。"
                "其中 forecast 为数组，元素包含 metric,value,unit,period,yoy,page,quote；"
                "drivers/risks/catalysts 为数组，元素包含 item,page,quote；"
                "缺失值用空字符串，不要省略键。"
            )
            try:
                fact_raw = _report_chat(
                    [{"role": "system", "content": fact_prompt}, {"role": "user", "content": tagged_u[:12000]}],
                    max_tokens=1800,
                    temperature=0.1,
                    json_mode=True,
                    timeout_sec=120,
                    deadline_sec=max(120.0, u_deadline),
                )
                fact_sheet = _deep_simplify_obj(_safe_json_obj(fact_raw))
            except Exception:
                fact_sheet = {}
        questions = (
            [
                "机构到底在说什么（看多/中性/看空）？投资评级是否变化（上调/下调）？",
                "收入、利润、EPS 的预测（今年/明年）是什么？目标价与估值方法（PE/DCF）是什么？与上一版相比是否调整？",
                "投资逻辑主线是什么（量/价/结构/成本/份额）？哪些假设是关键前提、最容易失效？",
                "下行风险与上行催化分别是什么？请按影响程度排序并说明触发条件。",
                "请做可信度校验：观点是否有页码证据支持？与最新财报是否一致？给出高/中/低可信度及原因。"
            ]
            if is_research
            else _build_questions_from_facts(facts, n=5)
        )
        if not summary:
            summary = (
                "研报观点解析完成：建议重点核对评级变化、预测调整与关键风险假设。"
                if is_research
                else "财报解析完成：建议优先核对盈利增速、现金流质量与费用结构变化。"
            )
        summary = _to_simplified(_scrub_forbidden_weipilou(summary))

        _set_stage("生成研报观点" if is_research else "生成解析")
        pages_out = []
        facts_ctx = json.dumps(facts[:12], ensure_ascii=False)
        fact_sheet_ctx = json.dumps(fact_sheet, ensure_ascii=False) if fact_sheet else "{}"
        a_deadline = _env_float("REPORT_LLM_ANSWER_DEADLINE_SEC", 240.0)
        for i, q in enumerate(questions):
            _set_stage(f"生成解析 Q{i+1}/{len(questions)}")
            prompt_a = (
                (
                    "你是严谨的卖方研报分析师。只依据下方研报文本与数据点作答，拒绝空泛结论。"
                    "【强制要求】所有输出内容必须使用简体中文，禁止使用繁体汉字，所有词汇均需转换为大陆通用简体表述。"
                    "输出必须含 5 段：核心结论、证据页码、风险/催化、与财报一致性、可信度分层。"
                    "每段必须提供新增信息，禁止复述上一段。"
                    "全文禁止出现「未披露」三字；证据不足时请写「需对照原文核实」或「摘录中未列示该口径」。"
                    "可信度分层必须给出：高/中/低其一 + 原因。"
                    "关键数字必须用 3-6 条列表输出，每条形如“指标｜数值｜Pxx”；行首不要写 1.2. 序号。"
                )
                if is_research
                else (
                    "你是严谨的卖方财报分析师。只依据下方财报文本与数据点作答，拒绝空泛结论。"
                    "【强制要求】所有输出内容必须使用简体中文，禁止使用繁体汉字，所有词汇均需转换为大陆通用简体表述。"
                    "输出简洁中文，格式必须含 4 段：核心结论、细节1、细节2、关键数字/概念。"
                    "每段必须提供新增信息，禁止复述上一段。"
                    "全文禁止出现「未披露」三字；证据不足时请写「需对照年报核实」或「摘录中未列示该口径」。"
                    "可引用 Pxx 页码辅助定位；勿在【问题】行或用户可见标题里写页码。"
                    "细节1：拆解驱动（量/价/结构/成本/一次性）至少 1 条，并给证据页码。"
                    "细节2：给出反证/风险与验证动作（需要再核对的表或指标），并给线索页码。"
                    "关键数字/概念：必须用 3-6 条列表输出，每条形如“指标｜数值｜Pxx”，不要写成一段话；"
                    "每条以 “- ” 开头，行首不要写 1. 2. 等序号。"
                )
            )
            q_show = _to_simplified(_scrub_forbidden_weipilou(_strip_question_page_markers(q)))
            user_a = (
                f"【问题】{q_show}\n\n【可用数据点】{facts_ctx}\n\n"
                f"【事实表】{fact_sheet_ctx}\n\n【财报文本】\n{tagged[:6000]}"
                if is_research
                else f"【问题】{q_show}\n\n【可用数据点】{facts_ctx}\n\n【财报文本】\n{tagged[:6000]}"
            )
            ans = _report_chat(
                [{"role": "system", "content": prompt_a}, {"role": "user", "content": user_a}],
                max_tokens=900,
                temperature=0.25,
                json_mode=False,
                timeout_sec=120,
                deadline_sec=a_deadline,
            )
            ans = _to_simplified(_scrub_forbidden_weipilou(str(ans or "").strip() or "本题暂无可用解析，请稍后重试。"))
            pages_out.append(f"### {i+1}. {q_show}\n\n{ans}")
            time.sleep(_env_float("REPORT_LLM_PACING_SEC", 0.65))

        audit_result = {}
        if is_research:
            _set_stage("审稿校验")
            audit_prompt = (
                "你是审稿纠错器。只依据【事实表】和【回答草稿】检查错误。"
                "检查：数字/单位/同比/页码是否一致；是否出现繁体字；是否有无证据推断。"
                "输出 JSON：issues(数组，每项含type,detail,severity)，"
                "corrected_summary(字符串)，corrected_pages(数组字符串)。"
                "若草稿无明显错误，issues 返回空数组，corrected_* 保持原文。"
            )
            draft_summary = summary
            draft_pages = pages_out
            try:
                audit_raw = _report_chat(
                    [
                        {"role": "system", "content": audit_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"【事实表】{fact_sheet_ctx}\n\n"
                                f"【回答草稿-摘要】{draft_summary}\n\n"
                                f"【回答草稿-逐题】{json.dumps(draft_pages, ensure_ascii=False)}"
                            ),
                        },
                    ],
                    max_tokens=1400,
                    temperature=0.0,
                    json_mode=True,
                    timeout_sec=120,
                    deadline_sec=max(120.0, a_deadline),
                )
                audit_result = _deep_simplify_obj(_safe_json_obj(audit_raw))
                corrected_summary = str(audit_result.get("corrected_summary") or "").strip()
                corrected_pages = audit_result.get("corrected_pages")
                if corrected_summary and len(corrected_summary) >= 30:
                    summary = _to_simplified(_scrub_forbidden_weipilou(corrected_summary))
                if isinstance(corrected_pages, list) and corrected_pages:
                    candidate_pages = [
                        _to_simplified(_scrub_forbidden_weipilou(str(x or "")))
                        for x in corrected_pages
                    ]
                    valid_count = sum(1 for x in candidate_pages if _looks_like_valid_page_md(x))
                    # 只有当审稿返回页数和原题数一致、且大部分内容看起来是完整答案时才覆盖。
                    if len(candidate_pages) == len(pages_out) and valid_count >= max(1, len(pages_out) - 1):
                        pages_out = candidate_pages
            except Exception:
                audit_result = {}

        result = {
            "summary": summary,
            "sessionId": session_id,
            "analyzeType": "research" if is_research else "finance",
            "questions": [
                {
                    "category": "研报观点" if is_research else "财务分析",
                    "question": _to_simplified(_scrub_forbidden_weipilou(_strip_question_page_markers(q))),
                }
                for q in questions
            ],
            "pages": pages_out,
            "facts": facts[:80] if isinstance(facts, list) else [],
        }
        if is_research:
            # 研报专用结构化输出：便于前端按模块渲染，不与财报同构文案混用。
            blocks = [
                "viewpoint_conclusion",
                "forecast_valuation",
                "logic_hypothesis",
                "risk_catalyst",
                "credibility_check",
            ]
            research_blocks = {}
            for i, key in enumerate(blocks):
                q_txt = ""
                if i < len(result.get("questions") or []):
                    q_obj = (result.get("questions") or [])[i]
                    if isinstance(q_obj, dict):
                        q_txt = str(q_obj.get("question") or "")
                a_txt = ""
                if i < len(pages_out):
                    a_txt = str(pages_out[i] or "")
                research_blocks[key] = {"question": q_txt, "answer": a_txt}
            result["researchBlocks"] = research_blocks
            result["researchSchemaVersion"] = "v1"
            result["factSheet"] = fact_sheet if isinstance(fact_sheet, dict) else {}
            result["qualityAudit"] = audit_result if isinstance(audit_result, dict) else {}
            # 研报模式再做一次全量繁转简兜底，避免任何字段漏转。
            result = _deep_simplify_obj(result)
        with _LOCK:
            if session_id in _SESSIONS:
                _SESSIONS[session_id]["facts"] = result.get("facts") or []
                _SESSIONS[session_id]["questions"] = result.get("questions") or []
                _SESSIONS[session_id]["pages"] = result.get("pages") or []
                _SESSIONS[session_id]["tagged"] = tagged
                _SESSIONS[session_id]["pages_map"] = pages_map

        with _LOCK:
            _TASKS[task_id]["status"] = "succeeded"
            _TASKS[task_id]["stage"] = "完成"
            _TASKS[task_id]["result"] = result
    except Exception as e:
        _set_failed(str(e))

