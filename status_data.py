"""Nonblocking local resource sampling for the status panel."""
import psutil


def sample_usage():
    try:
        return {'cpu': f'{psutil.cpu_percent(interval=None):.0f} %',
                'memory': f'{psutil.virtual_memory().percent:.0f} %'}
    except (OSError, RuntimeError, ValueError):
        return {'cpu': 'No disponible', 'memory': 'No disponible'}
