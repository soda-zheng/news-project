import json
import re
import time
import uuid
from datetime import datetime


def _cn_a_share_use_last_close_hot_snapshot() -> bool:
    """
    非连续竞价时段返回 True：盘前、午休、收盘后、周末。
    此时热点榜应展示上一交易日收盘时保存的快照，避免盘前接口涨跌幅为 -- / 无效。
    """
    try:
        from zoneinfo import ZoneInfo

        t = datetime.now(ZoneInfo("Asia/Shanghai"))
        wd = t.weekday()
        minutes = t.hour * 60 + t.minute
    except Exception:
        lt = time.localtime()
        wd = lt.tm_wday
        minutes = lt.tm_hour * 60 + lt.tm_min
    if wd >= 5:
        return True
    if minutes < 9 * 60 + 30:
        return True
    if 11 * 60 + 30 <= minutes < 13 * 60:
        return True
    if minutes >= 15 * 60:
        return True
    return False


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _parse_symbol(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    if len(s) == 8 and (s.startswith("sh") or s.startswith("sz") or s.startswith("bj")) and s[2:].isdigit():
        return s[2:]
    if len(s) == 6 and s.isdigit():
        return s
    return s


def _sina_symbol(code: str) -> str:
    c = _parse_symbol(code)
    if len(c) != 6 or not c.isdigit():
        return c
    if c.startswith(("6", "9")):
        return f"sh{c}"
    if c.startswith("8"):
        return f"bj{c}"
    return f"sz{c}"


def _to_float(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace("%", "")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _parse_sina_var(payload: str) -> list[str]:
    if not payload or "=" not in payload:
        return []
    right = payload.split("=", 1)[1].strip().strip(";").strip()
    right = right.strip('"')
    if not right:
        return []
    return right.split(",")


def _is_a_share_6digit(code: str) -> bool:
    c = _parse_symbol(code)
    return bool(c) and len(c) == 6 and c.isdigit()


def _parse_sina_json_v2(raw: str):
    s = str(raw or "").strip()
    if not s:
        return []
    fixed = re.sub(r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s)
    try:
        out = json.loads(fixed)
        return out if isinstance(out, list) else []
    except Exception:
        return []


def _parse_sina_flash_time(ts: str) -> int:
    s = str(ts or "").strip()
    if not s:
        return 0
    try:
        return int(time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S")))
    except Exception:
        pass
    try:
        return int(time.mktime(time.strptime(s[:16], "%Y-%m-%d %H:%M")))
    except Exception:
        return 0


def _normalize_a_code(raw: object) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 6:
        return digits[-6:]
    if len(s) == 6 and s.isdigit():
        return s
    return ""


def _df_to_code_name_items(df) -> list[dict[str, str]]:
    if df is None or getattr(df, "empty", True):
        return []
    col_code = col_name = None
    for c in df.columns:
        cs = str(c).lower()
        if col_code is None and ("代码" in str(c) or cs == "code"):
            col_code = c
        if col_name is None and ("名称" in str(c) or "name" == cs):
            col_name = c
    if col_code is None or col_name is None:
        return []
    codes = df[col_code].astype(str).str.strip()
    names = df[col_name].astype(str).str.strip()
    out: list[dict[str, str]] = []
    for c, n in zip(codes, names):
        c6 = _normalize_a_code(c)
        if len(c6) == 6 and c6.isdigit() and n:
            out.append({"code": c6, "name": n})
    return out


def _df_to_records(df):
    if df is None or getattr(df, "empty", True):
        return []
    import pandas as pd

    def _clean(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        return float(v) if isinstance(v, (int, float)) else v

    rows = []
    for _, row in df.iterrows():
        rows.append({str(k): _clean(row[k]) for k in df.columns})
    return rows


def _df_pick_col(df, *names: str):
    cols = list(df.columns)
    for want in names:
        for c in cols:
            sc = str(c)
            if sc == want or want in sc:
                return c
    return None


def _sina_symbol_prefix(code6: str) -> str:
    c = str(code6).strip()
    return ("sh" if c.startswith(("6", "9")) else "sz") + c


def _parse_maybe_timestamp_to_ymd(day: object) -> str:
    if day is None:
        return ""
    if isinstance(day, (int, float)):
        ts = int(day)
        if ts > 10_000_000_000:
            ts = ts // 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return ""

    s = str(day).strip()
    if not s:
        return ""
    if "-" in s:
        return s[:10]
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    m = re.search(r"(\d{10,13})", s)
    if m:
        ts = int(m.group(1))
        if ts > 10_000_000_000:
            ts = ts // 1000
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return ""
    return s[:10]


def _safe_bullets(items, max_items: int = 5):
    out = []
    if isinstance(items, list):
        for x in items:
            s = str(x).strip()
            if s:
                out.append(s[:80])
            if len(out) >= max_items:
                break
    return out


def _strip_markdown_json_fence(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    s = _strip_markdown_json_fence(text)
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    try:
        last = s.rfind("}")
        if last > start:
            obj = json.loads(s[start : last + 1])
            return obj if isinstance(obj, dict) else None
    except Exception:
        return None
    return None
