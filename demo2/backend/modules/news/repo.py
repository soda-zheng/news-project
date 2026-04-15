import json
import os
import sqlite3


def news_db_path(base_dir: str) -> str:
    return os.path.join(base_dir, "news_cache.sqlite3")


def news_db_conn(base_dir: str):
    conn = sqlite3.connect(news_db_path(base_dir), timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def news_db_init(base_dir: str):
    conn = news_db_conn(base_dir)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_summary (
              news_id TEXT PRIMARY KEY,
              url TEXT,
              title TEXT,
              source TEXT,
              ctime INTEGER,
              summary TEXT,
              importance INTEGER,
              keywords TEXT,
              category TEXT,
              created_at INTEGER
            )
            """
        )
        try:
            conn.execute("ALTER TABLE news_summary ADD COLUMN category TEXT")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def news_cache_get_many(base_dir: str, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    conn = news_db_conn(base_dir)
    try:
        q = ",".join(["?"] * len(ids))
        cur = conn.execute(
            f"SELECT news_id, summary, importance, keywords, category FROM news_summary WHERE news_id IN ({q})",
            ids,
        )
        out = {}
        for news_id, summary, importance, keywords, category in cur.fetchall():
            out[str(news_id)] = {
                "summary": summary,
                "importance": int(importance) if importance is not None else None,
                "keywords": keywords,
                "category": category,
            }
        return out
    finally:
        conn.close()


def news_cache_upsert(base_dir: str, now_ts, item: dict, summary: str, importance: int, keywords: list[str] | None = None, category: str | None = None):
    conn = news_db_conn(base_dir)
    try:
        conn.execute(
            """
            INSERT INTO news_summary(news_id,url,title,source,ctime,summary,importance,keywords,category,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(news_id) DO UPDATE SET
              url=excluded.url,
              title=excluded.title,
              source=excluded.source,
              ctime=excluded.ctime,
              summary=excluded.summary,
              importance=excluded.importance,
              keywords=excluded.keywords,
              category=excluded.category
            """,
            (
                item.get("id"),
                item.get("url"),
                item.get("title"),
                item.get("source"),
                int(item.get("ctime") or 0),
                summary,
                int(importance),
                json.dumps(keywords or [], ensure_ascii=False),
                category,
                int(now_ts()),
            ),
        )
        conn.commit()
    finally:
        conn.close()

