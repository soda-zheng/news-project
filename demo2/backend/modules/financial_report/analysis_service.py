from __future__ import annotations

import concurrent.futures
import os
import re
import traceback
from typing import Any

from .ai_analyzer_v2 import AIAnalyzer
from .pdf_parser_v2 import PDFParser
from .session_store import InMemoryStore


def _extract_rule_based_facts(parsed: dict[str, Any], *, max_per_page: int = 60, max_total: int = 240) -> list[dict]:
    pages = parsed.get("pages") or {}
    if not isinstance(pages, dict) or not pages:
        return []

    pat_colon = re.compile(
        r"^\s*([^\d]{2,50}?)[：:]\s*([+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|pct|bp|bps|亿元|万|千|百万|亿|港元|人民币|美元|HKD|USD|元|片|座|项目|人|次|GWh|MW|kWh))?(?:\s*[-~–—至]\s*[+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|pct|bp|bps|亿元|万|千|百万|亿|港元|人民币|美元|HKD|USD|元))?)?)\s*$"
    )
    pat_pipe = re.compile(r"^\s*([^｜]{2,60}?)\s*｜\s*([+-]?\d[\d,]*(?:\.\d+)?[^｜]{0,18})\s*(?:｜|$)")
    pat_space = re.compile(
        r"^\s*([^\d]{2,60}?)\s{1,6}([+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|pct|bp|bps|亿元|万|千|百万|亿|港元|人民币|美元|HKD|USD|元|片|座|项目|人|次|GWh|MW|kWh))?(?:\s*[-~–—至]\s*[+-]?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|pct|bp|bps|亿元|万|千|百万|亿|港元|人民币|美元|HKD|USD|元))?)?)\s*$"
    )

    def clean_indicator(s: str) -> str:
        s = re.sub(r"[\(\)（）\[\]【】]", "", s or "").strip()
        s = re.sub(r"\s{2,}", " ", s)
        s = re.sub(r"(单位|注释|说明)$", "", s).strip()
        return s[:60]

    section_pat = re.compile(r"^(第?\s*[一二三四五六七八九十\d]{1,3})[、\.\．:：]\s*$")
    section_prefix_pat = re.compile(r"^(第?\s*[一二三四五六七八九十\d]{1,3})[、\.\．:：]\s*")
    low_value = ["目录", "注：", "注:", "网址", "电话", "地址", "邮箱", "董事", "监事", "审计", "披露"]

    facts: list[dict] = []
    for p, text in pages.items():
        try:
            pi = int(p)
        except Exception:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        got = 0
        for raw_line in text.splitlines():
            line = (raw_line or "").strip()
            if not line:
                continue
            if any(x in line for x in low_value):
                continue
            if len(line) > 180:
                continue
            if not re.search(r"\d", line):
                continue
            m = pat_colon.match(line) or pat_pipe.match(line) or pat_space.match(line)
            if not m:
                continue
            ind = clean_indicator(m.group(1))
            val = (m.group(2) or "").strip()
            if not ind or not val:
                continue
            if section_pat.match(ind) or section_prefix_pat.match(ind):
                continue
            if not re.search(r"[\u4e00-\u9fa5A-Za-z]", ind):
                continue
            facts.append({"indicator": ind, "value": val[:80], "page": f"P{pi}", "evidence": line[:160]})
            got += 1
            if got >= max_per_page:
                break
        if len(facts) >= max_total:
            break

    seen = set()
    dedup: list[dict] = []
    for f in facts:
        key = (f.get("indicator", ""), f.get("value", ""), f.get("page", ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(f)
    return dedup[:max_total]


def _question_from_choice(choice: str) -> str:
    if not choice:
        return ""
    parts = [p.strip() for p in str(choice).split("｜") if p.strip()]
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


def _fact_from_choice(choice: str, facts: list[dict]) -> dict[str, str] | None:
    if not choice:
        return None
    parts = [p.strip() for p in str(choice).split("｜") if p.strip()]
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
        if (f.get("indicator") or "").strip() != ind:
            continue
        fp = (f.get("page") or "").strip()
        if page and fp and fp != page:
            continue
        best["value"] = (f.get("value") or best["value"] or "").strip()
        best["page"] = (fp or best["page"] or "").strip()
        break
    return best


class AnalysisService:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store
        self.pdf_parser = PDFParser()
        # 默认关闭 Docling（与原项目一致，优先稳定和速度）
        if os.getenv("ANALYSTGPT_USE_DOCLING", "0").lower() not in ("1", "true", "yes"):
            self.pdf_parser.use_docling = False
            self.pdf_parser.docling_converter = None

    def analyze_session(self, session_id: str, stage_cb) -> dict[str, Any]:
        s = self.store.get_session(session_id)
        try:
            stage_cb("解析 PDF")
            parsed = self.pdf_parser.parse_pdf(s.pdf_path)
            s.parsed = parsed
            s.extracted_text = str(parsed.get("text") or "")

            analyzer = AIAnalyzer()
            s.analyzer = analyzer

            stage_cb("理解财报")
            understanding = analyzer.understand_financial_report(parsed)
            s.understanding = understanding

            stage_cb("生成问题")
            questions = analyzer.generate_questions(parsed, understanding)
            s.questions = questions or []
            if not s.questions:
                raise RuntimeError("未能生成问题（请检查 PDF 解析是否有效、或 API 配置是否可用）")

            facts = []
            try:
                facts = getattr(analyzer, "disclosed_facts", []) if analyzer else []
            except Exception:
                facts = []
            if not facts and isinstance(understanding, dict):
                facts = understanding.get("disclosed_facts") or []
            if not facts:
                facts = _extract_rule_based_facts(parsed)
            # 如果 LLM 抽取到的 disclosed_facts 太少，则补充规则抽取（不改变 pinned/分析逻辑）。
            try:
                min_facts = int(os.getenv("FIN_FACTS_MIN", "60"))
            except Exception:
                min_facts = 60
            if isinstance(facts, list) and len(facts) < min_facts:
                rule_facts = _extract_rule_based_facts(parsed)
                if isinstance(rule_facts, list) and rule_facts:
                    seen = set()
                    merged: list[dict[str, Any]] = []
                    for f in (facts or []) + rule_facts:
                        if not isinstance(f, dict):
                            continue
                        key = (
                            (f.get("indicator") or "").strip(),
                            (f.get("value") or "").strip(),
                            (f.get("page") or "").strip(),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.append(f)
                    facts = merged
            s.facts = facts or []

            stage_cb("生成解析")
            pages: list[str] = [""] * len(s.questions)

            def one(i_q):
                i, q = i_q
                stage_cb(f"生成解析 Q{i+1}/{len(s.questions)}")
                analysis = analyzer.generate_analysis(q["question"], parsed, understanding)
                ans = (analysis.get("answer") or "").strip()
                raw_q = (analysis.get("question") or q["question"] or "").strip()
                display_q = re.sub(r"\s*[（(]P\d+[)）]\s*$", "", raw_q).strip()
                if not ans:
                    ans = "❌ 本题解析为空（模型返回空内容或网络/限流导致）。建议稍后重试。"
                return i, f"### {i+1}. {display_q}\n\n{ans}"

            max_workers = max(1, min(5, int(os.getenv("FIN_REPORT_MAX_WORKERS", "2"))))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = [ex.submit(one, (i, q)) for i, q in enumerate(s.questions)]
                for fut in concurrent.futures.as_completed(futs):
                    i, md = fut.result()
                    pages[i] = md

            s.pages = pages
            return {"pages": pages, "facts": s.facts, "questions": s.questions}
        except Exception as e:
            tb = traceback.format_exc(limit=2)
            raise RuntimeError(f"{e}\n{tb}") from e

    def regen_page(
        self,
        session_id: str,
        page_index: int,
        custom_question: str | None = None,
        choice: str | None = None,
    ) -> dict[str, Any]:
        s = self.store.get_session(session_id)
        if not s.pages or page_index < 0 or page_index >= len(s.pages):
            raise RuntimeError("请先完成分析生成 5 问 5 解。")
        if not s.analyzer or not s.parsed or not s.understanding:
            raise RuntimeError("会话缺少分析上下文，请重新上传并开始分析。")

        q = (custom_question or "").strip()
        pinned_fact = None
        if not q and choice:
            q = _question_from_choice(choice)
        if choice:
            pinned_fact = _fact_from_choice(choice, s.facts or [])
        if not q:
            md = s.pages[page_index] or ""
            m = re.search(r"^###\s+\d+\.\s+(.*)$", md, flags=re.M)
            q = (m.group(1).strip() if m else "").strip()
        if not q:
            q = "请基于财报已披露数据，追问本期业绩的核心分化点与可持续性（P1）。"

        analyzer: AIAnalyzer = s.analyzer
        analysis = analyzer.generate_analysis(q, s.parsed, s.understanding, pinned_fact=pinned_fact)
        raw_q = (analysis.get("question") or q).strip()
        display_q = re.sub(r"\s*[（(]P\d+[)）]\s*$", "", raw_q).strip()
        new_md = f"### {page_index + 1}. {display_q}\n\n{(analysis.get('answer') or '').strip()}"
        s.pages[page_index] = new_md
        return {"pages": s.pages, "pageIndex": page_index}
