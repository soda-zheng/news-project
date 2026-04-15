"""
Stooq CSV 解析（f=sd2t2ohlcv）

实际接口常返回「单行、无表头」：
  XAUUSD,2026-03-23,02:40:12,4498.43,4510.74,4320.68,4442.21,

若仍按「第一行表头 + 第二行数据」解析，会因只有一行而失败，导致行情永远回退到其它源（如 COMEX 期货），
与主流「伦敦金/现货」站点可差数十美元。
"""

from __future__ import annotations


def _safe_float(val, default=None):
    if val is None:
        return default
    s = str(val).strip()
    if not s or s == "N/D":
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def parse_stooq_ohlcv_csv(text: str) -> dict | None:
    """
    返回 dict: symbol, date, time, open, high, low, close（均为数值或字符串字段按需）
    close 为 float；open/high/low 可为 None。
    """
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    if not lines:
        return None

    # 少数情况下：表头行 + 数据行
    if len(lines) >= 2 and "Close" in lines[0]:
        cols = [x.strip() for x in lines[0].split(",")]
        vals = [x.strip() for x in lines[1].split(",")]
        row = dict(zip(cols, vals))
        close = _safe_float(row.get("Close"), None)
        if close is None:
            return None
        return {
            "symbol": row.get("Symbol") or "",
            "date": row.get("Date") or "",
            "time": row.get("Time") or "",
            "open": _safe_float(row.get("Open"), None),
            "high": _safe_float(row.get("High"), None),
            "low": _safe_float(row.get("Low"), None),
            "close": close,
        }

    # 常见：单行 Symbol,Date,Time,Open,High,Low,Close[,Volume]
    parts = [x.strip() for x in lines[0].split(",")]
    if len(parts) < 7:
        return None
    o = _safe_float(parts[3], None)
    h = _safe_float(parts[4], None)
    l_ = _safe_float(parts[5], None)
    c = _safe_float(parts[6], None)
    if c is None:
        return None
    return {
        "symbol": parts[0] or "",
        "date": parts[1] or "",
        "time": parts[2] or "",
        "open": o,
        "high": h,
        "low": l_,
        "close": c,
    }
