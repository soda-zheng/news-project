import os
import json
import requests
from utils.helpers import _strip_markdown_json_fence, _extract_json_object


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn",
    }
)


def _get_llm_env():
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
    content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content")
    if not content:
        raise RuntimeError(f"LLM empty content: {str(data)[:200]}")
    return str(content)


def _llm_repair_insight_json(bad_text: str) -> dict | None:
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
