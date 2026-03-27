"""
PDF 解析层 V2：使用 Docling（优先）+ pypdf（兜底）提取 PDF 文本，生成结构化内容
"""

from __future__ import annotations

import os
from typing import Any

try:
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except Exception:
    DOCLING_AVAILABLE = False

try:
    import pypdf

    PYPDF_AVAILABLE = True
except Exception:
    PYPDF_AVAILABLE = False


class PDFParser:
    """PDF 解析器，将 PDF 转换为结构化文本"""

    def __init__(self) -> None:
        self.use_docling = False
        self.docling_converter = None

        disable_docling = (os.getenv("ANALYSTGPT_DISABLE_DOCLING", "0") or "").lower() in ("1", "true", "yes")
        if DOCLING_AVAILABLE and not disable_docling:
            try:
                self.docling_converter = DocumentConverter()
                self.use_docling = True
            except Exception:
                pass

        if not self.use_docling and not PYPDF_AVAILABLE:
            raise RuntimeError("请安装 docling 或 pypdf 作为 PDF 解析后端")

    def parse_pdf(self, pdf_path: str) -> dict[str, Any]:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
        if self.use_docling and self.docling_converter is not None:
            try:
                return self._parse_with_docling(pdf_path)
            except Exception:
                pass
        return self._parse_with_pypdf(pdf_path)

    def _parse_with_docling(self, pdf_path: str) -> dict[str, Any]:
        result = self.docling_converter.convert(pdf_path)
        if hasattr(result, "document") and hasattr(result.document, "export_to_markdown"):
            md = result.document.export_to_markdown()
            pages = self._split_markdown_by_pages(md, result)
            return {
                "text": md,
                "markdown": md,
                "tables": self._extract_tables_from_markdown(md),
                "pages": pages,
                "total_pages": len(pages) or 1,
            }
        return self._parse_docling_manually(result)

    def _parse_docling_manually(self, result) -> dict[str, Any]:
        text_chunks: list[str] = []
        pages: dict[int, str] = {}
        try:
            if hasattr(result, "document") and hasattr(result.document, "iterate_items"):
                for item in result.document.iterate_items():
                    if hasattr(item, "text") and item.text:
                        text_chunks.append(item.text)
        except Exception:
            pass

        if hasattr(result, "document") and hasattr(result.document, "pages"):
            for idx, page in enumerate(result.document.pages, 1):
                page_text: list[str] = []
                if hasattr(page, "items"):
                    for item in page.items:
                        if hasattr(item, "text") and item.text:
                            page_text.append(item.text)
                pages[idx] = "\n".join(page_text)

        full_text = "\n\n".join(text_chunks) if text_chunks else "\n\n".join(pages.values())
        return {
            "text": full_text,
            "markdown": full_text,
            "tables": [],
            "pages": pages or {1: full_text},
            "total_pages": len(pages) or 1,
        }

    def _parse_with_pypdf(self, pdf_path: str) -> dict[str, Any]:
        if not PYPDF_AVAILABLE:
            raise RuntimeError("pypdf 未安装，且 Docling 不可用")
        pages: dict[int, str] = {}
        text_chunks: list[str] = []
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for idx, page in enumerate(reader.pages, 1):
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                pages[idx] = txt
                if txt.strip():
                    text_chunks.append(txt)

        full_text = "\n\n".join(text_chunks) if text_chunks else "\n\n".join(pages.values())
        return {
            "text": full_text,
            "markdown": full_text,
            "tables": [],
            "pages": pages or {1: full_text},
            "total_pages": len(pages) or 1,
        }

    def _split_markdown_by_pages(self, md: str, result) -> dict[int, str]:
        pages: dict[int, str] = {}
        try:
            if hasattr(result, "document") and hasattr(result.document, "pages"):
                n = len(result.document.pages)
                if n > 0:
                    step = max(len(md) // n, 1)
                    for i in range(n):
                        start = i * step
                        end = (i + 1) * step if i < n - 1 else len(md)
                        pages[i + 1] = md[start:end]
        except Exception:
            pages[1] = md
        return pages

    def _extract_tables_from_markdown(self, md: str) -> list[str]:
        tables: list[str] = []
        lines = md.split("\n")
        cur: list[str] = []
        in_table = False
        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                in_table = True
                cur.append(line)
            elif in_table:
                if cur:
                    tables.append("\n".join(cur))
                    cur = []
                in_table = False
        if cur:
            tables.append("\n".join(cur))
        return tables

