import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from google.genai import types
from brain import Brain
from system_control import SystemController
import main


def test_files_and_stats(tmp_path):
    control = SystemController()
    p = tmp_path / 'a.txt'
    control.files('create', str(p), content='hola')
    assert control.files('read', str(p))['content'] == 'hola'
    assert str(p) in control.files('search', str(tmp_path), pattern='*.txt')['matches']
    assert 'memory_percent' in control.system_stats()
    with pytest.raises(ValueError): control.open_url('file:///etc/passwd')


def test_function_denial_and_protocol():
    class Models:
        calls = 0
        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                content = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name='terminal', args={'command': 'echo hi'}))])
            else:
                assert 'rechazó' in str(kwargs['contents'][-1])
                content = types.Content(role='model', parts=[types.Part.from_text(text='Rechazado')])
            return SimpleNamespace(candidates=[SimpleNamespace(content=content)])
    controller = SimpleNamespace(terminal=lambda **kwargs: pytest.fail('No debía ejecutarse'))
    brain = Brain('', controller, lambda name, args: False, client=SimpleNamespace(models=Models()))
    assert brain.ask('ejecuta') == 'Rechazado'


def test_first_run_consent(tmp_path, monkeypatch):
    state = tmp_path / 'state.json'
    monkeypatch.setattr(main, 'STATE', state)
    monkeypatch.setattr(main, 'confirm', lambda prompt: False)
    assert not main.initial_security() and not state.exists()
    monkeypatch.setattr(main, 'confirm', lambda prompt: True)
    assert main.initial_security()
    assert json.loads(state.read_text())['initial_accepted'] is True


def test_updater_fast_forward_and_dirty_guard(tmp_path, monkeypatch):
    import subprocess
    import updater
    def run(*args, cwd):
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
    remote = tmp_path / 'remote.git'
    run('git', 'init', '--bare', str(remote), cwd=tmp_path)
    source = tmp_path / 'source'
    run('git', 'clone', str(remote), str(source), cwd=tmp_path)
    run('git', 'config', 'user.email', 'test@example.com', cwd=source)
    run('git', 'config', 'user.name', 'Test', cwd=source)
    (source / 'file.txt').write_text('v1')
    run('git', 'add', 'file.txt', cwd=source)
    run('git', 'commit', '-m', 'one', cwd=source)
    run('git', 'push', '-u', 'origin', 'HEAD', cwd=source)
    clone = tmp_path / 'clone'
    run('git', 'clone', str(remote), str(clone), cwd=tmp_path)
    monkeypatch.setattr(updater, 'ROOT', clone)
    (source / 'file.txt').write_text('v2')
    run('git', 'commit', '-am', 'two', cwd=source)
    run('git', 'push', cwd=source)
    (clone / 'untracked').write_text('no sobrescribir')
    with pytest.raises(updater.UpdateError): updater.update()
    (clone / 'untracked').unlink()
    assert updater.update() is True
    assert (clone / 'file.txt').read_text() == 'v2'
    assert updater.update() is False


def test_voice_fallback_and_off(monkeypatch):
    from voice import Voice
    voice = Voice()
    calls = []
    def fail(text):
        calls.append(('edge', text))
        raise OSError('network')
    monkeypatch.setattr(voice, '_neural', fail)
    monkeypatch.setattr(voice, '_local', lambda text: calls.append(('local', text)))
    monkeypatch.setenv('JARVIS_VOICE_MODE', 'edge')
    voice.speak('Hola')
    voice.queue.join()
    assert calls == [('edge', 'Hola'), ('local', 'Hola')]
    monkeypatch.setenv('JARVIS_VOICE_MODE', 'off')
    voice.speak('No hablar')
    assert len(calls) == 2


def test_voice_activity_stops_even_on_local_error(monkeypatch):
    import sys
    from voice import Voice
    events = []
    class Engine:
        def say(self, text): pass
        def runAndWait(self): raise RuntimeError('audio failure')
        def stop(self): pass
    monkeypatch.setitem(sys.modules, 'pyttsx3', SimpleNamespace(init=lambda: Engine()))
    voice = Voice()
    voice.on_activity = events.append
    with pytest.raises(RuntimeError):
        voice._local('hola')
    assert events == [True, False]


def test_spoken_authorization_fails_closed():
    from voice_session import VoiceSession, is_approval
    assert is_approval('¡Autorizo!')
    for text in ('no autorizo', 'sí autorizo', '', 'autorizar'):
        assert not is_approval(text)
    class Voice:
        def __init__(self, success): self.success = success; self.spoken = []
        def speak_wait(self, text): self.spoken.append(text); return self.success
    answers = iter(['autorizo', 'no autorizo'])
    voice = Voice(True)
    session = VoiceSession(None, voice, lambda: next(answers))
    assert session.approve('terminal', {'command': 'echo hola'})
    assert 'echo hola' in voice.spoken[0]
    assert not session.approve('terminal', {'command': 'echo hola'})
    assert not VoiceSession(None, Voice(False), lambda: 'autorizo').approve('terminal', {'command': 'echo hola'})
    session.stop()
    assert not session.approve('terminal', {'command': 'echo hola'})


def test_voice_session_does_not_execute_after_stop():
    from voice_session import VoiceSession
    brain = SimpleNamespace(ask=lambda text: pytest.fail('request after stop'))
    voice = SimpleNamespace(speak_wait=lambda text: True)
    session = VoiceSession(brain, voice, lambda: (session.stop(), 'haz algo')[1])
    session.run()


def test_wake_word_conversation():
    from voice_session import VoiceSession, wake_request
    assert wake_request('Jarvis, qué hora es') == 'qué hora es'
    assert wake_request('JARVIS') == ''
    assert wake_request('hola') is None
    assert wake_request('superjarvis') is None
    spoken, requests = [], []
    inputs = iter(['conversación ajena', 'Jarvis, hola', 'Jarvis', 'qué hora es'])
    voice = SimpleNamespace(speak_wait=lambda text: spoken.append(text) or True)
    def listen():
        try: return next(inputs)
        except StopIteration:
            session.stop()
            return ''
    brain = SimpleNamespace(ask=lambda text: requests.append(text) or 'respuesta')
    session = VoiceSession(brain, voice, listen)
    session.run()
    assert requests == ['hola', 'qué hora es']
    assert 'Le escucho, señor.' in spoken


def test_whatsapp_draft(monkeypatch):
    import system_control
    opened = []
    monkeypatch.setattr(system_control.webbrowser, 'open', lambda url: opened.append(url) or True)
    control = SystemController()
    result = control.whatsapp_prepare('+51987654321', 'te amo 💙')
    assert result['opened'] and not result['sent']
    assert opened[0].startswith('https://wa.me/51987654321?text=')
    assert 'te+amo' in opened[0]
    for phone in ('prisila', '000', '123?x=1'):
        with pytest.raises(ValueError): control.whatsapp_prepare(phone, 'hola')


def test_error_message_no_secrets():
    from google.genai import errors as genai_errors
    from errors import describe_error
    exc = genai_errors.ClientError(429, {'error': {'message': 'secret-api-key'}})
    text = describe_error(exc)
    assert '429' in text and 'secret-api-key' not in text


def test_nvidia_tool_approval_and_response():
    from nvidia_brain import NvidiaBrain
    responses = [
        {'choices': [{'message': {'content': None, 'tool_calls': [{'id': '1', 'type': 'function', 'function': {'name': 'system_stats', 'arguments': '{}'}}]}}]},
        {'choices': [{'message': {'content': 'Acción rechazada.'}}]},
    ]
    calls = []
    def post(url, headers, json, timeout):
        import copy
        calls.append(copy.deepcopy(json))
        return SimpleNamespace(status_code=200, json=lambda: responses.pop(0))
    controller = SimpleNamespace(system_stats=lambda: pytest.fail('Acción denegada'))
    brain = NvidiaBrain('test-only-key', controller, lambda *args: False, post=post)
    assert brain.ask('consulta el sistema') == 'Acción rechazada.'
    assert calls[1]['messages'][-1]['role'] == 'tool'
    assert 'rechazó' in calls[1]['messages'][-1]['content']
    assert all(t['function']['parameters']['type'] == 'object' for t in brain.tools)


def test_nvidia_errors_safe():
    from nvidia_brain import NvidiaBrain
    from errors import describe_error
    def post(*args, **kwargs): return SimpleNamespace(status_code=429)
    brain = NvidiaBrain('test-only-key', object(), lambda *args: False, post=post)
    with pytest.raises(Exception) as exc:
        brain.ask('hola')
    assert '429' in describe_error(exc.value)
    assert 'test-only-key' not in describe_error(exc.value)


def test_core_state_priority_and_transitions():
    from core_state import CoreState
    state = CoreState()
    assert state.current == 'idle'
    assert state.set_task('thinking') == 'thinking'
    assert state.set_speaking(True) == 'speaking'
    assert state.set_task('approval') == 'approval'
    assert state.set_speaking(False) == 'approval'
    assert state.set_speaking(True) == 'approval'
    assert state.set_task('thinking') == 'speaking'
    assert state.set_speaking(False) == 'thinking'
    assert state.set_task('idle') == 'idle'
    with pytest.raises(ValueError): state.set_task('unknown')


def test_voice_consent_indicates_approval_while_speaking():
    from voice_session import VoiceSession
    statuses = []
    class Voice:
        def speak_wait(self, text):
            assert statuses[-1] == 'Esperando autorización por voz'
            return True
    session = VoiceSession(None, Voice(), lambda: 'autorizo', statuses.append)
    assert session.approve('system_stats', {})
    assert statuses == ['Esperando autorización por voz', 'Pensando']


def test_status_resource_sampling(monkeypatch):
    import status_data
    monkeypatch.setattr(status_data.psutil, 'cpu_percent', lambda interval: 23.2)
    monkeypatch.setattr(status_data.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=46.7))
    assert status_data.sample_usage() == {'cpu': '23 %', 'memory': '47 %'}
    def fail(interval): raise OSError('No disponible')
    monkeypatch.setattr(status_data.psutil, 'cpu_percent', fail)
    assert status_data.sample_usage() == {'cpu': 'No disponible', 'memory': 'No disponible'}


def test_voice_session_reports_provider_result():
    from voice_session import VoiceSession
    statuses = []
    voice = SimpleNamespace(speak_wait=lambda text: True)
    utterances = iter(['Jarvis hola'])
    def listen():
        try: return next(utterances)
        except StopIteration:
            session.stop()
            return ''
    session = VoiceSession(SimpleNamespace(ask=lambda request: 'hola'), voice, listen, connection=statuses.append)
    session.run()
    assert statuses == ['Respondió']
