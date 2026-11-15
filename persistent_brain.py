"""Bridge local memory to either provider without persisting tool protocol data."""
import sqlite3
from google.genai import types
from brain import Brain
from nvidia_brain import NvidiaBrain
from permissions import preapproved
from music_commands import parse_music_request, format_result, is_music_action_request, MusicTrace


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
