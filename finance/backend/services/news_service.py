import time
import uuid
import requests
from utils.helpers import (
    _now_str, _parse_sina_flash_time, _parse_sina_json_v2, 
    _to_float, _df_pick_col
)

_SOURCE_PRIORITY = {
    "财新网": 95,
    "百度股票 RSS": 92,
    "东方财富": 88,
    "百度财经": 82,
    "新浪财经": 80,
}

_A_SHARE_KEYWORDS = [
    "a股", "沪深", "上证", "深证", "创业板", "科创板", "北交所", "证监会",
    "ipo", "并购", "回购", "分红", "财报", "业绩", "券商", "银行", "白酒",
    "新能源", "半导体", "算力", "人工智能", "北向资金", "融资融券", "中证",
]
_MACRO_CN_KEYWORDS = [
    "国务院", "央行", "财政部", "发改委", "工信部", "住建部", "国常会",
    "稳增长", "消费", "制造业", "出口", "社融", "m1", "m2", "利率",
    "经济", "就业", "通胀", "汇率", "内需", "外需", "财政", "货币政策",
]
_MACRO_GLOBAL_KEYWORDS = [
    "美联储", "非农", "cpi", "pmi", "美元", "美债", "纳指", "道指",
    "原油", "黄金", "地缘", "关税", "欧央行", "日本央行",
    "油价", "航运", "供应链", "贸易", "地缘政治", "冲突",
]
_FINANCE_GUARD_KEYWORDS = [
    "股", "指数", "市场", "经济", "政策", "利率", "汇率", "通胀", "金融",
    "期货", "债", "基金", "银行", "券商", "财政", "货币", "油价", "黄金",
]
_IRRELEVANT_NEWS_KEYWORDS = [
    "赏花", "一朵花", "花海", "花开", "春游", "春日", "文旅", "演唱会",
    "体育", "比赛", "电影", "电视剧", "极地", "南极", "科考", "钻探",
    "校园", "招生", "高考", "节庆",
]


SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn",
    }
)


def _normalize_url(raw: object, base: str = "") -> str:
    """
    将各种来源的 url 规范成可在 webview 打开的绝对链接：
    - //xxx -> https://xxx
    - /path -> base + /path（若提供 base）
    - 去掉空白
    """
    u = str(raw or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/") and base:
        return base.rstrip("/") + u
    return u


def _news_relevance_score(title: str, summary: str, source: str = "") -> float:
    blob = f"{title} {summary}".lower()
    score = 0.0
    score += sum(1.0 for k in _A_SHARE_KEYWORDS if k in blob) * 2.5
    score += sum(1.0 for k in _MACRO_CN_KEYWORDS if k.lower() in blob) * 1.8
    score += sum(1.0 for k in _MACRO_GLOBAL_KEYWORDS if k.lower() in blob) * 1.6
    src = str(source or "")
    if "人民日报" in src or "新华社" in src or "央视" in src:
        score += 1.8
    elif "财联社" in src or "证券时报" in src or "新浪" in src or "东方财富" in src:
        score += 0.8
    return score


def _is_relevant_news(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    if not title:
        return False
    blob = f"{title} {summary}".lower()
    # 明显非财经主线内容直接过滤
    if any(k in blob for k in _IRRELEVANT_NEWS_KEYWORDS):
        return False
    # 先过一层财经语义门槛，过滤“教育/娱乐/社会”类泛新闻
    if not any(k in blob for k in _FINANCE_GUARD_KEYWORDS):
        return False
    ashare_hit = any(k in blob for k in _A_SHARE_KEYWORDS)
    macro_cn_hit = any(k.lower() in blob for k in _MACRO_CN_KEYWORDS)
    macro_glb_hit = any(k.lower() in blob for k in _MACRO_GLOBAL_KEYWORDS)
    # 必须明确命中 A股 / 国内宏观 / 国际宏观 其中之一
    if not (ashare_hit or macro_cn_hit or macro_glb_hit):
        return False
    score = _news_relevance_score(title, summary, str(item.get("source") or ""))
    return score >= 1.6


def fetch_baidu_finance_news(limit=20):
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_news_baidu(symbol="财经")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    items = []
    for _, row in df.head(limit).iterrows():
        title = str(row.get("标题") or "").strip()
        if not title:
            continue
        summary = str(row.get("摘要") or title[:80]).strip()
        ctime = int(time.mktime(time.strptime(str(row.get("时间") or ""), "%Y-%m-%d %H:%M")))

        url = _normalize_url(row.get("链接"))
        source = str(row.get("来源") or "百度财经")
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"baidu|{title}|{url}").hex[:16]
        items.append({
            "id": nid,
            "title": title,
            "summary": summary,
            "source": source,
            "category": "财经新闻",
            "ctime": ctime,
            "picUrl": "",
            "url": url,
            "importance": 80,
            "score": 100.0 - len(items) * 0.01,
        })
    return items


def fetch_akshare_stock_news(symbol, limit=10):
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_news_em(symbol=symbol)
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    # 兼容不同版本 akshare 的字段命名
    col_title = _df_pick_col(df, "新闻标题", "标题", "title")
    col_summary = _df_pick_col(df, "新闻内容", "内容", "摘要", "summary", "description")
    col_pub = _df_pick_col(df, "发布时间", "时间", "pub_time", "publish_time")
    col_source = _df_pick_col(df, "文章来源", "来源", "source")
    col_url = _df_pick_col(df, "新闻链接", "链接", "url", "URL", "link", "新闻网址", "网址")

    items = []
    for _, row in df.head(limit).iterrows():
        title = str(row.get("新闻标题") or "").strip()
        if not title and col_title:
            title = str(row.get(col_title) or "").strip()
        if not title:
            continue
        summary = str(row.get("新闻内容") or "").strip()
        if not summary and col_summary:
            summary = str(row.get(col_summary) or "").strip()
        if not summary:
            summary = title[:80]

        pub_time = str(row.get("发布时间") or "")
        if (not pub_time) and col_pub:
            pub_time = str(row.get(col_pub) or "")
        ctime = 0
        if pub_time:
            try:
                ctime = int(time.mktime(time.strptime(pub_time[:19], "%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
        # 先获取来源
        source = str(row.get("文章来源") or "")
        if (not source) and col_source:
            source = str(row.get(col_source) or "")
        source = (source or "东方财富").strip()
        # 尝试从不同的字段获取链接
        url = str(row.get("新闻链接") or row.get("url") or row.get("link") or "").strip()
        if (not url) and col_url:
            url = str(row.get(col_url) or "").strip()
        url = _normalize_url(url, base="https://finance.eastmoney.com")
        # 如果没有链接，根据来源生成不同的搜索链接
        if not url:
            import urllib.parse
            if source == "东方财富":
                url = f"https://so.eastmoney.com/news/s?keyword={urllib.parse.quote(title)}"
            elif source == "百度财经":
                url = f"https://finance.baidu.com/s?tn=news&rtt=1&bsst=1&cl=2&wd={urllib.parse.quote(title)}"
            elif source == "财新网":
                url = f"https://search.caixin.com/search?keyword={urllib.parse.quote(title)}"
            else:
                url = f"https://search.sina.com.cn/?q={urllib.parse.quote(title)}"
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"em|{title}|{url}").hex[:16]
        items.append({
            "id": nid,
            "title": title,
            "summary": summary,
            "source": source,
            "category": "个股新闻",
            "ctime": ctime,
            "picUrl": "",
            "url": url,
            "importance": 85,
            "score": 100.0 - len(items) * 0.01,
        })
    return items


def fetch_akshare_caixin_news(limit=20):
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df = ak.stock_news_main_cx()
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    items = []
    for _, row in df.head(limit).iterrows():
        title = str(row.get("标题") or "").strip()
        if not title:
            continue
        summary = str(row.get("摘要") or title[:80]).strip()
        ctime = int(time.mktime(time.strptime(str(row.get("时间") or ""), "%Y-%m-%d %H:%M")))

        url = _normalize_url(row.get("链接"))
        source = str(row.get("来源") or "财新网")
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"caixin|{title}|{url}").hex[:16]
        items.append({
            "id": nid,
            "title": title,
            "summary": summary,
            "source": source,
            "category": "财新网",
            "ctime": ctime,
            "picUrl": "",
            "url": url,
            "importance": 90,
            "score": 100.0 - len(items) * 0.01,
        })
    return items


def fetch_baidu_stock_rss_news(limit=20):
    try:
        import feedparser
    except ImportError:
        return []
    try:
        url = "http://news.baidu.com/n?cmd=1&class=stock&tn=rss"
        feed = feedparser.parse(url)
    except Exception:
        return []
    items = []
    stock_keywords = [
        "a股", "券商", "策略", "涨停", "跌停", "板块", "主力资金",
        "北向资金", "融资融券", "科创板", "创业板", "上证指数",
        "深证成指", "沪深300", "中证500", "茅台", "宁德时代",
        "比亚迪", "新能源", "半导体", "ai", "算力", "机器人",
        "医药", "白酒", "地产", "银行", "保险", "券商股",
    ]
    for i, entry in enumerate(feed.entries[:limit * 2]):
        title = str(entry.get("title") or "").strip()
        if not title or len(title) < 6:
            continue
        summary = str(entry.get("summary") or entry.get("description") or title[:100]).strip()
        summary = summary.replace("<[^<]+?>", "")[:120]
        link = _normalize_url(entry.get("link"))
        published = entry.get("published") or entry.get("updated") or ""
        ctime = 0
        if published:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(published)
                ctime = int(dt.timestamp())
            except Exception:
                try:
                    ctime = int(time.mktime(time.strptime(published[:19], "%Y-%m-%dT%H:%M:%S")))
                except Exception:
                    pass
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"baidu-rss|{title}|{link}").hex[:16]
        content_lower = f"{title} {summary}".lower()
        score_base = 70.0 - i * 0.05
        score_boost = sum(2.0 for k in stock_keywords if k in content_lower)
        importance = min(95, int(65 + score_boost * 3))
        items.append({
            "id": nid,
            "title": title,
            "summary": summary,
            "source": "百度股票RSS",
            "category": "股票焦点",
            "ctime": ctime,
            "picUrl": "",
            "url": link,
            "importance": importance,
            "score": round(score_base + score_boost, 3),
        })
        if len(items) >= limit:
            break
    return items


def aggregate_news(sources, limit=30):
    all_news = []
    seen_titles = set()
    for source in sources:
        for item in source:
            title_key = (item.get("title") or "").strip()[:60]
            if title_key and title_key not in seen_titles:
                seen_titles.add(title_key)
                src = item.get("source") or ""
                priority_bonus = _SOURCE_PRIORITY.get(src, 70)
                rel = _news_relevance_score(
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(src),
                )
                item["score"] = (item.get("score") or 0) + priority_bonus * 0.1 + rel
                if _is_relevant_news(item):
                    all_news.append(item)

    # 时效优先：先按发布时间倒序，再按相关性/重要度打散同时间段
    sorter = lambda x: (
        int(_to_float(x.get("ctime"), 0) or 0),
        float(_to_float(x.get("score"), 0) or 0),
        float(_to_float(x.get("importance"), 0) or 0),
    )
    all_news.sort(
        key=sorter,
        reverse=True,
    )
    return all_news[:limit]


def get_news_summary(category=None, limit=30):
    baidu_finance = fetch_baidu_finance_news(limit=limit)
    baidu_rss = fetch_baidu_stock_rss_news(limit=limit)
    caixin = fetch_akshare_caixin_news(limit=limit)
    sina_live = _fetch_news_live(page=1, num=limit)
    all_news = aggregate_news([sina_live, baidu_finance, baidu_rss, caixin], limit=limit)
    return {
        "items": all_news,
        "update_time": _now_str(),
        "source_count": 4,
        "sources": ["新浪财经", "百度财经", "百度股票RSS", "财新网"],
        "total_count": len(all_news),
    }


def _fetch_sina_global_flash(limit: int = 20):
    limit = max(1, min(50, int(limit or 20)))
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_info_global_sina()
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    cols = list(df.columns)
    if len(cols) < 2:
        return None
    tcol = "时间" if "时间" in cols else cols[0]
    ccol = "内容" if "内容" in cols else cols[1]
    base_url = "https://finance.sina.com.cn/7x24"
    out = []
    for j, (_, row) in enumerate(df.head(limit).iterrows()):
        tstr = str(row.get(tcol) or "").strip()
        content = str(row.get(ccol) or "").strip()
        if not content:
            continue
        ctime = _parse_sina_flash_time(tstr)
        nid = uuid.uuid5(uuid.NAMESPACE_URL, f"sina-global|{tstr}|{content[:120]}").hex[:16]
        title = content[:80] + ("…" if len(content) > 80 else "")
        out.append({
            "id": nid,
            "title": title,
            "summary": content,
            "source": "新浪财经",
            "category": "全球财经快讯",
            "ctime": ctime,
            "picUrl": "",
            "url": base_url,
            "importance": 90,
            "score": 100.0 - j * 0.01,
        })
    return out


def _fetch_news_live(page: int = 1, num: int = 20):
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    resp = SESSION.get(
        url,
        params={"pageid": 155, "lid": 1686, "num": num, "page": page},
        timeout=10,
    )
    data = resp.json() if resp.text else {}
    lst = ((data or {}).get("result") or {}).get("data") or []
    items = []
    for x in lst:
        if not isinstance(x, dict):
            continue
        nid = str(x.get("oid") or x.get("docid") or x.get("id") or uuid.uuid4().hex[:8])
        title = str(x.get("title") or "").strip()
        if not title:
            continue
        summary = str(x.get("intro") or x.get("description") or title[:80]).strip()
        ctime = int(_to_float(x.get("ctime"), 0) or 0)
        raw_url = x.get("url") or x.get("wapurl") or x.get("wurl") or x.get("link") or ""
        url = _normalize_url(raw_url, base="https://finance.sina.com.cn")
        # 新浪 roll 有时返回不带协议的域名串；再兜一次
        if url and url.startswith("www."):
            url = "https://" + url
        if not url:
            url = f"https://search.sina.com.cn/?q={requests.utils.quote(title)}"
        pic = ""
        pics = x.get("images") or []
        if isinstance(pics, list) and pics:
            first = pics[0]
            if isinstance(first, dict):
                pic = str(first.get("u") or first.get("url") or "").strip()
        source = str(x.get("source") or "新浪财经")
        content = f"{title} {summary}".lower()
        score = _news_relevance_score(title, summary, source)
        age_hours = max(0, (time.time() - ctime) / 3600.0) if ctime else 24
        freshness = max(0.0, 3.0 - age_hours / 8.0)
        score += freshness
        if score < 2.5:
            continue
        category = "A股相关"
        if any(k.lower() in content for k in _MACRO_GLOBAL_KEYWORDS):
            category = "国际市场"
        if any(k.lower() in content for k in _MACRO_CN_KEYWORDS):
            category = "国内宏观"
        items.append({
            "id": nid,
            "title": title,
            "summary": summary,
            "source": source,
            "category": category,
            "ctime": ctime,
            "picUrl": pic,
            "url": url,
            "importance": int(min(95, 45 + score * 5)),
            "score": round(score, 3),
        })
    items.sort(key=lambda x: (x.get("score") or 0, x.get("ctime") or 0), reverse=True)
    return items
