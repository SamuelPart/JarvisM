"""NVIDIA NIM agent with per-tool authorization; no credentials in source."""
import json
import requests
from brain import INSTRUCTIONS, TOOLS

NVIDIA_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
DEFAULT_MODEL = 'nvidia/nemotron-3.5-bolt-e4b'


class NvidiaError(Exception):
    def __init__(self, status=None):
        self.status = status
        super().__init__('NVIDIA request failed')


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
    def __init__(self, api_key, controller, approve, name='Señor', model=DEFAULT_MODEL, post=None, max_steps=12):
        if not api_key:
            raise ValueError('Configure NVIDIA_API_KEY en .env; no comparta la clave.')
        self.api_key, self.controller, self.approve = api_key, controller, approve
        self.model, self.post, self.max_steps = model, post or requests.post, max_steps
        self.tools = nvidia_tools()
        self.allowed = {tool['function']['name'] for tool in self.tools}
        self.history = [{'role': 'system', 'content': INSTRUCTIONS.format(name=name)}]

    def ask(self, text):
        self.history.append({'role': 'user', 'content': text})
        for _ in range(self.max_steps):
            payload = {'model': self.model, 'messages': self.history, 'temperature': 1,
                       'top_p': 0.95, 'max_tokens': 1024, 'stream': False,
                       'tools': self.tools, 'tool_choice': 'auto',
                       'parallel_tool_calls': False, 'chat_template_kwargs': {'enable_thinking': True}}
            try:
                response = self.post(NVIDIA_URL, headers={'Authorization': 'Bearer ' + self.api_key,
                                     'Accept': 'application/json'}, json=payload, timeout=60)
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
                    if not self.approve(name, args):
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
