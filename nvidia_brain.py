"""NVIDIA NIM agent with per-tool authorization; no credentials in source.

The API key is resolved per request, in this order: static value passed to
the constructor, the desktop app's local settings file (Ajustes -> Proveedor
de IA, via provider_settings), then NVIDIA_API_KEY from the environment or
.env (console fallback). With no key configured, ask() raises
ProviderNotConfigured, which callers surface as a clear, safe message.
"""
import json
import os
import requests
from brain import INSTRUCTIONS, TOOLS
from permissions import authorize_tool
from provider_settings import resolve_api_key

NVIDIA_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
DEFAULT_MODEL = 'nvidia/nemotron-3.5-bolt-e4b'


class NvidiaError(Exception):
    def __init__(self, status=None):
        self.status = status
        super().__init__('NVIDIA request failed')


class ProviderNotConfigured(NvidiaError):
    """Raised when no NVIDIA API key is available (settings file or env)."""


def _schema(value):
    if isinstance(value, dict):
        return {k: (v.lower() if k == 'type' and isinstance(v, str) else _schema(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_schema(item) for item in value]
    return value


def nvidia_tools():
    result = []
    for tool in TOOLS:
        parameters = tool.parameters.model_dump(mode='json', exclude_none=True)
        result.append({'type': 'function', 'function': {'name': tool.name,
                       'description': tool.description, 'parameters': _schema(parameters)}})
    return result


class NvidiaBrain:
    def __init__(self, api_key=None, controller=None, approve=None, name='Señor', model=DEFAULT_MODEL, post=None, max_steps=12):
        self.api_key = (api_key or '').strip()  # optional static override; settings/env are consulted per request
        self.controller, self.approve = controller, approve
        self.model, self.post, self.max_steps = model, post or requests.post, max_steps
        self.tools = nvidia_tools()
        self.allowed = {tool['function']['name'] for tool in self.tools}
        self.history = [{'role': 'system', 'content': INSTRUCTIONS.format(name=name)}]

    def _target(self):
        key = resolve_api_key(self.api_key)
        if not key:
            raise ProviderNotConfigured()
        return NVIDIA_URL, {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}

    def ask(self, text):
        self.history.append({'role': 'user', 'content': text})
        for _ in range(self.max_steps):
            payload = {'model': self.model, 'messages': self.history, 'temperature': 1,
                       'top_p': 0.95, 'max_tokens': 1024, 'stream': False,
                       'tools': self.tools, 'tool_choice': 'auto',
                       'parallel_tool_calls': False, 'chat_template_kwargs': {'enable_thinking': True}}
            url, headers = self._target()
            try:
                response = self.post(url, headers=headers, json=payload, timeout=60)
            except requests.RequestException as exc:
                raise NvidiaError() from exc
            if not 200 <= response.status_code < 300:
                raise NvidiaError(response.status_code)
            try:
                message = response.json()['choices'][0]['message']
                calls = message.get('tool_calls') or []
                content = message.get('content') or ''
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise NvidiaError() from exc
            # Do not forward private reasoning fields returned by the provider.
            assistant = {'role': 'assistant', 'content': content}
            if calls:
                assistant['tool_calls'] = calls
            self.history.append(assistant)
            if not calls:
                return content.strip() or 'Señor, el modelo no devolvió una respuesta de texto.'
            for call in calls:
                name = call.get('function', {}).get('name', '')
                try:
                    args = json.loads(call.get('function', {}).get('arguments', '{}'))
                    if name not in self.allowed or not isinstance(args, dict):
                        raise ValueError('Herramienta o argumentos no válidos.')
                    if not authorize_tool(name, args, self.approve):
                        result = {'error': 'El usuario rechazó la acción.'}
                    else:
                        result = getattr(self.controller, name)(**args)
                except Exception as exc:
                    result = {'error': f'{type(exc).__name__}: {exc}'}
                output = json.dumps(result, ensure_ascii=False, default=str)
                if len(output) > 16000:
                    output = json.dumps({'result_truncated': output[:16000]}, ensure_ascii=False)
                self.history.append({'role': 'tool', 'tool_call_id': call.get('id', ''), 'content': output})
        return 'Señor, he pausado la tarea al alcanzar el límite de acciones.'
