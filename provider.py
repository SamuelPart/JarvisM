"""Create the selected provider; no implicit cross-provider fallback."""
import os
import sqlite3
from pathlib import Path
from memory import JarvisMemory
from persistent_brain import PersistentBrain
from brain import Brain
from nvidia_brain import NvidiaBrain, DEFAULT_MODEL


def create_brain(controller, approve):
    provider = os.getenv('JARVIS_PROVIDER', 'gemini').strip().lower()
    name = os.getenv('JARVIS_NAME', 'Señor')
    if provider == 'gemini':
        brain = Brain(os.getenv('GEMINI_API_KEY'), controller, approve, name=name,
                      model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
    elif provider == 'nvidia':
        brain = NvidiaBrain(os.getenv('NVIDIA_API_KEY'), controller, approve, name=name,
                            model=os.getenv('NVIDIA_MODEL', DEFAULT_MODEL))
    else:
        raise ValueError('JARVIS_PROVIDER debe ser gemini o nvidia.')
    path = os.getenv('JARVIS_MEMORY_PATH', str(Path(__file__).resolve().parent / '.jarvis-memory.sqlite3'))
    try:
        return PersistentBrain(brain, JarvisMemory(path))
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError('No se pudo abrir la memoria local de JARVIS.') from exc
