"""Conversation and per-action spoken consent, independent of the GUI toolkit."""
import json
import re
import threading
import queue
from errors import describe_error
from text_links import speech_text


def is_approval(text):
    # Only the exact affirmative phrase counts; all ambiguous input is denial.
    return re.sub(r'[^\w\s]', '', text.casefold()).strip() == 'autorizo'


def wake_request(text):
    """Return text following the wake word; None means the word was absent."""
    match = re.search(r'(?<!\w)jarvis(?!\w)', text, re.IGNORECASE)
    return text[match.end():].strip(' \t,.:;!?¡¿-') if match else None

def _normalize_phrase(text):
    import unicodedata
    folded = unicodedata.normalize('NFD', (text or '').casefold())
    plain = ''.join(char for char in folded if unicodedata.category(char) != 'Mn')
    words = re.sub(r'[^\w\s]', ' ', plain).split()
    while words and words[-1] in {'por', 'favor', 'gracias'}:
        words.pop()
    return ' '.join(words)

def _is_conversation_off(phrase):
    return _normalize_phrase(phrase) in CONVERSATION_OFF

CONVERSATION_OFF = frozenset({
    'eso es todo', 'esto es todo', 'eso sera todo', 'eso seria todo',
    'nada mas', 'eso es todo gracias', 'ya me voy', 'terminamos',
})


class VoiceSession:
    def __init__(self, brain, voice, listen, status=lambda _: None, connection=lambda _: None, conversation_changed=None):
        self.brain, self.voice, self.listen, self.status = brain, voice, listen, status
        self.connection = connection
        self.conversation_changed = conversation_changed
        self.conversation_mode = False
        self.stop_event = threading.Event()
        self.reminders = queue.Queue()

    def stop(self):
        self.stop_event.set()

    def set_conversation_mode(self, enabled, announce=False):
        """Live toggle; never persisted across restarts."""
        enabled = bool(enabled)
        if enabled == self.conversation_mode:
            return
        self.conversation_mode = enabled
        if callable(self.conversation_changed):
            try:
                self.conversation_changed(enabled)
            except Exception:
                pass

    def queue_reminder(self, title):
        self.queue_announcement('Señor, recordatorio: ' + title)

    def queue_announcement(self, message):
        self.reminders.put(message)

    def announce_reminders(self):
        # Only the listening thread speaks these, between capture cycles, never
        # during an approval or while the microphone is recording.
        while not self.stop_event.is_set():
            try:
                message = self.reminders.get_nowait()
            except queue.Empty:
                break
            self.speak(message)

    def speak(self, text):
        self.status('Hablando')
        return self.voice.speak_wait(text)

    def approve(self, name, args):
        if self.stop_event.is_set():
            return False
        self.status('Esperando autorización por voz')
        try:
            if name == 'schedule_email_permission':
                to, subject, body, when = (args.get('to'), args.get('subject'), args.get('body'), args.get('when'))
                if not all(isinstance(value, str) for value in (to, subject, body, when)) or len(body) > 700:
                    self.voice.speak_wait('No puedo leer el correo completo por voz; usa el chat para revisarlo.')
                    return False
                prompt = (f'Para {to}, asunto {subject}, el mensaje dice: {body}. Momento solicitado: {when}. '
                          '¿Autoriza una sola vez programar y enviar correos cuando lo pida, sin preguntar cada vez? '
                          'Quedarán guardados en este equipo y se enviarán cuando JARVIS esté abierto y conectado. '
                          'Si estuvo cerrado, se intentará al volver a abrirlo. Puede desactivar este permiso en Ajustes. Diga autorizo para aceptar.')
                if not self.voice.speak_wait(prompt) or self.stop_event.is_set():
                    return False
                try:
                    answer = self.listen()
                except Exception:
                    return False
                return not self.stop_event.is_set() and is_approval(answer)
            if name == 'delete_reminder_permission':
                prompt = ('¿Autoriza una sola vez que elimine recordatorios locales cuando me lo pida, '
                          'sin preguntar cada vez? Eliminaré el recordatorio solicitado. '
                          'Puede desactivar este permiso en Ajustes. Diga autorizo para aceptar.')
                if not self.voice.speak_wait(prompt) or self.stop_event.is_set():
                    return False
                try:
                    answer = self.listen()
                except Exception:
                    return False
                return not self.stop_event.is_set() and is_approval(answer)
            if name == 'whatsapp_prepare':
                phone, message = args.get('phone'), args.get('message')
                if not isinstance(phone, str) or not isinstance(message, str) or len(message) > 700:
                    self.voice.speak_wait('No puedo leer el borrador completo por voz; usa el chat para revisarlo.')
                    return False
                prompt = (f'Para el número {phone}, el mensaje es: {message}. '
                          '¿Abro este borrador de WhatsApp? Diga autorizo para abrirlo. '
                          'No puedo enviarlo automáticamente; deberá pulsar Enviar.')
                if not self.voice.speak_wait(prompt) or self.stop_event.is_set():
                    return False
                try:
                    answer = self.listen()
                except Exception:
                    return False
                return not self.stop_event.is_set() and is_approval(answer)
            details = json.dumps(args, ensure_ascii=False, sort_keys=True)
            if len(details) > 800:
                self.voice.speak_wait('La solicitud es demasiado larga para confirmarla por voz. La acción fue rechazada.')
                return False
            privacy = (' Se capturará la pantalla y se enviará a NVIDIA. La descripción puede enviarse al proveedor del chat.'
                       if name in ('inspect_screen', 'phone_inspect_screen') else ' La imagen se enviará a NVIDIA y la descripción puede enviarse al proveedor del chat.'
                       if name == 'inspect_image' else ' Se consultarán nombres de archivos del teléfono y se enviarán al proveedor del chat.'
                       if name == 'phone_list_files' else ' Se buscarán correos en Gmail y sus metadatos pueden enviarse al proveedor del chat.'
                       if name == 'search_gmail' else ' Se descargará el adjunto de Gmail y se enviará a NVIDIA; la descripción puede enviarse al proveedor del chat.'
                       if name == 'inspect_gmail_image' else ' El contenido del correo se enviará al proveedor del chat.'
                   if name == 'read_gmail' else ' Se enviará el correo completo al destinatario indicado.'
                   if name in ('send_gmail', 'reply_gmail') else ' Se modificará la clasificación de este correo en Gmail.'
                   if name == 'classify_gmail' else ' Se consultará tu agenda y los datos pueden enviarse al proveedor del chat.'
                   if name in ('list_calendar_events', 'list_reminders') else ' Los registros pueden contener datos sensibles y enviarse al proveedor del chat.'
                   if name == 'review_startup_logs' else '')
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
        if not self.speak('Señor, micrófono activado. Diga Jarvis para hablar conmigo; cuando termine, diga eso es todo.'):
            self.status('Error: voz no disponible; micrófono apagado')
            return
        while not self.stop_event.is_set():
            self.announce_reminders()
            self.status('Conversación activa · te escucho' if self.conversation_mode else 'Esperando que digas Jarvis')
            try:
                heard = self.listen()
                if self.stop_event.is_set():
                    break
                if self.conversation_mode:
                    stripped = wake_request(heard)
                    request = stripped if stripped is not None else heard.strip()
                    norm = _normalize_phrase(request)
                    if _is_conversation_off(request):
                        self.set_conversation_mode(False)
                        self.speak('Hasta luego, señor.')
                        continue
                    if stripped == '':
                        self.speak('Le escucho, señor.')
                        continue
                    if not norm:
                        continue
                else:
                    request = wake_request(heard)
                    if request is None:
                        continue
                    # Any wake-word interaction opens free conversation until «eso es todo».
                    self.set_conversation_mode(True)
                    if not request:
                        if not self.speak('Le escucho, señor.') or self.stop_event.is_set():
                            break
                        continue
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
