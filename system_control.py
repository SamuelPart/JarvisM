"""System tools. The caller must ask the user before EVERY tool invocation.

This is not a sandbox: terminal commands and GUI automation have the full
permissions of the current user. Never run this program as administrator.
"""
from __future__ import annotations
import os
import io
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse

import psutil
from datetime import datetime
from agenda import Agenda, timestamp_from_iso
from web_search import search
from music_player import MusicPlayer
from nvidia_vision import read_image, analyze, validate_image, VisionError
import gmail_access
import calendar_access
import startup_briefing


class SystemController:
    def __init__(self):
        self.system = platform.system()
        if self.system not in ('Windows', 'Linux'):
            raise RuntimeError('Solo Windows y Linux son compatibles.')
        self.music = MusicPlayer()

    def current_time(self) -> dict:
        return {'local_time': datetime.now().astimezone().isoformat(timespec='seconds')}

    def review_startup_logs(self) -> dict:
        return startup_briefing.log_details()

    def list_reminders(self) -> dict:
        reminders = Agenda().list()
        return {'reminders': [{'id': r['id'], 'title': r['title'],
                               'when': datetime.fromtimestamp(r['due']).astimezone().isoformat(timespec='seconds'),
                               'notified': r['notified']} for r in reminders]}

    def list_calendar_events(self, start: str, end: str) -> dict:
        return calendar_access.list_events(start, end)

    def create_reminder(self, title: str, when: str) -> dict:
        """Create a one-shot local reminder after explicit user authorization."""
        due = timestamp_from_iso(when)
        reminder_id = Agenda().add(title, due)
        return {'id': reminder_id, 'title': title, 'when': when,
                'note': 'Aviso local; JARVIS debe estar abierto para notificar a tiempo.'}

    def terminal(self, command: str) -> dict:
        """Execute a shell command after explicit interactive authorization."""
        if not command.strip() or len(command) > 4000:
            raise ValueError('Comando vacío o demasiado largo.')
        args = (['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command]
                if self.system == 'Windows' else ['/bin/bash', '-c', command])
        try:
            result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=30)
        except subprocess.TimeoutExpired:
            return {'error': 'Tiempo agotado. Los procesos secundarios podrían continuar ejecutándose.'}
        return {'returncode': result.returncode, 'stdout': result.stdout[-12000:], 'stderr': result.stderr[-12000:]}

    def files(self, action: str, path: str, destination: str = '', content: str = '', pattern: str = '*') -> dict:
        """Create, read, write, list, move or search files; deletion is via terminal."""
        p = Path(path).expanduser()
        if action == 'mkdir':
            p.mkdir(parents=True, exist_ok=True)
        elif action == 'create':
            with p.open('x', encoding='utf-8') as file:
                file.write(content)
        elif action == 'write':
            p.write_text(content, encoding='utf-8')
        elif action == 'read':
            if p.stat().st_size > 1_000_000:
                raise ValueError('El archivo supera 1 MB.')
            return {'content': p.read_text(encoding='utf-8')[:12000]}
        elif action == 'list':
            return {'entries': sorted(item.name for item in p.iterdir())[:200]}
        elif action == 'move':
            if not destination:
                raise ValueError('Se requiere destination.')
            return {'destination': shutil.move(str(p), str(Path(destination).expanduser()))}
        elif action == 'search':
            # Limit results and directory traversal so a broad search does not run forever.
            if not p.is_dir():
                raise ValueError('La búsqueda requiere una carpeta.')
            import fnmatch
            found, visited = [], 0
            for root, dirs, names in os.walk(p, followlinks=False):
                visited += 1
                if visited > 1000:
                    break
                for name in dirs + names:
                    if fnmatch.fnmatch(name, pattern):
                        found.append(str(Path(root) / name))
                        if len(found) >= 200:
                            return {'matches': found, 'truncated': True}
            return {'matches': found, 'truncated': visited > 1000}
        else:
            raise ValueError('Acción no reconocida: mkdir, create, write, read, list, move, search.')
        return {'ok': True, 'path': str(p)}

    def gui(self, action: str, x: int = 0, y: int = 0, text: str = '') -> dict:
        """Control mouse or keyboard in an available graphical session."""
        import pyautogui
        if action == 'click': pyautogui.click(x, y)
        elif action == 'move': pyautogui.moveTo(x, y, duration=0.2)
        elif action == 'type': pyautogui.write(text, interval=0.01)
        elif action == 'hotkey':
            keys = [k.strip() for k in text.split('+') if k.strip()]
            if not 1 <= len(keys) <= 4: raise ValueError('Atajo inválido.')
            pyautogui.hotkey(*keys)
        else: raise ValueError('Acción GUI no reconocida.')
        return {'ok': True}

    def open_url(self, url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('Solo se permiten URL HTTP o HTTPS válidas.')
        return {'opened': webbrowser.open(url)}

    def whatsapp_prepare(self, phone: str, message: str) -> dict:
        """Open a WhatsApp draft; the user must review and send it manually."""
        phone = phone.strip()
        if not re.fullmatch(r'\+?[1-9][0-9]{6,14}', phone):
            raise ValueError('Indique el número internacional con código de país y solo dígitos.')
        if not message.strip() or len(message) > 4000:
            raise ValueError('El mensaje debe tener entre 1 y 4000 caracteres.')
        url = 'https://wa.me/' + phone.lstrip('+') + '?text=' + quote_plus(message)
        opened = webbrowser.open(url)
        return {'opened': opened, 'sent': False,
                'note': 'Se solicitó abrir un borrador. El usuario debe revisar el destinatario y pulsar Enviar.'}

    def inspect_image(self, path: str, question: str = 'Describe esta imagen en español.') -> dict:
        """After consent, read the requested image and send it to NVIDIA for analysis."""
        if not path.strip():
            raise ValueError('Se necesita la ruta de una imagen.')
        image = read_image(path)
        return {'description': analyze(image, question),
                'note': 'La imagen y la pregunta se enviaron a NVIDIA. La descripción puede enviarse al proveedor del chat.'}

    def search_gmail(self, query: str) -> dict:
        return gmail_access.search_messages(query)

    def read_gmail(self, message_id: str) -> dict:
        return gmail_access.read_message(message_id)

    def send_gmail(self, to: str, subject: str, body: str) -> dict:
        return gmail_access.send_message(to, subject, body)

    def reply_gmail(self, message_id: str, to: str, subject: str, body: str) -> dict:
        return gmail_access.reply_message(message_id, to, subject, body)

    def classify_gmail(self, message_id: str, sender: str, subject: str, category: str) -> dict:
        return gmail_access.classify_message(message_id, sender, subject, category)

    def inspect_gmail_image(self, message_id: str, part_id: str, question: str = 'Describe esta imagen en español.') -> dict:
        return gmail_access.inspect_attachment(message_id, part_id, question)

    def inspect_screen(self, question: str = 'Describe lo que aparece en pantalla en español.') -> dict:
        """Capture visible screen only after consent; send the capture to NVIDIA."""
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            output = io.BytesIO()
            screenshot.save(output, format='PNG')
            image = validate_image(output.getvalue())
        except VisionError:
            raise
        except Exception as exc:
            raise VisionError('No se pudo capturar la pantalla. Comprueba que haya una sesión gráfica compatible.') from exc
        return {'description': analyze(image, question),
                'note': 'La captura de pantalla y la pregunta se enviaron a NVIDIA. La descripción puede enviarse al proveedor del chat.'}

    def play_music(self, query: str) -> dict:
        return self.music.play(query)

    def stop_music(self) -> dict:
        return self.music.stop()

    def music_search(self, query: str, service: str = 'youtube') -> dict:
        """Open music search results; playback requires a user selection."""
        query = query.strip()
        if not query or len(query) > 300:
            raise ValueError('Indica el título o artista de la canción (máximo 300 caracteres).')
        if service == 'youtube':
            url = 'https://www.youtube.com/results?search_query=' + quote_plus(query)
        elif service == 'spotify':
            url = 'https://open.spotify.com/search/' + quote(query, safe='')
        else:
            raise ValueError('El servicio debe ser youtube o spotify.')
        opened = webbrowser.open(url)
        return {'opened': opened, 'service': service,
                'note': 'Se solicitó abrir los resultados. El usuario debe elegir y reproducir la canción; no se ha confirmado reproducción.'}

    def web_search(self, query: str) -> dict:
        """Return untrusted search snippets for the model to summarize with citations."""
        return search(query)

    def system_stats(self) -> dict:
        battery = psutil.sensors_battery()
        disk = psutil.disk_usage(Path.home().anchor or '/')
        return {'cpu_percent': psutil.cpu_percent(interval=0.2), 'memory_percent': psutil.virtual_memory().percent,
                'battery_percent': battery.percent if battery else None, 'disk_free_bytes': disk.free}

    def volume_brightness(self, target: str, value: int) -> dict:
        """Set volume or screen brightness (0–100) using OS-native facilities."""
        if not 0 <= value <= 100: raise ValueError('El valor debe estar entre 0 y 100.')
        if target not in ('volume', 'brightness'): raise ValueError('Destino inválido.')
        if self.system == 'Linux':
            command = (['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{value}%'] if target == 'volume'
                       else ['brightnessctl', 'set', f'{value}%'])
        elif target == 'brightness':
            command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                       f'(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{value})']
        else:
            raise RuntimeError('El ajuste de volumen en Windows requiere una integración de audio adicional; puede usar GUI o terminal con autorización.')
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, errors='replace')
        return {'returncode': result.returncode, 'stdout': result.stdout[-2000:], 'stderr': result.stderr[-2000:]}
