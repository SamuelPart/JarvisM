"""Local persistent conversation and user-supplied preferences."""
import os
import sqlite3
from contextlib import closing
from pathlib import Path


class JarvisMemory:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            ''')
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute('PRAGMA secure_delete=ON')
        return db

    def recent(self, limit=20):
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError('Límite de memoria inválido')
        with closing(self._connect()) as db:
            rows = db.execute('SELECT role, content FROM (SELECT id, role, content FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id', (limit,)).fetchall()
        return [{'role': role, 'content': content} for role, content in rows]

    def add_turn(self, user, assistant):
        with closing(self._connect()) as db, db:
            db.executemany('INSERT INTO messages(role, content) VALUES (?, ?)',
                           [('user', user), ('assistant', assistant)])

    def get_preferences(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT value FROM preferences WHERE key='profile'").fetchone()
            return row[0] if row else ''

    def set_preferences(self, value):
        if len(value) > 2000:
            raise ValueError('Las preferencias no pueden superar 2000 caracteres.')
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO preferences(key, value) VALUES ('profile', ?)", (value.strip(),))

    def clear(self):
        with closing(self._connect()) as db, db:
            db.execute('DELETE FROM messages')
            db.execute('DELETE FROM preferences')
