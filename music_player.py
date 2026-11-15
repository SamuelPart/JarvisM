"""Local YouTube audio playback using yt-dlp metadata and mpv."""
import json
import os
import re
import tempfile
import sys
import uuid
from pathlib import Path
import psutil
import shutil
import subprocess


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
            options = {'quiet': True, 'no_warnings': True, 'extract_flat': True,
                       'socket_timeout': 15, 'retries': 1, 'noplaylist': True}
            with yt_dlp.YoutubeDL(options) as ydl:
                search = ydl.extract_info('ytsearch1:' + query, download=False)
            entry = next((x for x in (search.get('entries') or []) if x), None)
            if not entry:
                return {'started': False, 'error': 'No se encontraron canciones.'}
            video_id = entry.get('id') or ''
            if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                return {'started': False, 'error': 'No se pudo identificar un video compatible de YouTube.'}
            url = 'https://www.youtube.com/watch?v=' + video_id
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
            env = os.environ.copy()
            env['PATH'] = str(Path(sys.executable).absolute().parent) + os.pathsep + env.get('PATH', '')
            self.process = subprocess.Popen([mpv, '--no-video', '--no-config', '--no-terminal', marker, url],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            env=env, **detach)
        except OSError:
            return {'started': False, 'error': 'No se pudo iniciar mpv.'}
        try:
            self._save_process(self.process.pid, marker)
        except (OSError, psutil.Error):
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.process = None
            return {'started': False, 'error': 'No se pudo registrar el reproductor o se cerró al iniciar.'}
        try:
            self.process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            return {'started': True, 'title': title,
                    'note': 'El reproductor sigue abierto, pero aún podría fallar al cargar; no se ha comprobado que se oiga el audio.'}
        self._clear_matching(self.process.pid)
        self.process = None
        return {'started': False, 'error': 'El reproductor se cerró al iniciar; revisa mpv, yt-dlp y la disponibilidad del video.'}

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
