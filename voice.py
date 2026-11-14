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

    def speak(self, text):
        if not text.strip() or os.getenv('JARVIS_VOICE_MODE', 'edge').lower() == 'off':
            return
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, daemon=True)
                self.thread.start()
            self.queue.put(text)

    def _worker(self):
        while True:
            text = self.queue.get()
            try:
                if os.getenv('JARVIS_VOICE_MODE', 'edge').lower() == 'local':
                    self._local(text)
                else:
                    try:
                        self._neural(text)
                    except Exception:
                        print('(Voz neuronal no disponible; intentando voz local.)', flush=True)
                        self._local(text)
            except Exception:
                print('(Aviso: voz no disponible; la respuesta permanece en pantalla.)', flush=True)
            finally:
                self.queue.task_done()

    @staticmethod
    def _neural(text):
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
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            finally:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.quit()

    @staticmethod
    def _local(text):
        import pyttsx3
        engine = pyttsx3.init()
        try:
            engine.say(text)
            engine.runAndWait()
        finally:
            engine.stop()
