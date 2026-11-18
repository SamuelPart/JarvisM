import json
from types import SimpleNamespace
from pathlib import Path
import pytest
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
    from nvidia_brain import NvidiaBrain
    state = {'step': 0, 'bodies': []}
    def post(url, headers, json, timeout):
        state['step'] += 1
        state['bodies'].append(json)
        if state['step'] == 1:
            message = {'content': None, 'tool_calls': [{'id': '1', 'type': 'function', 'function':
                       {'name': 'terminal', 'arguments': '{"command": "echo hi"}'}}]}
        else:
            assert 'rechazó' in json['messages'][-1]['content']
            message = {'content': 'Rechazado'}
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(terminal=lambda **kwargs: pytest.fail('No debía ejecutarse'))
    brain = NvidiaBrain('test-only-key', controller, lambda name, args: False, post=post)
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
    from nvidia_brain import NvidiaError
    from errors import describe_error
    text = describe_error(NvidiaError(429))
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


def test_visual_preferences_round_trip_and_validation(tmp_path):
    from ui_settings import DEFAULTS, load, save
    path = tmp_path / 'settings.json'
    assert load(path) == DEFAULTS
    expected = {'color': 'violeta', 'size': 'grande', 'animation': 'reducida', 'weather_sound': 'activado'}
    assert save(path, expected) == expected
    assert load(path) == expected
    path.write_text('{"color":"invalido","size":"pequeño","animation":null}', encoding='utf-8')
    assert load(path) == {'color': 'azul', 'size': 'pequeño', 'animation': 'normal', 'weather_sound': 'activado'}
    path.write_text('{bad', encoding='utf-8')
    assert load(path) == DEFAULTS


def test_local_memory_persists_and_clears(tmp_path):
    from memory import JarvisMemory
    path = tmp_path / 'memory.sqlite3'
    memory = JarvisMemory(path)
    memory.add_turn('Mi nombre es Sam', 'Hola Sam')
    memory.set_preferences('Respuestas breves')
    reopened = JarvisMemory(path)
    assert reopened.recent() == [{'role': 'user', 'content': 'Mi nombre es Sam'}, {'role': 'assistant', 'content': 'Hola Sam'}]
    assert reopened.get_preferences() == 'Respuestas breves'
    reopened.clear()
    assert JarvisMemory(path).recent() == []
    assert JarvisMemory(path).get_preferences() == ''


def test_memory_is_shared_across_providers_and_no_duplicate_turn(tmp_path):
    from memory import JarvisMemory
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    memory = JarvisMemory(tmp_path / 'local.sqlite3')
    memory.add_turn('Recuerda que me gusta el café', 'Lo recordaré')
    memory.set_preferences('Prefiero español')
    seen = []
    def post(url, headers, json, timeout):
        import copy
        seen.append(copy.deepcopy(json['messages']))
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': 'Café'}}]})
    agent = PersistentBrain(NvidiaBrain('fake-key', object(), lambda *_: False, post=post), memory)
    assert agent.ask('¿Qué me gusta?') == 'Café'
    assert 'Prefiero español' in seen[0][0]['content']
    assert seen[0][1]['content'] == 'Recuerda que me gusta el café'
    assert seen[0][-1]['content'] == '¿Qué me gusta?'
    assert len(memory.recent()) == 4
    agent.clear_memory()
    agent.refresh_context()
    assert len(agent.brain.history) == 1
    assert 'Prefiero español' not in agent.brain.history[0]['content']


def test_reminder_lifecycle_and_restart(tmp_path):
    from agenda import Agenda
    path = tmp_path / 'agenda.sqlite3'
    agenda = Agenda(path)
    with pytest.raises(ValueError): agenda.add('   ', 1001, now=1000)
    with pytest.raises(ValueError): agenda.add('Prueba', 999, now=1000)
    reminder = agenda.add('Llamar', 1100, now=1000)
    assert agenda.claim_due(now=1099) == []
    assert Agenda(path).claim_due(now=1150) == [{'id': reminder, 'title': 'Llamar', 'due': 1100}]
    assert Agenda(path).claim_due(now=1200) == []
    assert agenda.list()[0]['notified'] is True
    assert agenda.delete(reminder) and agenda.list() == []


def test_reminder_atomic_claim_and_timezone(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from agenda import Agenda, timestamp_from_iso
    path = tmp_path / 'agenda.sqlite3'
    agenda = Agenda(path)
    reminder = agenda.add('Dos instancias', 2000, now=1000)
    def claim(_): return Agenda(path).claim_due(now=2000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(len(result) for result in results) == 1
    assert any(result and result[0]['id'] == reminder for result in results)
    assert timestamp_from_iso('2026-12-01T15:30:00-05:00') == timestamp_from_iso('2026-12-01T20:30:00+00:00')
    with pytest.raises(ValueError): timestamp_from_iso('2026-12-01T15:30:00')


def test_agent_reminder_tool(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from agenda import Agenda
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.db'))
    controller = SystemController()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = controller.create_reminder('Prueba', future)
    assert Agenda().list()[0]['id'] == result['id']
    assert 'local_time' in controller.current_time()


def test_web_search_returns_bounded_untrusted_snippets():
    from web_search import search
    class Searcher:
        def text(self, query, **kwargs):
            assert kwargs['backend'] == 'duckduckgo'
            return [{'title': 'Fuente', 'href': 'https://example.com/actual', 'body': 'Información actual'},
                    {'title': 'Inválido', 'href': 'file:///etc/passwd', 'body': 'no'},
                    {'title': 'Sin credenciales', 'href': 'https://user:secret@example.com/', 'body': 'no'}]
    result = search('noticias', Searcher())
    assert result['results'] == [{'title': 'Fuente', 'url': 'https://example.com/actual', 'snippet': 'Información actual'}]
    assert 'no contenido completo' in result['note']
    with pytest.raises(ValueError): search(' ', Searcher())


def test_web_search_failure_is_safe():
    from web_search import search
    class Broken:
        def text(self, *args, **kwargs): raise RuntimeError('dato-privado')
    result = search('consulta', Broken())
    assert result['results'] == [] and 'dato-privado' not in result['error']


def test_search_fallback_second_provider():
    from web_search import search
    attempts = []
    class Searcher:
        def text(self, query, **kwargs):
            attempts.append(kwargs['backend'])
            if kwargs['backend'] == 'duckduckgo': raise RuntimeError('network')
            return [{'title': 'Fuente', 'href': 'https://example.com', 'body': 'Resumen'}]
    result = search('noticias', Searcher())
    assert attempts == ['duckduckgo', 'brave']
    assert result['provider'] == 'brave' and result['results'][0]['url'] == 'https://example.com'


def test_music_search_opens_results_without_claiming_playback(monkeypatch):
    import system_control
    opened = []
    monkeypatch.setattr(system_control.webbrowser, 'open', lambda url: opened.append(url) or True)
    result = SystemController().music_search('amor y sol', 'youtube')
    assert opened == ['https://www.youtube.com/results?search_query=amor+y+sol']
    assert result['opened'] and 'usuario debe elegir' in result['note']
    with pytest.raises(ValueError): SystemController().music_search('tema', 'servicio_desconocido')


def test_links_are_clickable_safely_and_silent():
    from text_links import markup, without_links
    text = 'Mira <script>alert(1)</script> https://example.com/a?x=1&y=2.'
    rendered = markup(text)
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert '<a href="https://example.com/a?x=1&amp;y=2"' in rendered
    assert 'https://' not in without_links(text)
    assert '<a href=' not in markup('https://user:secret@example.com')


def test_scoped_permission_cannot_allow_terminal(tmp_path, monkeypatch):
    import permissions
    state = tmp_path / 'state.json'
    state.write_text('{"initial_accepted": true}')
    monkeypatch.setattr(permissions, 'STATE', state)
    assert not permissions.preapproved('web_search')
    permissions.set_network_permission(True)
    assert permissions.preapproved('web_search') and permissions.preapproved('play_music')
    assert not permissions.preapproved('terminal') and not permissions.preapproved('files')
    assert permissions.read_state()['initial_accepted'] is True
    permissions.set_network_permission(False)
    assert not permissions.preapproved('play_music')






def test_network_preapproval_applies_to_agent_but_not_terminal(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    from nvidia_brain import NvidiaBrain
    seen = []
    state = {'step': 0}
    def post(url, headers, json, timeout):
        state['step'] += 1
        step = state['step']
        if step == 1:
            message = {'content': None, 'tool_calls': [{'id': '1', 'type': 'function',
                        'function': {'name': 'web_search', 'arguments': '{"query": "noticias"}'}}]}
        elif step == 2:
            message = {'content': None, 'tool_calls': [{'id': '2', 'type': 'function',
                        'function': {'name': 'terminal', 'arguments': '{"command": "echo hello"}'}}]}
        else:
            message = {'content': 'Listo'}
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(web_search=lambda query: {'results': []}, terminal=lambda command: pytest.fail('terminal no autorizado'))
    agent = NvidiaBrain('test-only-key', controller, lambda name, args: seen.append(name) or False, post=post)
    assert agent.ask('Busca') == 'Listo'
    assert seen == ['terminal']


def test_speech_text_removes_markdown_stars_and_urls():
    from text_links import speech_text
    text = '**Hola**, Señor. *Ejemplo*. [Fuente](https://example.com/a)'
    result = speech_text(text)
    assert result == 'Hola, Señor. Ejemplo. Fuente'
    assert '*' not in result and 'https://' not in result



def test_nvidia_vision_request_encodes_selected_image(monkeypatch):
    import base64
    from nvidia_vision import analyze, NVIDIA_URL, DEFAULT_MODEL
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-key')
    monkeypatch.delenv('NVIDIA_VISION_API_KEY', raising=False)
    monkeypatch.delenv('NVIDIA_VISION_MODEL', raising=False)
    image = b'\x89PNG\r\n\x1a\n' + b'contenido'
    class Session:
        def __init__(self): self.trust_env = True; self.closed = False
        def post(self, url, **kwargs):
            assert url == NVIDIA_URL and self.trust_env is False and kwargs['allow_redirects'] is False
            assert kwargs['json']['model'] == DEFAULT_MODEL
            image_url = kwargs['json']['messages'][0]['content'][1]['image_url']['url']
            assert image_url.startswith('data:image/png;base64,')
            assert base64.b64decode(image_url.split(',', 1)[1]) == image
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': 'Una imagen.'}}]})
        def close(self): self.closed = True
    session = Session()
    assert analyze(image, 'Describe', session_factory=lambda: session) == 'Una imagen.'
    assert session.closed


def test_nvidia_vision_validation_and_quota(tmp_path, monkeypatch):
    from nvidia_vision import VisionError, analyze, read_image
    bad = tmp_path / 'fake.png'
    bad.write_bytes(b'not an image')
    with pytest.raises(VisionError): read_image(bad)
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-key')
    class Session:
        def post(self, *args, **kwargs): return SimpleNamespace(status_code=429)
        def close(self): pass
    with pytest.raises(VisionError, match='429'):
        analyze(b'\xff\xd8\xff' + b'test', 'Describe', session_factory=Session)


def test_vision_uses_separate_key_and_falls_back(monkeypatch):
    from nvidia_vision import analyze
    monkeypatch.setenv('NVIDIA_API_KEY', 'chat-key')
    monkeypatch.setenv('NVIDIA_VISION_API_KEY', 'vision-key')
    keys = []
    class Session:
        def post(self, url, **kwargs):
            keys.append(kwargs['headers']['Authorization'])
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': 'ok'}}]})
        def close(self): pass
    image = b'\x89PNG\r\n\x1a\n' + b'test'
    assert analyze(image, 'Describe', Session) == 'ok'
    monkeypatch.delenv('NVIDIA_VISION_API_KEY')
    assert analyze(image, 'Describe', Session) == 'ok'
    assert keys == ['Bearer vision-key', 'Bearer chat-key']


def test_chat_approval_fails_closed():
    from approval import is_approved
    for phrase in ('AUTORIZO', 'sí', 'Si', '¡Autorizo!'):
        assert is_approved(phrase)
    for phrase in ('no', '', 'no autorizo', 'sí pero no', 'autorizo todo'):
        assert not is_approved(phrase)


def test_inspect_image_reads_selected_path_and_calls_vision(tmp_path, monkeypatch):
    import system_control
    file = tmp_path / 'foto.png'
    image = b'\x89PNG\r\n\x1a\n' + b'contenido'
    file.write_bytes(image)
    received = []
    monkeypatch.setattr(system_control, 'analyze', lambda data, question: received.append((data, question)) or 'Una foto')
    result = SystemController().inspect_image(str(file), '¿Qué ves?')
    assert result['description'] == 'Una foto'
    assert received == [(image, '¿Qué ves?')]


def test_image_tool_never_preapproved_and_denial_skips_io(tmp_path, monkeypatch):
    import permissions
    from nvidia_brain import NvidiaBrain
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    assert not permissions.preapproved('inspect_image')
    approvals = []
    state = {'step': 0}
    def post(url, headers, json, timeout):
        state['step'] += 1
        if state['step'] == 1:
            message = {'content': None, 'tool_calls': [{'id': '1', 'type': 'function',
                        'function': {'name': 'inspect_image', 'arguments': '{"path": "/private.png"}'}}]}
        else:
            message = {'content': 'Rechazado'}
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(inspect_image=lambda **kwargs: pytest.fail('No se debe leer ni enviar imagen'))
    brain = NvidiaBrain('test-only-key', controller, lambda name, args: approvals.append(name) or False, post=post)
    assert brain.ask('analiza la imagen') == 'Rechazado'
    assert approvals == ['inspect_image']


def test_screen_inspection_after_approval_uses_in_memory_capture(monkeypatch):
    import sys
    import system_control
    image = b'\x89PNG\r\n\x1a\n' + b'screen'
    class Screenshot:
        def save(self, output, format):
            assert format == 'PNG'
            output.write(image)
    monkeypatch.setitem(sys.modules, 'pyautogui', SimpleNamespace(screenshot=lambda: Screenshot()))
    sent = []
    monkeypatch.setattr(system_control, 'analyze', lambda data, prompt: sent.append((data, prompt)) or 'Pantalla')
    result = SystemController().inspect_screen('¿Qué aparece?')
    assert result['description'] == 'Pantalla' and sent == [(image, '¿Qué aparece?')]


def test_screen_tool_never_preapproved(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    assert not permissions.preapproved('inspect_screen')


def test_vision_network_errors_are_safe(monkeypatch):
    import requests
    from nvidia_vision import analyze, VisionError
    monkeypatch.setenv('NVIDIA_VISION_API_KEY', 'test-key')
    class Session:
        def post(self, *args, **kwargs): raise requests.exceptions.SSLError('secret should not appear')
        def close(self): pass
    with pytest.raises(VisionError) as exc:
        analyze(b'\x89PNG\r\n\x1a\n' + b'test', 'Describe', Session)
    assert 'TLS' in str(exc.value) and 'secret' not in str(exc.value)


def test_gmail_search_and_attachment_flow(monkeypatch):
    import base64
    import gmail_access
    data = b'\x89PNG\r\n\x1a\ncontenido'
    message = {'id': 'abc123', 'payload': {'headers': [{'name': 'Subject', 'value': 'Foto'}],
                'parts': [{'partId': '1', 'filename': 'foto.png', 'mimeType': 'image/png',
                           'body': {'size': len(data), 'attachmentId': 'attachment_1'}}]}}
    closed = []
    class Response:
        status_code = 200
        def __init__(self, value): self.value = value
        def json(self): return self.value
    class Session:
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            if url.endswith('/messages'): return Response({'messages': [{'id': 'abc123'}]})
            if url.endswith('/attachments/attachment_1'):
                return Response({'data': base64.urlsafe_b64encode(data).decode().rstrip('=')})
            return Response(message)
        def close(self): closed.append(True)
    monkeypatch.setattr(gmail_access, 'client', Session)
    sent = []
    monkeypatch.setattr(gmail_access, 'analyze', lambda data, question: sent.append((data, question)) or 'Una foto')
    listing = gmail_access.search_messages('from:ana has:attachment')
    assert listing['messages'][0]['images'][0]['part_id'] == '1'
    assert gmail_access.inspect_attachment('abc123', '1', 'Describe')['description'] == 'Una foto'
    assert sent == [(data, 'Describe')] and len(closed) == 2
    with pytest.raises(gmail_access.GmailError): gmail_access.inspect_attachment('abc123', 'wrong', 'Describe')
    assert len(sent) == 1


def test_gmail_tools_need_per_action_authorization(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    assert not permissions.preapproved('search_gmail')
    assert not permissions.preapproved('inspect_gmail_image')


def test_gmail_send_validates_and_submits_with_approval_data(monkeypatch):
    import base64
    from email import message_from_bytes
    import gmail_access
    calls = []
    class Reply:
        status_code = 200
        def json(self): return {'id': 'sent123'}
    class Session:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Reply()
        def close(self): pass
    monkeypatch.setattr(gmail_access, 'client', Session)
    result = gmail_access.send_message('ana@example.com', 'Hola', 'Buenos días')
    assert result['sent'] is True
    email = message_from_bytes(base64.urlsafe_b64decode(calls[0][1]['json']['raw']))
    assert email['To'] == 'ana@example.com' and email['Subject'] == 'Hola'
    assert calls[0][1]['allow_redirects'] is False
    with pytest.raises(gmail_access.GmailError): gmail_access.send_message('ana@example.com\nBcc:evil@example.com', 'Hola', 'texto')
    assert len(calls) == 1


def test_gmail_classification_verifies_identity_and_only_one_message(monkeypatch):
    import gmail_access
    calls = []
    class Response:
        status_code = 200
        def json(self): return {'id': 'a123'}
    class Session:
        def get(self, *args, **kwargs):
            class Msg:
                status_code = 200
                def json(self): return {'id': 'a123', 'payload': {'headers': [{'name': 'From', 'value': 'Ana <ana@example.com>'}, {'name': 'Subject', 'value': 'Recibo'}]}}
            return Msg()
        def post(self, url, **kwargs): calls.append((url, kwargs)); return Response()
        def close(self): pass
    monkeypatch.setattr(gmail_access, 'client', Session)
    with pytest.raises(gmail_access.GmailError): gmail_access.classify_message('a123', 'Otro', 'Recibo', 'spam')
    assert not calls
    assert gmail_access.classify_message('a123', 'Ana <ana@example.com>', 'Recibo', 'important')['updated']
    assert calls[0][1]['json'] == {'addLabelIds': ['IMPORTANT']}
    assert calls[0][0].endswith('/messages/a123/modify')


def test_gmail_send_timeout_has_uncertain_status(monkeypatch):
    import gmail_access
    import requests
    class Session:
        def post(self, *args, **kwargs): raise requests.Timeout('secret')
        def close(self): pass
    monkeypatch.setattr(gmail_access, 'client', Session)
    with pytest.raises(gmail_access.GmailError, match='Enviados'):
        gmail_access.send_message('ana@example.com', 'Hola', 'texto')


def test_gmail_mutations_never_preapproved(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    for name in ('send_gmail', 'classify_gmail', 'read_gmail'):
        assert not permissions.preapproved(name)


def test_gmail_persistent_permission_is_separate_and_revocable(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    assert not permissions.preapproved('send_gmail')
    permissions.set_gmail_permission(True)
    for name in ('search_gmail', 'read_gmail', 'send_gmail', 'classify_gmail'):
        assert permissions.preapproved(name)
    for name in ('inspect_gmail_image', 'inspect_image', 'inspect_screen', 'terminal', 'files'):
        assert not permissions.preapproved(name)
    assert permissions.preapproved('web_search')
    permissions.set_gmail_permission(False)
    assert not permissions.preapproved('send_gmail')
    assert permissions.preapproved('web_search')


def test_reply_gmail_uses_verified_reply_to_and_thread(monkeypatch):
    import base64
    from email import message_from_bytes
    import gmail_access
    sent = []
    class Response:
        status_code = 200
        def __init__(self, value): self.value = value
        def json(self): return self.value
    class Session:
        def get(self, *args, **kwargs):
            return Response({'id': 'abc123', 'threadId': 'abc456', 'payload': {'headers': [
                {'name': 'From', 'value': 'Ana <ana@example.com>'}, {'name': 'Subject', 'value': 'Hola'},
                {'name': 'Message-ID', 'value': '<original@example.com>'}]}})
        def post(self, url, **kwargs):
            sent.append(kwargs['json'])
            return Response({'id': 'new123'})
        def close(self): pass
    monkeypatch.setattr(gmail_access, 'client', Session)
    with pytest.raises(gmail_access.GmailError): gmail_access.reply_message('abc123', 'otro@example.com', 'Hola', 'Respuesta')
    assert not sent
    assert gmail_access.reply_message('abc123', 'ana@example.com', 'Hola', 'Respuesta')['sent']
    assert sent[0]['threadId'] == 'abc456'
    email = message_from_bytes(base64.urlsafe_b64decode(sent[0]['raw']))
    assert email['In-Reply-To'] == '<original@example.com>' and email['Subject'] == 'Re: Hola'


def test_calendar_validates_interval_and_limits_output(monkeypatch):
    import calendar_access
    calls = []
    class Response:
        status_code = 200
        def json(self): return {'items': [{'summary': 'Reunión', 'start': {'dateTime': '2026-11-15T10:00:00-05:00'}}], 'nextPageToken': 'more'}
    class Session:
        def get(self, url, **kwargs): calls.append((url, kwargs)); return Response()
        def close(self): pass
    monkeypatch.setattr(calendar_access, 'client', Session)
    result = calendar_access.list_events('2026-11-15T00:00:00-05:00', '2026-11-16T00:00:00-05:00')
    assert result['events'][0]['title'] == 'Reunión' and result['truncated']
    assert calls[0][1]['allow_redirects'] is False
    with pytest.raises(calendar_access.CalendarError): calendar_access.list_events('2026-11-15', '2026-11-16')
    with pytest.raises(calendar_access.CalendarError): calendar_access.list_events('2026-01-01T00:00:00+00:00', '2026-03-01T00:00:00+00:00')
    assert len(calls) == 1


def test_reply_included_in_gmail_permission_but_not_calendar(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_gmail_permission(True)
    assert permissions.preapproved('reply_gmail')
    assert not permissions.preapproved('list_calendar_events')
    assert not permissions.preapproved('list_reminders')


def test_music_can_stop_verified_process_after_restart(tmp_path, monkeypatch):
    import json
    import music_player
    state = tmp_path / 'music.json'
    monkeypatch.setattr(music_player, 'STATE', state)
    marker = '--title=JARVIS-' + 'a' * 32
    state.write_text(json.dumps({'pid': 123, 'created': 100.0, 'marker': marker}))
    terminated = []
    class Process:
        def create_time(self): return 100.0
        def cmdline(self): return ['mpv', marker]
        def terminate(self): terminated.append(True)
        def wait(self, timeout): pass
    monkeypatch.setattr(music_player.psutil, 'Process', lambda pid: Process())
    assert music_player.MusicPlayer()._stop_legacy()['stopped']
    assert terminated == [True] and not state.exists()


def test_music_does_not_stop_reused_or_foreign_process(tmp_path, monkeypatch):
    import json
    import music_player
    state = tmp_path / 'music.json'
    monkeypatch.setattr(music_player, 'STATE', state)
    state.write_text(json.dumps({'pid': 123, 'created': 100.0, 'marker': '--title=JARVIS-' + 'a' * 32}))
    class Process:
        def create_time(self): return 101.0
        def terminate(self): pytest.fail('No debe detener un proceso ajeno')
    monkeypatch.setattr(music_player.psutil, 'Process', lambda pid: Process())
    assert not music_player.MusicPlayer()._stop_legacy()['stopped']
    assert not state.exists()



def test_default_voice_mode_is_elevenlabs(monkeypatch):
    from voice import Voice
    monkeypatch.delenv('JARVIS_VOICE_MODE', raising=False)
    calls = []
    voice = Voice()
    monkeypatch.setattr(voice, '_elevenlabs', lambda text: calls.append(text))
    assert voice.speak_wait('Hola')
    assert calls == ['Hola']


def test_elevenlabs_without_key_falls_back_to_edge(monkeypatch, capsys):
    from voice import Voice
    monkeypatch.setenv('JARVIS_VOICE_MODE', 'elevenlabs')
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    calls = []
    voice = Voice()
    monkeypatch.setattr(voice, '_neural', lambda text: calls.append(text))
    monkeypatch.setattr(voice, '_local', lambda text: pytest.fail('No debería usar voz local'))
    assert voice.speak_wait('Hola')
    assert calls == ['Hola']
    assert 'ELEVENLABS_API_KEY' in capsys.readouterr().out


def test_elevenlabs_success_downloads_and_plays(monkeypatch, tmp_path):
    import json
    import voice as voice_module
    fake_mp3 = b'ID3-fake-audio-bytes'

    class _Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, chunk_size=65536):
            yield fake_mp3

    class _Session:
        trust_env = True
        def post(self, url, headers=None, json=None, params=None, timeout=None, allow_redirects=None, stream=None):
            assert headers['xi-api-key'] == 'secret-key'
            assert url.rsplit('/', 1)[-1] == 'JBFqnCBsd6RMkjVDRZzb'  # George por defecto
            assert params['output_format'] == 'mp3_44100_128'
            return _Response()
        def close(self): pass

    monkeypatch.setenv('ELEVENLABS_API_KEY', 'secret-key')
    monkeypatch.delenv('ELEVENLABS_VOICE_ID', raising=False)
    monkeypatch.delenv('ELEVENLABS_MODEL_ID', raising=False)
    monkeypatch.setattr('requests.Session', _Session)
    played = []
    monkeypatch.setattr(voice_module.Voice, '_play_file', lambda self, path: played.append(path.read_bytes()))
    voice = voice_module.Voice()
    voice._elevenlabs('Hola, señor.')
    assert played == [fake_mp3]


def test_elevenlabs_http_error_never_leaks_key_or_provider_message(monkeypatch):
    import voice as voice_module

    class _Response:
        status_code = 401
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, chunk_size=4096):
            yield b'{"detail": {"status": "invalid_api_key"}}'

    def _fake_post(url, headers=None, json=None, params=None, timeout=None, allow_redirects=None, stream=None):
        return _Response()

    class _Session:
        trust_env = True
        def post(self, *args, **kwargs): return _fake_post(*args, **kwargs)
        def close(self): pass

    monkeypatch.setenv('ELEVENLABS_API_KEY', 'supersecretkey123')
    monkeypatch.setattr('requests.Session', _Session)
    voice = voice_module.Voice()
    with pytest.raises(voice_module.VoiceError) as error:
        voice._elevenlabs('Hola')
    message = str(error.value)
    assert 'HTTP 401' in message and 'clave' in message  # allowlisted body hint, no provider text
    assert 'supersecretkey123' not in message


def test_elevenlabs_output_format_env_passthrough(monkeypatch):
    import voice as voice_module

    seen = {}

    class _Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, chunk_size=65536):
            yield b'ID3-x'

    class _Session:
        trust_env = True
        def post(self, url, headers=None, json=None, params=None, timeout=None, allow_redirects=None, stream=None):
            seen['params'] = params
            return _Response()
        def close(self): pass

    monkeypatch.setenv('ELEVENLABS_API_KEY', 'secret-key')
    monkeypatch.setenv('ELEVENLABS_OUTPUT_FORMAT', 'mp3_22050_32')
    monkeypatch.setattr('requests.Session', _Session)
    monkeypatch.setattr(voice_module.Voice, '_play_file', lambda self, path: None)
    voice_module.Voice()._elevenlabs('Hola')
    assert seen['params'] == {'output_format': 'mp3_22050_32'}


def test_elevenlabs_string_detail_and_429_hint():
    import voice as voice_module

    class _Response:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
        def iter_content(self, chunk_size=4096):
            yield self._body

    assert 'cuota' in voice_module.elevenlabs_error(_Response(429, b'{"detail": "quota_exceeded"}'))
    assert 'clave' in voice_module.elevenlabs_error(_Response(401, b'{"detail": "invalid_api_key"}'))
    assert 'voz o modelo' in voice_module.elevenlabs_error(_Response(404, b'{}')).lower()


def test_edge_mode_skips_elevenlabs(monkeypatch):
    from voice import Voice
    monkeypatch.setenv('JARVIS_VOICE_MODE', 'edge')
    calls = []
    voice = Voice()
    monkeypatch.setattr(voice, '_elevenlabs', lambda text: pytest.fail('No debería usar ElevenLabs'))
    monkeypatch.setattr(voice, '_neural', lambda text: calls.append(text))
    assert voice.speak_wait('Hola')
    assert calls == ['Hola']














def test_disabled_animation_setting_migrates_to_reduced():
    from ui_settings import normalize
    assert normalize({'animation': 'desactivada'})['animation'] == 'reducida'








def test_agenda_persistent_permission_scoped_and_revocable(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    assert not permissions.preapproved('list_reminders')
    permissions.set_agenda_permission(True)
    for name in ('current_time', 'list_reminders', 'list_calendar_events'):
        assert permissions.preapproved(name)
    for name in ('create_reminder', 'terminal', 'files', 'inspect_screen', 'inspect_gmail_image', 'send_gmail'):
        assert not permissions.preapproved(name)
    permissions.set_gmail_permission(True)
    assert permissions.preapproved('send_gmail')
    permissions.set_agenda_permission(False)
    assert not permissions.preapproved('list_reminders')
    assert permissions.preapproved('send_gmail')


def test_startup_briefing_permission_persists_and_is_scoped(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    assert not permissions.read_state().get('startup_briefing_accepted', False)
    permissions.set_briefing_permission(True)
    assert permissions.read_state()['startup_briefing_asked']
    assert permissions.read_state()['startup_briefing_accepted']
    assert not permissions.preapproved('terminal')
    assert not permissions.preapproved('create_reminder')
    permissions.set_briefing_permission(False)
    assert not permissions.read_state()['startup_briefing_accepted']
    assert permissions.read_state()['startup_briefing_asked']


def test_startup_briefing_first_review_and_later_changes(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import startup_briefing as brief
    now = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(brief, 'STATE', tmp_path / 'baseline.json')
    monkeypatch.setattr(brief.calendar_access, 'TOKEN', tmp_path / 'missing-token')
    monkeypatch.setattr(brief, 'Agenda', lambda: SimpleNamespace(list=lambda: [
        {'title': 'Llamar a mamá', 'due': now.timestamp() - 60, 'notified': False},
        {'title': 'Después', 'due': now.timestamp() + 2 * 86400, 'notified': False}]))
    monkeypatch.setattr(brief.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=40))
    disk = SimpleNamespace(free=40 * 1024**3, percent=40)
    monkeypatch.setattr(brief.psutil, 'disk_usage', lambda _: disk)
    monkeypatch.setattr(brief.psutil, 'sensors_battery', lambda: SimpleNamespace(percent=75))
    monkeypatch.setattr(brief, 'journal_errors', lambda since, until: 3)
    first = brief.build(now)
    assert 'Buenos días' in first and '¿Cómo está hoy?' in first
    assert 'Llamar a mamá' in first and 'Después' not in first
    assert 'primera revisión' in first and 'batería al 75' in first
    assert 'registros de error' not in first
    disk.free = 30 * 1024**3
    second = brief.build(now.replace(hour=14))
    assert 'Buenas tardes' in second and '10 gigabytes' in second
    assert '3 registros de error' in second and 'no necesariamente' in second
    assert json.loads((tmp_path / 'baseline.json').read_text())['disk_free'] == disk.free


def test_startup_briefing_handles_calendar_and_unavailable_journal(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import startup_briefing as brief
    now = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(brief, 'STATE', tmp_path / 'baseline.json')
    token = tmp_path / 'calendar-token'
    token.touch()
    monkeypatch.setattr(brief.calendar_access, 'TOKEN', token)
    monkeypatch.setattr(brief.calendar_access, 'list_events', lambda start, end: {'events': [{'title': 'Reunión'}]})
    monkeypatch.setattr(brief, 'Agenda', lambda: SimpleNamespace(list=lambda: []))
    monkeypatch.setattr(brief.psutil, 'virtual_memory', lambda: SimpleNamespace(percent=20))
    monkeypatch.setattr(brief.psutil, 'disk_usage', lambda _: SimpleNamespace(free=50 * 1024**3, percent=10))
    monkeypatch.setattr(brief.psutil, 'sensors_battery', lambda: None)
    monkeypatch.setattr(brief.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(brief, 'journal_errors', lambda *_: None)
    (tmp_path / 'baseline.json').write_text(json.dumps({'checked_at': now.replace(hour=18).isoformat()}))
    result = brief.build(now)
    assert 'Buenas noches' in result and 'Reunión' in result
    assert 'No pude revisar los registros' in result and 'batería' not in result


def test_startup_details_are_bounded_to_prior_review_and_omit_metadata(tmp_path, monkeypatch):
    import startup_briefing as brief
    monkeypatch.setattr(brief, 'STATE', tmp_path / 'baseline.json')
    (tmp_path / 'baseline.json').write_text(json.dumps({'checked_at': '2026-11-15T10:00:00+00:00',
                                                        'previous_checked_at': '2026-11-14T10:00:00+00:00'}))
    monkeypatch.setattr(brief.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(brief.shutil, 'which', lambda name: '/usr/bin/journalctl')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'SYSLOG_IDENTIFIER': 'kernel', 'MESSAGE': 'x' * 500, 'EXTRA': 'private'}) + '\n')
    monkeypatch.setattr(brief.subprocess, 'run', run)
    result = brief.log_details()
    assert result['available'] and result['entries'][0]['source'] == 'kernel'
    assert len(result['entries'][0]['message']) == 300 and 'EXTRA' not in result['entries'][0]
    assert '--output-fields=PRIORITY,SYSLOG_IDENTIFIER,MESSAGE' in calls[0][0]
    assert calls[0][0][calls[0][0].index('-n') + 1] == '10'


def test_startup_log_details_require_scope(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    assert not permissions.preapproved('review_startup_logs')
    permissions.set_briefing_permission(True)
    assert permissions.preapproved('review_startup_logs')
    assert not permissions.preapproved('terminal')
    permissions.set_briefing_permission(False)
    assert not permissions.preapproved('review_startup_logs')


def test_direct_music_commands_are_conservative():
    from music_commands import parse_music_request
    assert parse_music_request('Jarvis, pon la canción de Cristo Rata, por favor') == ('play_music', {'query': 'Cristo Rata'})
    assert parse_music_request('Reproduce música de Justin Bieber') == ('play_music', {'query': 'Justin Bieber'})
    assert parse_music_request('Pausa la música') == ('stop_music', {})
    assert parse_music_request('Pon el brillo a 50') is None
    assert parse_music_request('pon el sexto sentido nada mas') == ('play_music', {'query': 'el sexto sentido nada mas'})
    assert parse_music_request('pon el sexto sentido') == ('play_music', {'query': 'el sexto sentido'})
    assert parse_music_request('pon una alarma a las ocho') is None
    assert parse_music_request('pon el volumen al 50') is None
    assert parse_music_request('No pongas música') is None
    assert parse_music_request('¿Qué es la música?') is None


def test_direct_music_calls_real_tool_and_never_claims_unconfirmed_playback(monkeypatch, tmp_path):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    calls = []
    controller = SimpleNamespace(play_music=lambda query: calls.append(query) or {'opened': False, 'error': 'Chromium no está disponible.'})
    brain = NvidiaBrain('fake', controller, lambda *_: pytest.fail('No requiere pregunta'), post=lambda **_: pytest.fail('No se necesita el modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    response = agent.ask('Pon la canción de Cristo Rata')
    assert calls == ['Cristo Rata']
    assert 'Chromium no está disponible' in response
    assert 'sonando' not in response and 'comenzado' not in response


def test_direct_music_respects_denial_and_confirmed_state(monkeypatch, tmp_path):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    calls = []
    controller = SimpleNamespace(play_music=lambda query: calls.append(query) or {'opened': True, 'playing': False, 'note': 'Hay un anuncio.'})
    brain = NvidiaBrain('fake', controller, lambda *_: False, post=lambda **_: pytest.fail('No se necesita el modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert 'no autorizada' in agent.ask('Reproduce música de prueba')
    assert calls == []
    permissions.set_network_permission(True)
    assert agent.ask('Reproduce música de prueba') == 'Hay un anuncio.'
    assert calls == ['prueba']


def test_music_model_hallucination_without_tool_is_blocked(tmp_path):
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    post = lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': 'La canción ha comenzado a sonar.'}}]})
    agent = PersistentBrain(NvidiaBrain('key', object(), lambda *_: True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('¿Me puedes abrir la canción de Cristo Rata?')
    assert 'No llegué a iniciar' in result and 'comenzado' not in result


def test_model_music_tool_failure_overrides_fabricated_success(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    calls = []
    def post(*args, **kwargs):
        calls.append(True)
        message = ({'content': '', 'tool_calls': [{'id': 't1', 'function': {'name': 'play_music', 'arguments': '{"query":"tema"}'}}]}
                   if len(calls) == 1 else {'content': 'La canción ya está sonando.'})
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(play_music=lambda query: {'opened': False, 'error': 'YouTube devolvió un error.'})
    agent = PersistentBrain(NvidiaBrain('key', controller, lambda *_: True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('¿Me puedes abrir la canción de tema?')
    assert 'YouTube devolvió un error' in result and 'sonando' not in result
















def test_music_requests_chrome_new_tab_without_claiming_playback(monkeypatch, tmp_path):
    import sys
    import music_player
    from music_commands import format_result
    class Downloader:
        def __init__(self, options): assert options['extract_flat'] is True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, query, download):
            assert query == 'ytsearch1:tema' and not download
            return {'entries': [{'id': 'dfojvebIwJc', 'title': 'Tema'}]}
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(music_player, 'STATE', tmp_path / 'music.json')
    monkeypatch.setattr(music_player.shutil, 'which', lambda name: '/usr/bin/google-chrome')
    calls = []
    monkeypatch.setattr(music_player.subprocess, 'Popen', lambda args, **kwargs: calls.append(args))
    result = music_player.MusicPlayer().play('tema')
    assert calls == [['/usr/bin/google-chrome', '--new-tab', 'https://www.youtube.com/watch?v=dfojvebIwJc']]
    assert result['requested'] and not result['playing']
    assert 'pedí abrir' in format_result('play_music', result)


def test_music_missing_chrome_and_pause_are_honest(monkeypatch, tmp_path):
    import sys
    import music_player
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs): return {'entries': [{'id': 'dfojvebIwJc'}]}
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(music_player, 'STATE', tmp_path / 'music.json')
    monkeypatch.setattr(music_player.shutil, 'which', lambda name: None)
    player = music_player.MusicPlayer()
    assert 'No encontré Google Chrome' in player.play('tema')['error']
    result = player.stop()
    assert not result['paused'] and 'directamente' in result['note']


def test_desktop_launcher_creates_gui_shortcuts_without_overwriting(monkeypatch, tmp_path):
    import desktop_launcher as launcher
    project = tmp_path / 'proyecto con espacios'
    (project / 'venv/bin').mkdir(parents=True)
    (project / 'venv/bin/python').touch()
    home = tmp_path / 'home'
    desktop = home / 'Escritorio'
    desktop.mkdir(parents=True)
    monkeypatch.setattr(launcher, 'ROOT', project)
    monkeypatch.setattr(launcher.Path, 'home', lambda: home)
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(launcher, 'desktop_directory', lambda home: desktop)
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: None)
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    paths = launcher.install()
    shortcut = desktop / 'JARVIS.desktop'
    assert shortcut in paths and shortcut.stat().st_mode & 0o111
    text = shortcut.read_text()
    assert 'Terminal=false' in text and 'gui.py"' in text
    assert f'"{project}/venv/bin/python"' in text
    assert (home / '.local/share/applications/jarvis-desktop.desktop').exists()
    shortcut.write_text('Archivo ajeno')
    launcher.install()
    assert shortcut.read_text() == 'Archivo ajeno'


def test_desktop_exec_escapes_field_codes_and_quotes():
    import desktop_launcher
    assert desktop_launcher._exec_arg('/a b/100%/$"x') == '"/a b/100%%/\\$\\"x"'
    with pytest.raises(ValueError):
        desktop_launcher._exec_arg('/bad\npath')


def test_pon_title_routes_directly_to_chrome(monkeypatch, tmp_path):
    import sys
    import music_player
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, query, download):
            assert query == 'ytsearch1:el sexto sentido'
            return {'entries': [{'id': 'dfojvebIwJc'}]}
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    monkeypatch.setattr(music_player, 'STATE', tmp_path / 'music.json')
    monkeypatch.setattr(music_player.shutil, 'which', lambda name: '/usr/bin/google-chrome')
    calls = []
    monkeypatch.setattr(music_player.subprocess, 'Popen', lambda args, **kwargs: calls.append(args))
    controller = SimpleNamespace(play_music=music_player.MusicPlayer().play)
    brain = NvidiaBrain('fake', controller, lambda *_: pytest.fail('No requiere pregunta'),
                        post=lambda **_: pytest.fail('No se necesita el modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    response = agent.ask('pon el sexto sentido')
    assert calls == [['/usr/bin/google-chrome', '--new-tab', 'https://www.youtube.com/watch?v=dfojvebIwJc']]
    assert 'pedí abrir' in response


def test_single_broad_consent_is_scoped_and_remembered(monkeypatch, tmp_path):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_automation_permission(True)
    for tool in ('web_search', 'play_music', 'send_gmail', 'create_reminder', 'files', 'open_app', 'run_routine', 'volume_brightness'):
        assert permissions.preapproved(tool), tool
    for tool in ('terminal', 'gui', 'inspect_screen', 'inspect_image', 'inspect_gmail_image'):
        assert not permissions.preapproved(tool), tool
    assert permissions.read_state()['startup_briefing_accepted']
    permissions.set_automation_permission(False)
    assert not permissions.preapproved('files')
    # Existing independent Gmail permission remains controllable separately.
    assert permissions.preapproved('send_gmail')
    permissions.set_gmail_permission(False)
    assert not permissions.preapproved('send_gmail')


def test_declining_automation_does_not_revoke_prior_permissions(monkeypatch, tmp_path):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_gmail_permission(True)
    permissions.set_automation_permission(False)
    assert permissions.preapproved('read_gmail')
    assert not permissions.preapproved('files')
    assert permissions.read_state()['network_actions_asked']


def test_routine_configures_only_supported_apps_and_handles_open_failure(monkeypatch, tmp_path):
    import routines
    monkeypatch.setattr(routines, 'STATE', tmp_path / 'routine.json')
    monkeypatch.setattr(routines.shutil, 'which', lambda name: '/usr/bin/google-chrome' if name == 'google-chrome-stable' else None)
    calls = []
    monkeypatch.setattr(routines.subprocess, 'Popen', lambda argv, **kwargs: calls.append(argv))
    monkeypatch.setattr(routines.startup_briefing, 'build', lambda: 'Buenos días.')
    assert routines.configure('Chrome, WhatsApp')['configured'] == ['chrome', 'whatsapp']
    result = routines.run()
    assert calls == [['/usr/bin/google-chrome']]
    assert result['summary'] == 'Buenos días.'
    assert result['applications'][0]['requested'] and 'No encontré' in result['applications'][1]['error']
    with pytest.raises(ValueError):
        routines.configure('chrome, rm -rf /')
    assert routines.run()['applications'][0]['application'] == 'chrome'
    assert not routines.open_app('otro programa')['requested']


def test_direct_app_and_morning_routine_respect_permission(monkeypatch, tmp_path):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    calls = []
    controller = SimpleNamespace(
        open_app=lambda name: calls.append(name) or {'requested': True},
        run_routine=lambda: {'summary': 'Buenos días.', 'applications': [{'error': 'No encontré WhatsApp instalado.'}]})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: False), JarvisMemory(tmp_path / 'memory.db'))
    assert 'no autorizada' in agent.ask('Abre Chrome')
    assert calls == []
    permissions.set_automation_permission(True)
    assert 'pedí abrir Chrome' in agent.ask('Abre Chrome')
    assert calls == ['Chrome']
    assert 'No encontré WhatsApp' in agent.ask('Jarvis, buenos días')


def test_updater_restart_uses_requested_entrypoint(monkeypatch, tmp_path):
    import updater
    called = []
    monkeypatch.setattr(updater, 'ROOT', tmp_path)
    monkeypatch.setattr(updater.os, 'execv', lambda exe, args: called.append((exe, args)))
    updater.restart('gui.py')
    assert called[0][1][1] == str(tmp_path / 'gui.py')
    with pytest.raises(ValueError):
        updater.restart('../other.py')


def test_privileged_apt_is_scoped_and_stops_on_failure(monkeypatch):
    import privileged_tasks as admin
    monkeypatch.setattr(admin.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(admin.os.path, 'isfile', lambda path: True)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr='', stdout='')
    monkeypatch.setattr(admin.subprocess, 'run', run)
    assert admin.install_program('vlc')['ok']
    assert calls[0] == ['/usr/bin/pkexec', '/usr/bin/apt-get', 'install', '-y', '--', 'vlc']
    for invalid in ('-y', 'vlc;id', 'vlc foo', '../vlc', 'vlc=1'):
        with pytest.raises(ValueError): admin.install_program(invalid)
    assert admin.update_system()['ok']
    assert calls[1][2:] == ['update']
    assert calls[2][2:4] == ['upgrade', '-y']
    calls.clear()
    monkeypatch.setattr(admin.subprocess, 'run', lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=1, stderr='secret', stdout=''))
    result = admin.update_system()
    assert not result['ok'] and result['stage'] == 'update' and len(calls) == 1
    assert 'secret' not in str(result)


def test_whatsapp_draft_requires_fresh_approval_even_with_automation(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_automation_permission(True)
    assert not permissions.preapproved('whatsapp_prepare')
    assert not permissions.preapproved('install_program')
    assert not permissions.preapproved('update_system')


def test_whatsapp_voice_reads_exact_draft_and_requires_approval():
    from voice_session import VoiceSession
    class Voice:
        def __init__(self): self.spoken = []
        def speak_wait(self, message): self.spoken.append(message); return True
    voice = Voice()
    session = VoiceSession(None, voice, lambda: 'autorizo')
    assert session.approve('whatsapp_prepare', {'phone': '+51987654321', 'message': 'Hola, ¿cómo estás?'})
    assert '+51987654321' in voice.spoken[0] and 'Hola, ¿cómo estás?' in voice.spoken[0]
    assert 'No puedo enviarlo automáticamente' in voice.spoken[0]
    assert not VoiceSession(None, voice, lambda: 'no').approve('whatsapp_prepare', {'phone': '+51987654321', 'message': 'hola'})


def test_whatsapp_tool_does_not_let_model_claim_message_was_sent(tmp_path, monkeypatch):
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    calls = []
    def post(*args, **kwargs):
        calls.append(True)
        msg = ({'content': '', 'tool_calls': [{'id': 't1', 'function': {'name': 'whatsapp_prepare', 'arguments': '{"phone":"+51987654321","message":"Hola"}'}}]}
               if len(calls) == 1 else {'content': 'Mensaje enviado.'})
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': msg}]})
    controller = SimpleNamespace(whatsapp_prepare=lambda **kwargs: {'opened': True, 'sent': False})
    agent = PersistentBrain(NvidiaBrain('key', controller, lambda *_: True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('Envía hola por WhatsApp al +51987654321')
    assert 'Pulsa Enviar' in result and 'Mensaje enviado' not in result


def test_natural_time_drops_seconds_and_timezone():
    from persistent_brain import natural_time
    assert natural_time('2026-11-14T19:48:13-05:00') == 'Son las 7:48 de la noche, señor.'
    assert natural_time('2026-11-14T01:03:13-05:00') == 'Es la 1:03 de la madrugada, señor.'
    assert natural_time('2026-11-14T12:00:00-05:00') == 'Son las 12:00 de la tarde, señor.'


def test_simple_time_request_uses_actual_time_without_model(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_agenda_permission(True)
    controller = SimpleNamespace(current_time=lambda: {'local_time': '2026-11-14T19:48:13-05:00'})
    brain = NvidiaBrain('fake', controller, lambda *_: pytest.fail('No requiere permiso'),
                        post=lambda **_: pytest.fail('No requiere modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert agent.ask('Jarvis, ¿qué hora es?') == 'Son las 7:48 de la noche, señor.'


def test_whatsapp_error_preserves_known_reason_without_leaking_details():
    from music_commands import MusicTrace
    def invalid(**kwargs):
        raise ValueError('Indique el número internacional con código de país y solo dígitos.')
    trace = MusicTrace(SimpleNamespace(whatsapp_prepare=invalid))
    with pytest.raises(ValueError): trace.whatsapp_prepare(phone='123', message='hola')
    assert 'código de país' in trace.results[0][1]['error']
    def unknown(**kwargs): raise RuntimeError('token privado')
    trace = MusicTrace(SimpleNamespace(whatsapp_prepare=unknown))
    with pytest.raises(RuntimeError): trace.whatsapp_prepare(phone='123', message='hola')
    assert 'no conozco la causa' in trace.results[0][1]['error']
    assert 'token privado' not in str(trace.results)


def test_whatsapp_reports_validation_failure_not_fake_cause(tmp_path, monkeypatch):
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    from system_control import SystemController
    calls = []
    def post(*args, **kwargs):
        calls.append(True)
        msg = ({'content': '', 'tool_calls': [{'id': 't1', 'function': {'name': 'whatsapp_prepare', 'arguments': '{"phone":"123","message":"Hola"}'}}]}
               if len(calls) == 1 else {'content': 'Listo.'})
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': msg}]})
    agent = PersistentBrain(NvidiaBrain('key', SystemController(), lambda *_: True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('Envía hola por WhatsApp')
    assert 'código de país' in result and result != 'Listo.'


def test_local_time_varied_requests_are_fresh_and_do_not_reuse_history(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain, is_local_time_request
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_agenda_permission(True)
    values = iter(['2026-11-14T19:50:03-05:00', '2026-11-14T20:42:00-05:00'])
    controller = SimpleNamespace(current_time=lambda: {'local_time': next(values)})
    brain = NvidiaBrain('fake', controller, lambda *_: pytest.fail('No requiere permiso'),
                        post=lambda **_: pytest.fail('No se debe consultar el modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert agent.ask('Jarvis, dime la hora actual') == 'Son las 7:50 de la noche, señor.'
    assert agent.ask('¿Me puedes decir qué hora es ahora?') == 'Son las 8:42 de la noche, señor.'
    for text in ('¿qué hora es en Madrid?', '¿qué hora es mañana?', '¿a qué hora es la reunión?'):
        assert not is_local_time_request(text)


def test_relative_reminders_interpret_normal_speech_and_local_clock():
    from datetime import datetime, timezone
    from reminder_commands import parse_relative_reminder
    now = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
    result = parse_relative_reminder('Jarvis, recuérdame tomar agua dentro de diez minutos', now)
    assert result['title'] == 'tomar agua'
    assert datetime.fromisoformat(result['when']).timestamp() == now.timestamp() + 600
    result = parse_relative_reminder('en un minuto recuérdame tomar agua', now)
    assert datetime.fromisoformat(result['when']).timestamp() == now.timestamp() + 60
    assert parse_relative_reminder('recuérdame tomar agua mañana', now) is None
    assert parse_relative_reminder('recuérdame tomar agua en 0 minutos', now) is None


def test_relative_reminder_creates_without_model_and_honors_permission(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    calls = []
    controller = SimpleNamespace(create_reminder=lambda **args: calls.append(args) or {'id': 12})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: False,
                             post=lambda **_: pytest.fail('No debe llamar al modelo')), JarvisMemory(tmp_path / 'memory.db'))
    assert 'no autorizada' in agent.ask('recuérdame tomar agua dentro de diez minutos')
    assert not calls
    permissions.set_automation_permission(True)
    assert 'Listo, te avisaré' in agent.ask('recuérdame tomar agua dentro de diez minutos')
    assert calls[0]['title'] == 'tomar agua' and 'T' in calls[0]['when']


def test_voice_reminder_waits_until_listening_cycle_is_clear():
    from voice_session import VoiceSession
    spoken = []
    voice = SimpleNamespace(speak_wait=lambda text: spoken.append(text) or True)
    session = VoiceSession(None, voice, lambda: '')
    session.queue_reminder('tomar agua')
    assert spoken == []
    session.announce_reminders()
    assert spoken == ['Señor, recordatorio: tomar agua']
    session.announce_reminders()
    assert len(spoken) == 1


def test_move_own_project_is_blocked(tmp_path):
    from pathlib import Path
    from system_control import SystemController
    project = Path(__file__).resolve().parents[1]
    controller = SystemController()
    assert controller.project_location()['project'] == str(project)
    with pytest.raises(ValueError, match='mi propia carpeta'):
        controller.files('move', str(project), str(tmp_path / 'project'))
    with pytest.raises(ValueError, match='mi propia carpeta'):
        controller.files('move', str(project.parent), str(tmp_path / 'parent'))


def test_project_move_request_does_not_ask_for_known_path_or_claim_success(tmp_path):
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    agent = PersistentBrain(NvidiaBrain('fake', object(), lambda *_: False,
                            post=lambda **_: pytest.fail('No se necesita modelo')), JarvisMemory(tmp_path / 'memory.db'))
    answer = agent.ask('quiero que jarvis prueba esté fuera de m3u_converter y lo pongas en la carpeta personal makao')
    assert 'carpeta personal' in answer and 'no puedo moverla' in answer.lower()
    assert 'ruta exacta' not in answer.lower()


def test_delete_reminder_permission_is_single_persistent_and_revocable(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_automation_permission(True)
    assert not permissions.preapproved('delete_reminder')
    calls = []
    approve = lambda name, args: calls.append(name) or True
    assert permissions.authorize_tool('delete_reminder', {'reminder_id': 1}, approve)
    assert permissions.authorize_tool('delete_reminder', {'reminder_id': 2}, approve)
    assert calls == ['delete_reminder_permission']
    permissions.set_agenda_delete_permission(False)
    assert not permissions.preapproved('delete_reminder')
    assert not permissions.authorize_tool('delete_reminder', {'reminder_id': 2}, lambda *_: False)


def test_delete_reminder_requires_matching_exact_snapshot(tmp_path, monkeypatch):
    import os
    from datetime import datetime
    import time
    from agenda import Agenda
    from system_control import SystemController
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    agenda = Agenda()
    due = int(time.time()) + 1000
    reminder_id = agenda.add('Tomar agua', due)
    when = datetime.fromtimestamp(due).astimezone().isoformat(timespec='seconds')
    controller = SystemController()
    assert not controller.delete_reminder(reminder_id, 'Otro', when)['deleted']
    assert agenda.list()
    assert controller.delete_reminder(reminder_id, 'Tomar agua', when)['deleted']
    assert not controller.delete_reminder(reminder_id, 'Tomar agua', when)['deleted']
    assert not agenda.list()
    with pytest.raises(ValueError): controller.delete_reminder(True, 'Tomar agua', when)


def test_remove_reminder_by_natural_language_honors_consent_and_ambiguity(tmp_path, monkeypatch):
    import permissions
    from agenda import Agenda
    from system_control import SystemController
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    import time
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    db = Agenda()
    db.add('Tomar agua', int(time.time()) + 300)
    controller = SystemController()
    prompts = []
    brain = NvidiaBrain('fake', controller, lambda name, args: prompts.append(name) or True,
                        post=lambda **_: pytest.fail('No se necesita el modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert 'eliminé el recordatorio' in agent.ask('Jarvis, elimina el recordatorio de tomar agua')
    assert db.list() == [] and prompts == ['delete_reminder_permission']
    db.add('Tomar agua', int(time.time()) + 400)
    assert 'eliminé' in agent.ask('borra mi recordatorio de tomar agua')
    assert prompts == ['delete_reminder_permission']
    db.add('Llamar a Ana', int(time.time()) + 500)
    db.add('Llamar a Ana', int(time.time()) + 600)
    assert 'varios' in agent.ask('elimina el recordatorio de llamar a Ana')
    assert len(db.list()) == 2
    assert 'no encontré' in agent.ask('borra el recordatorio de pasear al perro').lower()
    assert len(db.list()) == 2


def test_delete_reminder_refusal_does_not_modify_database(tmp_path, monkeypatch):
    import permissions
    from agenda import Agenda
    from system_control import SystemController
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    import time
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    db = Agenda()
    db.add('Agua', int(time.time()) + 300)
    brain = NvidiaBrain('fake', SystemController(), lambda *_: False)
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert 'no eliminé' in agent.ask('elimina el recordatorio de agua').lower()
    assert len(db.list()) == 1 and not permissions.preapproved('delete_reminder')


def test_delete_reminder_voice_says_permission_is_persistent():
    from voice_session import VoiceSession
    spoken = []
    voice = SimpleNamespace(speak_wait=lambda text: spoken.append(text) or True)
    session = VoiceSession(None, voice, lambda: 'autorizo')
    assert session.approve('delete_reminder_permission', {'reminder_id': 1})
    assert 'una sola vez' in spoken[0] and 'Ajustes' in spoken[0]


def test_duplicate_reminders_can_be_selected_by_date_and_time():
    from reminder_commands import find_matching_reminders
    reminders = [
        {'id': 1, 'title': 'Tomar agua', 'when': '2026-11-15T14:30:00-05:00'},
        {'id': 2, 'title': 'Tomar agua', 'when': '2026-11-16T14:30:00-05:00'},
    ]
    assert len(find_matching_reminders('tomar agua', reminders)) == 2
    assert [r['id'] for r in find_matching_reminders('tomar agua del 16/11/2026 a las 14:30', reminders)] == [2]
    assert find_matching_reminders('tomar agua del 16/11/2026 a las 15:30', reminders) == []


def test_delete_ambiguous_reminder_asks_time_then_deletes_by_voice_or_chat(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    import permissions
    from agenda import Agenda
    from system_control import SystemController
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_agenda_delete_permission(True)
    now = datetime.now().astimezone()
    tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    agenda = Agenda()
    first = agenda.add('Tomar agua', tomorrow.timestamp())
    second = agenda.add('Tomar agua', tomorrow.replace(hour=15, minute=30).timestamp())
    brain = NvidiaBrain('fake', SystemController(), lambda *_: pytest.fail('Ya autorizado'),
                        post=lambda **_: pytest.fail('No debe llamar al modelo'))
    agent = PersistentBrain(brain, JarvisMemory(tmp_path / 'memory.db'))
    assert '¿De qué hora?' in agent.ask('Jarvis, quiero que elimines el recordatorio de tomar agua')
    assert len(agenda.list()) == 2
    assert 'eliminé' in agent.ask('el de las 3 y media de la tarde')
    remaining = agenda.list()
    assert len(remaining) == 1 and remaining[0]['id'] == first and remaining[0]['id'] != second
    assert 'eliminé' in agent.ask('borra el recordatorio de tomar agua')
    assert agenda.list() == []


def test_reminder_time_ambiguity_never_deletes_wrong_candidate(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    import permissions
    from agenda import Agenda
    from system_control import SystemController
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_agenda_delete_permission(True)
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    db = Agenda()
    db.add('Agua', tomorrow.timestamp())
    db.add('Agua', tomorrow.replace(hour=21).timestamp())
    db.add('Agua', (tomorrow + timedelta(days=1)).timestamp())
    agent = PersistentBrain(NvidiaBrain('fake', SystemController(), lambda *_: True), JarvisMemory(tmp_path / 'memory.db'))
    assert 'qué hora' in agent.ask('elimina mi recordatorio de agua').lower()
    assert 'mañana, tarde o noche' in agent.ask('las nueve').lower()
    assert len(db.list()) == 3
    assert 'de qué día' in agent.ask('de la mañana').lower()
    assert 'eliminé' in agent.ask('mañana')
    assert len(db.list()) == 2


def test_reminder_time_selector_handles_midnight_and_meridian():
    from reminder_commands import select_reminders_by_time
    reminders = [
        {'when': '2026-11-15T00:00:00-05:00'},
        {'when': '2026-11-15T12:00:00-05:00'},
        {'when': '2026-11-15T21:00:00-05:00'},
    ]
    assert select_reminders_by_time('12 a.m.', reminders) == [reminders[0]]
    assert select_reminders_by_time('12 p.m.', reminders) == [reminders[1]]
    assert select_reminders_by_time('9 p.m.', reminders) == [reminders[2]]
    assert select_reminders_by_time('00:00', reminders) == [reminders[0]]


def test_reminder_selection_does_not_delete_if_original_changed(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    import permissions
    from agenda import Agenda
    from system_control import SystemController
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setenv('JARVIS_AGENDA_PATH', str(tmp_path / 'agenda.sqlite3'))
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_agenda_delete_permission(True)
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    db = Agenda()
    identifier = db.add('Agua', tomorrow.timestamp())
    db.add('Agua', tomorrow.replace(hour=10).timestamp())
    agent = PersistentBrain(NvidiaBrain('fake', SystemController(), lambda *_: True), JarvisMemory(tmp_path / 'memory.db'))
    assert '¿De qué hora?' in agent.ask('elimina el recordatorio de agua')
    with db._connect() as connection:
        connection.execute('UPDATE reminders SET title = ? WHERE id = ?', ('Otro', identifier))
    assert 'modificado' in agent.ask('a las nueve')
    assert len(db.list()) == 2


def test_reminder_minute_followup_only_matches_selected_minute():
    from reminder_commands import select_reminders_by_minute
    items = [{'when': '2026-11-15T09:15:00-05:00'}, {'when': '2026-11-15T09:30:00-05:00'}]
    assert select_reminders_by_minute('y media', items) == [items[1]]
    assert select_reminders_by_minute('y cuarto', items) == [items[0]]


def test_schedule_relative_durations_and_calendar_dates(monkeypatch):
    import os
    import time
    from datetime import datetime
    from scheduled_emails import resolve_when
    monkeypatch.setenv('TZ', 'UTC')
    if hasattr(time, 'tzset'): time.tzset()
    try:
        now = datetime(2028, 1, 31, 10, 20, 0).astimezone()
        assert resolve_when('dentro de diez minutos', now) == int(now.timestamp()) + 600
        assert resolve_when('en dos semanas', now) == int(now.timestamp()) + 14 * 86400
        assert datetime.fromtimestamp(resolve_when('en dos meses', now)).strftime('%Y-%m-%d %H:%M') == '2028-03-31 10:20'
        with pytest.raises(ValueError, match='no existe'):
            resolve_when('en un mes', now)
        leap = datetime(2028, 2, 29, 10, 20).astimezone()
        with pytest.raises(ValueError, match='no existe'):
            resolve_when('dentro de un año', leap)
        with pytest.raises(ValueError): resolve_when('en cero minutos', now)
        with pytest.raises(ValueError): resolve_when('2028-01-31T10:20:00', now)
    finally:
        monkeypatch.delenv('TZ', raising=False)
        if hasattr(time, 'tzset'): time.tzset()


def test_scheduled_email_cancel_and_one_time_send(tmp_path, monkeypatch):
    import time
    import sqlite3
    import scheduled_emails as scheduled
    import permissions
    import gmail_access
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    monkeypatch.setattr(gmail_access, 'TOKEN', tmp_path / 'token.json')
    gmail_access.TOKEN.touch()
    queue = scheduled.ScheduledEmails(tmp_path / 'queue.sqlite3')
    assert queue.path.stat().st_mode & 0o777 == 0o600
    first = queue.add('prueba@example.com', 'Hola', 'Mensaje', 'en un minuto')
    assert first['scheduled'] and queue.list()[0]['state'] == 'pending'
    assert not queue.cancel(first['id'], first['to'], 'otro asunto', first['when'])['cancelled']
    assert queue.cancel(first['id'], first['to'], first['subject'], first['when'])['cancelled']
    with sqlite3.connect(queue.path) as db:
        assert db.execute('SELECT body FROM scheduled_email WHERE id=?', (first['id'],)).fetchone()[0] == ''
    second = queue.add('prueba@example.com', 'Segundo', 'Cuerpo', 'en un minuto')
    with sqlite3.connect(queue.path) as db:
        db.execute('UPDATE scheduled_email SET due=? WHERE id=?', (int(time.time()) - 1, second['id']))
    sent = []
    sender = lambda *args: sent.append(args) or {'sent': True, 'message_id': 'abc123'}
    assert scheduled.process_one(queue, sender) is None and sent == []
    permissions.set_scheduled_email_permission(True)
    assert scheduled.process_one(queue, sender)['state'] == 'sent'
    assert scheduled.process_one(queue, sender) is None and len(sent) == 1
    assert [row['state'] for row in queue.list()] == ['sent', 'cancelled']
    with sqlite3.connect(queue.path) as db:
        assert db.execute('SELECT body FROM scheduled_email WHERE id=?', (second['id'],)).fetchone()[0] == ''


def test_scheduled_email_uncertain_never_retries_and_preserves_message(tmp_path, monkeypatch):
    import time
    import sqlite3
    import scheduled_emails as scheduled
    import permissions
    import gmail_access
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_scheduled_email_permission(True)
    monkeypatch.setattr(gmail_access, 'TOKEN', tmp_path / 'token.json')
    gmail_access.TOKEN.touch()
    queue = scheduled.ScheduledEmails(tmp_path / 'queue.sqlite3')
    item = queue.add('prueba@example.com', 'Prueba', 'No perder', 'en un minuto')
    with sqlite3.connect(queue.path) as db:
        db.execute('UPDATE scheduled_email SET due=? WHERE id=?', (int(time.time()) - 1, item['id']))
    calls = []
    def failed(*args):
        calls.append(True)
        raise TimeoutError('Could already have been sent')
    assert scheduled.process_one(queue, failed)['state'] == 'uncertain'
    assert scheduled.process_one(queue, failed) is None and len(calls) == 1
    with sqlite3.connect(queue.path) as db:
        assert db.execute('SELECT state, body FROM scheduled_email WHERE id=?', (item['id'],)).fetchone() == ('uncertain', 'No perder')


def test_scheduled_email_claim_is_atomic(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    import sqlite3
    import scheduled_emails as scheduled
    import gmail_access
    monkeypatch.setattr(gmail_access, 'TOKEN', tmp_path / 'token.json')
    gmail_access.TOKEN.touch()
    queue = scheduled.ScheduledEmails(tmp_path / 'queue.sqlite3')
    entry = queue.add('prueba@example.com', 'Prueba', 'Hola', 'en un minuto')
    with sqlite3.connect(queue.path) as db:
        db.execute('UPDATE scheduled_email SET due=? WHERE id=?', (int(time.time()) - 1, entry['id']))
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: queue.claim_one(), range(2)))
    assert sum(item is not None for item in outcomes) == 1
    assert queue.list()[0]['state'] == 'sending'


def test_schedule_permission_is_independent_and_revocable(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_gmail_permission(True)
    assert not permissions.preapproved('schedule_email')
    calls = []
    assert permissions.authorize_tool('schedule_email', {'to': 'x@example.com'}, lambda name, args: calls.append(name) or True)
    assert calls == ['schedule_email_permission']
    assert permissions.authorize_tool('schedule_email', {}, lambda *_: pytest.fail('No debe preguntar otra vez'))
    permissions.set_scheduled_email_permission(False)
    assert not permissions.preapproved('schedule_email')


def test_schedule_voice_confirmation_explains_future_sending():
    from voice_session import VoiceSession
    spoken = []
    voice = SimpleNamespace(speak_wait=lambda text: spoken.append(text) or True)
    session = VoiceSession(None, voice, lambda: 'autorizo')
    assert session.approve('schedule_email_permission', {'to': 'x@example.com', 'subject': 'Hola', 'body': 'Prueba', 'when': 'en diez minutos'})
    assert 'sin preguntar cada vez' in spoken[0] and 'JARVIS esté abierto' in spoken[0]
    assert 'Prueba' in spoken[0] and 'x@example.com' in spoken[0]


def test_future_email_never_invokes_immediate_send_even_if_model_chooses_it(tmp_path, monkeypatch):
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_gmail_permission(True)
    calls = []
    sent = []
    def post(*args, **kwargs):
        calls.append(True)
        message = ({'content': '', 'tool_calls': [{'id': 't1', 'function': {'name': 'send_gmail', 'arguments': '{"to":"test@example.com","subject":"Prueba","body":"Hola"}'}}]}
                   if len(calls) == 1 else {'content': 'Correo programado.'})
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(send_gmail=lambda **kwargs: sent.append(kwargs) or {'sent': True})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('envía un correo dentro de diez minutos')
    assert sent == [] and 'Todavía no quedó programado' in result


def test_schedule_email_tool_reports_real_scheduled_state(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    calls = []
    def post(*args, **kwargs):
        calls.append(True)
        message = ({'content': '', 'tool_calls': [{'id': 't1', 'function': {'name': 'schedule_email', 'arguments': '{"to":"test@example.com","subject":"Hola","body":"Prueba","when":"en dos minutos"}'}}]}
                   if len(calls) == 1 else {'content': 'Enviado.'})
        return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': message}]})
    controller = SimpleNamespace(schedule_email=lambda **args: {'scheduled': True, 'when': '2030-02-10T15:00:00-05:00'})
    questions = []
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda name, args: questions.append(name) or True, post=post), JarvisMemory(tmp_path / 'memory.db'))
    result = agent.ask('Programa un correo en dos minutos')
    assert questions == ['schedule_email_permission']
    assert 'quedó programado' in result and 'abierto y conectado' in result and 'Enviado' not in result


def test_revoking_scheduled_email_permission_prevents_claimed_send(tmp_path, monkeypatch):
    import time
    import sqlite3
    import scheduled_emails as scheduled
    import gmail_access
    import permissions
    monkeypatch.setattr(gmail_access, 'TOKEN', tmp_path / 'token.json')
    gmail_access.TOKEN.touch()
    queue = scheduled.ScheduledEmails(tmp_path / 'queue.sqlite3')
    entry = queue.add('test@example.com', 'Prueba', 'Mensaje', 'en un minuto')
    with sqlite3.connect(queue.path) as db:
        db.execute('UPDATE scheduled_email SET due=? WHERE id=?', (int(time.time()) - 1, entry['id']))
    states = iter([{'scheduled_email_accepted': True}, {'scheduled_email_accepted': False}])
    monkeypatch.setattr(permissions, 'read_state', lambda: next(states))
    assert scheduled.process_one(queue, lambda *_: pytest.fail('No debe enviar')) is None
    assert queue.list()[0]['state'] == 'pending'


def test_email_with_no_gmail_token_or_invalid_data_is_not_stored(tmp_path, monkeypatch):
    import scheduled_emails as scheduled
    import gmail_access
    monkeypatch.setattr(gmail_access, 'TOKEN', tmp_path / 'nonexistent.json')
    queue = scheduled.ScheduledEmails(tmp_path / 'queue.sqlite3')
    with pytest.raises(gmail_access.GmailError, match='no está configurado'):
        queue.add('test@example.com', 'Hola', 'Texto', 'en un minuto')
    with pytest.raises(gmail_access.GmailError, match='dirección'):
        queue.add('not-an-email', 'Hola', 'Texto', 'en un minuto')
    assert queue.list() == []


def test_schedule_calendar_durations_respect_dst_and_reject_nonexistent_hour(monkeypatch):
    import time
    from datetime import datetime
    from scheduled_emails import resolve_when
    if not hasattr(time, 'tzset'):
        pytest.skip('TZ changes are unavailable')
    monkeypatch.setenv('TZ', 'America/New_York')
    time.tzset()
    try:
        if time.localtime(datetime(2028, 3, 1).timestamp()).tm_zone not in ('EST', 'EDT'):
            pytest.skip('Timezone database is unavailable')
        # One calendar week preserves wall clock despite the spring transition.
        now = datetime(2028, 3, 5, 10, 0).astimezone()
        result = datetime.fromtimestamp(resolve_when('en una semana', now))
        assert (result.day, result.hour) == (12, 10)
        missing = datetime(2028, 3, 11, 2, 30).astimezone()
        with pytest.raises(ValueError, match='no existe'):
            resolve_when('en un día', missing)
    finally:
        monkeypatch.delenv('TZ', raising=False)
        time.tzset()


def test_sent_email_search_returns_actual_recipient_and_gmail_timestamp(monkeypatch):
    import gmail_access
    seen = []
    closed = []
    class Session:
        def close(self): closed.append(True)
    monkeypatch.setattr(gmail_access, 'client', Session)
    def get(session, path, params=None):
        seen.append((path, params))
        if path == 'messages':
            return {'messages': [{'id': 'abc123'}]}
        return {'id': 'abc123', 'internalDate': '1700000000000', 'labelIds': ['SENT'],
                'payload': {'headers': [{'name': 'To', 'value': 'ana@example.com'},
                                        {'name': 'Subject', 'value': 'Prueba'}]}}
    monkeypatch.setattr(gmail_access, '_get', get)
    result = gmail_access.search_messages('in:sent')
    assert seen[0] == ('messages', {'q': 'in:sent', 'maxResults': 10})
    assert result['messages'][0]['to'] == 'ana@example.com'
    assert result['messages'][0]['internal_date_ms'] == 1700000000000
    assert closed == [True]


def test_recent_sent_direct_query_checks_gmail_and_never_uses_chat_memory(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_gmail_permission(True)
    queries = []
    controller = SimpleNamespace(search_gmail=lambda query: queries.append(query) or {'messages': [
        {'subject': 'Viejo', 'to': 'primero@example.com', 'internal_date_ms': 1700000000000},
        {'subject': 'Actual', 'to': 'segundo@example.com', 'internal_date_ms': 1700001000000}]})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: pytest.fail('Ya autorizado'),
                         post=lambda **_: pytest.fail('No debe llamar al modelo')), JarvisMemory(tmp_path / 'memory.db'))
    answer = agent.ask('Jarvis, ¿cuál fue el último correo que envié?')
    assert queries == ['in:sent']
    assert 'Actual' in answer and 'segundo@example.com' in answer
    assert 'programado' not in answer and 'no tengo acceso' not in answer.lower()


def test_recent_sent_denial_and_gmail_failure_are_honest(tmp_path, monkeypatch):
    import permissions
    from gmail_access import GmailError
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    calls = []
    def search(query):
        calls.append(query)
        raise GmailError('Gmail no está configurado en JARVIS.')
    agent = PersistentBrain(NvidiaBrain('fake', SimpleNamespace(search_gmail=search), lambda *_: False), JarvisMemory(tmp_path / 'memory.db'))
    assert 'no se autorizó' in agent.ask('el último correo enviado').lower() and not calls
    permissions.set_gmail_permission(True)
    result = agent.ask('el último correo enviado')
    assert calls == ['in:sent'] and 'no está configurado' in result
    assert 'programado' not in result


def test_recent_sent_empty_and_incomplete_response():
    from persistent_brain import format_recent_sent
    assert 'No encontré' in format_recent_sent({'messages': []})
    assert 'respuesta incompleta' in format_recent_sent({'error': 'problema'})


def test_latest_sent_request_is_distinct_from_scheduled_mail():
    from persistent_brain import is_last_sent_request
    for phrase in ('¿Cuál fue el último correo que envié?', 'dime mi último correo enviado',
                   'último mensaje que mandaste'):
        assert is_last_sent_request(phrase)
    for phrase in ('cuál es el último correo programado', 'qué envié a juan',
                   'último correo enviado a ana@example.com'):
        assert not is_last_sent_request(phrase)


def test_weather_queries_keep_region_and_country_and_do_not_hijack_email():
    from weather_commands import parse_weather_request
    assert parse_weather_request('Jarvis, dime el clima en Perú por favor') == 'Perú'
    assert parse_weather_request('¿Cómo está el clima en La Libertad de Perú?') == 'La Libertad de Perú'
    assert parse_weather_request('clima de hoy en Lima, Perú') == 'Lima, Perú'
    assert parse_weather_request('¿qué temperatura hace?') == ''
    assert parse_weather_request('envía un correo sobre el clima de Perú') is None


def test_weather_country_uses_real_capital_and_forecast_values(monkeypatch):
    import weather
    calls = []
    def fetch(url, params):
        calls.append((url, params))
        if 'restcountries' in url:
            return [{'name': {'common': 'Peru'}, 'translations': {'spa': {'common': 'Perú'}}, 'capital': ['Lima'], 'cca2': 'PE', 'cca3': 'PER'}]
        if 'nominatim' in url:
            return [{'lat': '-12.04', 'lon': '-77.03', 'display_name': 'Lima, Perú', 'importance': .7,
                     'address': {'city': 'Lima', 'country': 'Perú', 'country_code': 'pe'}}]
        return {'timezone': 'America/Lima', 'current': {'time': '2026-11-14T17:30', 'temperature_2m': 23.2,
                    'apparent_temperature': 25.1, 'relative_humidity_2m': 67, 'precipitation': 0,
                    'weather_code': 2, 'wind_speed_10m': 11.0, 'is_day': 1},
                'daily': {'time': ['2026-11-14'], 'weather_code': [2], 'temperature_2m_max': [26],
                          'temperature_2m_min': [17], 'precipitation_probability_max': [8], 'uv_index_max': [6.5],
                          'sunrise': ['2026-11-14T05:30'], 'sunset': ['2026-11-14T18:00']}}
    monkeypatch.setattr(weather, '_fetch', fetch)
    result = weather.get_weather('Perú')
    assert result['ok'] and result['is_capital'] and result['location']['place'] == 'Lima'
    assert result['current']['temperature'] == 23.2 and result['current']['humidity'] == 67
    assert result['current']['time'] == '2026-11-14T17:30' and result['daily'][0]['max'] == 26
    assert calls[-1][1]['latitude'] == -12.04 and calls[-1][1]['timezone'] == 'auto'


def test_weather_does_not_guess_between_homonyms(monkeypatch):
    import weather
    def fetch(url, params):
        if 'restcountries' in url:
            return None
        assert 'nominatim' in url
        return [
            {'lat': '-8', 'lon': '-79', 'display_name': 'Trujillo, Perú', 'importance': .3, 'address': {'country': 'Perú'}},
            {'lat': '9', 'lon': '-70', 'display_name': 'Trujillo, Venezuela', 'importance': .25, 'address': {'country': 'Venezuela'}}]
    monkeypatch.setattr(weather, '_fetch', fetch)
    result = weather.get_weather('Trujillo')
    assert result['ambiguous'] and len(result['options']) == 2


def test_weather_error_never_returns_fake_values(monkeypatch):
    import weather
    monkeypatch.setattr(weather, '_country', lambda name: None)
    monkeypatch.setattr(weather, '_geocode', lambda *args, **kwargs: {'latitude': 1, 'longitude': 2, 'place': 'Lugar'})
    monkeypatch.setattr(weather, '_fetch', lambda *args, **kwargs: {'current': {'temperature_2m': None}})
    with pytest.raises(weather.WeatherError, match='incompletos'):
        weather.get_weather('Lugar')


def test_weather_voice_and_text_use_same_tool_and_events(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    events, calls = [], []
    result = {'ok': True, 'requested': 'Perú', 'is_capital': True, 'location': {'place': 'Lima'},
              'current': {'temperature': 21.4, 'description': 'Nublado'}, 'daily': []}
    controller = SimpleNamespace(get_weather=lambda location: calls.append(location) or result)
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: pytest.fail('Ya autorizado'),
                            post=lambda **_: pytest.fail('No necesita modelo')), JarvisMemory(tmp_path / 'memory.db'))
    agent.weather_event = lambda event, data: events.append((event, data))
    answer = agent.ask('dime el clima en Perú')
    assert calls == ['Perú'] and 'capital de Perú' in answer and '21 grados' in answer
    assert [e[0] for e in events] == ['loading', 'result'] and events[-1][1] == result


def test_weather_followup_uses_country_without_guessing(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    calls = []
    def get_weather(location):
        calls.append(location)
        if len(calls) == 1:
            return {'ambiguous': True, 'location': location, 'options': ['Trujillo, Perú', 'Trujillo, Venezuela']}
        return {'ok': True, 'is_capital': False, 'location': {'place': 'Trujillo'},
                'current': {'temperature': 20, 'description': 'Despejado'}}
    agent = PersistentBrain(NvidiaBrain('fake', SimpleNamespace(get_weather=get_weather), lambda *_: True), JarvisMemory(tmp_path / 'memory.db'))
    assert 'varios' in agent.ask('clima en Trujillo')
    assert 'Trujillo' in agent.ask('Perú')
    assert calls == ['Trujillo', 'Trujillo, Perú']


def test_weather_spanish_region_country_qualifier_is_not_lost(monkeypatch):
    import weather
    countries = []
    geocodes = []
    def lookup(name):
        countries.append(name)
        return {'cca2': 'PE'} if name == 'Perú' else None
    def geocode(name, forced_country=None, allow_top=False):
        geocodes.append((name, forced_country))
        return {'ambiguous': True, 'options': ['La Libertad, Perú', 'Otra región']}
    monkeypatch.setattr(weather, '_country', lookup)
    monkeypatch.setattr(weather, '_geocode', geocode)
    result = weather.get_weather('La Libertad de Perú')
    assert result['ambiguous']
    assert geocodes == [('La Libertad, Perú', 'PE')]


def test_weather_permission_denied_does_not_call_network(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    events = []
    controller = SimpleNamespace(get_weather=lambda **kwargs: pytest.fail('No debe acceder a la red'))
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: False), JarvisMemory(tmp_path / 'memory.db'))
    agent.weather_event = lambda name, data: events.append(name)
    assert 'no se autorizó' in agent.ask('dime el clima en Perú').lower()
    assert events == ['error']


def test_weather_http_failures_are_not_disguised_as_weather(monkeypatch):
    import requests
    import weather
    def timeout(*args, **kwargs):
        assert kwargs['allow_redirects'] is False
        raise requests.Timeout('private internals')
    monkeypatch.setattr(weather.requests, 'get', timeout)
    with pytest.raises(weather.WeatherError) as error:
        weather._fetch('https://api.open-meteo.com/v1/forecast', {})
    assert 'Open-Meteo' in str(error.value) and 'tardó demasiado' in str(error.value) and 'private internals' not in str(error.value)


def test_weather_failure_shows_no_fabricated_values(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_network_permission(True)
    events = []
    controller = SimpleNamespace(get_weather=lambda **kwargs: {'error': 'No pude conectar con el servicio del clima.'})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: True), JarvisMemory(tmp_path / 'memory.db'))
    agent.weather_event = lambda name, data: events.append((name, data))
    answer = agent.ask('¿Cómo está el clima en Lima?')
    assert 'No pude conectar' in answer and 'grados' not in answer
    assert [e[0] for e in events] == ['loading', 'error']


def test_country_lookup_is_local_and_recognizes_spanish_without_network(monkeypatch):
    import weather
    monkeypatch.setattr(weather, '_fetch', lambda *_: pytest.fail('No debe consultar un servicio de países'))
    peru = weather._country('Perú')
    assert peru['cca2'] == 'PE' and peru['capital'] == ['Lima']
    assert weather._country('España')['cca2'] == 'ES'
    assert weather._country('Perúx') is None


def test_country_service_outage_is_not_reported_as_missing_location(monkeypatch):
    import weather
    def unavailable(name):
        raise weather.WeatherError('No pude consultar el servicio de países. Revisa tu conexión e inténtalo de nuevo.')
    def missing(*args, **kwargs):
        raise weather.WeatherError('No encontré esa ubicación. Dime una ciudad o región y su país.')
    monkeypatch.setattr(weather, '_country', unavailable)
    monkeypatch.setattr(weather, '_geocode', missing)
    with pytest.raises(weather.WeatherError, match='servicio de países'):
        weather.get_weather('Perú')


def test_weather_animation_delays_fast_success_not_errors_or_slow_requests():
    from weather_timing import WeatherLoadingTiming
    now, waits = [10.0], []
    timing = WeatherLoadingTiming(clock=lambda: now[0], sleep=waits.append)
    timing.wait_for_event('loading')
    now[0] = 11.2
    timing.wait_for_event('result')
    assert waits == [pytest.approx(1.8)]
    timing.wait_for_event('loading')
    now[0] = 16
    timing.wait_for_event('result')
    assert len(waits) == 1
    timing.wait_for_event('loading')
    timing.wait_for_event('error')
    timing.wait_for_event('result')
    assert len(waits) == 1


def test_weather_search_sound_is_short_original_wav(tmp_path):
    import wave
    from weather_sound import write_search_cue
    path = tmp_path / 'cue.wav'
    write_search_cue(path)
    with wave.open(str(path), 'rb') as sound:
        assert sound.getnchannels() == 1 and sound.getsampwidth() == 2
        assert sound.getnframes() / sound.getframerate() == pytest.approx(.78, abs=.001)
        data = sound.readframes(sound.getnframes())
        assert any(data)


def test_weather_sound_setting_can_be_disabled_and_survives_restart(tmp_path):
    from ui_settings import load, save
    path = tmp_path / 'settings.json'
    save(path, {'weather_sound': 'desactivado'})
    assert load(path)['weather_sound'] == 'desactivado'


def test_thinking_and_weather_cues_vary_without_changing_duration(tmp_path):
    import wave
    from weather_sound import write_search_cue
    sounds = []
    for kind in ('thinking', 'weather'):
        for variant in range(3):
            path = tmp_path / f'{kind}-{variant}.wav'
            write_search_cue(path, kind=kind, variant=variant)
            with wave.open(str(path), 'rb') as sound:
                assert sound.getnframes() / sound.getframerate() == pytest.approx(.78, abs=.001)
                sounds.append(sound.readframes(sound.getnframes()))
    assert len(set(sounds)) == 6


def test_pcm_voice_envelope_tracks_audio_and_silence():
    import math
    from array import array
    from audio_envelope import pcm_envelope, level_at
    rate = 8000
    silence = [0] * 400
    loud = [int(14000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(400)]
    raw = array('h', silence + loud + silence).tobytes()
    levels = pcm_envelope(raw, rate, 1)
    assert len(levels) == 3 and levels[0] == 0 and levels[1] > .8 and levels[2] == 0
    assert level_at(levels, 55) == levels[1] and level_at(levels, 250) == 0
    with pytest.raises(ValueError):
        pcm_envelope(b'\x00', rate, 1)


def test_voice_envelope_failure_does_not_interrupt_audio(tmp_path):
    from voice import Voice
    voice = Voice()
    voice.on_level = lambda level: None
    audio = tmp_path / 'voice.mp3'
    audio.write_bytes(b'fake')
    mixer = SimpleNamespace(get_init=lambda: (22050, -16, 2), Sound=lambda path: (_ for _ in ()).throw(ValueError('decode failure')))
    assert voice._envelope(SimpleNamespace(mixer=mixer), audio) is None


def test_voice_local_fallback_reports_no_measured_audio(monkeypatch):
    import sys
    from voice import Voice
    events = []
    engine = SimpleNamespace(say=lambda text: None, runAndWait=lambda: None, stop=lambda: None)
    monkeypatch.setitem(sys.modules, 'pyttsx3', SimpleNamespace(init=lambda: engine))
    voice = Voice()
    voice.on_activity = lambda active: events.append(('activity', active))
    voice.on_level = lambda level: events.append(('level', level))
    voice._local('Hola')
    assert events == [('level', None), ('activity', True), ('activity', False)]


def test_orb_transition_is_smooth_frame_independent_and_bounded():
    from orb_motion import approach
    first = approach(0, 1, .04, .26)
    assert 0 < first < 1
    assert approach(first, 0, .04, .26) < first
    one_step = approach(0, 1, .08, .26)
    two_steps = approach(approach(0, 1, .04, .26), 1, .04, .26)
    assert one_step == pytest.approx(two_steps)
    assert 0 < approach(0, 1, 999, .26) < 1
    assert approach(.4, 1, -1, .26) == .4
    assert approach(.4, 1, .04, 0) == 1


def test_android_pairing_code_stays_out_of_argv_and_rejects_public_ips():
    from android_phone import AndroidPhone, PhoneError, local_endpoint
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='Successfully paired to 192.168.43.1:37123')
    phone = AndroidPhone(runner=run, find=lambda name: '/usr/bin/adb')
    assert phone.pair('192.168.43.1:37123', '123456')['paired']
    assert '123456' not in calls[0][0] and calls[0][1]['input'] == '123456\n'
    assert local_endpoint('172.20.10.1:5000') == '172.20.10.1:5000'
    for address in ('8.8.8.8:55', '127.0.0.1:12', '192.168.1.2:0', 'localhost:5555', '192.168.1.1:5555;whoami'):
        with pytest.raises(PhoneError):
            local_endpoint(address)
    with pytest.raises(PhoneError):
        phone.pair('192.168.1.4:1234', '111111;rm')


def test_android_connection_pins_device_and_failure_clears_previous():
    from android_phone import AndroidPhone, PhoneError
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == 'connect':
            return SimpleNamespace(returncode=0, stdout='connected to 192.168.1.8:4000\n')
        if argv[-1] == 'get-state':
            return SimpleNamespace(returncode=0, stdout='device\n')
        return SimpleNamespace(returncode=0, stdout='level: 68\n')
    phone = AndroidPhone(runner=run, find=lambda name: 'adb')
    assert phone.connect('192.168.1.8:4000')['connected']
    assert phone.status()['battery_percent'] == 68
    assert all(call[1:3] == ['-s', '192.168.1.8:4000'] for call in calls[1:])
    with pytest.raises(PhoneError):
        phone.connect('192.168.1.9:4000')
    assert phone.serial is None


def test_android_restricts_actions_and_never_interpolates_shell_commands():
    from android_phone import AndroidPhone, PhoneError
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='ok')
    phone = AndroidPhone(runner=run, find=lambda name: 'adb')
    phone.serial = '192.168.1.8:4000'
    assert phone.action('tocar', 50, 70)['requested']
    assert calls[-1] == ['adb', '-s', phone.serial, 'shell', 'input', 'tap', '50', '70']
    with pytest.raises(PhoneError):
        phone.action('tocar', '5;rm', 3)
    with pytest.raises(PhoneError):
        phone.action('reboot')
    with pytest.raises(PhoneError):
        phone.list_files('../../data')
    assert len(calls) == 1


def test_android_screenshot_validated_before_vision():
    from android_phone import AndroidPhone, PhoneError
    phone = AndroidPhone(runner=lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b'not png'), find=lambda name: 'adb')
    phone.serial = '192.168.1.8:4000'
    with pytest.raises(PhoneError, match='captura válida'):
        phone.screenshot()


def test_phone_permissions_are_scoped_and_sensitive_capture_always_asks(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    calls = []
    approve = lambda name, args: calls.append(name) or False
    assert not permissions.authorize_tool('phone_status', {}, approve)
    permissions.set_phone_permission(True)
    assert permissions.authorize_tool('phone_status', {}, approve)
    assert permissions.authorize_tool('phone_action', {'action': 'whatsapp'}, approve)
    assert not permissions.authorize_tool('phone_action', {'action': 'tocar', 'x': 3, 'y': 4}, approve)
    assert not permissions.authorize_tool('phone_inspect_screen', {}, approve)
    assert not permissions.authorize_tool('phone_list_files', {'folder': 'fotos'}, approve)
    permissions.set_phone_permission(False)
    assert not permissions.authorize_tool('phone_status', {}, approve)
    assert calls == ['phone_status', 'phone_action', 'phone_inspect_screen', 'phone_list_files', 'phone_status']


def test_phone_requests_route_only_explicit_phone_and_report_honestly():
    from phone_commands import parse_phone_request, format_phone_result
    assert parse_phone_request('Jarvis, abre WhatsApp en mi celular') == ('phone_action', {'action': 'whatsapp'})
    assert parse_phone_request('¿cuánta batería tiene mi teléfono?') == ('phone_status', {})
    assert parse_phone_request('abre WhatsApp') is None
    assert parse_phone_request('no abras WhatsApp en mi celular') is None
    assert 'no pude comprobar' in format_phone_result('phone_action', {'requested': True}).lower()
    assert '68 por ciento' in format_phone_result('phone_status', {'connected': True, 'battery_percent': 68})


def test_phone_voice_and_chat_route_to_connected_device_without_model(tmp_path, monkeypatch):
    import permissions
    from persistent_brain import PersistentBrain
    from nvidia_brain import NvidiaBrain
    from memory import JarvisMemory
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'permissions.json')
    permissions.set_phone_permission(True)
    calls = []
    controller = SimpleNamespace(phone_status=lambda: {'connected': True, 'battery_percent': 73},
                                 phone_action=lambda **kwargs: calls.append(kwargs) or {'requested': True})
    agent = PersistentBrain(NvidiaBrain('fake', controller, lambda *_: pytest.fail('Acción autorizada'),
                            post=lambda **_: pytest.fail('No debe recurrir al modelo')), JarvisMemory(tmp_path / 'memory.db'))
    assert '73 por ciento' in agent.ask('qué batería tiene mi celular')
    assert 'no pude comprobar' in agent.ask('abre WhatsApp en mi teléfono').lower()
    assert calls == [{'action': 'whatsapp'}]


def test_microphone_muted_is_detected():
    import hardware_diagnostics
    def runner(cmd, **kwargs):
        cmd = list(cmd)
        body = {'arecord': 'card 0: I82801AALB [Intel], device 0: ALC [ALC]\n  Subdevices: 1/1\n',
                'pactl info': 'Default Source: alsa_input.pci-0000_00_1b.0.analog-stereo\n',
                'pactl list sources short': '4\talsa_input.pci-0000_00_1b.0.analog-stereo\tmodule\ts16le 2ch\tRUNNING\n'}.get(
                    ' '.join(cmd[:2]), '')
        if cmd[:2] == ['pactl', 'get-source-mute']: body = 'Mute: yes'
        if cmd[:2] == ['pactl', 'get-source-volume']: body = 'Volume: front-left: 65536 / 100%'
        if cmd[:2] == ['arecord', '-l']: body = 'card 0: I82801AALB [Intel], device 0: ALC [ALC]\n  Subdevices: 1/1\n'
        return SimpleNamespace(returncode=0, stdout=body, stderr='')
    result = hardware_diagnostics.diagnose_microphone(system='Linux', runner=runner, capture=False)
    assert result['microphone_detected'] is True
    assert result['muted'] is True
    assert 'silencia' in result['summary'].lower()


def test_microphone_missing_is_reported_honestly():
    import hardware_diagnostics
    def runner(cmd, **kwargs):
        cmd = list(cmd)
        body = {'arecord -l': '', 'pactl info': '', 'pactl list sources short': ''}.get(' '.join(cmd[:2]), '')
        code = 0 if cmd[:2] == ['arecord', '-l'] else (1 if cmd[:2] == ['pactl', 'info'] else 0)
        return SimpleNamespace(returncode=code, stdout=body, stderr='')
    result = hardware_diagnostics.diagnose_microphone(system='Linux', runner=runner, capture=False)
    assert result['microphone_detected'] is False
    assert 'no detect' in result['summary'].lower()


def test_microphone_healthy_path_local_capture(tmp_path):
    import hardware_diagnostics
    import wave
    def runner(cmd, **kwargs):
        cmd = list(cmd)
        if cmd[:1] == ['arecord'] and cmd[1] == '-q':
            path = cmd[-1]
            with wave.open(path, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes((b'\x40\x1f' * 2000))  # constant ~8000 amplitude
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if cmd[:2] == ['arecord', '-l']: body = 'card 0: HDA [Intel], device 0: ALC [ALC]\n  Subdevices: 1/1\n'
        elif cmd[:2] == ['pactl', 'info']: body = 'Default Source: alsa_input.test\n'
        elif cmd[:2] == ['pactl', 'list']: body = '4\talsa_input.test\tmodule\ts16le 2ch\tRUNNING\n'
        elif cmd[:2] == ['pactl', 'get-source-mute']: body = 'Mute: no'
        elif cmd[:2] == ['pactl', 'get-source-volume']: body = 'Volume: 80%'
        else: body = ''
        return SimpleNamespace(returncode=0, stdout=body, stderr='')
    result = hardware_diagnostics.diagnose_microphone(system='Linux', runner=runner, capture=True)
    assert result['microphone_detected'] is True and result['muted'] is False
    assert any(c['check'] == 'prueba de grabación' and c['status'] == 'ok' for c in result['checks'])
    assert 'cuantificación' not in result['summary'].lower()


def test_microphone_non_linux_is_honest():
    import hardware_diagnostics
    result = hardware_diagnostics.diagnose_microphone(system='Windows', runner=None, capture=False)
    assert result['microphone_detected'] is None
    assert 'solo está disponible en Linux' in result['checks'][0]['detail']



def test_conversation_mode_voice_flow():
    from voice_session import VoiceSession, _normalize_phrase, CONVERSATION_OFF
    assert _normalize_phrase('eso es todo, gracias') in CONVERSATION_OFF
    assert _normalize_phrase('eso será todo') in CONVERSATION_OFF
    spoken, requests = [], []
    inputs = iter(['conversación ajena', 'Jarvis, hola', 'qué hora es', 'eso es todo', 'qué hora es'])
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
    assert session.conversation_mode is False
    assert 'Hasta luego, señor.' in spoken


def test_conversation_mode_empty_wake_word_enters():
    from voice_session import VoiceSession
    spoken, requests = [], []
    inputs = iter(['Jarvis', 'enciende la luz del salón', 'eso es todo', 'qué hora es'])
    voice = SimpleNamespace(speak_wait=lambda text: spoken.append(text) or True)
    def listen():
        try: return next(inputs)
        except StopIteration:
            session.stop()
            return ''
    brain = SimpleNamespace(ask=lambda text: requests.append(text) or 'ok')
    session = VoiceSession(brain, voice, listen)
    session.run()
    assert requests == ['enciende la luz del salón']
    assert 'Le escucho, señor.' in spoken
    assert session.conversation_mode is False


def test_conversation_mode_not_persisted_by_default():
    from voice_session import VoiceSession
    session = VoiceSession(SimpleNamespace(ask=lambda t: ''), SimpleNamespace(speak_wait=lambda t: True), lambda: '')
    assert session.conversation_mode is False
    session.set_conversation_mode(True)
    assert session.conversation_mode is True


def test_explicit_remember_fact_parsing():
    from learning import explicit_fact
    assert explicit_fact('recuerda que odio el café') == 'odio el café'
    assert explicit_fact('Recuerda que prefiero respuestas breves.') == 'prefiero respuestas breves'
    assert explicit_fact('recuerda esto: trabajo en Trujillo') == 'trabajo en Trujillo'
    assert explicit_fact('recuerda') is None
    assert explicit_fact('hola, recuerda que vendrás mañana ¿verdad?') is None


def test_parse_facts_tolerates_model_output():
    from learning import parse_facts
    assert parse_facts('["Prefiere respuestas breves", "Le gusta el jazz"]') == ['Prefiere respuestas breves', 'Le gusta el jazz']
    assert parse_facts('Claro, aquí tienes: ["Odia el calor.", "", 5]') == ['Odia el calor.']
    assert parse_facts('[]') == []
    assert parse_facts('no es json') == []
    assert parse_facts('["Prefiere respuestas breves"] ') == ['Prefiere respuestas breves']


def test_merge_facts_dedupes_dates_and_caps(tmp_path):
    import memory as memory_module
    mem = memory_module.JarvisMemory(tmp_path / 'mem.db')
    mem.set_preferences('Prefiero respuestas breves')
    assert mem.get_preferences() == 'Prefiero respuestas breves'
    from learning import merge_facts
    added = merge_facts(mem, ['Odia el calor', 'odia el calor '], date='2026-11-16')
    assert added == 1
    stored = mem.get_preferences()
    assert 'Odia el calor' in stored and '(2026-11-16)' in stored
    # Re-adding the same fact through a different case does not duplicate it
    assert merge_facts(mem, ['ODIA EL CALOR'], date='2026-11-16') == 0
    # Cap: oldest learned bullet gets dropped first with big facts
    many = [f'hecho número {i} con palabras suficientes para ocupar espacio' for i in range(60)]
    assert merge_facts(mem, many, date='2026-11-16') > 0
    assert len(mem.get_preferences()) <= 2000


def test_merge_facts_keeps_user_text_with_priority(tmp_path):
    import memory as memory_module
    mem = memory_module.JarvisMemory(tmp_path / 'mem.db')
    mem.set_preferences('Mi perfil importante: "lengua materna quechua, prefiero trato formal"\n' + 'x' * 1900)
    from learning import merge_facts
    before = mem.get_preferences()
    # Oldest learned content is discarded first; only 99 chars of learned text fit
    added = merge_facts(mem, [f'hecho {i} con detalle extenso para ocupar el límite de almacenamiento establecido' for i in range(10)], date='2026-11-16')
    stored = mem.get_preferences()
    assert 'Mi perfil importante' in stored
    assert len(stored) <= 2000


def test_create_txt_md_csv_json_rtf(tmp_path):
    from documents import create_document
    txt = create_document('txt', str(tmp_path / 'nota.txt'), body='línea uno\nlínea dos\n', overwrite=True)
    assert txt['created'].endswith('nota.txt')
    assert (tmp_path / 'nota.txt').read_text(encoding='utf-8') == 'línea uno\nlínea dos\n'
    md = create_document('md', str(tmp_path / 'nota.md'), body='## Sección\n- punto', overwrite=True)
    assert '## Sección' in (tmp_path / 'nota.md').read_text(encoding='utf-8')
    csv_res = create_document('csv', str(tmp_path / 'tabla.csv'), rows_json='[["Nombre","Edad"],["Ana",30]]')
    assert csv_res['format'] == 'csv' and (tmp_path / 'tabla.csv').read_text(encoding='utf-8-sig').startswith('Nombre,Edad')
    res_json = create_document('json', str(tmp_path / 'data.json'), body='{"clave": "valor"}')
    assert '"clave"' in (tmp_path / 'data.json').read_text(encoding='utf-8')
    rtf = create_document('rtf', str(tmp_path / 'nota.rtf'), body='Ático… perforado')
    assert (tmp_path / 'nota.rtf').read_text(encoding='utf-8').startswith('{\\rtf1')


def test_create_pdf_docx_xlsx_pptx(tmp_path):
    from documents import create_document
    pdf = create_document('pdf', str(tmp_path / 'informe.pdf'), title='Informe',
                          body='## Resumen\n- punto uno\n\nTexto final')
    assert (tmp_path / 'informe.pdf').read_bytes().startswith(b'%PDF')
    docx = create_document('docx', str(tmp_path / 'carta.docx'), title='Carta',
                           body='## Asunto\n- punto\n\npárrafo')
    assert open(tmp_path / 'carta.docx', 'rb').read(2) == b'PK'
    xlsx = create_document('xlsx', str(tmp_path / 'datos.xlsx'),
                           rows_json='[["Nombre","Edad"],["Ana",30],["Luis",25]]', header=True)
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / 'datos.xlsx')
    ws = wb.active
    assert ws['A1'].value == 'Nombre' and ws['A2'].value == 'Ana' and ws['B3'].value == 25
    pptx = create_document('pptx', str(tmp_path / 'charla.pptx'), title='Charla',
                           body='## Tema\n- punto uno\n- punto dos')
    assert open(tmp_path / 'charla.pptx', 'rb').read(2) == b'PK'


def test_create_document_refuses_overwrite_and_relative_path(tmp_path, monkeypatch):
    import documents
    target = tmp_path / 'ya-existe.txt'
    target.write_text('original')
    out = documents.create_document('txt', str(target), body='otra cosa')
    assert 'ya existe' in out['error']
    assert target.read_text() == 'original'
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    rel = documents.create_document('txt', 'prueba-relativa.txt', body='hola')
    assert rel['created'] == str(home / 'Documentos' / 'prueba-relativa.txt')


def test_create_document_bad_format_and_bad_rows(tmp_path):
    from documents import create_document
    assert 'no admitido' in create_document('exe', str(tmp_path / 'x.exe'))['error']
    assert 'JSON' in create_document('csv', str(tmp_path / 'x.csv'), rows_json='{no es json')['error']


def test_create_document_desktop_alias(tmp_path, monkeypatch):
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    out = documents.create_document('pdf', 'escritorio/prueba.pdf', body='hola')
    assert out['created'] == str(desktop / 'prueba.pdf')
    assert out['exists'] is True and out['bytes'] > 0
    assert open(desktop / 'prueba.pdf', 'rb').read(4) == b'%PDF'
    out = documents.create_document('txt', 'desktop/nota.txt', body='hola')
    assert out['created'] == str(desktop / 'nota.txt')
    out = documents.create_document('txt', 'escritorio', body='hola')
    assert 'Indica el nombre' in out['error']


def test_creation_report_is_truthful(tmp_path):
    import documents
    real = tmp_path / 'ok.pdf'
    real.write_bytes(b'%PDF-1.4 test')
    report = documents.creation_report([{'created': str(real), 'bytes': real.stat().st_size}])
    assert str(real) in report and 'No pude' not in report
    report = documents.creation_report([{'created': str(real)}, {'created': str(tmp_path / 'ok2.pdf')}])
    (tmp_path / 'ok2.pdf').write_text('x')
    report = documents.creation_report([{'created': str(real)}, {'created': str(tmp_path / 'ok2.pdf')}])
    assert 'He creado 2 archivos' in report
    report = documents.creation_report([{'error': 'Falta la dependencia para PDF'}])
    assert 'No pude crear' in report and 'dependencia' in report
    report = documents.creation_report([{'created': str(tmp_path / 'ghost.pdf')}])
    assert 'no encuentro' in report
    report = documents.creation_report([])
    assert 'No creé ningún archivo' in report


def test_create_document_verified_flag(tmp_path):
    from documents import create_document
    out = create_document('txt', str(tmp_path / 'v.txt'), body='abc')
    assert out['exists'] is True and out['bytes'] == 3


def test_action_log_roundtrip_and_redaction(tmp_path, monkeypatch):
    import action_log
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    entry = action_log.record('create_document', {'path': '/home/u/Escritorio/p.pdf', 'body': 'contenido-privado'}, {'created': '/home/u/Escritorio/p.pdf', 'bytes': 10})
    assert entry['ok'] is True
    raw = (tmp_path / 'actions.jsonl').read_text(encoding='utf-8')
    assert 'contenido-privado' not in raw and 'oculto' in raw
    summary = action_log.summary()
    assert 'create_document' in summary and 'OK' in summary and 'Escritorio/p.pdf' in summary
    action_log.clear()
    assert action_log.entries() == [] and action_log.summary() == ''


def test_action_log_rotation_keeps_last(tmp_path, monkeypatch):
    import action_log
    state = tmp_path / 'actions.jsonl'
    monkeypatch.setattr(action_log, 'STATE', state)
    monkeypatch.setattr(action_log, 'ROTATE_AT', 5)
    monkeypatch.setattr(action_log, 'MAX_ENTRIES', 2)
    for index in range(6):
        action_log.record('files', {'path': str(index)}, {'error': 'falló'} if index % 2 else {'path': str(index)})
    lines = state.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    entries = action_log.entries()
    assert [entry['ok'] for entry in entries] == [True, False]


def test_action_log_never_breaks_tools(tmp_path, monkeypatch):
    import action_log
    monkeypatch.setattr(action_log, 'STATE', tmp_path)  # a directory, unwritable as a file
    assert action_log.record('files', {}, {'ok': True}) is None


def test_document_commands_create_defaults(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    command = document_commands.parse_create('créame un archivo pdf de prueba en escritorio')
    assert command == {'count': 1, 'format': 'pdf', 'dest': 'desktop'}
    answer = document_commands.handle_create(command)
    assert str(desktop / 'prueba.pdf') in answer and (desktop / 'prueba.pdf').is_file()
    answer = document_commands.handle_create(command)
    assert str(desktop / 'prueba-2.pdf') in answer  # never overwrites silently
    assert (desktop / 'prueba.pdf').read_bytes().startswith(b'%PDF')


def test_document_commands_create_count(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    command = document_commands.parse_create('créame 3 archivos pdf de prueba en el escritorio')
    assert command['count'] == 3 and command['format'] == 'pdf' and command['dest'] == 'desktop'
    answer = document_commands.handle_create(command)
    for index in (1, 2, 3):
        name = 'prueba.pdf' if index == 1 else f'prueba-{index}.pdf'
        assert (desktop / name).is_file()
    assert 'prueba-2.pdf' in answer and 'prueba-3.pdf' in answer


def test_document_commands_require_testish(tmp_path):
    import document_commands
    assert document_commands.parse_create('créame un informe anual para la empresa') is None
    assert document_commands.parse_create('crea un archivo pdf importante') is None


def test_document_commands_delete_only_ledger(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    state = tmp_path / 'actions.jsonl'
    monkeypatch.setattr(action_log, 'STATE', state)
    command = document_commands.parse_create('créame un archivo pdf de prueba en escritorio')
    document_commands.handle_create(command)
    user_file = desktop / 'prueba.pdf'
    note = desktop / 'mío.pdf'
    note.write_bytes(b'not mine')  # same name pattern, but not in the ledger
    # ledger holds only the created one; deleting must not touch the unknown file
    action_log.STATE = state
    candidates = document_commands.delete_candidates({'format': 'pdf', 'plural': True, 'prueba': True})
    assert user_file in candidates and note not in candidates
    targets, question, stage = document_commands.select_delete({'format': 'pdf', 'plural': True, 'prueba': True})
    assert question is None and stage is None and targets == [user_file]  # single target: no confirmation needed
    answer = document_commands.delete_paths(targets)
    assert not user_file.exists() and note.exists()
    assert 'Eliminé' in answer


def test_document_commands_delete_ambiguous_and_choice(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    document_commands.handle_create(document_commands.parse_create('créame 3 archivos pdf de prueba en escritorio'))
    files = document_commands.delete_candidates({'format': 'pdf', 'plural': False, 'prueba': True})
    assert len(files) == 3
    targets, question, stage = document_commands.select_delete({'format': 'pdf', 'plural': False, 'prueba': True})
    assert stage == 'choose' and question and '¿Cuáles elimino' in question
    targets, question, stage = document_commands.select_delete({'format': 'pdf', 'plural': True, 'prueba': True})
    assert stage == 'confirm' and question and '¿Confirmas?' in question
    picked = document_commands.resolve_delete_choice('todos', files)
    assert picked == files
    picked = document_commands.resolve_delete_choice('el primero', files)
    assert picked == files[:1]
    picked = document_commands.resolve_delete_choice('cancela', files)
    assert picked == []
    assert document_commands.resolve_delete_choice('algo incomprensible que no cuadra', files) is None


def test_document_commands_delete_refuses_outside_ledger(tmp_path, monkeypatch):
    import document_commands
    import action_log
    state = tmp_path / 'actions.jsonl'
    monkeypatch.setattr(action_log, 'STATE', state)
    stranger = tmp_path / 'test.pdf'
    stranger.write_bytes(b'x')
    answer = document_commands.delete_paths([stranger])
    # delete_paths itself only unlinks what it is handed (caller filters by ledger);
    # the stranger is still refused at selection time
    targets, question, stage = document_commands.select_delete({'format': 'pdf', 'plural': True, 'prueba': True})
    assert targets == [] and 'no borro archivos que no creé' in question


def test_persistent_brain_deterministic_create_delete(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    import memory
    import persistent_brain
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    state = tmp_path / 'actions.jsonl'
    monkeypatch.setattr(action_log, 'STATE', state)
    db = tmp_path / 'memory.sqlite3'
    mem = memory.JarvisMemory(db)
    class FakeBrain:
        model = 'fake'
        instructions = 'fake instructions'
        history = []
        class client:
            pass
    brain = persistent_brain.PersistentBrain.__new__(persistent_brain.PersistentBrain)
    from types import SimpleNamespace
    brain.brain = FakeBrain()
    brain.memory = mem
    brain.model = 'fake'
    brain.pending_reminder_choices = None
    brain.pending_weather = None
    brain.pending_delete_created = None
    brain.weather_event = lambda *_: None
    brain.pending_reminder_deadline = 0
    brain.pending_reminder_question = None
    brain.base_instruction = 'fake'
    brain.approve = lambda *_, **__: False
    answer = brain.ask('créame un archivo pdf de prueba en escritorio')
    assert str(desktop / 'prueba.pdf') in answer
    assert (desktop / 'prueba.pdf').is_file()
    answer = brain.ask('elimina el archivo de prueba que creaste')  # un solo archivo: directo
    assert 'Eliminé' in answer and not (desktop / 'prueba.pdf').exists()


def test_delete_created_file_natural_phrasing(tmp_path, monkeypatch):
    import document_commands
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    document_commands.handle_create(document_commands.parse_create('créame un archivo pdf de prueba en escritorio'))
    command = document_commands.parse_delete('elimina el archivo prueba.pdf que creaste')
    assert command and command['filenames'] == ['prueba.pdf']
    targets, question, stage = document_commands.select_delete(command)
    assert targets == [desktop / 'prueba.pdf'] and question is None and stage is None
    command = document_commands.parse_delete('elimina el archivo que creaste')
    assert command and command['filenames'] == []
    targets, question, stage = document_commands.select_delete(command)
    assert targets == [desktop / 'prueba.pdf']


def _brain_with_tmp_desktop(tmp_path, monkeypatch):
    import memory
    import persistent_brain
    import action_log
    import documents
    desktop = tmp_path / 'Escritorio'
    desktop.mkdir()
    monkeypatch.setattr(documents, 'desktop_dir', lambda: desktop)
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    mem = memory.JarvisMemory(tmp_path / 'm.sqlite3')

    class FakeBrain:
        model = 'fake'
        class client: pass
        instructions = 'fake'
        history = []

    brain = persistent_brain.PersistentBrain.__new__(persistent_brain.PersistentBrain)
    brain.brain = FakeBrain()
    brain.memory = mem
    brain.model = 'fake'
    brain.pending_reminder_choices = None
    brain.pending_weather = None
    brain.pending_delete_created = None
    brain.weather_event = lambda *_: None
    brain.pending_reminder_deadline = 0
    brain.pending_reminder_question = None
    brain.base_instruction = 'fake'
    brain.approve = lambda *_, **__: False
    return brain, desktop


def test_delete_multiple_files_waits_for_confirmation(tmp_path, monkeypatch):
    brain, desktop = _brain_with_tmp_desktop(tmp_path, monkeypatch)
    brain.ask('créame 2 archivos pdf de prueba en escritorio')
    assert len(list(desktop.glob('prueba*.pdf'))) == 2
    answer = brain.ask('elimina los dos archivos pdf de prueba que creaste')
    assert '¿Confirmas?' in answer
    assert len(list(desktop.glob('prueba*.pdf'))) == 2  # aún no borra
    answer = brain.ask('no')
    assert 'no eliminé' in answer.lower()
    assert len(list(desktop.glob('prueba*.pdf'))) == 2  # nada borrado
    answer = brain.ask('elimina los dos archivos pdf de prueba que creaste')
    assert '¿Confirmas?' in answer
    answer = brain.ask('sí')
    assert 'Eliminé' in answer
    assert len(list(desktop.glob('prueba*.pdf'))) == 0  # confirmado → borrados


def test_delete_choose_then_confirm_flow(tmp_path, monkeypatch):
    brain, desktop = _brain_with_tmp_desktop(tmp_path, monkeypatch)
    brain.ask('créame 2 archivos pdf de prueba en escritorio')
    answer = brain.ask('elimina el archivo de prueba que creaste')  # ambiguo en plural/ singular
    assert '¿Cuáles elimino' in answer
    answer = brain.ask('todos')
    assert '¿Confirmas?' in answer
    assert len(list(desktop.glob('prueba*.pdf'))) == 2
    answer = brain.ask('vale')
    assert 'Eliminé' in answer
    assert len(list(desktop.glob('prueba*.pdf'))) == 0


def test_delete_no_candidates_keeps_explicit_message(tmp_path, monkeypatch):
    brain, desktop = _brain_with_tmp_desktop(tmp_path, monkeypatch)
    answer = brain.ask('elimina el archivo pdf que creaste')
    assert 'no borro archivos que no creé' in answer
    assert brain.pending_delete_created is None


def test_confirm_stage_ignores_unrelated_chatter(tmp_path, monkeypatch):
    brain, desktop = _brain_with_tmp_desktop(tmp_path, monkeypatch)
    brain.ask('créame 2 archivos pdf de prueba en escritorio')
    answer = brain.ask('elimina los dos archivos pdf de prueba que creaste')
    assert '¿Confirmas?' in answer
    answer = brain.ask('¿qué hora es?')  # no confirma ni cancela: repregunta, fail-closed
    assert '¿Confirmas' in answer or 'sí' in answer.lower()
    assert len(list(desktop.glob('prueba*.pdf'))) == 2
