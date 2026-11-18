"""Create the NVIDIA NIM brain; the single AI provider of JARVIS (no silent switching)."""
import os
import sqlite3
from pathlib import Path
from memory import JarvisMemory
from persistent_brain import PersistentBrain
from nvidia_brain import NvidiaBrain, DEFAULT_MODEL


def create_brain(controller, approve):
    name = os.getenv('JARVIS_NAME', 'Señor')
    provider = os.getenv('JARVIS_PROVIDER', 'nvidia').strip().lower()
    if provider != 'nvidia':
        raise ValueError('JARVIS_PROVIDER debe ser nvidia; Gemini fue retirado del proyecto.')
    brain = NvidiaBrain(os.getenv('NVIDIA_API_KEY'), controller, approve, name=name,
                        model=os.getenv('NVIDIA_MODEL', DEFAULT_MODEL))
    path = os.getenv('JARVIS_MEMORY_PATH', str(Path(__file__).resolve().parent / '.jarvis-memory.sqlite3'))
    try:
        return PersistentBrain(brain, JarvisMemory(path))
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError('No se pudo abrir la memoria local de JARVIS.') from exc
