from __future__ import annotations

from flask import Blueprint, jsonify

from core.utils import now_str

bp = Blueprint("ping", __name__, url_prefix="/api")


@bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"code": 200, "msg": "finance-backend", "data": {"time": now_str()}})
