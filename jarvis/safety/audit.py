"""Audit log append-only con cadena de hashes SHA-256.

Cada entrada incluye el hash de la anterior: si alguien borra o modifica una
fila, `verify()` lo detecta. No sustituye a un firmado criptográfico con clave
externa (Fase 8), pero cubre la manipulación casual y los bugs.

La base vive en ~/.local/share/jarvis/audit.sqlite3 con permisos 700/600.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    -- Sin AUTOINCREMENT a propósito: el `seq` se calcula de forma explícita porque
    -- forma parte del hash. Con AUTOINCREMENT, sqlite_sequence puede devolver un
    -- valor distinto del que usamos al calcular la cadena (tras un purgado, por
    -- ejemplo) y la verificación fallaría sin que nadie hubiera manipulado nada.
    seq        INTEGER PRIMARY KEY,
    ts         REAL    NOT NULL,
    kind       TEXT    NOT NULL,
    tier       TEXT,
    decision   TEXT,
    skill      TEXT,
    detail     TEXT    NOT NULL,
    prev_hash  TEXT    NOT NULL,
    hash       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS idx_audit_kind ON audit(kind);
CREATE INDEX IF NOT EXISTS idx_audit_skill ON audit(skill);
"""


@dataclass(slots=True)
class AuditEntry:
    seq: int
    ts: float
    kind: str
    tier: str | None
    decision: str | None
    skill: str | None
    detail: dict[str, Any]
    prev_hash: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["time_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts))
        return data


def _compute(
    seq: int,
    ts: float,
    kind: str,
    tier: str | None,
    decision: str | None,
    skill: str | None,
    detail: str,
    prev_hash: str,
) -> str:
    payload = f"{seq}|{ts:.6f}|{kind}|{tier}|{decision}|{skill}|{detail}|{prev_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=FULL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        with contextlib.suppress(OSError):  # pragma: no cover - Windows
            self.path.chmod(0o600)
        self._last_hash = self._tail_hash()

    def _tail_hash(self) -> str:
        row = self._conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        return row["hash"] if row else GENESIS_HASH

    def _next_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq),0)+1 AS n FROM audit").fetchone()
        return int(row["n"])

    def record(
        self,
        kind: str,
        *,
        tier: str | None = None,
        decision: str | None = None,
        skill: str | None = None,
        **detail: Any,
    ) -> AuditEntry:
        """Añade una entrada. `detail` se serializa de forma determinista."""
        detail_json = json.dumps(detail, sort_keys=True, ensure_ascii=False, default=str)
        seq = self._next_seq()
        ts = time.time()
        prev_hash = self._last_hash
        entry_hash = _compute(seq, ts, kind, tier, decision, skill, detail_json, prev_hash)
        self._conn.execute(
            "INSERT INTO audit (seq,ts,kind,tier,decision,skill,detail,prev_hash,hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (seq, ts, kind, tier, decision, skill, detail_json, prev_hash, entry_hash),
        )
        self._conn.commit()
        self._last_hash = entry_hash
        return AuditEntry(seq, ts, kind, tier, decision, skill, detail, prev_hash, entry_hash)

    def tail(self, n: int = 20, kind: str | None = None) -> list[AuditEntry]:
        query = "SELECT * FROM audit"
        params: list[Any] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY seq DESC LIMIT ?"
        params.append(n)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_entry(r) for r in reversed(rows)]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
        return AuditEntry(
            seq=row["seq"],
            ts=row["ts"],
            kind=row["kind"],
            tier=row["tier"],
            decision=row["decision"],
            skill=row["skill"],
            detail=json.loads(row["detail"]),
            prev_hash=row["prev_hash"],
            hash=row["hash"],
        )

    def verify(self) -> tuple[bool, str]:
        """Recalcula toda la cadena. Devuelve (ok, mensaje)."""
        prev = GENESIS_HASH
        count = 0
        for row in self._conn.execute("SELECT * FROM audit ORDER BY seq ASC"):
            count += 1
            if row["prev_hash"] != prev:
                return False, f"rotura en seq={row['seq']}: prev_hash no enlaza con la entrada anterior"
            expected = _compute(
                row["seq"],
                row["ts"],
                row["kind"],
                row["tier"],
                row["decision"],
                row["skill"],
                row["detail"],
                row["prev_hash"],
            )
            if expected != row["hash"]:
                return False, f"entrada seq={row['seq']} modificada (hash no coincide)"
            prev = row["hash"]
        return True, f"cadena íntegra: {count} entradas verificadas"

    def purge_older_than(self, days: int) -> int:
        """Borra el historial antiguo y **re-ancla** la cadena de lo que sobrevive.

        Purgar es una operación legítima del usuario (`--purge-older-than`), así que
        el log debe seguir siendo verificable después. Tras borrar, se recalcula la
        cadena de las entradas supervivientes y se registra el propio purgado como
        una entrada nueva: no se puede hacer desaparecer historial en silencio.

        Nota de seguridad: quien tenga acceso de escritura al fichero puede re-hacer
        la cadena entera, con purga o sin ella. Para eso está el anclaje externo
        (Fase 8), no el hash por sí solo.
        """
        cutoff = time.time() - days * 86_400
        deleted = int(
            self._conn.execute("SELECT COUNT(*) AS n FROM audit WHERE ts < ?", (cutoff,)).fetchone()["n"]
        )
        if deleted == 0:
            return 0
        self._conn.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
        self._reanchor()
        self._conn.commit()
        self.record("audit.purged", entries=deleted, days=days)
        return deleted

    def _reanchor(self) -> None:
        """Recalcula prev_hash/hash de las entradas supervivientes en orden."""
        prev = GENESIS_HASH
        for row in self._conn.execute("SELECT * FROM audit ORDER BY seq ASC"):
            new_hash = _compute(
                row["seq"],
                row["ts"],
                row["kind"],
                row["tier"],
                row["decision"],
                row["skill"],
                row["detail"],
                prev,
            )
            if row["prev_hash"] != prev or row["hash"] != new_hash:
                self._conn.execute(
                    "UPDATE audit SET prev_hash = ?, hash = ? WHERE seq = ?",
                    (prev, new_hash, row["seq"]),
                )
            prev = new_hash
        self._last_hash = prev

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"])

    def close(self) -> None:
        self._conn.close()
