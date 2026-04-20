from __future__ import annotations

import os
import sqlite3
import threading
import time

_LOCK = threading.Lock()


def _db_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "user_data.sqlite3")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=8)
    c.row_factory = sqlite3.Row
    return c


def init_user_db() -> None:
    with _LOCK:
        c = _conn()
        try:
            cur = c.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    openid TEXT UNIQUE NOT NULL,
                    nickname TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_watchlist (
                    user_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, code)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_watchlist_user ON user_watchlist(user_id)")
            c.commit()
        finally:
            c.close()


def upsert_wechat_user(openid: str, nickname: str = "", avatar_url: str = "") -> str:
    oid = str(openid or "").strip()
    if not oid:
        raise ValueError("openid is required")
    now = int(time.time())
    user_id = f"wx_{oid}"
    with _LOCK:
        c = _conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT user_id FROM users WHERE openid = ?", (oid,))
            row = cur.fetchone()
            if row and row["user_id"]:
                user_id = str(row["user_id"])
                cur.execute(
                    "UPDATE users SET nickname=?, avatar_url=?, updated_at=? WHERE user_id=?",
                    (str(nickname or ""), str(avatar_url or ""), now, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO users(user_id, openid, nickname, avatar_url, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                    (user_id, oid, str(nickname or ""), str(avatar_url or ""), now, now),
                )
            c.commit()
            return user_id
        finally:
            c.close()


def get_watchlist_codes(user_id: str) -> list[str]:
    uid = str(user_id or "").strip()
    if not uid:
        return []
    with _LOCK:
        c = _conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT code FROM user_watchlist WHERE user_id=? ORDER BY created_at ASC", (uid,))
            rows = cur.fetchall() or []
            return [str(r["code"]).strip() for r in rows if r and r["code"]]
        finally:
            c.close()


def set_watchlist_codes(user_id: str, codes: list[str]) -> list[str]:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    uniq = []
    seen = set()
    for raw in (codes or []):
        c = str(raw or "").strip()
        if len(c) == 6 and c.isdigit() and c not in seen:
            seen.add(c)
            uniq.append(c)
    now = int(time.time())
    with _LOCK:
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_watchlist WHERE user_id=?", (uid,))
            for code in uniq:
                cur.execute(
                    "INSERT INTO user_watchlist(user_id, code, created_at) VALUES(?,?,?)",
                    (uid, code, now),
                )
            conn.commit()
            return uniq
        finally:
            conn.close()

