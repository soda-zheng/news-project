"""非交易时段热点榜：持久化上一交易日有效快照，避免盘前显示 -- / 无涨跌幅。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

_SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "hot_topics_last_close.json")


def _ensure_dir() -> None:
    d = os.path.dirname(_SNAPSHOT_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def load_hot_close_snapshot() -> dict[str, Any]:
    try:
        if not os.path.isfile(_SNAPSHOT_PATH):
            return {}
        with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        items = raw.get("items")
        if not isinstance(items, list) or not items:
            return {}
        return raw
    except Exception:
        return {}


def save_hot_close_snapshot(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    _ensure_dir()
    payload = {
        "saved_ts": time.time(),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "items": items[:80],
    }
    try:
        with open(_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def snapshot_has_meaningful_pct(items: list[dict[str, Any]], min_nonzero: int = 3) -> bool:
    """避免把全 0 / 无效数据写入快照。"""
    if not items:
        return False
    ok = 0
    for x in items:
        try:
            p = float(x.get("pct_chg") or 0)
        except Exception:
            continue
        if abs(p) > 1e-6:
            ok += 1
    return ok >= min_nonzero
