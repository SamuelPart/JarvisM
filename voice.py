"""Voz neuronal opcional con alternativa local y reproducción secuencial."""
import asyncio
import json
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path


class VoiceError(Exception):
    pass


ELEVENLABS_ERRORS = {
    'quota_exceeded': 'La cuenta alcanzó su cuota de ElevenLabs.',
    'voice_not_found': 'ElevenLabs no encontró la voz; revisa el ID y que esté disponible en tu cuenta.',
    'invalid_voice_id': 'El ID de voz no es válido para ElevenLabs.',
    'model_not_found': 'ElevenLabs no encontró el modelo configurado.',
    'invalid_model_id': 'El modelo de ElevenLabs no es válido.',
    'invalid_api_key': 'ElevenLabs rechazó la clave API.',
    'missing_permissions': 'La clave no tiene los permisos necesarios para texto a voz.',
    'detected_unusual_activity': 'ElevenLabs detectó actividad inusual o restricciones de la cuenta. Revisa tu cuenta o contacta con su soporte.',
    'free_users_not_allowed': 'Tu plan de ElevenLabs no permite esta solicitud o voz.',
    'only_for_creator': 'Esta voz puede estar restringida a su creador.',
    'too_many_concurrent_requests': 'Hay demasiadas solicitudes simultáneas a ElevenLabs.',
}


def elevenlabs_error(response):
    """Only report a fixed allowlist; never expose provider messages, keys or text."""
    explanation = None
    try:
        data = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            data.extend(chunk)
            if len(data) > 16384:
                break
        if len(data) <= 16384:
            payload = json.loads(data)
            detail = payload.get('detail', {}) if isinstance(payload, dict) else {}
            code = detail.get('status') if isinstance(detail, dict) else None
            if isinstance(code, str):
                explanation = ELEVENLABS_ERRORS.get(code)
    except (ValueError, TypeError, OSError):
        pass
    generic = 'revisa la voz, el modelo, la clave y la cuota; la causa exacta no está disponible.'
    return f'ElevenLabs rechazó la solicitud (HTTP {response.status_code}): ' + (explanation or generic)


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
                mode = os.getenv('JARVIS_VOICE_MODE', 'edge').strip().lower()
                if mode == 'local':
                    self._local(text)
                elif mode == 'elevenlabs':
                    self._elevenlabs(text)
                elif mode == 'edge':
                    try:
                        self._neural(text)
                    except Exception:
                        print('(Voz neuronal no disponible; intentando voz local.)', flush=True)
                        self._local(text)
                else:
                    raise VoiceError('Modo de voz no reconocido. Usa edge, elevenlabs, local u off.')
                ok = True
            except VoiceError as exc:
                print('(Aviso de voz: ' + str(exc) + ')', flush=True)
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
        voice = os.getenv('JARVIS_TTS_VOICE', 'es-MX-JorgeNeural')
        with tempfile.TemporaryDirectory(prefix='jarvis-tts-') as directory:
            path = Path(directory) / 'voice.mp3'
            async def synthesize():
                await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(path)), timeout=30)
            asyncio.run(synthesize())
            self._play_file(path)

    def _elevenlabs(self, text):
        import requests
        key = os.getenv('ELEVENLABS_API_KEY', '').strip()
        voice_id = os.getenv('ELEVENLABS_VOICE_ID', 'JBFqnCBsd6RMkjVDRZzb').strip()
        model = os.getenv('ELEVENLABS_MODEL_ID', 'eleven_multilingual_v2').strip()
        if not key:
            raise VoiceError('Falta ELEVENLABS_API_KEY en .env.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice_id):
            raise VoiceError('ELEVENLABS_VOICE_ID no es válido.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', model):
            raise VoiceError('ELEVENLABS_MODEL_ID no es válido.')
        session = requests.Session()
        session.trust_env = False
        try:
            with session.post('https://api.elevenlabs.io/v1/text-to-speech/' + voice_id,
                              headers={'xi-api-key': key, 'Accept': 'audio/mpeg'},
                              json={'text': text, 'model_id': model},
                              params={'output_format': 'mp3_44100_128'},
                              timeout=(10, 90), allow_redirects=False, stream=True) as response:
                if not 200 <= response.status_code < 300:
                    raise VoiceError(elevenlabs_error(response))
                with tempfile.TemporaryDirectory(prefix='jarvis-tts-') as directory:
                    path = Path(directory) / 'voice.mp3'
                    size = 0
                    with path.open('wb') as file:
                        for chunk in response.iter_content(chunk_size=65536):
                            size += len(chunk)
                            if size > 20 * 1024 * 1024:
                                raise VoiceError('El audio de ElevenLabs es demasiado grande.')
                            file.write(chunk)
                    if not size:
                        raise VoiceError('ElevenLabs devolvió audio vacío.')
                    self._play_file(path)
        except requests.RequestException as exc:
            raise VoiceError('No se pudo conectar con ElevenLabs o se agotó el tiempo de espera.') from exc
        finally:
            session.close()

    def _play_file(self, path):
        import pygame
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
