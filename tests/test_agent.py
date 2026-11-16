"""Tests for the new additive agent architecture (agent/ package)."""
import json
import threading
import urllib.request

import pytest

import action_log
from pathlib import Path
from agent import memory as agent_memory
from agent import reflex
from agent import tools as agent_tools
from agent.heartbeats import Heartbeat
from agent.core import Orchestrator, naive_decompose, StepStatus


def test_persistent_memory_roundtrip_and_context(tmp_path):
    store = agent_memory.PersistentMemory(tmp_path)
    assert store.soul_path.exists()
    store.remember_preference('Prefiero respuestas breves')
    store.remember_preference('Prefiero respuestas breves')  # no crash on duplicates
    store.set_project_state('JARVIS', 'Pendiente probar el micrófono')
    store.record_decision('Arranque simplificado a solo saludo')
    context = store.context_block()
    assert 'respuestas breves' in context and 'JARVIS' in context and 'saludo' in context
    # set_project_state replaces in place instead of duplicating
    store.set_project_state('JARVIS', 'Micrófono verificado')
    assert store.section('Proyectos').count('**JARVIS**') == 1
    assert 'Micrófono verificado' in store.section('Proyectos')
    assert store.section('Preferencias').count('respuestas breves') == 2


def test_persistent_memory_clear_keeps_soul(tmp_path):
    store = agent_memory.PersistentMemory(tmp_path)
    store.remember_preference('algo')
    store.clear()
    assert store.section('Preferencias') == ''
    assert store.soul().strip().startswith('# SOUL.md')


def test_reflex_yes_no():
    assert reflex.classify_yes_no('Sí').value is True
    assert reflex.classify_yes_no('vale').value is True
    assert reflex.classify_yes_no('no').value is False
    assert reflex.classify_yes_no('jamas').value is False
    assert reflex.classify_yes_no('según tú').kind is reflex.ReflexKind.UNKNOWN


def test_reflex_select():
    options = ['Chrome', 'Firefox', 'WhatsApp']
    assert reflex.classify_select('el primero', options).value == 0
    assert reflex.classify_select('2', options).value == 1
    assert reflex.classify_select('dos', options).value == 1
    assert reflex.classify_select('el último', options).value == 2
    assert reflex.classify_select('abre firefox', options).value == 1
    assert reflex.classify_select('potato', options).kind is reflex.ReflexKind.UNKNOWN


def test_reflex_score_bounds():
    assert reflex.classify_score('7').value == 7
    assert reflex.classify_score('nueve').value == 9
    assert reflex.classify_score('42', max_score=10).kind is reflex.ReflexKind.UNKNOWN
    assert reflex.classify_score('cien').kind is reflex.ReflexKind.UNKNOWN


def test_tool_registry_enforces_confirmation():
    registry = agent_tools.build_default_registry()
    out = registry.execute('delete_created_file', {'path': '/tmp/x.pdf'})
    assert out['status'] == 'needs_confirmation'
    out = registry.execute('delete_created_file', {'path': '/tmp/x.pdf'}, confirmed=True)
    assert out['status'] == 'error'  # refused: not in the ledger
    assert registry.execute('unknown_tool', {}).get('status') == 'error'
    assert registry.get('current_time').danger is False


def test_heartbeat_runs_due_jobs():
    beat = Heartbeat()
    calls = []
    beat.register('demo', 60, lambda: calls.append('run'))
    assert beat.run_due(now=1000) == ['demo']
    assert beat.run_due(now=1010) == []   # not due yet
    assert beat.run_due(now=1100) == ['demo']
    assert beat.status()[0]['run_count'] == 2
    beat.set_enabled('demo', False)
    assert beat.run_due(now=9999) == []


def test_orchestrator_fallback_and_execution(tmp_path):
    memory = agent_memory.PersistentMemory(tmp_path)
    plan = Orchestrator(memory=memory, decomposer=naive_decompose).plan('abre chrome y abre firefox')
    assert len(plan.steps) == 1  # no LLM: a single honest step, nothing invented
    registry = agent_tools.build_default_registry()
    orchestrator = Orchestrator(registry=registry, memory=memory, decomposer=lambda goal: [
        {'description': 'Hora actual', 'tool': 'current_time', 'args': {}},
        {'description': 'Borrar prueba', 'tool': 'delete_created_file', 'args': {'path': '/tmp/no.pdf'}},
    ])
    plan = orchestrator.plan('objetivo de prueba')
    plan = orchestrator.execute(plan)
    assert plan.steps[0].status is StepStatus.DONE
    assert plan.steps[1].status is StepStatus.BLOCKED  # danger + no confirmation callback
    decisions = memory.section('Decisiones')
    assert 'objetivo de prueba' in decisions


def test_rest_server_status_and_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, '_DEFAULT_DIR', tmp_path)
    from agent import server as agent_server
    token = agent_server.load_or_create_token()
    registry = agent_tools.build_default_registry()
    handler = agent_server.make_handler(registry, token)
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/status') as response:
            body = json.loads(response.read())
        assert body['ok'] is True and 'current_time' in body['tools']
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/action',
            data=json.dumps({'tool': 'current_time', 'args': {}}).encode(),
            headers={'Content-Type': 'application/json'},  # no token → 401
            method='POST')
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 401
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}/action',
            data=json.dumps({'tool': 'current_time', 'args': {}}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
            method='POST')
        with urllib.request.urlopen(req) as response:
            body = json.loads(response.read())
        assert body['status'] == 'ok' and 'local_time' in body
    finally:
        httpd.shutdown()


def test_whatsapp_cloud_send_paths(monkeypatch):
    import whatsapp_cloud
    monkeypatch.setenv('WHATSAPP_TOKEN', 'fake-token')
    monkeypatch.setenv('WHATSAPP_PHONE_NUMBER_ID', '12345')
    monkeypatch.setenv('WHATSAPP_RECIPIENT', '+51 987 654 321')

    class FakeResponse:
        status_code = 200
        def json(self):
            return {'messages': [{'id': 'wamid.123'}]}

    sent = []
    monkeypatch.setattr(whatsapp_cloud.requests, 'post',
                        lambda url, data, headers, timeout: sent.append((url, data, headers)) or FakeResponse())
    out = whatsapp_cloud.send_message('hola desde JARVIS')
    assert out['sent'] is True and out['message_id'] == 'wamid.123' and out['to'] == '51987654321'
    url, data, headers = sent[0]
    assert '12345/messages' in url and headers['Authorization'] == 'Bearer fake-token'

    class FakeError(FakeResponse):
        status_code = 401
        def json(self):
            return {'error': {'message': 'invalid token'}}

    monkeypatch.setattr(whatsapp_cloud.requests, 'post',
                        lambda *args, **kwargs: FakeError())
    out = whatsapp_cloud.send_message('hola')
    assert '401' in out['error'] and 'invalid token' in out['error']

    monkeypatch.delenv('WHATSAPP_TOKEN')
    assert 'no está configurado' in whatsapp_cloud.send_message('hola')['error']


def test_whatsapp_webhook_verify_and_signature(monkeypatch):
    import whatsapp_cloud, hashlib, hmac
    monkeypatch.setenv('WHATSAPP_VERIFY_TOKEN', 'verify-me')
    assert whatsapp_cloud.verify_webhook({'hub.mode': 'subscribe', 'hub.verify_token': 'verify-me', 'hub.challenge': '12345'}) == '12345'
    assert whatsapp_cloud.verify_webhook({'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '12345'}) is None
    monkeypatch.delenv('WHATSAPP_APP_SECRET', raising=False)
    assert whatsapp_cloud.verify_signature(b'{}', 'sha256=abc') is False  # sin secreto, todo se rechaza
    monkeypatch.setenv('WHATSAPP_APP_SECRET', 'shh')
    digest = hmac.new(b'shh', b'{"entry":[]}', hashlib.sha256).hexdigest()
    assert whatsapp_cloud.verify_signature(b'{"entry":[]}', 'sha256=' + digest) is True
    assert whatsapp_cloud.verify_signature(b'{"entry":[]}', 'sha256=' + '0' * 64) is False


def test_whatsapp_parse_inbound():
    import whatsapp_cloud
    payload = {'entry': [{'changes': [{'value': {
        'contacts': [{'wa_id': '51987654321', 'profile': {'name': 'Señor'}}],
        'messages': [{'from': '51987654321', 'id': 'wamid.1', 'type': 'text', 'text': {'body': 'hola'}},
                     {'from': '51987654321', 'id': 'wamid.2', 'type': 'image'}]}}]}]}
    messages = whatsapp_cloud.parse_inbound(payload)
    assert messages == [{'from': '51987654321', 'id': 'wamid.1', 'text': 'hola', 'name': 'Señor'}]


def _whatsapp_post(handler, port, body, signature=None):
    import urllib.request, urllib.error
    headers = {'Content-Type': 'application/json'}
    if signature:
        headers['X-Hub-Signature-256'] = signature
    req = urllib.request.Request(f'http://127.0.0.1:{port}/whatsapp/webhook',
                                 data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b'{}')


def test_whatsapp_webhook_flow(tmp_path, monkeypatch):
    import json as _json
    import whatsapp_cloud
    from agent import server as agent_server
    from agent.tools import build_default_registry
    monkeypatch.setenv('WHATSAPP_APP_SECRET', 'secret')
    monkeypatch.setenv('WHATSAPP_RECIPIENT', '51987654321')
    monkeypatch.setattr(agent_server, 'load_or_create_token', lambda: 'tok')
    calls, replies = [], []
    monkeypatch.setattr(whatsapp_cloud, 'send_message',
                        lambda body, to=None, timeout=20: replies.append((body, to)) or {'sent': True})
    registry = build_default_registry()
    httpd = None
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(('127.0.0.1', 0),
                                agent_server.make_handler(registry, 'tok',
                                                          whatsapp_handler=lambda text: calls.append(text) or 'respuesta del cerebro'))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    import hmac, hashlib
    body = _json.dumps({'entry': [{'changes': [{'value': {
        'contacts': [{'wa_id': '51987654321', 'profile': {'name': 'Señor'}}],
        'messages': [{'from': '51987654321', 'id': 'w1', 'type': 'text', 'text': {'body': '¿qué hora es?'}}]}}]}]}).encode()
    signature = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
    code, payload = _whatsapp_post(None, port, body, signature)
    assert code == 200 and payload['processed'] == 1
    assert calls == ['¿qué hora es?'] and replies == [('respuesta del cerebro', '51987654321')]
    # intruso: mismo webhook, otro número → ignorado
    calls.clear()
    body2 = body.replace(b'51987654321', b'99999999999')
    signature2 = 'sha256=' + hmac.new(b'secret', body2, hashlib.sha256).hexdigest()
    code, payload = _whatsapp_post(None, port, body2, signature2)
    assert code == 200 and payload['processed'] == 0 and calls == []
    # firma inválida → rechazado
    code, _ = _whatsapp_post(None, port, body, 'sha256=' + '0' * 64)
    assert code == 503
    httpd.shutdown()


def test_disk_watchdog_journals_only_on_transition(monkeypatch, tmp_path):
    import action_log
    from agent import watchdogs
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    monkeypatch.setattr(watchdogs, '_LAST', {'disk_low': False})
    class FakeDisk:
        def __init__(self, percent):
            self.percent = percent
    monkeypatch.setattr(watchdogs.psutil, 'disk_usage', lambda root: FakeDisk(50))
    assert watchdogs.disk_watchdog(90)['low'] is False
    assert action_log.entries() == []
    monkeypatch.setattr(watchdogs.psutil, 'disk_usage', lambda root: FakeDisk(95))
    watchdogs.disk_watchdog(90)
    watchdogs.disk_watchdog(90)  # segunda vez: sin duplicado
    errors = [e for e in action_log.entries() if 'disco' in str(e).lower()]
    assert len(errors) == 1 and '95 por ciento' in errors[0]['detail']['error']


def test_planifica_shortcut(tmp_path, monkeypatch):
    import memory
    import persistent_brain
    import action_log
    from types import SimpleNamespace
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
    monkeypatch.setenv('GEMINI_API_KEY', '')  # sin clave → descomposición honesta de un paso
    answer = brain.ask('planifica: revisar el estado de las pruebas')
    assert 'Plan' in answer and 'revisar el estado' in answer and '¿Necesitas algo más?' in answer


def test_controller_delete_created_file_bounded(tmp_path, monkeypatch):
    import action_log
    import system_control
    monkeypatch.setattr(action_log, 'STATE', tmp_path / 'actions.jsonl')
    controller = system_control.SystemController()
    created = tmp_path / 'prueba.pdf'
    created.write_bytes(b'%PDF-1.4 test')
    action_log.record('create_document', {'format': 'pdf', 'path': str(created)}, {'created': str(created), 'bytes': 13})
    out = controller.delete_created_file(str(created))
    assert out.get('deleted') == str(created) and not created.exists()
    stranger = tmp_path / 'mio.pdf'
    stranger.write_bytes(b'not mine')
    out = controller.delete_created_file(str(stranger))
    assert out['error'].startswith('No consta') and stranger.exists()
    # dentro de la carpeta de JARVIS: rechazado aunque conste como creado
    inside = Path(__file__).resolve().parent.parent / 'borrame-no.pdf'
    action_log.record('create_document', {'format': 'pdf', 'path': str(inside)}, {'created': str(inside)})
    out = controller.delete_created_file(str(inside))
    assert 'carpeta de JARVIS' in out['error']
