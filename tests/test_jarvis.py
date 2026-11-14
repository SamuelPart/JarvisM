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
