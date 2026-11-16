"""Fast-forward updater for a clean checkout with an explicitly tracked upstream."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class UpdateError(RuntimeError): pass


def git(*args, check=True):
    result = subprocess.run(['git', *args], cwd=ROOT, text=True, capture_output=True, timeout=90)
    if check and result.returncode:
        raise UpdateError(result.stderr.strip() or 'Error de git')
    return result


def update():
    """Fetch and fast-forward only; returns True when a restart is required."""
    git('rev-parse', '--is-inside-work-tree')
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD').stdout.strip()
    if not branch: raise UpdateError('HEAD está desacoplado.')
    if git('status', '--porcelain', '--untracked-files=normal').stdout.strip():
        raise UpdateError('Hay cambios locales o archivos sin seguimiento; no se actualizó nada.')
    remote = git('config', '--get', f'branch.{branch}.remote').stdout.strip()
    if not remote or remote == '.': raise UpdateError('La rama no tiene un remoto válido configurado.')
    git('fetch', '--', remote)
    upstream = git('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}').stdout.strip()
    local = git('rev-parse', 'HEAD').stdout.strip()
    remote_commit = git('rev-parse', '@{upstream}').stdout.strip()
    if local == remote_commit: return False
    # Do not discard local commits, divergent history or advance when local is ahead.
    if git('merge-base', '--is-ancestor', local, remote_commit, check=False).returncode != 0:
        raise UpdateError(f'La rama local y {upstream} han divergido o la local está adelantada.')
    changed = git('diff', '--name-only', local, remote_commit, '--', 'requirements.txt').stdout.strip()
    git('merge', '--ff-only', remote_commit)
    if changed:
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], cwd=ROOT)
        if result.returncode:
            raise UpdateError('Código actualizado, pero falló la instalación de dependencias. Corrija el entorno antes de reiniciar.')
    return True


def restart(entrypoint='main.py'):
    if entrypoint not in ('main.py', 'gui.py'):
        raise ValueError('Punto de inicio no válido.')
    os.execv(sys.executable, [sys.executable, str(ROOT / entrypoint), *sys.argv[1:]])
