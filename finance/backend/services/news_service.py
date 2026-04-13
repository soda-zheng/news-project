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
# 国际面：默认视为对 A 股风险偏好/资金流向有传导（利率、美元、大宗、主要股指、地缘等）
_GLOBAL_ASHARE_SPILLOVER = [
    "美联储", "加息", "降息", "美债", "美元", "美元指数", "非农", "美联储议息",
    "纳指", "纳斯达克", "道指", "道琼斯", "标普500", "标普", "vix", "恐慌指数",
    "原油", "油价", "布伦特", "wti", "黄金", "白银", "铜价",
    "地缘", "关税", "贸易战", "欧央行", "日本央行", "英央行",
    "俄乌", "中东", "霍尔木兹", "制裁", "供应链", "芯片禁令",
]
# 国内：与资本市场、货币政策、财政金融政策直接相关的表述（避免仅靠泛社会新闻）
_MACRO_CN_MARKET_TIGHT = [
    "国务院", "国常会", "央行", "证监会", "财政部", "发改委", "金融监管", "外汇局",
    "货币政策", "财政政策", "降准", "降息", "lpr", "mlf", "逆回购", "公开市场",
    "社融", "m2", "信贷", "专项债", "赤字", "汇率", "人民币", "离岸人民币",
    "资本市场", "注册制", "北交所", "沪深", "a股", "港股通", "互联互通",
    "稳增长", "内需", "外需", "制造业", "出口", "进口",
]
# 与 A 股/中国资产定价相关的“挂钩词”（国际新闻里出现则更易判定与 A 股有关）
_CHINA_MARKET_BRIDGE = [
    "a股", "沪深", "上证", "深证", "创业板", "科创板", "北交所", "北向", "外资",
    "陆股通", "港股", "中概", "msci", "富时", "中国资产", "人民币", "离岸人民币",
    "人民银行", "央行", "证监会",
]
_FINANCE_GUARD_KEYWORDS = [
    "股", "指数", "市场", "经济", "政策", "利率", "汇率", "通胀", "金融",
    "期货", "债", "基金", "银行", "券商", "财政", "货币", "油价", "黄金",
    "加息", "降息", "美元", "美债", "原油", "大宗", "资产", "流动性",
]
# 财经语义底线：须命中至少一词，避免纯社会/文体新闻混进来
_FINANCE_MARKET_HINT = [
    "股", "债", "汇", "利率", "期货", "基金", "券商", "银行", "保险", "上市", "融资",
    "资本", "证券", "指数", "财经", "金融", "资产", "投资", "估值", "财报", "业绩",
]
_IRRELEVANT_NEWS_KEYWORDS = [
    "赏花", "一朵花", "花海", "花开", "春游", "春日", "文旅", "演唱会",
    "体育", "比赛", "电影", "电视剧", "极地", "南极", "科考", "钻探",
    "校园", "招生", "高考", "节庆",
]

_GLOBAL_TITLE_HINTS = (
    "美联储", "欧洲央行", "日本央行", "美国商务部", "白宫", "欧佩克", "霍尔木兹",
    "俄乌", "北约", "美债", "非农", "道琼斯", "纳斯达克", "标普500",
)
_CN_TITLE_HINTS = (
    "国务院", "国常会", "央行", "证监会", "沪深", "北向", "人民币中间价",
    "发改委", "财政部", "工信部",
)


def normalize_news_region_param(raw: object) -> str:
    s = str(raw or "all").strip().lower()
    aliases = {"国内": "domestic", "国际": "global", "海外": "global", "全部": "all"}
    s = aliases.get(s, s)
    return s if s in ("all", "domestic", "global") else "all"


def _region_keyword_scores(item: dict) -> tuple[float, float]:
    """
    国内/国际分值：不用「经济、汇率」等泛宏观词抬国内分，否则海外稿几乎全被判成国内。
    标题权重更高，且显式奖励 _GLOBAL_ASHARE_SPILLOVER。
    """
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    t_raw = title
    s_raw = summary
    t = t_raw.lower()
    s = s_raw.lower()

    d = 0.0
    g = 0.0
    wt = 2.4  # 标题权重
    wb = 1.0  # 摘要权重

    def _add_kw(keys: list[str], weight: float, text_raw: str, text_lower: str, use_lower: bool) -> float:
        n = 0.0
        for k in keys:
            if not k:
                continue
            if use_lower:
                kk = k.lower()
                if kk in text_lower:
                    n += weight
            elif k in text_raw:
                n += weight
        return n

    # A 股 / 国内资本市场（标题优先）
    d += _add_kw(list(_A_SHARE_KEYWORDS), 2.0, t_raw, t, False) * wt
    d += _add_kw(list(_A_SHARE_KEYWORDS), 2.0, s_raw, s, False) * wb
    # 国内政策/市场：只用紧集合，避免「经济」类泛词压死国际标签
    d += _add_kw(list(_MACRO_CN_MARKET_TIGHT), 1.2, t_raw, t, False) * wt
    d += _add_kw(list(_MACRO_CN_MARKET_TIGHT), 1.0, s_raw, s, False) * wb

    # 国际宏观（中英混合：全球类关键词）
    g += _add_kw(list(_MACRO_GLOBAL_KEYWORDS), 1.7, t_raw, t, True) * wt
    g += _add_kw(list(_MACRO_GLOBAL_KEYWORDS), 1.4, s_raw, s, True) * wb
    if _blob_has_any(t_raw, _GLOBAL_ASHARE_SPILLOVER):
        g += 4.0
    elif _blob_has_any(s_raw, _GLOBAL_ASHARE_SPILLOVER):
        g += 2.2

    src = str(item.get("source") or "")
    if any(x in src for x in ("路透", "彭博", "华尔街日报", "金融时报", "FT", "Reuters")):
        g += 1.4
    if any(m in title for m in _CN_TITLE_HINTS):
        d += 1.3
    if any(m in title for m in _GLOBAL_TITLE_HINTS):
        g += 1.4
    return d, g


def classify_news_region(item: dict) -> str:
    """国内 / 国际 / 内外联动（both）。用于 Tab 过滤；规则可后续迭代。"""
    title = str(item.get("title") or "").strip()
    d, g = _region_keyword_scores(item)
    if d < 1.0 and g < 1.0:
        blob = f"{item.get('title', '')} {item.get('summary', '')}"
        if any(k in blob for k in ("美国", "欧盟", "英国财政部", "美联储加息", "欧洲央行")):
            g += 2.0
        if any(k in blob for k in ("中国", "A股", "沪深", "国务院", "发改委", "证监会")):
            d += 2.0
    # 标题以海外传导事件为主、且未以国内部委/A股统领，直接标国际
    if title and _blob_has_any(title, _GLOBAL_ASHARE_SPILLOVER):
        cn_lead = any(
            x in title
            for x in ("国务院", "国常会", "证监会", "沪深交易所", "北交所", "上证综指", "深证成指", "央行宣布", "人民银行")
        )
        ashare_lead = any(k in title for k in ("A股", "a股", "科创板", "创业板", "北向资金"))
        if not cn_lead and not ashare_lead and g >= d:
            return "global"
    if d < 0.5 and g < 0.5:
        return "domestic"
    ratio = 1.08
    if d >= g * ratio:
        return "domestic"
    if g >= d * ratio:
        return "global"
    return "both"


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
    blob_raw = f"{title} {summary}"
    blob = blob_raw.lower()
    score = 0.0
    score += sum(1.0 for k in _A_SHARE_KEYWORDS if k in blob) * 2.5
    score += sum(1.0 for k in _MACRO_CN_KEYWORDS if k.lower() in blob) * 1.8
    score += sum(1.0 for k in _MACRO_GLOBAL_KEYWORDS if k.lower() in blob) * 1.6
    # 国际传导稿常较短，补分避免达不到阈值进不了列表
    if _blob_has_any(blob_raw, _GLOBAL_ASHARE_SPILLOVER):
        score += 1.25
    src = str(source or "")
    if "人民日报" in src or "新华社" in src or "央视" in src:
        score += 1.8
    elif "财联社" in src or "证券时报" in src or "新浪" in src or "东方财富" in src:
        score += 0.8
    return score


def _blob_has_any(blob_raw: str, keys: list[str]) -> bool:
    blob_lower = blob_raw.lower()
    for k in keys:
        if not k:
            continue
        ascii_only = all(ord(c) < 128 for c in k)
        if ascii_only:
            if k.lower() in blob_lower:
                return True
        elif k in blob_raw:
            return True
    return False


def _is_relevant_news(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    if not title:
        return False
    blob_raw = f"{title} {summary}"
    blob = blob_raw.lower()
    # 明显非财经主线内容直接过滤
    if any(k in blob for k in _IRRELEVANT_NEWS_KEYWORDS):
        return False

    ashare_hit = any(k in blob_raw for k in _A_SHARE_KEYWORDS)
    bridge_hit = any(k in blob_raw for k in _CHINA_MARKET_BRIDGE)
    cn_market_tight = any(k in blob_raw for k in _MACRO_CN_MARKET_TIGHT)
    global_spill = _blob_has_any(blob_raw, _GLOBAL_ASHARE_SPILLOVER)
    macro_glb_broad = any(k.lower() in blob for k in _MACRO_GLOBAL_KEYWORDS)
    macro_cn_broad = any(k.lower() in blob for k in _MACRO_CN_KEYWORDS)
    finance_hint = any(k in blob_raw for k in _FINANCE_MARKET_HINT)

    # ① A股 / 中国资本市场直接相关
    direct_cn_market = ashare_hit or (
        bridge_hit and (finance_hint or cn_market_tight or global_spill)
    )
    # ② 国内：政策与宏观金融相关，或宽口径宏观词 + 财经/市场语义（避免纯社会新闻）
    cn_macro_ok = cn_market_tight or (macro_cn_broad and finance_hint)
    # ③ 国际：对全球资产定价有传导、进而影响 A 股风险偏好的类别
    intl_ok = global_spill or (macro_glb_broad and finance_hint)

    if not (direct_cn_market or cn_macro_ok or intl_ok):
        return False

    # 财经/资产定价语义底线；已命中强国际传导或 A 股关键词时通常已满足
    if not any(k in blob for k in _FINANCE_GUARD_KEYWORDS):
        if not (global_spill or ashare_hit or cn_market_tight):
            return False

    score = _news_relevance_score(title, summary, str(item.get("source") or ""))
    return score >= 2.0


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


def get_news_summary(category=None, limit=30, region: str = "all"):
    region = normalize_news_region_param(region)
    out_cap = max(1, int(limit or 30))
    if region == "all":
        # 略多抓候选，再按时间排序截取，便于「全部」里自然混入国内/国际稿
        fetch_n = min(max(out_cap * 5, 60), 160)
    else:
        fetch_n = min(max(out_cap * 10, 80), 200)

    baidu_finance = fetch_baidu_finance_news(limit=fetch_n)
    baidu_rss = fetch_baidu_stock_rss_news(limit=fetch_n)
    caixin = fetch_akshare_caixin_news(limit=fetch_n)
    sina_live = _fetch_news_live(page=1, num=fetch_n)
    all_news = aggregate_news([sina_live, baidu_finance, baidu_rss, caixin], limit=fetch_n)

    sorter = lambda x: (
        int(_to_float(x.get("ctime"), 0) or 0),
        float(_to_float(x.get("score"), 0) or 0),
        float(_to_float(x.get("importance"), 0) or 0),
    )

    for item in all_news:
        item["region"] = classify_news_region(item)

    # 国内：仅 domestic；国际：仅 global；内外联动 both 只在「全部」里出现
    if region == "domestic":
        all_news = [x for x in all_news if x.get("region") == "domestic"]
        all_news.sort(key=sorter, reverse=True)
        all_news = all_news[:out_cap]
    elif region == "global":
        all_news = [x for x in all_news if x.get("region") == "global"]
        all_news.sort(key=sorter, reverse=True)
        all_news = all_news[:out_cap]
    elif region == "all":
        # 国内+国际+内外联动，统一按时间（新在上），其次分数、重要度
        all_news.sort(key=sorter, reverse=True)
        all_news = all_news[:out_cap]
    else:
        all_news.sort(key=sorter, reverse=True)
        all_news = all_news[:out_cap]

    return {
        "items": all_news,
        "update_time": _now_str(),
        "source_count": 4,
        "sources": ["新浪财经", "百度财经", "百度股票RSS", "财新网"],
        "total_count": len(all_news),
        "region": region,
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
