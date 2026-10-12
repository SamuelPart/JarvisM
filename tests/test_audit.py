"""Tests del audit log: la cadena de hashes debe detectar cualquier manipulación."""

from __future__ import annotations

import sqlite3

from jarvis.safety.audit import GENESIS_HASH, AuditLog


def test_records_and_chains(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.sqlite3")
    first = log.record("turn.started", turn_id="t1")
    second = log.record("tool.executed", skill="system.info", tier="T0", decision="allow")
    assert first.prev_hash == GENESIS_HASH
    assert second.prev_hash == first.hash
    assert first.hash != second.hash
    log.close()


def test_verify_detects_tampering(tmp_path) -> None:
    path = tmp_path / "a.sqlite3"
    log = AuditLog(path)
    for i in range(5):
        log.record("event", n=i)
    log.close()

    # Manipulación directa de la base (el escenario que queremos detectar).
    conn = sqlite3.connect(path)
    conn.execute("UPDATE audit SET detail = '{\"n\": 999}' WHERE seq = 3")
    conn.commit()
    conn.close()

    reopened = AuditLog(path)
    ok, message = reopened.verify()
    assert not ok
    assert "modificada" in message
    reopened.close()


def test_verify_detects_deletion(tmp_path) -> None:
    path = tmp_path / "a.sqlite3"
    log = AuditLog(path)
    for i in range(4):
        log.record("event", n=i)
    log.close()

    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM audit WHERE seq = 2")
    conn.commit()
    conn.close()

    reopened = AuditLog(path)
    ok, message = reopened.verify()
    assert not ok
    assert "prev_hash" in message or "no enlaza" in message
    reopened.close()


def test_verify_ok_on_untouched_chain(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.sqlite3")
    for i in range(10):
        log.record("event", n=i, texto="áéíóú ñ")
    ok, message = log.verify()
    assert ok
    assert "10 entradas" in message
    log.close()


def test_tail_returns_most_recent(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.sqlite3")
    for i in range(7):
        log.record("event", n=i)
    recent = log.tail(3)
    assert [e.detail["n"] for e in recent] == [4, 5, 6]
    assert log.count() == 7
    log.close()


def test_purge_older_than_keeps_chain_valid(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.sqlite3")
    for i in range(3):
        log.record("old", n=i)
    log._conn.execute("UPDATE audit SET ts = ts - 86400 * 40")
    log._conn.commit()
    deleted = log.purge_older_than(30)
    assert deleted == 3
    ok, _ = log.verify()
    assert ok
    log.close()


def test_detail_is_serialized_deterministically(tmp_path) -> None:
    """El orden de claves no debe alterar el hash (json sort_keys)."""
    log = AuditLog(tmp_path / "a.sqlite3")
    log.record("event", b=2, a=1, c=3)
    log.record("event", c=3, a=1, b=2)
    ok, _ = log.verify()
    assert ok
    rows = log.tail(2)
    assert rows[0].detail == rows[1].detail
    log.close()
