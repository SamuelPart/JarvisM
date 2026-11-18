"""Local one-shot reminders with transactional claiming across instances."""
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / '.jarvis-agenda.sqlite3'


class Agenda:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('JARVIS_AGENDA_PATH', str(DEFAULT_PATH))).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, due INTEGER NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0
            )''')
        try: os.chmod(self.path, 0o600)
        except OSError: pass

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.execute('PRAGMA secure_delete=ON')
        return db

    def add(self, title, timestamp, now=None):
        title = title.strip()
        now = time.time() if now is None else now
        if not title or len(title) > 300: raise ValueError('La descripción debe tener entre 1 y 300 caracteres.')
        if not isinstance(timestamp, (int, float)) or timestamp <= now: raise ValueError('Elige una fecha y hora futuras.')
        with closing(self._connect()) as db, db:
            cursor = db.execute('INSERT INTO reminders(title, due) VALUES (?, ?)', (title, int(timestamp)))
            return cursor.lastrowid

    def list(self):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT id, title, due, notified FROM reminders ORDER BY due, id').fetchall()
        return [{'id': row[0], 'title': row[1], 'due': row[2], 'notified': bool(row[3])} for row in rows]

    def delete(self, reminder_id):
        with closing(self._connect()) as db, db:
            return db.execute('DELETE FROM reminders WHERE id = ?', (reminder_id,)).rowcount > 0

    def delete_matching(self, reminder_id, title, due):
        """Delete only if the reminder is still the one the user selected."""
        with closing(self._connect()) as db, db:
            return db.execute('DELETE FROM reminders WHERE id = ? AND title = ? AND due = ?',
                              (reminder_id, title, due)).rowcount > 0

    def claim_due(self, now=None, limit=20):
        now = time.time() if now is None else now
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id, title, due FROM reminders WHERE notified=0 AND due<=? ORDER BY due, id LIMIT ?', (int(now), limit)).fetchall()
            db.executemany('UPDATE reminders SET notified=1 WHERE id=?', [(r[0],) for r in rows])
            db.commit()
        return [{'id': row[0], 'title': row[1], 'due': row[2]} for row in rows]


def timestamp_from_iso(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('Usa fecha y hora ISO con zona horaria, por ejemplo 2026-12-01T15:30:00-05:00.') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Incluye la zona horaria o desplazamiento UTC en la fecha.')
    return parsed.timestamp()
