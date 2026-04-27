from __future__ import annotations

import time
import requests

_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
_PDF_BASE = "https://static.cninfo.com.cn/"
_SUGGEST_URL = "https://www.cninfo.com.cn/new/information/getSearchSecurities"

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.cninfo.com.cn/new/disclosure",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
)

_CATEGORY_MAP = {
    "all": "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh",
    "annual": "category_ndbg_szsh",
    "half": "category_bndbg_szsh",
    "q1": "category_yjdbg_szsh",
    "q3": "category_sjdbg_szsh",
}

_HK_KEYWORD_BY_TYPE = {
    "annual": "年度业绩",
    "half": "中期业绩",
    "q1": "第一季度业绩",
    "q3": "第三季度业绩",
}

_TITLE_KEYS_ALL = (
    "年报", "年報", "年度报告", "年度報告",
    "半年报", "半年報", "半年度报告", "半年度報告", "中报", "中報",
    "一季度报告", "一季度報告", "一季报", "一季報", "第一季度报告", "第一季度報告",
    "三季度报告", "三季度報告", "三季报", "三季報", "第三季度报告", "第三季度報告",
    "年度业绩", "年度業績", "年度业绩公告", "年度業績公告",
    "中期业绩", "中期業績", "中期业绩公告", "中期業績公告",
    "第一季度业绩", "第一季度業績", "第一季度业绩公告", "第一季度業績公告",
    "第三季度业绩", "第三季度業績", "第三季度业绩公告", "第三季度業績公告",
    "业绩公告", "業績公告",
    "annual report", "interim report", "quarterly report",
)
_TITLE_KEYS_BY_TYPE = {
    "annual": (
        "年报", "年報", "年度报告", "年度報告",
        "年度业绩", "年度業績", "年度业绩公告", "年度業績公告",
        "annual report",
    ),
    "half": (
        "半年报", "半年報", "半年度报告", "半年度報告", "中报", "中報",
        "中期业绩", "中期業績", "中期业绩公告", "中期業績公告",
        "interim report",
    ),
    "q1": (
        "一季度报告", "一季度報告", "一季报", "一季報", "第一季度报告", "第一季度報告",
        "第一季度业绩", "第一季度業績", "第一季度业绩公告", "第一季度業績公告",
    ),
    "q3": (
        "三季度报告", "三季度報告", "三季报", "三季報", "第三季度报告", "第三季度報告",
        "第三季度业绩", "第三季度業績", "第三季度业绩公告", "第三季度業績公告",
    ),
}


def _to_time_str(v) -> str:
    try:
        if v is None:
            return ""
        n = int(float(v))
        if n > 10_000_000_000:
            n //= 1000
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(n))
    except Exception:
        s = str(v or "").strip()
        return s[:19] if s else ""


def fetch_cninfo_reports(
    *,
    stock: str = "",
    searchkey: str = "",
    report_type: str = "all",
    page_num: int = 1,
    page_size: int = 20,
    se_date: str = "",
    column: str = "",
) -> dict:
    stock = str(stock or "").strip()
    searchkey = str(searchkey or "").strip()
    report_type = str(report_type or "all").strip().lower()
    col = str(column or "").strip().lower()
    # 巨潮港股参数兼容：统一强制走 hke
    if col == "hk":
        col = "hke"
    if col not in ("szse", "hk", "hke"):
        if stock.isdigit() and len(stock) == 5:
            col = "hke"
        else:
            col = "szse"
    category = _CATEGORY_MAP.get(report_type, _CATEGORY_MAP["all"]) if col != "hk" else ""
    if col in ("hk", "hke") and not searchkey and report_type in _HK_KEYWORD_BY_TYPE:
        searchkey = _HK_KEYWORD_BY_TYPE[report_type]
    if not se_date:
        se_date = "2023-01-01~2030-12-31"

    def _is_financial_title(title: str, rtype: str) -> bool:
        t = str(title or "").strip().lower()
        if not t:
            return False
        keys = _TITLE_KEYS_BY_TYPE.get(rtype) if rtype in _TITLE_KEYS_BY_TYPE else _TITLE_KEYS_ALL
        return any(k in t for k in keys)

    data = {
        "pageNum": str(max(1, int(page_num or 1))),
        "pageSize": str(max(1, min(50, int(page_size or 20)))),
        "column": col,
        "tabName": "fulltext",
        "plate": "",
        "stock": stock,
        "searchkey": searchkey,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": se_date,
        "sortName": "time",
        "sortType": "desc",
    }
    def _post_once(form: dict) -> dict:
        rr = _SESSION.post(_URL, data=form, timeout=15)
        rr.raise_for_status()
        return rr.json() if rr.content else {}

    payload = {}
    rows = []

    columns_try = [col]
    if col in ("hk", "hke"):
        columns_try = [col, "hke" if col == "hk" else "hk"]

    for c in columns_try:
        form = dict(data)
        form["column"] = c
        if c in ("hk", "hke"):
            form["category"] = ""
        payload = _post_once(form)
        rows = payload.get("announcements") or []
        if rows:
            break

        # stock 直查无结果时，回退 searchkey
        if stock and stock.isdigit() and len(stock) in (5, 6):
            form2 = dict(form)
            form2["stock"] = ""
            form2["searchkey"] = stock
            payload = _post_once(form2)
            rows = payload.get("announcements") or []
            if rows:
                break

    # 中文关键词在 A 股查不到，再补一次港股（hke/hk）
    if not rows and col == "szse" and searchkey and not stock:
        for c in ("hke", "hk"):
            form3 = dict(data)
            form3["column"] = c
            form3["category"] = ""
            payload = _post_once(form3)
            rows = payload.get("announcements") or []
            if rows:
                break
    out = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        title = str(x.get("announcementTitle") or "").strip()
        # 强约束：无论“全部”还是分标签，都只返回财报（年报/中报/季报），剔除股东大会等杂公告
        if not _is_financial_title(title, report_type):
            continue
        rel = str(x.get("adjunctUrl") or "").strip()
        pdf_url = (_PDF_BASE + rel.lstrip("/")) if rel else ""
        out.append(
            {
                "id": str(x.get("announcementId") or rel or "").strip(),
                "title": title,
                "publish_time": _to_time_str(x.get("announcementTime")),
                "symbol": str(x.get("secCode") or "").strip(),
                "name": str(x.get("secName") or "").strip(),
                "pdf_url": pdf_url,
                "adjunct_size": str(x.get("adjunctSize") or "").strip(),
            }
        )
    return {
        "pageNum": int(payload.get("pageNum") or data["pageNum"]),
        "pageSize": int(payload.get("pageSize") or data["pageSize"]),
        "totalRecordNum": int(payload.get("totalRecordNum") or 0),
        "items": out,
        "source": "cninfo-public-query",
    }


def fetch_cninfo_suggest(keyword: str, limit: int = 12) -> list[dict]:
    kw = str(keyword or "").strip()
    if not kw:
        return []
    rr = _SESSION.get(_SUGGEST_URL, params={"keyWord": kw}, timeout=10)
    rr.raise_for_status()
    payload = rr.json() if rr.content else {}
    rows = payload.get("securities") or []
    out = []
    seen = set()
    for x in rows:
        if not isinstance(x, dict):
            continue
        code = str(x.get("code") or "").strip()
        name = str(x.get("name") or "").strip()
        mkt = str(x.get("type") or "").strip().upper()
        if not code or not name:
            continue
        k = (code, mkt, name)
        if k in seen:
            continue
        seen.add(k)
        out.append(
            {
                "code": code,
                "name": name,
                "type": mkt,
                "orgId": str(x.get("orgId") or "").strip(),
            }
        )
        if len(out) >= max(1, min(30, int(limit or 12))):
            break
    return out

