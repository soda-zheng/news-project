from __future__ import annotations

import time
import requests

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        # SEC 建议提供可联系的 UA 标识，避免被限流。
        "User-Agent": "finance-news-project/1.0 (research use; contact: student-project@example.com)",
        "Accept": "application/json,text/plain,*/*",
    }
)

_TICKER_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_TICKER_CACHE = {"ts": 0.0, "map": {}}


def _load_ticker_map() -> dict[str, dict]:
    now = time.time()
    if _TICKER_CACHE["map"] and (now - float(_TICKER_CACHE["ts"] or 0)) < 12 * 3600:
        return _TICKER_CACHE["map"]
    rr = _SESSION.get(_TICKER_URL, timeout=20)
    rr.raise_for_status()
    data = rr.json() if rr.content else {}
    rows = data.get("data") or []
    out = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 3:
            continue
        ticker = str(row[2] or "").strip().upper()
        cik = str(row[0] or "").strip()
        name = str(row[1] or "").strip()
        if ticker and cik:
            out[ticker] = {"cik": cik, "name": name}
    _TICKER_CACHE["ts"] = now
    _TICKER_CACHE["map"] = out
    return out


def _to_form_set(report_type: str) -> set[str]:
    t = str(report_type or "all").strip().lower()
    if t == "annual":
        return {"10-K", "20-F", "40-F"}
    if t in ("q1", "half", "q3"):
        return {"10-Q", "6-K"}
    return {"10-K", "20-F", "40-F", "10-Q", "6-K"}


def fetch_us_reports(
    *,
    ticker: str = "",
    report_type: str = "all",
    page_num: int = 1,
    page_size: int = 20,
) -> dict:
    tk = str(ticker or "").strip().upper()
    if not tk:
        return {"pageNum": 1, "pageSize": 20, "totalRecordNum": 0, "items": [], "source": "sec-submissions"}
    tmap = _load_ticker_map()
    meta = tmap.get(tk)
    if not meta:
        return {"pageNum": 1, "pageSize": 20, "totalRecordNum": 0, "items": [], "source": "sec-submissions"}
    cik = str(meta.get("cik") or "").strip().zfill(10)
    company_name = str(meta.get("name") or tk)

    rr = _SESSION.get(_SUBMISSIONS_URL.format(cik=cik), timeout=20)
    rr.raise_for_status()
    payload = rr.json() if rr.content else {}
    recent = ((payload.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []

    allowed_forms = _to_form_set(report_type)
    rows = []
    total = min(len(forms), len(dates), len(accs), len(docs))
    for i in range(total):
        form = str(forms[i] or "").strip().upper()
        if form not in allowed_forms:
            continue
        filing_date = str(dates[i] or "").strip()
        accession = str(accs[i] or "").strip()
        primary_doc = str(docs[i] or "").strip()
        if not accession or not primary_doc:
            continue
        acc_no_dash = accession.replace("-", "")
        filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_no_dash}/{primary_doc}"
        lower_doc = primary_doc.lower()
        pdf_url = filing_url if lower_doc.endswith(".pdf") else ""
        period_label = "年报" if form in ("10-K", "20-F", "40-F") else "季报"
        rows.append(
            {
                "id": f"{tk}-{accession}",
                "title": f"{form} {company_name} {filing_date}",
                "publish_time": f"{filing_date} 00:00:00" if filing_date else "",
                "symbol": tk,
                "name": company_name,
                "pdf_url": pdf_url,
                "doc_url": filing_url,
                "doc_type": primary_doc.rsplit(".", 1)[-1].lower() if "." in primary_doc else "html",
                "adjunct_size": "",
                "periodLabel": period_label,
                "market": "US",
                "form_type": form,
            }
        )

    pnum = max(1, int(page_num or 1))
    psz = max(1, min(50, int(page_size or 20)))
    start = (pnum - 1) * psz
    end = start + psz
    items = rows[start:end]
    return {
        "pageNum": pnum,
        "pageSize": psz,
        "totalRecordNum": len(rows),
        "items": items,
        "source": "sec-submissions",
    }
