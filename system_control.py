"""System tools. The caller must ask the user before EVERY tool invocation.

This is not a sandbox: terminal commands and GUI automation have the full
permissions of the current user. Never run this program as administrator.
"""
from __future__ import annotations
import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import psutil


class SystemController:
    def __init__(self):
        self.system = platform.system()
        if self.system not in ('Windows', 'Linux'):
            raise RuntimeError('Solo Windows y Linux son compatibles.')

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

    def web_search(self, query: str) -> dict:
        if not query.strip(): raise ValueError('La consulta está vacía.')
        url = 'https://www.google.com/search?q=' + quote_plus(query)
        return {'opened': webbrowser.open(url), 'url': url, 'note': 'Consulta abierta en el navegador; no se han leído resultados.'}

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
