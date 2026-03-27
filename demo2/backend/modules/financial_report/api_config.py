"""
财报分析 API 配置（模块内专用）
"""

from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


DEFAULT_API_TYPE = _env("DEFAULT_API_TYPE", "glm")
GLM_API_KEY = _env("GLM_API_KEY", "")
GLM_MODEL = _env("GLM_MODEL", "glm-4")
GLM_API_BASE = _env("GLM_API_BASE", "https://open.bigmodel.cn/api/paas/v4")

