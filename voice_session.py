"""Conversation and per-action spoken consent, independent of the GUI toolkit."""
import json
import re
import threading


def is_approval(text):
    # Only the exact affirmative phrase counts; all ambiguous input is denial.
    return re.sub(r'[^\w\s]', '', text.casefold()).strip() == 'autorizo'


class VoiceSession:
    def __init__(self, brain, voice, listen, status=lambda _: None):
        self.brain, self.voice, self.listen, self.status = brain, voice, listen, status
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def speak(self, text):
        self.status('Hablando')
        return self.voice.speak_wait(text)

    def approve(self, name, args):
        if self.stop_event.is_set():
            return False
        details = json.dumps(args, ensure_ascii=False, sort_keys=True)
        if len(details) > 800:
            self.speak('La solicitud es demasiado larga para confirmarla por voz. La acción fue rechazada.')
            return False
        message = (f'Señor, solicito permiso para usar la herramienta {name}, '
                   f'con estos argumentos: {details}. '
                   'Diga autorizo para aprobar esta acción, o cualquier otra cosa para rechazarla.')
        if not self.speak(message) or self.stop_event.is_set():
            return False
        self.status('Esperando autorización por voz')
        try:
            answer = self.listen()
        except Exception:
            return False
        return not self.stop_event.is_set() and is_approval(answer)

    def run(self):
        self.brain.approve = self.approve
        if not self.speak('Señor, estoy listo. Puede hablarme. El micrófono está activado.'):
            self.status('No se pudo reproducir la voz; micrófono detenido')
            return
        while not self.stop_event.is_set():
            self.status('Escuchando')
            try:
                request = self.listen()
            except TimeoutError:
                continue
            except Exception:
                if not self.stop_event.is_set():
                    self.status('Error de micrófono o reconocimiento; micrófono detenido')
                    self.speak('No puedo usar el micrófono o el reconocimiento de voz. He detenido la escucha.')
                break
            if self.stop_event.is_set():
                break
            if not request.strip():
                continue
            self.status('Pensando')
            try:
                answer = self.brain.ask(request)
            except Exception:
                answer = 'Señor, no pude completar la solicitud. Compruebe la conexión e inténtelo de nuevo.'
            if not self.stop_event.is_set():
                self.speak(answer)
        self.status('Micrófono apagado')
