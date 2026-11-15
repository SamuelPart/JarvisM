"""Create per-user Linux launchers without a terminal or elevated privileges."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKER = 'X-JARVIS-Launcher=true'


def _exec_arg(value):
    # Desktop Entry Exec is not a shell command. Quote each argument and escape
    # reserved characters, including % which otherwise introduces field codes.
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('Ruta incompatible con el acceso directo.')
    value = value.replace('%', '%%')
    for c in ('\\', '"', '`', '$'):
        value = value.replace(c, '\\' + c)
    return '"' + value + '"'


def desktop_directory(home):
    try:
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=3, check=True)
        path = Path(result.stdout.strip())
        # xdg-user-dir returns HOME if the desktop directory is disabled.
        if path.is_absolute() and path != home and path.is_dir():
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ('Desktop', 'Escritorio'):
        path = home / name
        if path.is_dir():
            return path
    return None


def install():
    """Return created paths; do not overwrite unrelated files or symlinks."""
    if platform.system() != 'Linux':
        return []
    python = ROOT / 'venv' / 'bin' / 'python'
    if not python.is_file():
        return []
    home = Path.home()
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(home / '.local' / 'share')))
    if not data_home.is_absolute():
        data_home = home / '.local' / 'share'
    apps = data_home / 'applications'
    apps.mkdir(parents=True, exist_ok=True)
    content = ('[Desktop Entry]\nType=Application\nName=JARVIS\n'
               'Comment=Asistente de escritorio JARVIS\n'
               f'Exec={_exec_arg(python)} {_exec_arg(ROOT / "gui.py")}\n'
               f'Icon={ROOT / "jarvis-icon.svg"}\n'
               'Terminal=false\nCategories=Utility;\n' + MARKER + '\n')
    created = []
    desktop = desktop_directory(home)
    targets = [(apps / 'jarvis-desktop.desktop', False)]
    if desktop:
        targets.append((desktop / 'JARVIS.desktop', True))
    for path, is_desktop in targets:
        try:
            if path.is_symlink() or (path.exists() and MARKER not in path.read_text(encoding='utf-8')):
                continue
            path.write_text(content, encoding='utf-8')
            path.chmod(0o755 if is_desktop else 0o644)
            created.append(path)
            # GNOME/Nautilus may require the trusted metadata in addition to chmod.
            if is_desktop and shutil.which('gio'):
                subprocess.run(['gio', 'set', str(path), 'metadata::trusted', 'true'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        except (OSError, UnicodeError, subprocess.SubprocessError):
            continue
    return created


if __name__ == '__main__':
    try:
        paths = install()
        if paths:
            print('Acceso directo creado:', ', '.join(map(str, paths)))
        else:
            print('No se pudo crear el acceso directo. Comprueba la instalación y la sesión de escritorio.')
            raise SystemExit(1)
    except (OSError, ValueError) as exc:
        print('No se pudo crear el acceso directo:', exc)
        raise SystemExit(1)
