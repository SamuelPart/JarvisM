"""Memoria conversacional.

Dos niveles por ahora (Fase 1):
  - memoria de trabajo: los mensajes del turno/sesión con truncado por tokens;
  - memoria de sesión: persistida en SQLite para poder retomarla y resumirla.

La memoria episódica/semántica con embeddings llega en Fase 5 (ver docs/02).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from jarvis.config.settings import Settings
from jarvis.providers.base import Message

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    session  TEXT NOT NULL,
    role     TEXT NOT NULL,
    content  TEXT NOT NULL,
    meta     TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session, ts);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at   REAL,
    summary    TEXT,
    turns      INTEGER DEFAULT 0,
    cost_usd   REAL DEFAULT 0
);
"""


def estimate_tokens(text: str) -> int:
    """Aproximación barata y suficiente para truncar (1 token ≈ 4 caracteres)."""
    return max(1, len(text) // 4)


class ConversationMemory:
    def __init__(self, settings: Settings, session_id: str | None = None) -> None:
        self.settings = settings
        self.session_id = session_id or time.strftime("s-%Y%m%d-%H%M%S")
        self.messages: list[Message] = []
        self.cost_usd = 0.0
        self._conn: sqlite3.Connection | None = None
        if settings.memory.persist_sessions:
            settings.ensure_dirs()
            self._conn = sqlite3.connect(settings.memory_db, check_same_thread=False)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            self._conn.execute(
                "INSERT INTO sessions (id, started_at) VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                (self.session_id, time.time()),
            )
            self._conn.commit()

    # -- API -------------------------------------------------------------- #
    def add(self, role: str, content: str, *, meta: dict[str, Any] | None = None) -> Message:
        message = Message(role=role, content=content)  # type: ignore[arg-type]
        self.messages.append(message)
        if self._conn is not None and content:
            self._conn.execute(
                "INSERT INTO turns (ts,session,role,content,meta) VALUES (?,?,?,?,?)",
                (time.time(), self.session_id, role, content, json.dumps(meta or {}, ensure_ascii=False)),
            )
            self._conn.commit()
        return message

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def history(self, *, system: str | None = None) -> list[Message]:
        """Devuelve el contexto a enviar al modelo, truncado por turnos y tokens."""
        trimmed = self._trim(self.messages)
        if system:
            return [Message(role="system", content=system), *trimmed]
        return trimmed

    def _trim(self, messages: list[Message]) -> list[Message]:
        limits = self.settings.memory
        recent = messages[-limits.max_turns_in_context :] if limits.max_turns_in_context else messages
        budget = limits.max_context_tokens
        out: list[Message] = []
        used = 0
        for message in reversed(recent):
            cost = estimate_tokens(message.content)
            if used + cost > budget and out:
                break
            out.insert(0, message)
            used += cost
        return out

    def context_tokens(self) -> int:
        return sum(estimate_tokens(m.content) for m in self._trim(self.messages))

    def add_cost(self, usd: float) -> None:
        self.cost_usd += usd

    # -- persistencia ----------------------------------------------------- #
    def close(self, summary: str = "") -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "UPDATE sessions SET ended_at=?, summary=?, turns=?, cost_usd=? WHERE id=?",
            (time.time(), summary, len(self.messages), round(self.cost_usd, 6), self.session_id),
        )
        self._conn.commit()
        self._conn.close()
        self._conn = None

    def recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT id, started_at, turns, cost_usd, summary FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(r[1])),
                "turns": r[2],
                "cost_usd": round(r[3] or 0.0, 5),
                "summary": r[4] or "",
            }
            for r in rows
        ]

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Búsqueda LIKE simple. La búsqueda semántica llega en Fase 5."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT ts, role, content FROM turns WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [
            {
                "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(r[0])),
                "role": r[1],
                "content": r[2][:300],
            }
            for r in rows
        ]


def memory_stats(path: Path) -> dict[str, Any]:
    """Estadísticas de la base de memoria sin abrirla en modo escritura."""
    if not path.is_file():
        return {"exists": False}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        return {
            "exists": True,
            "path": str(path),
            "size_kb": round(path.stat().st_size / 1024, 1),
            "sessions": sessions,
            "turns": turns,
        }
    finally:
        conn.close()
