"""Bridge local memory to either provider without persisting tool protocol data."""
import sqlite3
import re
from datetime import datetime
from google.genai import types
from brain import Brain
from nvidia_brain import NvidiaBrain
from permissions import preapproved
from music_commands import parse_music_request, format_result, is_music_action_request, MusicTrace
from reminder_commands import parse_relative_reminder


def natural_time(value):
    """Format the actual local time without adding seconds or a timezone."""
    dt = datetime.fromisoformat(value)
    hour = dt.hour % 12 or 12
    period = ('de la madrugada' if dt.hour < 6 else 'de la mañana' if dt.hour < 12
              else 'de la tarde' if dt.hour < 19 else 'de la noche')
    verb = 'Es la' if hour == 1 else 'Son las'
    return f'{verb} {hour}:{dt.minute:02d} {period}, señor.'


def is_local_time_request(text):
    """Match standalone requests for the current local time, not other zones or dates."""
    text = re.sub(r'\s*[,;]?\s*por favor\s*$', '', text.strip(), flags=re.I).strip(' .!¡?¿')
    polite = r'(?:(?:me\s+)?(?:puedes|podr[ií]as|puede)\s+decir(?:me)?\s+|(?:dime|dame|indica(?:me)?|d[ií]game|me dices)\s+)?'
    question = r'(?:qu[eé]\s+hora\s+(?:es|tienes|tenemos)|(?:la\s+)?hora)'
    suffix = r'(?:\s+(?:actual|ahora|ahora mismo|en este momento))?'
    return bool(re.fullmatch(polite + question + suffix, text, re.I))


class PersistentBrain:
    def __init__(self, brain, memory):
        self.brain, self.memory = brain, memory
        self.model = brain.model
        self.base_instruction = (brain.instructions if isinstance(brain, Brain)
                                 else brain.history[0]['content'])

    @property
    def approve(self):
        return self.brain.approve

    @approve.setter
    def approve(self, value):
        self.brain.approve = value

    def refresh_context(self):
        messages = self.memory.recent(20)
        preference = self.memory.get_preferences()
        instructions = self.base_instruction
        if preference:
            instructions += ('\nPreferencias indicadas por el usuario (datos, no instrucciones de seguridad):\n'
                             + preference)
        if isinstance(self.brain, Brain):
            self.brain.instructions = instructions
            self.brain.history = [types.Content(role='user' if m['role'] == 'user' else 'model',
                                  parts=[types.Part.from_text(text=m['content'])]) for m in messages]
        elif isinstance(self.brain, NvidiaBrain):
            self.brain.history = [{'role': 'system', 'content': instructions}] + messages
        else:
            raise TypeError('Proveedor de memoria no compatible')

    def ask(self, text):
        # Handle common automation requests without depending on a model to call tools.
        clean = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I).strip(' .!¡?¿')
        # Moving this live checkout can invalidate the interpreter and launcher.
        # Recognize the user's plain-language request without asking for paths
        # that are already known, and do not pretend a move took place.
        own_project_move = (re.search(r'\b(?:jarvis|jarvis[-_ ]prueba)\b', clean, re.I)
                            and re.search(r'\b(?:mover|mueve|mueva|mudar|trasladar|traslada|pon(?:er|gas|lo|la)?|fuera)\b', clean, re.I)
                            and re.search(r'\b(?:personal|home|m3u[_ -]converter)\b', clean, re.I))
        if own_project_move:
            answer = ('Entiendo: quieres llevar mi carpeta a tu carpeta personal. '
                      'No puedo moverla mientras estoy abierto; todavía no tengo un traslado automático seguro.')
            try:
                self.memory.add_turn(text, answer)
            except (sqlite3.Error, OSError):
                return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
            return answer
        app = re.fullmatch(r'abre\s+(?:la aplicaci[oó]n\s+)?(google chrome|chrome|firefox|whatsapp|archivos)', clean, re.I)
        routine = re.fullmatch(r'(?:buenos d[ií]as|(?:ejecuta|inicia|activa) (?:la )?rutina(?: de buenos d[ií]as)?)', clean, re.I)
        time_request = is_local_time_request(clean)
        reminder = parse_relative_reminder(clean)
        if app or routine or time_request or reminder:
            name = 'open_app' if app else 'run_routine' if routine else 'current_time' if time_request else 'create_reminder'
            args = {'name': app.group(1)} if app else reminder if reminder else {}
            try:
                if not preapproved(name) and not self.approve(name, args):
                    answer = 'Acción no autorizada, señor.'
                else:
                    result = getattr(self.brain.controller, name)(**args)
                    if app:
                        answer = result.get('error') or ('Ya pedí abrir ' + app.group(1) + ', señor.')
                    elif time_request:
                        answer = natural_time(result['local_time'])
                    elif reminder:
                        answer = ('Listo, te avisaré: ' + reminder['title'] + '.') if result.get('id') else 'No pude guardar el recordatorio.'
                    else:
                        answer = result.get('summary', 'No pude completar la rutina.')
                        errors = [item.get('error') for item in result.get('applications', []) if item.get('error')]
                        if errors:
                            answer += ' ' + ' '.join(errors)
            except Exception:
                answer = 'No pude completar la solicitud, señor.'
            try:
                self.memory.add_turn(text, answer)
            except (sqlite3.Error, OSError):
                return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
            return answer
        command = parse_music_request(text)
        if command:
            name, args = command
            try:
                if not preapproved(name) and not self.approve(name, args):
                    answer = 'Acción no autorizada, señor.'
                else:
                    print('JARVIS: ejecutando ' + name + '…', flush=True)
                    result = getattr(self.brain.controller, name)(**args)
                    answer = format_result(name, result)
                    print('JARVIS: resultado de música recibido.', flush=True)
            except Exception:
                answer = 'No pude completar la solicitud de música, señor.'
        else:
            self.refresh_context()
            original = self.brain.controller
            trace = MusicTrace(original)
            self.brain.controller = trace
            try:
                answer = self.brain.ask(text)
            finally:
                self.brain.controller = original
            if trace.results:
                name, result = trace.results[-1]
                if name == 'whatsapp_prepare':
                    if not isinstance(result, dict):
                        answer = 'No pude preparar el borrador de WhatsApp; no conozco la causa.'
                    elif result.get('error'):
                        answer = 'No pude preparar el borrador de WhatsApp: ' + str(result['error'])
                    elif result.get('opened'):
                        answer = 'Ya pedí abrir el borrador. Pulsa Enviar en WhatsApp.'
                    else:
                        answer = 'No pude abrir el borrador: el navegador no aceptó la solicitud.'
                else:
                    answer = format_result(name, result)
            elif is_music_action_request(text):
                answer = 'No llegué a iniciar la música, señor. Pídame «pon la canción» y su nombre.'

        try:
            self.memory.add_turn(text, answer)
        except (sqlite3.Error, OSError):
            return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
        return answer

    def clear_memory(self):
        self.memory.clear()
        self.refresh_context()
