"""Puente sync ↔ async.

El orquestador es síncrono (la CLI de Typer lo es), pero los providers son
`httpx.AsyncClient`. Si ya hay un loop corriendo (p. ej. dentro de FastAPI o de
un test `pytest-asyncio`), `asyncio.run` lanza RuntimeError; en ese caso
delegamos en un hilo dedicado con su propio loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    """Loop permanente en un hilo daemon para llamadas desde contexto async."""
    global _loop_thread, _loop
    with _lock:
        if _loop is not None and _loop.is_running():
            return _loop
        ready = threading.Event()

        def runner() -> None:
            global _loop
            loop = asyncio.new_event_loop()
            _loop = loop
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        _loop_thread = threading.Thread(target=runner, name="jarvis-async", daemon=True)
        _loop_thread.start()
        ready.wait(timeout=10)
        assert _loop is not None
        return _loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Ejecuta una corutina desde código síncrono, haya o no loop activo."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Hay loop activo: no podemos anidar asyncio.run.
    return asyncio.run_coroutine_threadsafe(coro, _background_loop()).result()


def shutdown_background_loop() -> None:
    global _loop_thread, _loop
    with _lock:
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_loop.stop)
        if _loop_thread is not None:
            _loop_thread.join(timeout=5)
        _loop = None
        _loop_thread = None
