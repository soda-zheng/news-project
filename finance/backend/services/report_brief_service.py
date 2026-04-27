from __future__ import annotations

from services.llm_service import _openai_compat_chat, _get_llm_env


def _llm_ready() -> bool:
    env = _get_llm_env()
    return bool(env.get("api_base") and env.get("model") and env.get("api_key"))


def generate_report_brief(
    *,
    company: str,
    symbol: str,
    title: str,
    publish_time: str,
    pdf_url: str,
    period_label: str = "",
) -> str:
    company = str(company or "").strip()
    symbol = str(symbol or "").strip()
    title = str(title or "").strip()
    publish_time = str(publish_time or "").strip()
    pdf_url = str(pdf_url or "").strip()
    period_label = str(period_label or "").strip()

    if not company or not title:
        raise RuntimeError("缺少财报关键字段（company/title）")

    if not _llm_ready():
        return (
            f"核心结论：\n{company}（{symbol}）{period_label or '定期报告'}已披露，建议先从管理层讨论与分析、三大报表及附注入手。\n\n"
            "细节1：\n优先核对收入与利润增速、毛利率变化、费用率变化及其原因，确认增长质量。\n\n"
            "细节2：\n重点核对应收、存货、经营现金流与利润匹配度，识别潜在兑现风险。\n\n"
            "关键数字/概念：\n"
            f"- 报告标题：{title}\n"
            f"- 披露时间：{publish_time or '未知'}\n"
            f"- 原文链接：{pdf_url or '未提供'}\n"
        )

    prompt = (
        "你是一位 sell-side 财报分析师。请按下面固定结构输出中文解读，不要输出Markdown代码块。\n"
        "输出必须包含以下4个模块（标题必须完全一致）：\n"
        "核心结论：\n"
        "细节1：\n"
        "细节2：\n"
        "关键数字/概念：\n"
        "要求：\n"
        "1) 仅基于给定公告元信息给出“阅读框架与风险关注点”，不要编造具体财务数值；\n"
        "2) 在关键数字/概念里明确列出公告标题、发布时间、报告期别、原文链接；\n"
        "3) 语言简洁、可执行，便于投资者快速阅读。\n\n"
        f"公司：{company}（{symbol}）\n"
        f"报告期别：{period_label or '未标注'}\n"
        f"公告标题：{title}\n"
        f"发布时间：{publish_time or '未知'}\n"
        f"原文链接：{pdf_url or '未提供'}\n"
    )

    out = _openai_compat_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=900,
        temperature=0.2,
        json_mode=False,
        timeout_sec=70,
    )
    return str(out or "").strip()

