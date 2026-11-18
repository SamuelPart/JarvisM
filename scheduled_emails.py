"""Local scheduled Gmail queue; no automatic retry after an uncertain send."""
from __future__ import annotations
import calendar
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import gmail_access
import permissions
from agenda import timestamp_from_iso

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / '.jarvis-scheduled-email.sqlite3'
NUMBERS = {'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
           'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9,
           'diez': 10, 'once': 11, 'doce': 12, 'quince': 15, 'veinte': 20,
           'treinta': 30, 'cincuenta': 50, 'sesenta': 60}


def _local_wall_timestamp(wall):
    candidates = set()
    for dst in (0, 1):
        try:
            ts = time.mktime((*wall, -1, -1, dst))
            if time.localtime(ts)[:6] == wall:
                candidates.add(ts)
        except (OverflowError, OSError, ValueError):
            pass
    if len(candidates) != 1:
        raise ValueError('La hora local es ambigua o no existe por un cambio horario. Dime otra hora.')
    return candidates.pop()


def resolve_when(value, now=None):
    """Resolve ISO or explicit Spanish duration, using calendar months/years."""
    if not isinstance(value, str):
        raise ValueError('Necesito saber cuándo quieres enviarlo.')
    text = value.strip().casefold()
    units = r'(segundos?|minutos?|horas?|d[ií]as?|semanas?|mes(?:es)?|a[nñ]os?)'
    match = re.fullmatch(r'(?:dentro\s+de|en)\s+(\d{1,4}|[a-záéíóúñ]+)\s+' + units, text)
    current = datetime.now().astimezone() if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('El reloj necesita una zona horaria local válida.')
    if not match:
        try:
            timestamp = timestamp_from_iso(value)
        except ValueError as exc:
            raise ValueError('No entendí cuándo enviarlo. Dime, por ejemplo, dentro de diez minutos o una fecha y hora.') from exc
    else:
        number, unit = match.groups()
        amount = int(number) if number.isdecimal() else NUMBERS.get(number)
        if amount is None or amount <= 0:
            raise ValueError('Indica una cantidad de tiempo válida y futura.')
        if unit.startswith(('mes', 'año', 'ano')):
            months = amount * (12 if unit.startswith(('año', 'ano')) else 1)
            month_index = current.year * 12 + current.month - 1 + months
            year, month0 = divmod(month_index, 12)
            month = month0 + 1
            if not 1 <= year <= 9999 or current.day > calendar.monthrange(year, month)[1]:
                raise ValueError('Esa fecha no existe en el mes de destino. Dime una fecha y hora concreta.')
            # Use the machine's local zone for the target date, including DST.
            wall = (year, month, current.day, current.hour, current.minute, current.second)
            timestamp = _local_wall_timestamp(wall)
        elif unit.startswith(('día', 'dia', 'semana')):
            days = amount * (7 if unit.startswith('semana') else 1)
            try:
                target = current.replace(tzinfo=None) + timedelta(days=days)
            except OverflowError as exc:
                raise ValueError('Esa fecha está fuera del rango permitido.') from exc
            timestamp = _local_wall_timestamp((target.year, target.month, target.day,
                                               target.hour, target.minute, target.second))
        else:
            scale = 1 if unit.startswith('segundo') else 60 if unit.startswith('minuto') else 3600
            timestamp = current.timestamp() + amount * scale
    if timestamp <= current.timestamp():
        raise ValueError('La fecha de envío debe ser futura.')
    return int(timestamp)


class ScheduledEmails:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv('JARVIS_SCHEDULED_EMAIL_PATH', str(DEFAULT_PATH))).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with closing(self._connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS scheduled_email (
                id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                body TEXT NOT NULL, due INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                message_id TEXT NOT NULL DEFAULT '')''')

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.execute('PRAGMA secure_delete=ON')
        return db

    def add(self, to, subject, body, when, now=None):
        gmail_access.validate_message(to, subject, body)
        due = resolve_when(when, now)
        if not gmail_access.TOKEN.is_file():
            raise gmail_access.GmailError('Gmail no está configurado en JARVIS; primero conecta tu cuenta.')
        with closing(self._connect()) as db, db:
            row = db.execute('INSERT INTO scheduled_email(recipient, subject, body, due) VALUES (?, ?, ?, ?)',
                             (to, subject, body, due))
            identifier = row.lastrowid
        return {'scheduled': True, 'id': identifier, 'to': to, 'subject': subject,
                'when': datetime.fromtimestamp(due).astimezone().isoformat(timespec='seconds'),
                'note': 'Guardado localmente; se envía solo si JARVIS está abierto y tiene conexión. Si estuvo cerrado, intentará enviarlo al abrirlo.'}

    def list(self):
        with closing(self._connect()) as db:
            rows = db.execute('SELECT id, recipient, subject, due, state FROM scheduled_email ORDER BY due, id LIMIT 100').fetchall()
        return [{'id': r[0], 'to': r[1], 'subject': r[2],
                 'when': datetime.fromtimestamp(r[3]).astimezone().isoformat(timespec='seconds'), 'state': r[4]} for r in rows]

    def cancel(self, identifier, to, subject, when):
        if type(identifier) is not int or identifier <= 0:
            raise ValueError('Correo programado no válido.')
        due = int(timestamp_from_iso(when))
        with closing(self._connect()) as db, db:
            count = db.execute("UPDATE scheduled_email SET state='cancelled', body='' WHERE id=? AND recipient=? AND subject=? AND due=? AND state='pending'",
                               (identifier, to, subject, due)).rowcount
        return {'cancelled': bool(count), 'note': 'Solo se pueden cancelar correos pendientes; puede que ya se estén enviando.'}

    def claim_one(self, now=None):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id, recipient, subject, body FROM scheduled_email WHERE state='pending' AND due<=? ORDER BY due, id LIMIT 1", (int(time.time() if now is None else now),)).fetchone()
            if row:
                db.execute("UPDATE scheduled_email SET state='sending' WHERE id=? AND state='pending'", (row[0],))
            db.commit()
        return row

    def release(self, identifier):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE scheduled_email SET state='pending' WHERE id=? AND state='sending'", (identifier,))

    def finish(self, identifier, state, message_id=''):
        if state not in ('sent', 'uncertain'):
            raise ValueError('Estado no válido.')
        with closing(self._connect()) as db, db:
            db.execute("UPDATE scheduled_email SET state=?, message_id=?, body=CASE WHEN ?='sent' THEN '' ELSE body END WHERE id=? AND state='sending'",
                       (state, message_id, state, identifier))


def process_one(queue=None, sender=None):
    """Claim at most once; any failure is uncertain and is never retried."""
    if permissions.read_state().get('scheduled_email_accepted') is not True:
        return None
    queue = queue or ScheduledEmails()
    item = queue.claim_one()
    if item is None:
        return None
    identifier, to, subject, body = item
    if permissions.read_state().get('scheduled_email_accepted') is not True:
        queue.release(identifier)
        return None
    try:
        result = (sender or gmail_access.send_message)(to, subject, body)
        if not isinstance(result, dict) or result.get('sent') is not True or not result.get('message_id'):
            raise ValueError('No confirmation')
        queue.finish(identifier, 'sent', str(result['message_id'])[:200])
        return {'state': 'sent', 'id': identifier, 'to': to, 'subject': subject}
    except Exception:
        try:
            queue.finish(identifier, 'uncertain')
        except (OSError, sqlite3.Error):
            pass  # 'sending' is also terminal and requires manual review.
        return {'state': 'uncertain', 'id': identifier, 'to': to, 'subject': subject}


class Scheduler:
    def __init__(self, notify=lambda _: None):
        self.notify = notify
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        def run():
            try:
                for item in ScheduledEmails().list():
                    if item['state'] in ('sending', 'uncertain'):
                        self.notify({'state': 'needs_review', 'to': item['to'], 'subject': item['subject']})
            except (OSError, sqlite3.Error):
                pass
            while not self.stop_event.is_set():
                try:
                    result = process_one()
                    if result:
                        self.notify(result)
                        continue
                except (OSError, sqlite3.Error):
                    pass
                self.stop_event.wait(5)
        self.thread = threading.Thread(target=run, name='JARVIS correos programados', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
