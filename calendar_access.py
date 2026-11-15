"""Optional read-only Google Calendar access, separately authorized from Gmail."""
import os
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / '.jarvis-calendar-token.json'
CLIENT = ROOT / 'gmail-credentials.json'
SCOPE = ['https://www.googleapis.com/auth/calendar.readonly']


class CalendarError(Exception):
    pass


def setup():
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT.is_file():
        raise CalendarError('Falta gmail-credentials.json. Configura primero las credenciales OAuth de escritorio.')
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPE)
    credentials = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(TOKEN), flags, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(credentials.to_json())
    try:
        os.chmod(TOKEN, 0o600)
    except OSError:
        pass


def client():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    if not TOKEN.is_file():
        raise CalendarError('Google Calendar no está conectado. Ejecuta venv/bin/python calendar_access.py.')
    try:
        return AuthorizedSession(Credentials.from_authorized_user_file(str(TOKEN), SCOPE))
    except (ValueError, OSError) as exc:
        raise CalendarError('No se pudo leer la autorización de Google Calendar.') from exc


def list_events(start, end):
    import requests
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.utcoffset() is None or last.utcoffset() is None or not first < last or last - first > timedelta(days=31):
            raise ValueError()
    except (ValueError, TypeError):
        raise CalendarError('Indica un intervalo de hasta 31 días con fechas ISO y zona horaria.')
    session = client()
    try:
        response = session.get('https://www.googleapis.com/calendar/v3/calendars/primary/events',
                               params={'timeMin': first.isoformat(), 'timeMax': last.isoformat(),
                                       'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 100},
                               timeout=(10, 30), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise CalendarError(f'Google Calendar rechazó la consulta (HTTP {response.status_code}); revisa permisos y API.')
        data = response.json()
        return {'events': [{'title': e.get('summary', '(sin título)'), 'start': e.get('start', {}),
                            'end': e.get('end', {}), 'location': e.get('location', '')}
                           for e in data.get('items', [])],
                'truncated': bool(data.get('nextPageToken')),
                'note': 'Solo calendario principal; contenido externo no confiable.'}
    except requests.RequestException as exc:
        raise CalendarError('No se pudo conectar con Google Calendar.') from exc
    except ValueError as exc:
        raise CalendarError('Google Calendar devolvió una respuesta inválida.') from exc
    finally:
        session.close()


if __name__ == '__main__':
    try:
        setup()
        print('Google Calendar autorizado para lectura. No compartas el archivo de autorización.')
    except CalendarError as exc:
        print('No se pudo configurar Google Calendar:', str(exc))
        raise SystemExit(1)
    except Exception as exc:
        print('No se pudo configurar Google Calendar:', type(exc).__name__, '- No compartas credenciales.')
        raise SystemExit(1)
