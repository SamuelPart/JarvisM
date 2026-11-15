"""Open the first YouTube result in the browser; recover legacy mpv processes."""
import json
import os
import re
import shutil
import platform
from pathlib import Path
import psutil
import subprocess
import webbrowser


STATE = Path(__file__).resolve().parent / '.jarvis-music.json'


class MusicPlayer:
    def __init__(self):
        self.process = None

    def play(self, query):
        query = query.strip()
        if not query or len(query) > 300:
            raise ValueError('Indica una canción o artista (máximo 300 caracteres).')
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
        prior = self._stop_legacy()
        if prior.get('error'):
            return {'started': False, 'error': prior['error']}
        try:
            opened = webbrowser.open(url, new=2)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            return {'opened': False, 'error': 'No se pudo abrir el navegador.', 'url': url}
        return {'opened': True, 'title': title, 'url': url,
                'note': 'Se solicitó abrir YouTube en el navegador. No se ha confirmado la reproducción; el navegador puede exigir pulsar reproducir. Para pausarla puedes pedirlo a JARVIS si el navegador expone controles multimedia.'}

    def _clear_matching(self, pid):
        try:
            if json.loads(STATE.read_text(encoding='utf-8')).get('pid') == pid:
                STATE.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass

    def stop(self):
        """Pause one active browser media session, without toggle or guessing."""
        if platform.system() != 'Linux':
            legacy = self._stop_legacy()
            if legacy.get('stopped') or legacy.get('error'):
                return legacy
            return {'paused': False, 'note': 'La pausa automática del navegador solo está disponible en Linux; pausa la pestaña manualmente.'}
        playerctl = shutil.which('playerctl')
        if not playerctl:
            legacy = self._stop_legacy()
            if legacy.get('stopped') or legacy.get('error'):
                return legacy
            return {'paused': False, 'note': 'Falta playerctl. Instálalo para intentar pausar el navegador, o pausa la pestaña manualmente.'}
        try:
            listing = subprocess.run([playerctl, '--list-all'], capture_output=True, text=True, timeout=3, check=False)
            if listing.returncode and listing.stdout.strip():
                return {'paused': False, 'error': 'No se pudieron consultar los reproductores multimedia.'}
            names = [n for n in listing.stdout.splitlines()
                     if re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', n)
                     and n.lower().startswith(('chromium', 'chrome', 'firefox', 'brave', 'microsoft-edge'))]
            active, paused = [], []
            for name in names:
                status = subprocess.run([playerctl, '--player=' + name, 'status'], capture_output=True, text=True, timeout=3, check=False)
                if status.returncode:
                    return {'paused': False, 'error': 'No se pudo comprobar el estado del navegador.'}
                if status.stdout.strip() == 'Playing': active.append(name)
                elif status.stdout.strip() == 'Paused': paused.append(name)
            if len(active) > 1:
                return {'paused': False, 'error': 'Hay varios navegadores reproduciendo audio; pausa la pestaña deseada manualmente.'}
            if not active:
                legacy = self._stop_legacy()
                if legacy.get('stopped') or legacy.get('error'):
                    return legacy
                if len(paused) == 1:
                    return {'paused': True, 'already_paused': True, 'note': 'El navegador ya indica que está en pausa.'}
                return {'paused': False, 'note': 'No se encontró una sesión activa del navegador; pausa la pestaña manualmente.'}
            name = active[0]
            result = subprocess.run([playerctl, '--player=' + name, 'pause'], capture_output=True, text=True, timeout=3, check=False)
            if result.returncode:
                return {'paused': False, 'error': 'No se pudo pausar el navegador; pausa la pestaña manualmente.'}
            status = subprocess.run([playerctl, '--player=' + name, 'status'], capture_output=True, text=True, timeout=3, check=False)
            if not status.returncode and status.stdout.strip() in ('Paused', 'Stopped'):
                return {'paused': True, 'note': 'El navegador informa que su reproducción se pausó. Puede tratarse de otra pestaña.'}
            return {'paused': False, 'error': 'Se solicitó la pausa, pero no se pudo confirmar; revisa el navegador.'}
        except (OSError, subprocess.TimeoutExpired):
            return {'paused': False, 'error': 'No se pudieron consultar o pausar los controles multimedia.'}

    def _stop_legacy(self):
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
                return {'stopped': True, 'note': 'Se detuvo mpv anterior. Esto no detiene pestañas de YouTube; páusalas o ciérralas manualmente.'}
        try:
            info = json.loads(STATE.read_text(encoding='utf-8'))
            pid, created, marker = info['pid'], info['created'], info['marker']
            if not isinstance(pid, int) or pid <= 0 or not isinstance(created, (int, float)) or not isinstance(marker, str) or not re.fullmatch(r'--title=JARVIS-[0-9a-f]{32}', marker):
                raise ValueError('Registro inválido')
            process = psutil.Process(pid)
            if process.create_time() != created or marker not in process.cmdline():
                self._clear_matching(pid)
                return {'stopped': False, 'note': 'No se encontró un reproductor mpv anterior de JARVIS. Si la música está en el navegador, pausa o cierra la pestaña de YouTube.'}
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            self._clear_matching(pid)
            return {'stopped': True, 'note': 'Se detuvo mpv anterior. Esto no detiene pestañas de YouTube; páusalas o ciérralas manualmente.'}
        except FileNotFoundError:
            return {'stopped': False, 'note': 'No se encontró un reproductor mpv anterior de JARVIS. Si la música está en el navegador, pausa o cierra la pestaña de YouTube.'}
        except psutil.NoSuchProcess:
            self._clear_matching(pid)
            return {'stopped': False, 'note': 'No se encontró un reproductor mpv anterior de JARVIS. Si la música está en el navegador, pausa o cierra la pestaña de YouTube.'}
        except (psutil.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            return {'stopped': False, 'error': 'No se pudo verificar o detener el reproductor guardado; comprueba mpv en el sistema.'}
