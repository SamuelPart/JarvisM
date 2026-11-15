"""Conversation and per-action spoken consent, independent of the GUI toolkit."""
import json
import re
import threading
from errors import describe_error
from text_links import speech_text


def is_approval(text):
    # Only the exact affirmative phrase counts; all ambiguous input is denial.
    return re.sub(r'[^\w\s]', '', text.casefold()).strip() == 'autorizo'


def wake_request(text):
    """Return text following the wake word; None means the word was absent."""
    match = re.search(r'(?<!\w)jarvis(?!\w)', text, re.IGNORECASE)
    return text[match.end():].strip(' \t,.:;!?¡¿-') if match else None


class VoiceSession:
    def __init__(self, brain, voice, listen, status=lambda _: None, connection=lambda _: None):
        self.brain, self.voice, self.listen, self.status = brain, voice, listen, status
        self.connection = connection
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def speak(self, text):
        self.status('Hablando')
        return self.voice.speak_wait(text)

    def approve(self, name, args):
        if self.stop_event.is_set():
            return False
        self.status('Esperando autorización por voz')
        try:
            details = json.dumps(args, ensure_ascii=False, sort_keys=True)
            if len(details) > 800:
                self.voice.speak_wait('La solicitud es demasiado larga para confirmarla por voz. La acción fue rechazada.')
                return False
            privacy = (' Se capturará la pantalla y se enviará a NVIDIA. La descripción puede enviarse al proveedor del chat.'
                       if name == 'inspect_screen' else ' La imagen se enviará a NVIDIA y la descripción puede enviarse al proveedor del chat.'
                       if name == 'inspect_image' else ' Se buscarán correos en Gmail y sus metadatos pueden enviarse al proveedor del chat.'
                       if name == 'search_gmail' else ' Se descargará el adjunto de Gmail y se enviará a NVIDIA; la descripción puede enviarse al proveedor del chat.'
                       if name == 'inspect_gmail_image' else ' El contenido del correo se enviará al proveedor del chat.'
                   if name == 'read_gmail' else ' Se enviará el correo completo al destinatario indicado.'
                   if name in ('send_gmail', 'reply_gmail') else ' Se modificará la clasificación de este correo en Gmail.'
                   if name == 'classify_gmail' else ' Se consultará tu agenda y los datos pueden enviarse al proveedor del chat.'
                   if name in ('list_calendar_events', 'list_reminders') else '')
            message = (f'Señor, solicito permiso para usar la herramienta {name}, '
                       f'con estos argumentos: {details}.' + privacy +
                       ' Diga autorizo para aprobar esta acción, o cualquier otra cosa para rechazarla.')
            if not self.voice.speak_wait(message) or self.stop_event.is_set():
                return False
            try:
                answer = self.listen()
            except Exception:
                return False
            return not self.stop_event.is_set() and is_approval(answer)
        finally:
            if not self.stop_event.is_set():
                self.status('Pensando')

    def run(self):
        self.brain.approve = self.approve
        if not self.speak('Señor, micrófono activado. Diga Jarvis para hablar conmigo.'):
            self.status('Error: voz no disponible; micrófono apagado')
            return
        while not self.stop_event.is_set():
            self.status('Esperando que digas Jarvis')
            try:
                heard = self.listen()
                if self.stop_event.is_set():
                    break
                request = wake_request(heard)
                if request is None:
                    continue
                if not request:
                    if not self.speak('Le escucho, señor.') or self.stop_event.is_set():
                        break
                    self.status('Escuchando tu orden')
                    request = self.listen().strip()
            except TimeoutError:
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.speak('No puedo usar el micrófono o el reconocimiento de voz. He detenido la escucha.')
                    self.status(f'Error de micrófono o conexión: {type(exc).__name__}')
                return
            if self.stop_event.is_set():
                break
            if not request.strip():
                continue
            self.status('Pensando')
            try:
                answer = self.brain.ask(request)
                self.connection('Respondió')
            except Exception as exc:
                self.connection('Error al consultar')
                answer = 'Señor, ' + describe_error(exc)
            if not self.stop_event.is_set():
                self.speak(speech_text(answer))
        self.status('Micrófono apagado')
