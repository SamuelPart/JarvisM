"""HUD de JARVIS — panel local con métricas reales del equipo.

Ejecución:
    pip install flask psutil
    python hud/app.py                 # http://127.0.0.1:5050
    python hud/app.py --host 0.0.0.0  # expone a la LAN (sin contraseña: solo red de confianza)

Datos 100% locales vía psutil; nada sale del equipo. Los campos marcados como
infidelity-free no existen: si una métrica no está disponible, la API dice «N/D»
en vez de inventarla (p. ej. temperatura en hardware sin sensores).
"""
from __future__ import annotations

import argparse
import importlib
import os
import platform
import time
from pathlib import Path

import psutil
from flask import Flask, jsonify, render_template

_STARTED = time.time()
_LAST_NET = psutil.net_io_counters()
_LAST_NET_T = time.monotonic()
psutil.cpu_percent(interval=0.1, percpu=True)  # prime: la primera lectura siempre da 0.0

app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent / 'templates'))


def _net_mbps():
    global _LAST_NET, _LAST_NET_T
    counters = psutil.net_io_counters()
    now = time.monotonic()
    elapsed = max(now - _LAST_NET_T, 0.001)
    sent = (counters.bytes_sent - _LAST_NET.bytes_sent) / elapsed / 1_000_000
    recv = (counters.bytes_recv - _LAST_NET.bytes_recv) / elapsed / 1_000_000
    _LAST_NET, _LAST_NET_T = counters, now
    return round(recv, 2), round(sent, 2)


def _health(cpu, ram, swap, disk):
    score = 100.0
    for value, weight in ((cpu, 0.4), (ram, 0.35), (swap, 0.1), (disk, 0.15)):
        score -= max(0, value - 60) * weight
    return round(max(5, min(100, score)), 1)


def _cpu_model():
    info = platform.processor() or (platform.machine() + ' / ' + platform.system())
    return ' '.join(info.split())[:90]


def _temperature():
    try:
        sensors = psutil.sensors_temperatures() or {}
    except (AttributeError, OSError):
        return None
    for entries in sensors.values():
        for entry in entries:
            if entry.current is not None:
                return round(entry.current, 1)
    return None


def _module(ok):
    return 100 if ok else 0


def _modules():
    voice = False
    for name in ('edge_tts', 'pyttsx3'):
        try:
            importlib.import_module(name)
            voice = True
            break
        except Exception:
            pass
    vision = bool(os.environ.get('NVIDIA_VISION_API_KEY') or os.environ.get('NVIDIA_API_KEY'))
    network = False
    try:
        stats = psutil.net_if_stats()
        network = any(info.isup for info in stats.values())
    except Exception:
        pass
    try:
        memory = (Path(__file__).resolve().parent.parent / '.jarvis-memory.sqlite3')
        db_ok = memory.parent.exists() and os.access(memory.parent, os.W_OK)
    except OSError:
        db_ok = False
    return {'VOICE': _module(voice), 'VISION': _module(vision), 'NETWORK': _module(network),
            'MEMORY': _module(db_ok), 'CORE': _module(True)}


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/stats')
def stats():
    per_core = psutil.cpu_percent(percpu=True)
    cpu_total = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(Path.home().anchor or '/'))
    down, up = _net_mbps()
    battery = psutil.sensors_battery()
    battery_percent = round(battery.percent) if battery else None
    plugged = bool(battery.power_plugged) if battery else None
    health = _health(cpu_total, ram.percent, swap.percent, disk.percent)
    environment_temp = _temperature()
    uptime = time.time() - psutil.boot_time()
    return jsonify({
        'server_time': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'uptime_seconds': int(uptime),
        'cpu_percent': round(cpu_total, 1),
        'per_core': [round(value, 1) for value in per_core],
        'cpu_freq_mhz': round(psutil.cpu_freq().current, 0) if psutil.cpu_freq() else None,
        'cpu_model': _cpu_model(),
        'cpu_count': psutil.cpu_count(logical=True),
        'ram': {'percent': round(ram.percent, 1), 'used_gb': round(ram.used / 1024**3, 1),
                'total_gb': round(ram.total / 1024**3, 1)},
        'swap': {'percent': round(swap.percent, 1), 'used_gb': round(swap.used / 1024**3, 1),
                 'total_gb': round(swap.total / 1024**3, 1)},
        'disk': {'percent': round(disk.percent, 1), 'free_gb': round(disk.free / 1024**3, 1),
                 'total_gb': round(disk.total / 1024**3, 1)},
        'net': {'down_mbps': down, 'up_mbps': up},
        'battery': {'percent': battery_percent, 'plugged': plugged},
        'processes': len(psutil.pids()),
        'health': health,
        'environment': {'cpu_temp_c': environment_temp},
        'modules': _modules(),
        'all_systems_operational': health >= 70,
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', help='127.0.0.1 (local) o 0.0.0.0 (LAN; sin auth)')
    parser.add_argument('--port', type=int, default=5050)
    args = parser.parse_args()
    url = f'http://{args.host}:{args.port}'
    print(f'JARVIS HUD en {url} (Ctrl+C para salir). Datos locales; nada sale del equipo.')
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == '__main__':
    main()
