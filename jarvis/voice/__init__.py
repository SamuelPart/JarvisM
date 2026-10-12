"""Pila de voz (Fase 3): audio, VAD, wake word, STT y TTS.

Los módulos de este paquete se importan de forma perezosa y todas sus
dependencias son opcionales (`pip install -e '.[voice]'`). Mientras no estén
instaladas, JarvisM funciona en modo texto sin degradar ninguna otra función
(principio P5). Contrato previsto en docs/01-arquitectura.md §2 y la Fase 3 de
docs/02-roadmap.md.
"""

from __future__ import annotations

__all__ = ["explain_missing_voice_deps", "voice_available"]

_REQUIRED = ("sounddevice", "numpy", "faster_whisper")


def voice_available() -> bool:
    """True si las dependencias de audio están instaladas."""
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in _REQUIRED)


def explain_missing_voice_deps() -> list[str]:
    """Lista lo que falta y cómo instalarlo (lo usa `jarvis doctor`)."""
    import importlib.util

    missing = [m for m in _REQUIRED if importlib.util.find_spec(m) is None]
    if not missing:
        return []
    return [
        f"Faltan: {', '.join(missing)}",
        "En Debian/Kali: sudo apt install portaudio19-dev libsndfile1 ffmpeg espeak-ng",
        "Luego: pip install -e '.[voice]'",
        "Mientras tanto JarvisM funciona en modo texto (`jarvis chat`).",
    ]
