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
    expected = {'color': 'violeta', 'size': 'grande', 'animation': 'reducida'}
    assert save(path, expected) == expected
    assert load(path) == expected
    path.write_text('{"color":"invalido","size":"pequeño","animation":null}', encoding='utf-8')
    assert load(path) == {'color': 'azul', 'size': 'pequeño', 'animation': 'normal'}
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


def test_gemini_memory_context(tmp_path):
    from memory import JarvisMemory
    from persistent_brain import PersistentBrain
    memory = JarvisMemory(tmp_path / 'local.sqlite3')
    memory.add_turn('Me llamo Ana', 'Hola Ana')
    memory.set_preferences('Me gusta el ajedrez')
    class Models:
        def generate_content(self, **kwargs):
            assert kwargs['contents'][0].role == 'user'
            assert kwargs['contents'][1].role == 'model'
            assert 'ajedrez' in kwargs['config'].system_instruction
            return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role='model', parts=[types.Part.from_text(text='Ana')]))])
    brain = Brain('', object(), lambda *_: False, client=SimpleNamespace(models=Models()))
    agent = PersistentBrain(brain, memory)
    assert agent.ask('¿Cómo me llamo?') == 'Ana'
    assert len(memory.recent()) == 4


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


def test_music_player_start_and_stop(monkeypatch):
    import sys
    import music_player
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, query, download):
            assert query == 'ytsearch1:tema' and not download
            return {'entries': [{'title': 'Tema', 'url': 'https://r1.googlevideo.com/videoplayback?id=1'}]}
    class Process:
        def __init__(self, args, **kwargs): self.args, self.running = args, True
        def poll(self): return None if self.running else 0
        def terminate(self): self.running = False
        def wait(self, timeout): return 0
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(music_player.shutil, 'which', lambda name: '/usr/bin/mpv')
    monkeypatch.setattr(music_player.subprocess, 'Popen', Process)
    player = music_player.MusicPlayer()
    assert player.play('tema')['started']
    assert player.process.args[0] == '/usr/bin/mpv'
    assert player.stop()['stopped']
    assert not player.stop()['stopped']


def test_network_preapproval_applies_to_agent_but_not_terminal(tmp_path, monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, 'STATE', tmp_path / 'state.json')
    permissions.set_network_permission(True)
    seen = []
    def call_part(name, args):
        return types.Part(function_call=types.FunctionCall(name=name, args=args))
    class Models:
        step = 0
        def generate_content(self, **kwargs):
            self.step += 1
            parts = ([call_part('web_search', {'query': 'noticias'})] if self.step == 1 else
                     [call_part('terminal', {'command': 'echo hello'})] if self.step == 2 else
                     [types.Part.from_text(text='Listo')])
            return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role='model', parts=parts))])
    controller = SimpleNamespace(web_search=lambda query: {'results': []}, terminal=lambda command: pytest.fail('terminal no autorizado'))
    agent = Brain('', controller, lambda name, args: seen.append(name) or False,
                  client=SimpleNamespace(models=Models()))
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
