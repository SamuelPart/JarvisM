"""Local YouTube audio playback using yt-dlp metadata and mpv."""
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
import psutil
import shutil
import subprocess
from urllib.parse import urlsplit


STATE = Path(__file__).resolve().parent / '.jarvis-music.json'


class MusicPlayer:
    def __init__(self):
        self.process = None

    def play(self, query):
        query = query.strip()
        if not query or len(query) > 300:
            raise ValueError('Indica una canción o artista (máximo 300 caracteres).')
        mpv = shutil.which('mpv')
        if not mpv:
            return {'started': False, 'error': 'Falta mpv. En Kali instala mpv con sudo apt install mpv.'}
        try:
            import yt_dlp
            options = {'quiet': True, 'no_warnings': True, 'format': 'bestaudio/best',
                       'socket_timeout': 15, 'retries': 1, 'noplaylist': True}
            with yt_dlp.YoutubeDL(options) as ydl:
                search = ydl.extract_info('ytsearch1:' + query, download=False)
            entry = next((x for x in (search.get('entries') or []) if x), None)
            if not entry:
                return {'started': False, 'error': 'No se encontraron canciones.'}
            url = entry.get('url') or ''
            parsed = urlsplit(url)
            host = (parsed.hostname or '').lower()
            if parsed.scheme != 'https' or not host.endswith('.googlevideo.com') or parsed.username or parsed.password:
                return {'started': False, 'error': 'No se pudo obtener un audio compatible de YouTube.'}
            title = str(entry.get('title') or query)[:300]
        except Exception:
            return {'started': False, 'error': 'No se pudo obtener la canción de YouTube. Revisa la conexión o intenta otra búsqueda.'}
        prior = self.stop()
        if prior.get('error'):
            return {'started': False, 'error': prior['error']}
        marker = '--title=JARVIS-' + uuid.uuid4().hex
        try:
            # A separate session lets playback survive a normal JARVIS/terminal exit.
            detach = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
                      if os.name == 'nt' else {'start_new_session': True})
            self.process = subprocess.Popen([mpv, '--no-video', '--ytdl=no', '--no-terminal', marker, url],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            **detach)
        except OSError:
            return {'started': False, 'error': 'No se pudo iniciar mpv.'}
        try:
            self._save_process(self.process.pid, marker)
        except (OSError, psutil.Error):
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process = None
            return {'started': False, 'error': 'No se pudo registrar el reproductor; se detuvo por seguridad.'}
        return {'started': True, 'title': title,
                'note': 'Se inició el reproductor; si no oyes audio revisa el dispositivo de salida. La disponibilidad depende de YouTube.'}

    def _save_process(self, pid, marker):
        info = {'pid': pid, 'created': psutil.Process(pid).create_time(), 'marker': marker}
        name = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=STATE.parent, delete=False) as file:
                name = file.name
                json.dump(info, file)
            os.replace(name, STATE)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def _clear_matching(self, pid):
        try:
            if json.loads(STATE.read_text(encoding='utf-8')).get('pid') == pid:
                STATE.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass

    def stop(self):
        if self.process is not None:
            process = self.process
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    stopped = True
                else:
                    stopped = False
            except (OSError, subprocess.TimeoutExpired):
                return {'stopped': False, 'error': 'No se pudo detener el reproductor de JARVIS.'}
            self._clear_matching(process.pid)
            self.process = None
            if stopped:
                return {'stopped': True}
        try:
            info = json.loads(STATE.read_text(encoding='utf-8'))
            pid, created, marker = info['pid'], info['created'], info['marker']
            if not isinstance(pid, int) or pid <= 0 or not isinstance(created, (int, float)) or not isinstance(marker, str) or not re.fullmatch(r'--title=JARVIS-[0-9a-f]{32}', marker):
                raise ValueError('Registro inválido')
            process = psutil.Process(pid)
            if process.create_time() != created or marker not in process.cmdline():
                self._clear_matching(pid)
                return {'stopped': False, 'note': 'No hay reproducción de JARVIS en curso.'}
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            self._clear_matching(pid)
            return {'stopped': True}
        except FileNotFoundError:
            return {'stopped': False, 'note': 'No hay reproducción de JARVIS en curso.'}
        except psutil.NoSuchProcess:
            self._clear_matching(pid)
            return {'stopped': False, 'note': 'No hay reproducción de JARVIS en curso.'}
        except (psutil.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            return {'stopped': False, 'error': 'No se pudo verificar o detener el reproductor guardado; comprueba mpv en el sistema.'}
