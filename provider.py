"""Create the NVIDIA NIM brain; the single AI provider of JARVIS.

The API key lives in the desktop app's Ajustes (local settings file managed
by provider_settings, gitignored, owner-only) or, for the console, in
NVIDIA_API_KEY from .env. It is never embedded in the repository.
"""
import os
import sqlite3
from pathlib import Path
from memory import JarvisMemory
from persistent_brain import PersistentBrain
from nvidia_brain import NvidiaBrain, DEFAULT_MODEL


def create_brain(controller, approve):
    name = os.getenv('JARVIS_NAME', 'Señor')
    brain = NvidiaBrain(None, controller, approve, name=name,
                        model=os.getenv('NVIDIA_MODEL', DEFAULT_MODEL))
    path = os.getenv('JARVIS_MEMORY_PATH', str(Path(__file__).resolve().parent / '.jarvis-memory.sqlite3'))
    try:
        return PersistentBrain(brain, JarvisMemory(path))
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError('No se pudo abrir la memoria local de JARVIS.') from exc
