"""Narrow Debian package operations; the OS authenticates each elevation."""
import os
import platform
import re
import subprocess


def _run_apt(arguments):
    if platform.system() != 'Linux':
        return {'ok': False, 'error': 'Esta operación está disponible solo en Linux con APT y pkexec.'}
    pkexec = '/usr/bin/pkexec'
    apt = '/usr/bin/apt-get'
    if not os.path.isfile(pkexec) or not os.path.isfile(apt):
        return {'ok': False, 'error': 'Se necesitan pkexec y APT instalados, además de una sesión gráfica con agente de autorización.'}
    try:
        result = subprocess.run([pkexec, apt, *arguments], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors='replace', timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Se agotó el tiempo; APT podría seguir trabajando. Comprueba el gestor de paquetes antes de reintentar.'}
    except OSError:
        return {'ok': False, 'error': 'No se pudo iniciar pkexec o APT.'}
    if result.returncode:
        return {'ok': False, 'returncode': result.returncode,
                'error': 'La operación no se completó. Puede haberse cancelado la autenticación o fallado APT.'}
    return {'ok': True, 'returncode': 0}


def install_program(package):
    if not isinstance(package, str) or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]{0,99}(?::[a-z0-9][a-z0-9-]{0,31})?', package):
        raise ValueError('Indica un único nombre exacto de paquete APT válido, sin opciones ni versión.')
    result = _run_apt(['install', '-y', '--', package])
    result['package'] = package
    return result


def update_system():
    updated = _run_apt(['update'])
    if not updated.get('ok'):
        return {'ok': False, 'stage': 'update', 'error': updated.get('error')}
    upgraded = _run_apt(['upgrade', '-y', '-o', 'Dpkg::Options::=--force-confdef',
                         '-o', 'Dpkg::Options::=--force-confold'])
    if not upgraded.get('ok'):
        return {'ok': False, 'stage': 'upgrade', 'error': upgraded.get('error')}
    return {'ok': True, 'note': 'APT actualizó los índices y aplicó upgrade; algunos paquetes pueden quedar retenidos.'}
