"""Local, read-only hardware diagnostics. Nothing leaves the machine.

The microphone test records one second to a temporary file, computes its
level and deletes it immediately; it is never transmitted or stored.
Only available on Linux for now; other platforms get an honest "not
supported yet" instead of invented results.
"""
from __future__ import annotations

import math
import os
import platform
import re
import struct
import subprocess
import tempfile
import wave

_TIMEOUT = 8


def _run(runner, cmd, timeout=_TIMEOUT):
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=timeout, errors='replace')
        return result.returncode, ((result.stdout or '') + '\n' + (result.stderr or '')).strip()
    except FileNotFoundError:
        return None, ''
    except subprocess.TimeoutExpired:
        return -1, 'La comprobación tardó demasiado; el sistema puede estar ocupado.'


def _check(name, status, detail):
    return {'check': name, 'status': status, 'detail': detail}


def _capture_test(runner):
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            path = tmp.name
        try:
            code, out = _run(runner, ['arecord', '-q', '-d', '1', '-f', 'S16_LE', '-r', '16000', '-c', '1', path])
            if code != 0:
                return _check('prueba de grabación', 'problem', 'No se pudo abrir el micrófono: ' + (out or 'sin detalle'))
            try:
                with wave.open(path, 'rb') as wav:
                    frames = wav.readframes(wav.getnframes())
                if not frames:
                    return _check('prueba de grabación', 'unknown', 'El archivo quedó vacío; no se pudo analizar la señal.')
                count = len(frames) // 2
                data = struct.unpack(f'<{count}h', frames[:count * 2])
                peak = max(abs(v) for v in data) if data else 0
                rms = math.sqrt(sum(v * v for v in data) / len(data)) if data else 0.0
                if peak < 128:
                    return _check('prueba de grabación', 'no_signal',
                                  f'No capté sonido en 1 segundo (nivel máximo {peak}). Puede ser silencio normal; habla durante la prueba o comprueba que estás usando el dispositivo correcto.')
                return _check('prueba de grabación', 'ok',
                              f'El micrófono capta señal (nivel máximo {peak} de 32767, promedio {rms:.0f}).')
            except Exception:
                return _check('prueba de grabación', 'unknown', 'No se pudo analizar la señal grabada.')
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:
        return _check('prueba de grabación', 'unknown', 'No se pudo ejecutar la prueba de captura.')


def diagnose_microphone(system=None, runner=None, capture=True):
    system = system or platform.system()
    runner = runner or subprocess.run
    if system != 'Linux':
        return {'microphone_detected': None,
                'checks': [_check('plataforma', 'unknown', 'El diagnóstico de micrófono solo está disponible en Linux por ahora; no voy a inventar resultados para este sistema.')],
                'summary': 'El diagnóstico de micrófono solo está disponible en Linux por ahora.',
                'privacy': 'No se grabó ni envió nada.'}

    checks = []
    # 1. ALSA capture cards
    cards = None
    code, out = _run(runner, ['arecord', '-l'])
    if code is not None:
        cards = len(re.findall(r'^card\s+\d+', out, flags=re.MULTILINE))
        if cards:
            checks.append(_check('dispositivos ALSA', 'ok', f'alsa detecta {cards} dispositivo(s) de captura.'))
        else:
            checks.append(_check('dispositivos ALSA', 'problem', 'alsa no detecta micrófonos. Salida: ' + (out or '(vacía)')))
    else:
        checks.append(_check('dispositivos ALSA', 'unknown', 'arecord no está disponible; compruebo con pactl.'))

    # 2. PulseAudio / PipeWire sources
    sources = None
    default_source = None
    code, out = _run(runner, ['pactl', 'info'])
    if code == 0:
        match = re.search(r'Default Source:\s*(\S+)', out)
        default_source = match.group(1) if match else None
        code2, out2 = _run(runner, ['pactl', 'list', 'sources', 'short'])
        if code2 == 0:
            lines = [l for l in out2.splitlines() if l.strip()]
            real = [l for l in lines if '.monitor' not in l]
            sources = len(real)
            checks.append(_check('entradas de audio (pactl)', 'ok' if real else 'problem',
                                 f'{len(real)} entrada(s) de micrófono y {len(lines) - len(real)} monitor(es) de salida.' +
                                 (f' Predeterminado: {default_source}.' if default_source else '')))
    else:
        checks.append(_check('entradas de audio (pactl)', 'unknown', 'pactl no está disponible o falló; no puedo comprobar el estado de silencio y volumen.'))

    detected = None
    if cards is not None or sources is not None:
        detected = bool((cards or 0) + (sources or 0))

    # 3. Mute and volume of the default capture source
    muted = None
    volume = None
    if default_source:
        code, out = _run(runner, ['pactl', 'get-source-mute', '@DEFAULT_SOURCE@'])
        if code == 0:
            muted = 'yes' in out.lower()
            checks.append(_check('silencio del micrófono', 'problem' if muted else 'ok',
                                 'El micrófono está silenciado.' if muted else 'El micrófono no está silenciado.'))
        code, out = _run(runner, ['pactl', 'get-source-volume', '@DEFAULT_SOURCE@'])
        if code == 0:
            match = re.search(r'(\d+)%', out)
            if match:
                volume = int(match.group(1))
                checks.append(_check('volumen del micrófono', 'problem' if volume == 0 else 'ok',
                                     f'Volumen de captura: {volume}%.'))

    # 4. One-second capture test (local, temporary, discarded)
    if capture and detected and cards:
        checks.append(_capture_test(runner))
    elif capture and detected:
        checks.append(_check('prueba de grabación', 'unknown', 'omito la prueba de captura porque arecord no detectó micrófono; revisa primero si hay dispositivo.'))

    problems = [c for c in checks if c['status'] == 'problem']
    if problems:
        summary = 'Encontré esto en el micrófono: ' + '; '.join(c['detail'] for c in problems)
    elif detected is False:
        summary = 'No detecté ningún micrófono en el sistema. Comprueba que esté conectado, que el sistema lo reconozca (o usa un micrófono USB) e inténtalo de nuevo.'
    elif any(c['check'] == 'prueba de grabación' and c['status'] == 'no_signal' for c in checks):
        summary = 'El micrófono está detectado y no está silenciado, pero no capté señal. Puede ser silencio, el dispositivo equivocado o un fallo del micrófono; habla durante la prueba o escribe en Ajustes de sonido qué dispositivo prefieres.'
    elif detected:
        summary = 'El micrófono está detectado, no está silenciado y capta señal o al menos está operativo a nivel de sistema. Si la app que usas no te escucha, apunta a ella al dispositivo predeterminado.'
    else:
        summary = 'No pude comprobar el micrófono: faltan las herramientas de sonido (alsa-utils o pulseaudio-utils) o el sistema no responde.'

    return {'microphone_detected': detected,
            'muted': muted,
            'volume_percent': volume,
            'checks': checks,
            'summary': summary,
            'privacy': 'La prueba graba un segundo de audio localmente en un archivo temporal que se borra al terminar; no se envía nada a la red ni a ningún proveedor.'}
