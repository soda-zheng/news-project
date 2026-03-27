"""
AI 分析层 V2：使用 GLM/OpenAI API 完成财报理解、提问生成和带溯源解析
"""

from __future__ import annotations

from typing import Any, Dict, List
import json
import re
import time

import requests

from .api_config import DEFAULT_API_TYPE, GLM_API_BASE, GLM_API_KEY, GLM_MODEL


class AIAnalyzer:
    def __init__(
        self,
        api_type: str = DEFAULT_API_TYPE,
        api_key: str | None = None,
        api_base: str | None = None,
        industry: str = "其他",
        business_boundary: Dict[str, Any] | None = None,
        data_indicators: List[str] | None = None,
    ) -> None:
        # 财报分析模块硬锁定仅使用 GLM，避免误走其它 LLM 通道（如 DashScope 的 LLM_*）。
        self.api_type = "glm"
        self.api_key = (api_key or GLM_API_KEY).strip() or None
        self.api_base = (api_base or GLM_API_BASE).strip()
        self.model = GLM_MODEL

        self.industry = industry
        self.business_boundary = business_boundary or {}
        self.data_indicators = data_indicators or []
        self.disclosed_facts: List[Dict[str, str]] = []

    def _call_api(self, messages: List[Dict[str, str]], *, max_tokens: int) -> str:
        if not self.api_key:
            raise ValueError("API Key 未配置")
        return self._call_glm(messages, max_tokens=max_tokens)

    def _call_glm(self, messages: List[Dict[str, str]], *, max_tokens: int) -> str:
        url = f"{self.api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1, "top_p": 0.8}

        last_err: Exception | None = None
        for attempt in range(5):
            try:
                resp = requests.post(url, json=data, headers=headers, timeout=(10, 120))
                if resp.status_code == 429:
                    time.sleep(min(16, 2 ** (attempt + 1)))
                    last_err = requests.HTTPError(resp.text)
                    continue
                resp.raise_for_status()
                j = resp.json()
                content = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                if not content:
                    reasoning = (((j.get("choices") or [{}])[0].get("message") or {}).get("reasoning_content") or "").strip()
                    if reasoning:
                        return reasoning
                    raise RuntimeError("模型返回空 content")
                return content
            except Exception as e:
                last_err = e
                time.sleep(min(16, 2 ** (attempt + 1)))
        raise RuntimeError(f"GLM 接口调用失败：{last_err}")

    def _call_openai(self, messages: List[Dict[str, str]], *, max_tokens: int) -> str:
        url = f"{self.api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        data = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1, "top_p": 0.8}

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=data, headers=headers, timeout=60)
                if resp.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    last_err = requests.HTTPError(resp.text)
                    continue
                resp.raise_for_status()
                j = resp.json()
                content = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
                if not content:
                    raise RuntimeError("模型返回空 content")
                return content
            except Exception as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"OpenAI 接口调用失败：{last_err}")

    def _build_page_tagged_content(self, parsed: Dict[str, Any], *, max_chars: int) -> str:
        pages = parsed.get("pages") or {}
        if not isinstance(pages, dict) or not pages:
            md = (parsed.get("markdown") or parsed.get("text") or "").strip()
            return f"[P1]\n{md[:max_chars]}" if md else "[P1]\n（PDF 文本提取为空）"
        pieces: list[str] = []
        cur = 0
        for p in sorted(pages.keys()):
            try:
                pi = int(p)
            except Exception:
                continue
            txt = (pages.get(p) or "").strip()
            if not txt:
                continue
            chunk = f"[P{pi}]\n{txt}\n"
            if cur + len(chunk) > max_chars:
                chunk = chunk[: max(0, max_chars - cur)]
            if not chunk:
                break
            pieces.append(chunk)
            cur += len(chunk)
            if cur >= max_chars:
                break
        return "\n\n".join(pieces) if pieces else "[P1]\n（PDF 文本提取为空）"

    def _extract_first_json_object(self, text: str) -> Dict[str, Any] | None:
        if not text:
            return None
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start : i + 1]
                    try:
                        return json.loads(blob)
                    except Exception:
                        return None
        return None

    def understand_financial_report(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        content = self._build_page_tagged_content(parsed, max_chars=6500)
        prompt = f"""你是一位专业的 sell-side 财报分析师。请先读懂财报并输出 JSON+中文总结。

【财报原文（带页码标签）】
{content}

先输出一个合法 JSON（不要代码块）：
{{
  "company_name": "",
  "industry": "从['半导体','动力电池','金融服务','消费电子','其他']中选",
  "core_business": ["..."],
  "non_business_keywords": ["..."],
  "disclosed_indicators": [
    {{"indicator":"指标名","value":"具体数值或描述","page":"P3","evidence":"原文摘录"}}
  ]
}}
再输出 150-250 字中文总结（尽量带页码 Pxx）。
"""
        text = self._call_api([{"role": "user", "content": prompt}], max_tokens=1400)
        j = self._extract_first_json_object(text) or {}

        industry = (j.get("industry") if isinstance(j, dict) else None) or "其他"
        self.industry = str(industry).strip() or self.industry

        disclosed = j.get("disclosed_indicators") if isinstance(j, dict) else None
        facts: List[Dict[str, str]] = []
        indicators: List[str] = []
        if isinstance(disclosed, list):
            for it in disclosed:
                if not isinstance(it, dict):
                    continue
                ind = str(it.get("indicator") or "").strip()
                if ind:
                    indicators.append(ind)
                page = str(it.get("page") or "").strip()
                val = str(it.get("value") or "").strip()
                ev = str(it.get("evidence") or "").strip()
                if ind and re.fullmatch(r"P\d+", page) and (val or ev):
                    facts.append({"indicator": ind, "value": val, "page": page, "evidence": ev})

        self.data_indicators = list(dict.fromkeys(indicators))
        self.disclosed_facts = facts[:260]
        self.business_boundary = {
            "核心业务": "、".join([x for x in (j.get("core_business") or []) if isinstance(x, str)]) if isinstance(j, dict) else "",
            "非业务范围": "",
            "非业务关键词": j.get("non_business_keywords") if isinstance(j, dict) else [],
        }
        return {
            "understanding": text,
            "industry": self.industry,
            "business_boundary": self.business_boundary,
            "data_indicators": self.data_indicators,
            "disclosed_facts": self.disclosed_facts,
        }

    def generate_questions(self, parsed: Dict[str, Any], understanding: Dict[str, Any]) -> List[Dict[str, str]]:
        facts = understanding.get("disclosed_facts") or self.disclosed_facts or []
        facts = [f for f in facts if isinstance(f, dict) and (f.get("indicator") or "").strip()]
        facts_ctx = "\n".join(
            [f"- F{i+1}: {(f.get('indicator') or '').strip()}：{(f.get('value') or '').strip()}（{(f.get('page') or '').strip()}）" for i, f in enumerate(facts[:14])]
        )
        prompt = f"""你是投研分析师。仅根据【已披露数据点】出 5 个高价值问题，避免套话、避免“请结合财报说明…影响”模板。
每题必须包含具体指标/数值或对比口径，并在末尾标注对应页码（Pxx）。
只输出 1-5 五行。

【已披露数据点】
{facts_ctx}
"""
        text = self._call_api([{"role": "user", "content": prompt}], max_tokens=600)
        qs: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^(\d+)\.\s*(.*)$", line)
            q = (m.group(2) if m else line).strip()
            if q:
                qs.append(q)
        qs = qs[:5]
        return [{"category": "财务分析", "question": q} for q in qs]

    def generate_analysis(
        self,
        question: str,
        parsed: Dict[str, Any],
        understanding: Dict[str, Any],
        pinned_fact: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        content = self._build_page_tagged_content(parsed, max_chars=5500)
        facts = understanding.get("disclosed_facts") or self.disclosed_facts or []
        facts_ctx = "\n".join(
            [f"- {(f.get('indicator') or '').strip()}：{(f.get('value') or '').strip()}（{(f.get('page') or '').strip()}）" for f in facts[:14] if isinstance(f, dict)]
        )
        pinned = ""
        if pinned_fact and isinstance(pinned_fact, dict) and (pinned_fact.get("indicator") or "").strip():
            pinned = f"\n【强约束】必须围绕数据点：{pinned_fact.get('indicator')}（{pinned_fact.get('page','')}）\n"
        prompt = f"""你是一位严谨的卖方分析师。基于财报原文与已披露数据点回答问题，必须给出溯源页码。
输出严格按 4 个模块（标题必须一致）：
核心结论：
一句话结论（禁止出现页码/来源）。要求：不要以“：”开头。
细节1：
...（来源：财报 Pxx）。要求：不要以“：”开头。
细节2：
...（来源：财报 Pxx）。要求：不要以“：”开头。
关键数字/概念：
- ...（来源：财报 Pxx）
- ...（来源：财报 Pxx）

【财报原文（带页码标签）】
{content}

【已披露数据点】
{facts_ctx}
{pinned}

【问题】
{question}
"""
        answer = self._call_api([{"role": "user", "content": prompt}], max_tokens=800)
        return {"question": question, "answer": answer, "sources": []}

