"""Tests for the new additive agent architecture (agent/ package)."""
import json
import threading
import urllib.request

import pytest

import action_log
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
