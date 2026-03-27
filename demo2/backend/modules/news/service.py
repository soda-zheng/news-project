import os
import re
from datetime import datetime


def news_fetch_juhe(session, parse_juhe_ctime, page: int = 1, num: int = 30) -> list[dict]:
    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少环境变量 NEWS_API_KEY")
    url = "http://apis.juhe.cn/fapigx/caijing/query"
    params = {"key": api_key, "page": int(page), "num": int(num)}
    r = session.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    if int(j.get("error_code", -1)) != 0:
        raise RuntimeError(j.get("reason") or "新闻接口返回失败")
    newslist = ((j.get("result") or {}).get("newslist") or [])
    items = []
    for n in newslist:
        nid = str(n.get("id") or "").strip()
        title = str(n.get("title") or "").strip()
        url_ = str(n.get("url") or "").strip()
        if not nid or not title or not url_:
            continue
        items.append(
            {
                "id": nid,
                "title": title,
                "source": str(n.get("source") or "").strip() or None,
                "ctime": parse_juhe_ctime(n.get("ctime")),
                "picUrl": str(n.get("picUrl") or "").strip() or None,
                "url": url_,
            }
        )
    return items


def _parse_tianapi_ctime(s: str) -> int:
    txt = str(s or "").strip()
    if not txt:
        return int(datetime.now().timestamp())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(txt, fmt).timestamp())
        except Exception:
            continue
    return int(datetime.now().timestamp())


def news_fetch_tianapi(session, page: int = 1, num: int = 30, word: str = "") -> list[dict]:
    """
    天行财经新闻接口：
    https://apis.tianapi.com/caijing/index
    """
    api_key = (
        os.environ.get("NEWS_TIANAPI_KEY", "").strip()
        or os.environ.get("TIANAPI_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("缺少环境变量 NEWS_TIANAPI_KEY（或 TIANAPI_KEY）")

    url = "https://apis.tianapi.com/caijing/index"
    params = {
        "key": api_key,
        "num": max(1, min(50, int(num))),
        "form": 1,
        "page": max(1, int(page)),
    }
    if str(word or "").strip():
        params["word"] = str(word).strip()

    r = session.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()
    if int(j.get("code", -1)) != 200:
        raise RuntimeError(j.get("msg") or "天行新闻接口返回失败")

    lst = ((j.get("result") or {}).get("list") or [])
    items = []
    for n in lst:
        nid = str(n.get("id") or "").strip()
        title = str(n.get("title") or "").strip()
        url_ = str(n.get("url") or "").strip()
        if not nid or not title or not url_:
            continue
        items.append(
            {
                "id": nid,
                "title": title,
                "source": str(n.get("source") or n.get("description") or "").strip() or "天行财经",
                "ctime": _parse_tianapi_ctime(n.get("ctime")),
                "picUrl": str(n.get("picUrl") or "").strip() or None,
                "url": url_,
            }
        )
    return items


def news_fallback_pic_url(news_id: str) -> str:
    seed = re.sub(r"[^a-zA-Z0-9]+", "", str(news_id or "news"))[:32] or "news"
    return f"https://picsum.photos/seed/{seed}/640/360"


def fallback_summary(title: str, source: str | None) -> str:
    t = str(title or "").strip()
    if len(t) > 80:
        t = t[:80].rstrip() + "…"
    src = f"（来源：{source}）" if source else ""
    return f"{t}{src}"


def fallback_category(title: str) -> str:
    t = str(title or "")
    if "美联储" in t:
        return "降息预期"
    if "加息" in t:
        return "加息预期"
    if "降息" in t:
        return "降息预期"
    if "人民币" in t or "汇率" in t:
        return "汇率波动"
    if "黄金" in t:
        return "金价波动"
    if "原油" in t or "油价" in t:
        return "油价波动"
    if "通胀" in t or "CPI" in t or "PPI" in t:
        return "通胀变化"
    if "央行" in t:
        return "政策信号"
    if "证监会" in t:
        return "监管动态"
    return "市场关注"

