"""Bridge local memory to either provider without persisting tool protocol data."""
import sqlite3
import re
import time
from datetime import datetime
from google.genai import types
from brain import Brain
from nvidia_brain import NvidiaBrain
from permissions import preapproved, authorize_tool
from music_commands import parse_music_request, format_result, is_music_action_request, MusicTrace
from reminder_commands import parse_relative_reminder, parse_delete_request, find_matching_reminders, select_reminders_by_time, select_reminders_by_date, select_reminders_by_period, select_reminders_by_minute


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


def is_scheduled_email_request(text):
    """Prevent an immediately sent Gmail message when the request is for later."""
    email = re.search(r'\b(?:correos?|email|e-mail|gmail)\b', text, re.I)
    future = re.search(r'\b(?:program(?:a|ar|e|ado|arlo)|dentro|despu[eé]s|ma[ñn]ana|pasado ma[ñn]ana|semana|mes(?:es)?|a[ñn]os?|horas?|minutos?|segundos?|m[aá]s tarde|fecha futura)\b|\ben\s+\d+\b|\bpara el\s+\d+\b', text, re.I)
    return bool(email and future)


class PersistentBrain:
    def __init__(self, brain, memory):
        self.brain, self.memory = brain, memory
        self.model = brain.model
        self.pending_reminder_choices = None
        self.pending_reminder_deadline = 0
        self.pending_reminder_question = None
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

    def _delete_selected_reminder(self, reminder):
        args = {'reminder_id': reminder['id'], 'title': reminder['title'], 'when': reminder['when']}
        if not authorize_tool('delete_reminder', args, self.approve):
            return 'No eliminé el recordatorio; no se autorizó la acción o no se pudo guardar el permiso.'
        result = self.brain.controller.delete_reminder(**args)
        return ('Listo, eliminé el recordatorio.' if result.get('deleted') is True
                else 'No encontré ese recordatorio; puede que ya se haya eliminado o modificado.')

    def _remember_answer(self, text, answer):
        try:
            self.memory.add_turn(text, answer)
        except (sqlite3.Error, OSError):
            return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
        return answer

    def ask(self, text):
        # Handle common automation requests without depending on a model to call tools.
        clean = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I).strip(' .!¡?¿')
        if self.pending_reminder_choices:
            if time.monotonic() > self.pending_reminder_deadline:
                self.pending_reminder_choices = None
            elif re.fullmatch(r'(?:no|cancela|cancelar|olvida(?:lo|r)?|ninguno)', clean, re.I):
                self.pending_reminder_choices = None
                return self._remember_answer(text, 'De acuerdo, no eliminé ningún recordatorio.')
            elif parse_delete_request(clean) is None:
                choices = self.pending_reminder_choices
                if self.pending_reminder_question == 'period':
                    matches = select_reminders_by_period(clean, choices)
                elif self.pending_reminder_question == 'minute':
                    matches = select_reminders_by_minute(clean, choices)
                elif self.pending_reminder_question == 'day':
                    matches = select_reminders_by_date(clean, choices)
                else:
                    matches = None
                if matches is None:
                    matches = select_reminders_by_time(clean, choices)
                if matches is None and self.pending_reminder_question != 'period':
                    matches = select_reminders_by_date(clean, choices)
                if matches is not None:
                    if len(matches) == 1:
                        self.pending_reminder_choices = None
                        try:
                            answer = self._delete_selected_reminder(matches[0])
                        except Exception:
                            answer = 'No pude eliminar el recordatorio; revisa la agenda local.'
                    elif not matches:
                        answer = 'No encontré un recordatorio a esa hora o fecha. ¿Cuál es?'
                    else:
                        self.pending_reminder_choices = matches
                        timestamps = [datetime.fromisoformat(item['when']) for item in matches]
                        hours = {dt.hour for dt in timestamps}
                        minutes = {dt.minute for dt in timestamps}
                        if len(hours) > 1:
                            self.pending_reminder_question = 'period'
                            answer = 'Hay más de uno a esa hora. ¿Es de la mañana, tarde o noche?'
                        elif len(minutes) > 1:
                            self.pending_reminder_question = 'minute'
                            answer = 'Hay más de uno a esa hora. ¿Me dices también los minutos?'
                        else:
                            self.pending_reminder_question = 'day'
                            answer = 'Hay más de uno a esa hora. ¿De qué día?'
                    return self._remember_answer(text, answer)
                # A new unrelated request abandons the pending deletion.
                self.pending_reminder_choices = None
            else:
                self.pending_reminder_choices = None
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
        delete_name = parse_delete_request(clean)
        if delete_name is not None:
            try:
                if not delete_name:
                    answer = '¿Qué recordatorio quieres eliminar?'
                else:
                    matches = find_matching_reminders(delete_name, self.brain.controller.list_reminders().get('reminders', []))
                    if not matches:
                        answer = 'No encontré ese recordatorio en la agenda local.'
                    elif len(matches) > 1:
                        self.pending_reminder_choices = matches
                        self.pending_reminder_question = 'hour'
                        self.pending_reminder_deadline = time.monotonic() + 300
                        answer = 'Hay varios recordatorios con ese nombre. ¿De qué hora?'
                    else:
                        answer = self._delete_selected_reminder(matches[0])
            except Exception:
                answer = 'No pude eliminar el recordatorio; revisa la agenda local.'
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
            trace = MusicTrace(original, block_immediate_email=is_scheduled_email_request(clean))
            self.brain.controller = trace
            try:
                answer = self.brain.ask(text)
            finally:
                self.brain.controller = original
            if trace.results:
                name, result = trace.results[-1]
                if name == 'schedule_email':
                    if isinstance(result, dict) and result.get('scheduled') is True:
                        try:
                            when = datetime.fromisoformat(result['when']).strftime('%d/%m/%Y a las %H:%M')
                            answer = ('Listo, quedó programado para el ' + when + '. '
                                      'JARVIS debe estar abierto y conectado; si está cerrado lo intentará al volver a abrirlo.')
                        except (KeyError, ValueError, TypeError):
                            answer = 'El correo quedó guardado, pero no pude leer la fecha. Revísala en los correos programados.'
                    else:
                        reason = result.get('error') if isinstance(result, dict) else None
                        answer = 'No pude programar el correo: ' + (str(reason) if reason else 'no conozco la causa.')
                elif name == 'cancel_scheduled_email':
                    answer = ('Listo, cancelé el correo programado.' if isinstance(result, dict) and result.get('cancelled') is True
                              else 'No pude cancelarlo: puede que ya no esté pendiente o esté enviándose.')
                elif name == 'delete_reminder':
                    answer = ('Listo, eliminé el recordatorio.' if isinstance(result, dict) and result.get('deleted') is True
                              else 'No pude eliminar el recordatorio; puede que ya no exista.')
                elif name == 'whatsapp_prepare':
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
            elif (is_scheduled_email_request(clean)
                  and re.search(r'\b(?:programa|programar|programes|env[ií]a|env[ií]es|enviar|manda|mandar)\b', clean, re.I)
                  and '?' not in answer and '¿' not in answer):
                answer = 'Todavía no quedó programado. Dime el destinatario, el asunto, el mensaje y cuándo quieres enviarlo.'
            elif (re.search(r'\b(?:cancela|cancelar|elimina|eliminar|borra|borrar)\b', clean, re.I)
                  and re.search(r'\b(?:correo|email|e-mail)\b', clean, re.I)
                  and re.search(r'\bprogramad[oa]s?\b', clean, re.I) and '?' not in answer and '¿' not in answer):
                answer = 'No cancelé ningún correo programado. Dime cuál quieres cancelar.'
            elif (re.search(r'\b(?:elimina|eliminar|borra|borrar|quita|quitar|cancela|cancelar)\b', clean, re.I)
                  and re.search(r'\brecordatorios?\b', clean, re.I)):
                answer = 'No eliminé ningún recordatorio. Dime cuál quieres eliminar.'
            elif is_music_action_request(text):
                answer = 'No llegué a iniciar la música, señor. Pídame «pon la canción» y su nombre.'

        try:
            self.memory.add_turn(text, answer)
        except (sqlite3.Error, OSError):
            return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
        return answer

    def clear_memory(self):
        self.pending_reminder_choices = None
        self.memory.clear()
        self.refresh_context()
