from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from flask import Response, jsonify, request, stream_with_context

_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()
_TASK_QUEUE: queue.Queue = queue.Queue()
_SUBSCRIBERS: set[queue.Queue] = set()
_WORKER_STARTED = False
_MAX_TASKS = 200
_CHAT_DB_READY = False
_CHAT_DB_LOCK = threading.Lock()


def _chat_db_path() -> str:
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(backend_dir, "research_chat.sqlite3")


def _chat_db_conn():
    conn = sqlite3.connect(_chat_db_path(), timeout=8, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _chat_db_init():
    global _CHAT_DB_READY
    if _CHAT_DB_READY:
        return
    with _CHAT_DB_LOCK:
        if _CHAT_DB_READY:
            return
        conn = _chat_db_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id)")
            conn.commit()
            _CHAT_DB_READY = True
        finally:
            conn.close()


def _session_title_from_question(q: str) -> str:
    s = str(q or "").strip()
    return s[:30] if s else "投研会话"


def _chat_session_ensure(session_id: str, question: str):
    _chat_db_init()
    now = _now_str()
    conn = _chat_db_conn()
    try:
        row = conn.execute("SELECT session_id FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            conn.execute("UPDATE chat_sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        else:
            conn.execute(
                "INSERT INTO chat_sessions(session_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (session_id, _session_title_from_question(question), now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _chat_append_pair(session_id: str, question: str, answer: str):
    if not session_id:
        return
    _chat_session_ensure(session_id, question)
    now = _now_str()
    conn = _chat_db_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
            (session_id, "user", str(question or "").strip(), now),
        )
        conn.execute(
            "INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
            (session_id, "assistant", str(answer or "").strip(), now),
        )
        conn.execute("UPDATE chat_sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        conn.commit()
    finally:
        conn.close()


def _chat_list_sessions(limit: int = 50):
    _chat_db_init()
    conn = _chat_db_conn()
    try:
        rows = conn.execute(
            """
            SELECT s.session_id, s.title, s.created_at, s.updated_at,
                   COALESCE(m.cnt, 0) AS message_count
              FROM chat_sessions s
              LEFT JOIN (
                SELECT session_id, COUNT(*) AS cnt
                  FROM chat_messages
                 GROUP BY session_id
              ) m ON m.session_id = s.session_id
             ORDER BY s.updated_at DESC
             LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [
            {
                "session_id": r[0],
                "title": r[1] or "投研会话",
                "created_at": r[2],
                "updated_at": r[3],
                "message_count": int(r[4] or 0),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _chat_get_messages(session_id: str, limit: int = 200):
    _chat_db_init()
    conn = _chat_db_conn()
    try:
        rows = conn.execute(
            """
            SELECT role, content, created_at
              FROM chat_messages
             WHERE session_id=?
             ORDER BY id ASC
             LIMIT ?
            """,
            (session_id, int(limit)),
        ).fetchall()
        return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]
    finally:
        conn.close()


def _chat_delete_session(session_id: str):
    _chat_db_init()
    conn = _chat_db_conn()
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        cur = conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return int(cur.rowcount or 0)
    finally:
        conn.close()


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _safe_emit(event_type: str, data: dict):
    dead = []
    with _TASKS_LOCK:
        subs = list(_SUBSCRIBERS)
    for q in subs:
        try:
            q.put_nowait({"type": event_type, "data": data})
        except Exception:
            dead.append(q)
    if dead:
        with _TASKS_LOCK:
            for q in dead:
                _SUBSCRIBERS.discard(q)


def _trim_tasks():
    with _TASKS_LOCK:
        if len(_TASKS) <= _MAX_TASKS:
            return
        items = sorted(_TASKS.items(), key=lambda kv: kv[1].get("created_at", ""))
        for tid, _ in items[: max(0, len(_TASKS) - _MAX_TASKS)]:
            _TASKS.pop(tid, None)


def _start_worker_if_needed():
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True

    def _worker_loop():
        while True:
            task = _TASK_QUEUE.get()
            if not isinstance(task, dict):
                continue
            tid = task.get("task_id")
            deps = task.get("deps") or {}
            payload = task.get("payload") or {}
            session_id = str(payload.get("session_id") or "")
            question = str(payload.get("question") or "").strip()
            if not tid:
                continue
            with _TASKS_LOCK:
                if tid in _TASKS:
                    _TASKS[tid]["status"] = "processing"
                    _TASKS[tid]["progress"] = 30
                    _TASKS[tid]["message"] = "正在汇总行情与资讯并调用模型"
            _safe_emit("task_started", {"task_id": tid})
            try:
                out = deps["research_analyze"](
                    deps["session"],
                    deps["research_llm_state"],
                    payload,
                    fetch_stock_snapshot=deps.get("fetch_stock_snapshot"),
                    fetch_hot_items=deps["fetch_hot_items"],
                )
                with _TASKS_LOCK:
                    if tid in _TASKS:
                        _TASKS[tid]["status"] = "completed"
                        _TASKS[tid]["progress"] = 100
                        _TASKS[tid]["message"] = "分析完成"
                        _TASKS[tid]["result"] = out
                        _TASKS[tid]["session_id"] = session_id
                        _TASKS[tid]["completed_at"] = _now_str()
                if session_id:
                    ans = str((out or {}).get("summary") or "已完成本次分析。")
                    _chat_append_pair(session_id, question, ans)
                _safe_emit("task_completed", {"task_id": tid, "result": out})
            except Exception as e:
                with _TASKS_LOCK:
                    if tid in _TASKS:
                        _TASKS[tid]["status"] = "failed"
                        _TASKS[tid]["progress"] = 100
                        _TASKS[tid]["message"] = "分析失败"
                        _TASKS[tid]["error"] = str(e)
                        _TASKS[tid]["completed_at"] = _now_str()
                _safe_emit("task_failed", {"task_id": tid, "error": str(e)})

    threading.Thread(target=_worker_loop, daemon=True).start()


def research_analyze_route(deps):
    if request.method == "GET":
        return jsonify(
            {
                "code": 200,
                "msg": "ok",
                "data": {
                    "endpoint": "/api/research/analyze",
                    "hint": "请使用 POST，Content-Type: application/json。",
                },
            }
        )

    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    async_mode = bool(body.get("async_mode"))
    session_id = str(body.get("session_id") or "").strip() or uuid.uuid4().hex
    body["session_id"] = session_id
    if async_mode:
        _start_worker_if_needed()
        task_id = uuid.uuid4().hex
        task = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "已进入队列，等待执行",
            "error": None,
            "result": None,
            "session_id": session_id,
            "created_at": _now_str(),
            "completed_at": None,
        }
        with _TASKS_LOCK:
            _TASKS[task_id] = task
        _trim_tasks()
        _TASK_QUEUE.put({"task_id": task_id, "payload": body, "deps": deps})
        _safe_emit("task_created", {"task_id": task_id})
        return jsonify(
            {
                "code": 202,
                "msg": "accepted",
                "data": {
                    "task_id": task_id,
                    "session_id": session_id,
                    "status": "pending",
                    "message": "任务已创建，可通过 /api/research/tasks/<task_id> 查询状态",
                },
            }
        )

    try:
        out = deps["research_analyze"](
            deps["session"],
            deps["research_llm_state"],
            body,
            fetch_stock_snapshot=deps.get("fetch_stock_snapshot"),
            fetch_hot_items=deps["fetch_hot_items"],
        )
        ans = str((out or {}).get("summary") or "已完成本次分析。")
        _chat_append_pair(session_id, str(body.get("question") or ""), ans)
        out = {**(out or {}), "session_id": session_id}
        return jsonify({"code": 200, "msg": "success", "data": out})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"分析失败：{e}", "data": None})


def research_task_status_route(task_id: str):
    with _TASKS_LOCK:
        task = _TASKS.get(str(task_id or ""))
    if not task:
        return jsonify({"code": 404, "msg": "任务不存在", "data": None})
    return jsonify({"code": 200, "msg": "success", "data": task})


def research_tasks_stream_route():
    @stream_with_context
    def event_stream():
        q: queue.Queue = queue.Queue(maxsize=200)
        with _TASKS_LOCK:
            _SUBSCRIBERS.add(q)
            pending = [
                {"task_id": tid, "status": t.get("status"), "progress": t.get("progress")}
                for tid, t in list(_TASKS.items())[-30:]
                if t.get("status") in ("pending", "processing")
            ]
        yield f"event: connected\ndata: {json.dumps({'message': 'connected', 'pending': pending}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    evt = q.get(timeout=20)
                    yield f"event: {evt.get('type')}\ndata: {json.dumps(evt.get('data') or {}, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': _now_str()}, ensure_ascii=False)}\n\n"
        finally:
            with _TASKS_LOCK:
                _SUBSCRIBERS.discard(q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def research_chat_sessions_route():
    try:
        limit = int(request.args.get("limit", "50") or "50")
    except Exception:
        limit = 50
    limit = max(1, min(200, limit))
    return jsonify({"code": 200, "msg": "success", "data": {"sessions": _chat_list_sessions(limit)}})


def research_chat_session_messages_route(session_id: str):
    sid = str(session_id or "").strip()
    if not sid:
        return jsonify({"code": 400, "msg": "参数错误：session_id", "data": None})
    return jsonify({"code": 200, "msg": "success", "data": {"session_id": sid, "messages": _chat_get_messages(sid)}})


def research_chat_session_delete_route(session_id: str):
    sid = str(session_id or "").strip()
    if not sid:
        return jsonify({"code": 400, "msg": "参数错误：session_id", "data": None})
    deleted = _chat_delete_session(sid)
    if not deleted:
        return jsonify({"code": 404, "msg": "会话不存在", "data": None})
    return jsonify({"code": 200, "msg": "success", "data": {"deleted": deleted}})

