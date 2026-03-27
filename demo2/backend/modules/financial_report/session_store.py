from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionData:
    pdf_path: str
    file_name: str
    file_size: int
    extracted_text: str = ""
    pages: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    parsed: dict[str, Any] | None = None
    understanding: dict[str, Any] | None = None
    questions: list[dict[str, Any]] = field(default_factory=list)
    analyzer: Any = None


@dataclass
class TaskInfo:
    status: str
    stage: str
    error: str | None = None
    result: dict[str, Any] | None = None


class InMemoryStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
        self._tasks: dict[str, TaskInfo] = {}

    def create_session(self, session_id: str, data: SessionData) -> None:
        self._sessions[session_id] = data

    def get_session(self, session_id: str) -> SessionData:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        return self._sessions[session_id]

    def create_task(self, task_id: str, info: TaskInfo) -> None:
        self._tasks[task_id] = info

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        t = self._tasks[task_id]
        for k, v in kwargs.items():
            setattr(t, k, v)

    def get_task(self, task_id: str) -> TaskInfo:
        if task_id not in self._tasks:
            raise KeyError(task_id)
        return self._tasks[task_id]
