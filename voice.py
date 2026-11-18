"""Voz neuronal por defecto (ElevenLabs) con Edge/local como respaldo y reproducción secuencial.

Orden de síntesis: ElevenLabs (por defecto; exige ELEVENLABS_API_KEY en .env)
  → Edge TTS → voz local (pyttsx3). Cada nivel informa del fallo antes de bajar.
"""
import asyncio
import json
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path


_ELEVENLABS_ERRORS = {
    'invalid_api_key': 'la clave de API no es válida.',
    'missing_api_key': 'falta la clave de API.',
    'quota_exceeded': 'se agotó la cuota de tu plan de ElevenLabs.',
    'only_for_creator': 'esta voz puede estar restringida a su creador.',
    'too_many_concurrent_requests': 'hay demasiadas solicitudes simultáneas a ElevenLabs.',
    'payment_required': 'tu plan de ElevenLabs requiere pago para esta solicitud.',
    'voice_not_found': 'la voz (ELEVENLABS_VOICE_ID) no existe o no pertenece a tu cuenta.',
    'model_not_found': 'el modelo (ELEVENLABS_MODEL_ID) no está disponible en tu cuenta.',
    'output_format_not_allowed': 'el formato de salida no está permitido en tu plan (prueba ELEVENLABS_OUTPUT_FORMAT=mp3_22050_32).',
    'output_format_not_supported': 'el formato de salida no está soportado para este modelo.',
    'text_too_long': 'el texto supera el límite permitido para una sola petición.',
    'invalid_text': 'el texto de la petición no es válido.',
    'max_character_limit_exceeded': 'se superó el límite de caracteres de tu plan.',
}


_HTTP_HINTS = {
    400: 'la petición fue rechazada; las causas habituales son un voice_id ajeno/inexistente o un formato de salida no permitido para tu plan (prueba ELEVENLABS_OUTPUT_FORMAT=mp3_22050_32).',
    401: 'la clave de API parece inválida o revocada; crea una nueva en tu cuenta y ponla en .env.',
    402: 'tu plan de ElevenLabs requiere pago para esta solicitud o la cuota se agotó.',
    403: 'sin permiso para este recurso (la voz puede estar restringida a su creador o al plan).',
    404: 'voz o modelo no encontrado; revisa ELEVENLABS_VOICE_ID y ELEVENLABS_MODEL_ID.',
    429: 'se agotó la cuota de caracteres o el límite de peticiones de tu plan.',
}


def elevenlabs_error(response):
    """Diagnóstico seguro: lista blanca fija; nunca expone mensajes del proveedor, claves ni texto."""
    explanation = _HTTP_HINTS.get(response.status_code)
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
            if not isinstance(code, str) and isinstance(detail, str):
                # ElevenLabs también devuelve detail como cadena; busca el código en la lista blanca.
                lowered = detail.lower()
                for known in _ELEVENLABS_ERRORS:
                    if known in lowered:
                        code = known
                        break
            if isinstance(code, str):
                explanation = _ELEVENLABS_ERRORS.get(code, explanation)
    except (ValueError, TypeError, OSError):
        pass
    generic = 'revisa la voz, el modelo, la clave y la cuota; la causa exacta no está disponible.'
    return f'ElevenLabs rechazó la solicitud (HTTP {response.status_code}): ' + (explanation or generic)


class VoiceError(Exception):
    pass


def _edge_then_local(voice, text):
    try:
        voice._neural(text)
    except Exception:
        print('(Edge también falló; intentando voz local.)', flush=True)
        voice._local(text)


class Voice:
    def __init__(self):
        self.queue = queue.Queue()
        self.thread = None
        self.lock = threading.Lock()
        self.on_activity = None
        self.on_level = None

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
        if not text.strip() or os.getenv('JARVIS_VOICE_MODE', 'elevenlabs').lower() == 'off':
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
                mode = os.getenv('JARVIS_VOICE_MODE', 'elevenlabs').strip().lower()
                if mode == 'local':
                    self._local(text)
                elif mode == 'elevenlabs':
                    try:
                        self._elevenlabs(text)
                    except VoiceError as first:
                        print(f'(ElevenLabs no disponible: {first}; probando voz Edge.)', flush=True)
                        _edge_then_local(self, text)
                    except Exception:
                        print('(ElevenLabs no disponible (causa no publicada); probando voz Edge.)', flush=True)
                        _edge_then_local(self, text)
                elif mode == 'edge':
                    try:
                        self._neural(text)
                    except Exception:
                        print('(Voz neuronal no disponible; intentando voz local.)', flush=True)
                        self._local(text)
                else:
                    raise VoiceError('Modo de voz no reconocido. Usa elevenlabs, edge, local u off.')
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

    def _level(self, value):
        if self.on_level:
            try:
                self.on_level(value)
            except Exception:
                pass  # The visualizer must never interrupt speech.

    def _envelope(self, pygame, path):
        if not self.on_level:
            return None
        try:
            from audio_envelope import pcm_envelope
            frequency, sample_format, channels = pygame.mixer.get_init()
            if sample_format != -16 or path.stat().st_size > 512_000:
                return None
            raw = pygame.mixer.Sound(str(path)).get_raw()
            if len(raw) > 32_000_000:
                return None
            return pcm_envelope(raw, frequency, channels)
        except Exception:
            return None  # Decoding for visualization must never break playback.

    def _neural(self, text):
        import edge_tts
        voice = os.getenv('JARVIS_TTS_VOICE', 'es-MX-JorgeNeural')
        with tempfile.TemporaryDirectory(prefix='jarvis-tts-') as directory:
            path = Path(directory) / 'voice.mp3'
            async def synthesize():
                await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(path)), timeout=30)
            asyncio.run(synthesize())
            self._play_file(path)

    def _play_file(self, path):
        import pygame
        pygame.mixer.init()
        try:
            envelope = self._envelope(pygame, path)
            pygame.mixer.music.load(str(path))
            self._level(None if envelope is None else 0.0)
            pygame.mixer.music.play()
            self._activity(True)
            while pygame.mixer.music.get_busy():
                if envelope is not None:
                    from audio_envelope import level_at
                    self._level(level_at(envelope, pygame.mixer.music.get_pos()))
                time.sleep(0.05)
        finally:
            self._level(None)
            self._activity(False)
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.quit()

    def _elevenlabs(self, text):
        import requests
        key = os.getenv('ELEVENLABS_API_KEY', '').strip()
        voice_id = os.getenv('ELEVENLABS_VOICE_ID', 'JBFqnCBsd6RMkjVDRZzb').strip()  # George (británica, profunda)
        model = os.getenv('ELEVENLABS_MODEL_ID', 'eleven_multilingual_v2').strip()
        output_format = os.getenv('ELEVENLABS_OUTPUT_FORMAT', 'mp3_44100_128').strip()
        if not key:
            raise VoiceError('Falta ELEVENLABS_API_KEY en .env (o usa JARVIS_VOICE_MODE=edge para Edge TTS).')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice_id):
            raise VoiceError('ELEVENLABS_VOICE_ID no es válido.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', model):
            raise VoiceError('ELEVENLABS_MODEL_ID no es válido.')
        if not re.fullmatch(r'[a-z0-9_]{1,40}', output_format):
            raise VoiceError('ELEVENLABS_OUTPUT_FORMAT no es válido (p. ej. mp3_44100_128 o mp3_22050_32).')
        session = requests.Session()
        session.trust_env = False
        try:
            with session.post('https://api.elevenlabs.io/v1/text-to-speech/' + voice_id,
                              headers={'xi-api-key': key, 'Accept': 'audio/mpeg'},
                              json={'text': text, 'model_id': model},
                              params={'output_format': output_format},
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

    def _local(self, text):
        import pyttsx3
        engine = pyttsx3.init()
        try:
            engine.say(text)
            self._level(None)  # Local TTS does not expose its playback samples.
            self._activity(True)
            engine.runAndWait()
        finally:
            self._activity(False)
            engine.stop()
