from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from flask import jsonify, request

from .analysis_service import AnalysisService
from .api_config import GLM_API_BASE, GLM_MODEL
from .session_store import InMemoryStore, SessionData, TaskInfo

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UPLOAD_DIR = os.path.join(BACKEND_ROOT, "analystgpt_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STORE = InMemoryStore()
SERVICE = AnalysisService(STORE)
EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _json_body() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def register_financial_report_routes(app) -> None:
    """
    财报分析 API（内置实现，不依赖外部 analystgpt-demo 目录）：
    - POST /api/upload
    - POST /api/analyze
    - GET  /api/tasks/:task_id
    - POST /api/regen
    """

    @app.route("/api/upload", methods=["POST", "OPTIONS"])
    def upload_financial_report():
        if request.method == "OPTIONS":
            return ("", 204)

        file = request.files.get("file")
        if not file:
            return jsonify({"error": "file is required"}), 400

        filename = file.filename or ""
        filename = str(filename).strip()
        if not filename.lower().endswith(".pdf"):
            return jsonify({"error": "Only .pdf is supported"}), 400

        session_id = uuid.uuid4().hex
        out_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")
        file.save(out_path)

        size = 0
        try:
            size = os.path.getsize(out_path)
        except Exception:
            size = 0

        STORE.create_session(
            session_id,
            SessionData(
                pdf_path=out_path,
                file_name=filename,
                file_size=int(size),
            ),
        )

        return jsonify({"sessionId": session_id, "fileInfo": {"name": filename, "size": int(size)}})

    @app.route("/api/analyze", methods=["POST", "OPTIONS"])
    def analyze_financial_report():
        if request.method == "OPTIONS":
            return ("", 204)

        payload = _json_body()
        session_id = (payload.get("sessionId") or "").strip()
        if not session_id:
            return jsonify({"error": "sessionId is required"}), 400

        try:
            STORE.get_session(session_id)
        except KeyError:
            return jsonify({"error": "session not found"}), 404

        task_id = uuid.uuid4().hex
        STORE.create_task(task_id, TaskInfo(status="queued", stage="排队中"))

        def stage_cb(s: str) -> None:
            STORE.update_task(task_id, stage=s, status="running")

        def run():
            try:
                STORE.update_task(task_id, status="running", stage="启动中")
                result = SERVICE.analyze_session(session_id, stage_cb=stage_cb)
                STORE.update_task(task_id, status="succeeded", stage="完成", result=result)
            except Exception as e:
                # 加前缀，便于快速判断是否命中当前财报模块代码
                STORE.update_task(task_id, status="failed", stage="失败", error=f"[FIN_REPORT] {e}")

        EXECUTOR.submit(run)
        return jsonify({"taskId": task_id, "engine": "financial_report_glm_only", "module": "fin_report_v3"})

    @app.route("/api/tasks/<task_id>", methods=["GET", "OPTIONS"])
    def get_financial_report_task(task_id: str):
        if request.method == "OPTIONS":
            return ("", 204)

        try:
            t = STORE.get_task(task_id)
        except KeyError:
            return jsonify({"error": "task not found"}), 404

        return jsonify({"status": t.status, "stage": t.stage, "error": t.error, "result": t.result})

    @app.route("/api/regen", methods=["POST", "OPTIONS"])
    def regen_financial_report():
        if request.method == "OPTIONS":
            return ("", 204)

        payload = _json_body()
        session_id = (payload.get("sessionId") or "").strip()
        page_index_raw = payload.get("pageIndex")
        if not session_id or page_index_raw is None:
            return jsonify({"error": "sessionId and pageIndex are required"}), 400

        try:
            page_index = int(page_index_raw)
        except Exception:
            return jsonify({"error": "pageIndex must be int"}), 400

        custom_question = payload.get("customQuestion")
        choice = payload.get("choice")

        try:
            out = SERVICE.regen_page(
                session_id,
                page_index,
                custom_question=custom_question,
                choice=choice,
            )
        except KeyError:
            return jsonify({"error": "session not found"}), 404
        except Exception as e:
            return jsonify({"error": f"[FIN_REPORT] {e}"}), 500

        return jsonify({"pages": out["pages"], "pageIndex": out["pageIndex"]})

    @app.route("/api/financial-report/debug", methods=["GET"])
    def financial_report_debug():
        base = (GLM_API_BASE or "").rstrip("/")
        model = GLM_MODEL or ""
        return jsonify(
            {
                "code": 200,
                "msg": "ok",
                "data": {
                    "module": "fin_report_v3",
                    "engine": "glm_only",
                    "glm_base": base,
                    "glm_model": model,
                },
            }
        )
