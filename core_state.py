"""UI-independent state priority for the animated core."""


class CoreState:
    def __init__(self):
        self.task = 'idle'
        self.speaking = False

    def set_task(self, task):
        if task not in ('idle', 'thinking', 'approval'):
            raise ValueError('Estado no válido')
        self.task = task
        return self.current

    def set_speaking(self, active):
        self.speaking = bool(active)
        return self.current

    @property
    def current(self):
        if self.task == 'approval':
            return 'approval'
        if self.speaking:
            return 'speaking'
        return self.task
