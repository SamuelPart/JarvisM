#!/usr/bin/env python3
"""Banco de pruebas local para JARVIS.

Uso:
    python benchmark.py            # batería determinista (sin red, sin modelo)
    python benchmark.py --live     # añade tiempos reales del proveedor IA (consume API)

Nunca imprime claves ni contenido sensible: solo PASS/FAIL, recuentos y tiempos.
Sal tolerable con forma modesta; las medidas varían según tu equipo y red.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

REPORT = {'machine': platform.platform(), 'python': platform.python_version(),
          'git_tip': None, 'checks': [], 'timings': {}}


def check(name, ok, detail='', optional=False):
    ok = bool(ok)
    REPORT['checks'].append({'name': name, 'ok': ok or optional, 'optional': optional, 'detail': str(detail)[:200]})
    label = 'INFO' if optional else ('PASS' if ok else 'FAIL')
    print(f"[{label}] {name}" + (f' — {detail}' if detail else ''))


def time_it(name, func, repeat=5):
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = func()
        samples.append((time.perf_counter() - start) * 1000)
    REPORT['timings'][name] = {'samples_ms': [round(s, 3) for s in samples],
                               'mean_ms': round(statistics.mean(samples), 3),
                               'max_ms': round(max(samples), 3)}
    print(f'  {name}: media {statistics.mean(samples):.1f} ms · máx {max(samples):.1f} ms (n={repeat})')
    return result


def git_tip():
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='También mide respuestas reales del modelo (gasta API)')
    parser.add_argument('--save', default=None, help='Guarda el informe JSON en esta ruta')
    args = parser.parse_args()

    REPORT['git_tip'] = git_tip()
    print(f'JARVIS benchmark · {REPORT["machine"]} · Python {REPORT["python"]} · tip {REPORT["git_tip"]}\n')

    # ---- entorno ----
    check('tip de Git presente', REPORT['git_tip'])
    import importlib
    for module in ('documents', 'document_commands', 'action_log', 'agent.memory', 'agent.reflex',
                   'agent.tools', 'agent.core', 'persistent_brain', 'memory', 'provider'):
        try:
            importlib.import_module(module)
            check(f'import {module}', True)
        except Exception as exc:
            check(f'import {module}', False, f'{type(exc).__name__}: {exc}')
    check('GEMINI_API_KEY configurada (no se muestra)', bool(os.environ.get('GEMINI_API_KEY')) or (ROOT / '.env').exists(),
          optional=True)
    check('whatsapp configurado (opcional)', __import__('whatsapp_cloud').is_configured(),
          'sin WHATSAPP_*; el resto funciona igual', optional=True)

    # ---- batería determinista (sin red) ----
    print('\nBatería determinista:')
    from agent import reflex
    time_it('reflejo sí/no', lambda: reflex.classify_yes_no('vale'), repeat=200)
    time_it('reflejo selección', lambda: reflex.classify_select('el segundo', ['a', 'b', 'c']), repeat=200)

    import documents
    import document_commands
    time_it('parsear «créame 2 archivos pdf de prueba»',
            lambda: document_commands.parse_create('créame 2 archivos pdf de prueba en escritorio'), repeat=200)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / 'bench.txt'
        out = documents.create_document('txt', str(target), body='1' * 4096)
        check('crear + verificar archivo txt (4 KB)', out.get('created') == str(target) and target.is_file())

    import action_log
    with tempfile.TemporaryDirectory() as tmp:
        action_log.STATE = Path(tmp) / 'actions.jsonl'
        entry = action_log.record('bench', {'x': 'y'}, {'ok': True})
        check('registro de acciones: escribe y abre', bool(entry) and len(action_log.entries()) == 1)
        time_it('acción registrada (append+rotate)', lambda: action_log.record('bench', {'x': 'y' * 100}, {'ok': True}), repeat=50)

    from agent.memory import PersistentMemory
    with tempfile.TemporaryDirectory() as tmp:
        store = PersistentMemory(tmp)
        store.remember_preference('respuestas breves')
        time_it('contexto de memoria (context_block)', lambda: store.context_block(), repeat=100)

    import memory as sqlite_memory
    with tempfile.TemporaryDirectory() as tmp:
        db = sqlite_memory.JarvisMemory(Path(tmp) / 'm.sqlite3')
        db.add_turn('hola', 'señor')
        time_it('lectura de memoria SQLite (20 turnos)', lambda: db.recent(20), repeat=100)

    # ---- medición en vivo (opcional) ----
    if args.live:
        print('\nMedición en vivo (consume tu cuota de IA):')
        os.environ.setdefault('JARVIS_PROVIDER', 'gemini')
        try:
            from provider import create_brain
            from system_control import SystemController
            brain = create_brain(SystemController(), lambda name, a: False)
            t0 = time.perf_counter()
            answer = brain.ask('¿qué hora es?')
            t1 = time.perf_counter()
            check('turno local (hora, sin modelo)', bool(answer), f'{(t1 - t0) * 1000:.0f} ms')
            for prompt in ('Responde solo: ok.', 'Di, en una frase, para qué sirve un registro local de acciones.'):
                t0 = time.perf_counter()
                answer = brain.ask(prompt)
                t1 = time.perf_counter()
                ok = bool(answer and 'No pude' not in answer[:20])
                print(f'  modelo ← «{prompt[:40]}…»: {(t1 - t0) * 1000:.0f} ms')
                check(f'modelo «{prompt[:40]}…»', ok)
        except Exception as exc:
            check('modelo en vivo', False, f'{type(exc).__name__}: {exc}')
    else:
        print('\n(Medición en vivo omitida; usa --live para medir el modelo — consume cuota.)')

    passed = sum(1 for item in REPORT['checks'] if item['ok'])
    failed = len(REPORT['checks']) - passed
    print(f'\nResultado: {passed} PASS · {failed} FAIL')
    if args.save:
        Path(args.save).write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Informe guardado en {args.save}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
