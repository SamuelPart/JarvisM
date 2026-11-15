"""Bridge local memory to either provider without persisting tool protocol data."""
import sqlite3
from google.genai import types
from brain import Brain
from nvidia_brain import NvidiaBrain


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
        self.refresh_context()
        answer = self.brain.ask(text)
        try:
            self.memory.add_turn(text, answer)
        except (sqlite3.Error, OSError):
            return answer + '\n\nAviso: no se pudo guardar esta conversación en la memoria local.'
        return answer

    def clear_memory(self):
        self.memory.clear()
        self.refresh_context()
