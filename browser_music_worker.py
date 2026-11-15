"""Owns one isolated browser and accepts local, narrowly scoped music commands."""
import fcntl
import json
import os
import re
import socket
from urllib.parse import parse_qs, urlsplit
from browser_music import socket_path


class BrowserMusic:
    def __init__(self):
        self.engine = None
        self.browser = None
        self.page = None

    def _ensure_browser(self):
        if self.browser and self.browser.is_connected():
            return
        from playwright.sync_api import sync_playwright
        self.engine = sync_playwright().start()
        try:
            self.browser = self.engine.chromium.launch(headless=False, args=['--autoplay-policy=no-user-gesture-required'])
            context = self.browser.new_context()
            self.page = context.new_page()
        except Exception:
            self.engine.stop()
            self.engine = None
            raise

    def open(self, video_id):
        if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            return {'opened': False, 'error': 'ID de video inválido.'}
        try:
            self._ensure_browser()
            if self.page.is_closed():
                self.page = self.browser.contexts[0].new_page()
            self.page.goto('https://www.youtube.com/watch?v=' + video_id, wait_until='domcontentloaded', timeout=30000)
            parsed = urlsplit(self.page.url)
            if parsed.hostname not in ('www.youtube.com', 'youtube.com', 'm.youtube.com') or parse_qs(parsed.query).get('v') != [video_id]:
                return {'opened': False, 'error': 'YouTube no abrió el video solicitado; comprueba la ventana.'}
            try:
                self.page.wait_for_selector('video', timeout=15000)
                self.page.evaluate("""() => { const v = document.querySelector('video'); if (v && v.paused) v.play().catch(() => {}); }""")
                self.page.wait_for_function("""() => { const v = document.querySelector('video'); return v && !v.paused && v.currentTime > 0.5; }""", timeout=12000)
                is_ad = bool(self.page.locator('.ad-showing').count())
                if is_ad:
                    return {'opened': True, 'playing': False, 'note': 'La página abrió pero se está mostrando un anuncio; no se confirmó la canción.'}
                return {'opened': True, 'playing': True, 'note': 'El reproductor de la página avanza; no se puede verificar el sonido del dispositivo.'}
            except Exception:
                return {'opened': True, 'playing': False, 'note': 'La página abrió, pero no se pudo confirmar la reproducción. Revisa la ventana.'}
        except Exception:
            return {'opened': False, 'error': 'No se pudo abrir YouTube en la ventana controlada. Comprueba Playwright, Chromium y la conexión.'}

    def pause(self):
        try:
            if not self.browser or not self.browser.is_connected() or not self.page or self.page.is_closed():
                return {'paused': False, 'note': 'No hay una ventana musical activa.'}
            result = self.page.evaluate("""() => { const v = document.querySelector('video'); if (!v) return false; v.pause(); return v.paused; }""")
            if result is True:
                return {'paused': True}
            return {'paused': False, 'note': 'No se encontró un video para pausar.'}
        except Exception:
            return {'paused': False, 'error': 'No se pudo confirmar la pausa en la ventana musical.'}

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.engine:
                self.engine.stop()


def main():
    path = socket_path()
    lock_path = path.parent / 'worker.lock'
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(4)
        server.settimeout(1)
        music = BrowserMusic()
        try:
            while True:
                if music.browser and not music.browser.is_connected():
                    break
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(3)
                    try:
                        request = bytearray()
                        while b'\n' not in request and len(request) < 4096:
                            chunk = conn.recv(4096)
                            if not chunk:
                                break
                            request.extend(chunk)
                        if len(request) >= 4096:
                            raise ValueError('request too large')
                        data = json.loads(request.split(b'\n', 1)[0])
                        if data.get('action') == 'open':
                            answer = music.open(data.get('video_id'))
                        elif data.get('action') == 'pause':
                            answer = music.pause()
                        else:
                            answer = {'error': 'Acción no válida.'}
                        conn.sendall(json.dumps(answer, ensure_ascii=False).encode('utf-8') + b'\n')
                    except (ValueError, AttributeError, OSError):
                        pass
        finally:
            server.close()
            path.unlink(missing_ok=True)
            music.close()


if __name__ == '__main__':
    main()
