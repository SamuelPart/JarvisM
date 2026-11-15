"""Voz neuronal opcional con alternativa local y reproducción secuencial."""
import asyncio
import os
import queue
import tempfile
import threading
import time
from pathlib import Path


class Voice:
    def __init__(self):
        self.queue = queue.Queue()
        self.thread = None
        self.lock = threading.Lock()
        self.on_activity = None

    def speak(self, text):
        self._enqueue(text, None)

    def speak_wait(self, text):
        """Wait for playback and return False if no audio engine succeeded."""
        done = threading.Event()
        result = {'ok': False}
        if not self._enqueue(text, (done, result)):
            return False
        done.wait()
        return result['ok']

    def _enqueue(self, text, completion):
        if not text.strip() or os.getenv('JARVIS_VOICE_MODE', 'edge').lower() == 'off':
            return False
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, daemon=True)
                self.thread.start()
            self.queue.put((text, completion))
        return True

    def _worker(self):
        while True:
            text, completion = self.queue.get()
            ok = False
            try:
                if os.getenv('JARVIS_VOICE_MODE', 'edge').lower() == 'local':
                    self._local(text)
                else:
                    try:
                        self._neural(text)
                    except Exception:
                        print('(Voz neuronal no disponible; intentando voz local.)', flush=True)
                        self._local(text)
                ok = True
            except Exception:
                print('(Aviso: voz no disponible; la respuesta permanece en pantalla.)', flush=True)
            finally:
                if completion is not None:
                    done, result = completion
                    result['ok'] = ok
                    done.set()
                self.queue.task_done()

    def _activity(self, active):
        if self.on_activity:
            try:
                self.on_activity(active)
            except Exception:
                pass  # Visual feedback must never interrupt audio.

    def _neural(self, text):
        import edge_tts
        import pygame
        voice = os.getenv('JARVIS_TTS_VOICE', 'es-MX-JorgeNeural')
        with tempfile.TemporaryDirectory(prefix='jarvis-tts-') as directory:
            path = Path(directory) / 'voice.mp3'
            async def synthesize():
                await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(path)), timeout=30)
            asyncio.run(synthesize())
            pygame.mixer.init()
            try:
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
                self._activity(True)
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            finally:
                self._activity(False)
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.quit()

    def _local(self, text):
        import pyttsx3
        engine = pyttsx3.init()
        try:
            engine.say(text)
            self._activity(True)
            engine.runAndWait()
        finally:
            self._activity(False)
            engine.stop()
