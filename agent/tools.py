"""Tool registry: the single place external actions enter the system.

Decision (AI) is strictly separated from execution: tools here are plain Python
callables with a declared `danger` flag. Dangerous tools (delete, send, modify
config) refuse to run without `confirmed=True` — the confirmation comes from a
human approval callback in the orchestrator, never from the model itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[..., Any]
    danger: bool = False           # requires explicit human confirmation
    schema: dict = field(default_factory=dict)  # {param: 'string'|'integer'|'boolean'}

    def to_dict(self):
        return {'name': self.name, 'description': self.description,
                'danger': self.danger, 'schema': self.schema}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if not tool.name or tool.handler is None:
            raise ValueError('Herramienta inválida: nombre y handler obligatorios.')
        self._tools[tool.name] = tool
        return tool

    def get(self, name):
        return self._tools.get(name)

    def list(self):
        return [tool.to_dict() for tool in self._tools.values()]

    def execute(self, name, args=None, *, confirmed=False):
        args = dict(args or {})
        tool = self._tools.get(name)
        if tool is None:
            return {'status': 'error', 'error': f'Herramienta desconocida: {name}'}
        if tool.danger and not confirmed:
            return {'status': 'needs_confirmation',
                    'error': f'«{name}» borra, envía o modifica el sistema: requiere confirmación humana.'}
        try:
            result = tool.handler(**args)
        except TypeError as exc:
            return {'status': 'error', 'error': f'Argumentos inválidos para {name}: {exc}'}
        except Exception as exc:
            return {'status': 'error', 'error': f'{type(exc).__name__}: {exc}'}
        if isinstance(result, dict):
            if 'status' not in result:
                result['status'] = 'error' if result.get('error') else 'ok'
            return result
        return {'status': 'ok', 'result': result}


def build_default_registry():
    """Curated, safe-by-default registry. Destructive tools still need confirmation."""
    import os
    from datetime import datetime
    from pathlib import Path

    registry = ToolRegistry()

    registry.register(Tool('current_time', 'Fecha y hora local.',
                           lambda: {'local_time': datetime.now().astimezone().isoformat(timespec='seconds')},
                           danger=False))
    registry.register(Tool('list_created_files', 'Lista los archivos que JARVIS ha creado según su registro local.',
                           lambda: {'created': [p for p in _created_files()]},
                           danger=False))

    def _delete_created(path):
        target = Path(path)
        known = set(_created_files())
        if str(target) not in known:
            return {'error': 'No consta en mi registro que yo creara ese archivo; no lo borro.'}
        root = Path(__file__).resolve().parent.parent
        if target.resolve() == root or root in target.resolve().parents:
            return {'error': 'No borro nada dentro de la carpeta de JARVIS.'}
        if not target.is_file():
            return {'error': f'Ya no existe: {target}'}
        target.unlink()
        return {'deleted': str(target)}

    registry.register(Tool('delete_created_file',
                           'Borra un archivo creado por JARVIS (según su registro). No borra archivos del usuario.',
                           _delete_created,
                           danger=True,
                           schema={'path': 'string'}))

    def _remember(preference):
        from agent.memory import PersistentMemory
        PersistentMemory().remember_preference(preference)
        return {'remembered': preference}

    registry.register(Tool('remember_preference', 'Guarda una preferencia estable del usuario en la memoria local.',
                           _remember,
                           danger=False,
                           schema={'preference': 'string'}))
    return registry


def _created_files():
    import action_log
    seen = []
    for entry in action_log.entries(200):
        path = (entry.get('detail') or {}).get('created') if isinstance(entry, dict) else None
        if path and path not in seen:
            seen.append(path)
    return seen
