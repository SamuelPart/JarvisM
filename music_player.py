"""Local YouTube audio playback using yt-dlp metadata and mpv."""
import re
import shutil
import subprocess
from urllib.parse import urlsplit


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
        self.stop()
        try:
            self.process = subprocess.Popen([mpv, '--no-video', '--ytdl=no', '--no-terminal', url],
                                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return {'started': False, 'error': 'No se pudo iniciar mpv.'}
        return {'started': True, 'title': title,
                'note': 'Se inició el reproductor; si no oyes audio revisa el dispositivo de salida. La disponibilidad depende de YouTube.'}

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process = None
            return {'stopped': True}
        self.process = None
        return {'stopped': False, 'note': 'No hay reproducción de JARVIS en curso.'}
