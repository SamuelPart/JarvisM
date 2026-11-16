"""Safe, local heartbeat jobs for JARVIS (opt-out individually via env).

Nothing here phones home, uses the network, or acts without the registry's
own guards; the disk watchdog only journals when usage crosses the threshold
(transition, not every check).
"""
from __future__ import annotations

from pathlib import Path

import psutil

import action_log

_LAST = {'disk_low': False}


def disk_watchdog(threshold_percent=90):
    """Journals a low-disk event only on the transition below/above the threshold."""
    try:
        usage = psutil.disk_usage(Path.home().anchor or '/').percent
    except (OSError, RuntimeError):
        return {'ok': False, 'error': 'No se pudo consultar el disco.'}
    low = usage >= threshold_percent
    if low and not _LAST['disk_low']:
        _LAST['disk_low'] = True
        action_log.record('disk_watchdog', {'threshold': threshold_percent},
                          {'error': f'Disco al {round(usage)} por ciento: queda poco espacio.'})
    elif not low and _LAST['disk_low']:
        _LAST['disk_low'] = False
        action_log.record('disk_watchdog', {'threshold': threshold_percent},
                          {'ok': True, 'note': f'Disco recuperado: {round(usage)} por ciento.'})
    return {'disk_percent': round(usage, 1), 'low': low}
