"""API local (REST + WebSocket) que consumirá el HUD y el panel web — Fase 6.

Reglas de seguridad no negociables:
  - escucha en 127.0.0.1 por defecto;
  - todo endpoint (salvo /health) exige el token de la sesión;
  - las acciones pasan por el MISMO policy engine que la CLI: la API no es un
    canal privilegiado y no puede aprobar nada por sí sola;
  - CORS cerrado salvo configuración explícita.

El esqueleto ya es funcional: `jarvis serve` y puedes consultar el estado del
sistema. Los endpoints de voz y del HUD se completan en Fase 6.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import asdict, is_dataclass
from typing import Any

# FastAPI se importa a nivel de módulo (y no dentro de `create_app`) por un motivo
# concreto: con `from __future__ import annotations` FastAPI resuelve los tipos con
# `get_type_hints()` contra los globales del MÓDULO. Si `WebSocket` viviera solo en
# el espacio local de la función, la anotación no se resolvería y FastAPI trataría
# el parámetro `websocket` como un query param obligatorio.
# `jarvis.server.__init__` expone `create_app` de forma perezosa, así que importar
# el paquete sin el extra [ui] sigue funcionando.
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jarvis.config.settings import Settings, get_settings
from jarvis.core.events import Event, get_bus
from jarvis.core.orchestrator import Orchestrator
from jarvis.platforms.factory import get_adapter
from jarvis.ui.tui import ConsoleApproval

log = logging.getLogger("jarvis.server")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def load_token(settings: Settings) -> str:
    settings.ensure_dirs()
    token_file = settings.data_dir / "api.token"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(32)
    token_file.write_text(value, encoding="utf-8")
    with contextlib.suppress(OSError):
        token_file.chmod(0o600)
    return value


def create_app() -> Any:
    """Fábrica para `uvicorn.run(..., factory=True)`."""
    settings = get_settings()
    token = load_token(settings) if settings.server.require_token else ""
    adapter = get_adapter()
    orchestrator = Orchestrator(settings, adapter=adapter, approval=ConsoleApproval())
    bus = get_bus()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Cierra el orquestador al apagar (libera SQLite y clientes HTTP)."""
        yield
        orchestrator.close()

    app = FastAPI(
        title="JarvisM local API",
        version="0.1.0",
        description="API local del agente. Solo loopback y con token.",
        docs_url="/docs" if settings.server.host in {"127.0.0.1", "localhost"} else None,
        lifespan=lifespan,
    )
    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str:
        if not token:
            return ""
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(status_code=401, detail="token inválido o ausente")
        return credentials.credentials

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": "0.1.0",
            "offline": orchestrator.offline,
            "time": time.time(),
            "kill_switch": orchestrator.policy.kill_switch,
        }

    @app.get("/v1/system", dependencies=[Depends(require_token)])
    async def system_info() -> dict[str, Any]:
        return _jsonable(adapter.system_info())

    @app.get("/v1/disks", dependencies=[Depends(require_token)])
    async def disks() -> list[dict[str, Any]]:
        return _jsonable(adapter.disks())

    @app.get("/v1/processes", dependencies=[Depends(require_token)])
    async def processes(top_n: int = 10) -> list[dict[str, Any]]:
        return _jsonable(adapter.processes(top_n=max(1, min(top_n, 50))))

    @app.get("/v1/skills", dependencies=[Depends(require_token)])
    async def skills_list() -> list[dict[str, Any]]:
        return orchestrator.registry.describe_table()

    @app.get("/v1/capabilities", dependencies=[Depends(require_token)])
    async def capabilities() -> list[dict[str, Any]]:
        return _jsonable(adapter.capabilities())

    @app.get("/v1/budget", dependencies=[Depends(require_token)])
    async def budget() -> dict[str, Any]:
        return orchestrator.budget.snapshot()

    @app.get("/v1/audit", dependencies=[Depends(require_token)])
    async def audit_tail(n: int = 20) -> list[dict[str, Any]]:
        return [_jsonable(e.to_dict()) for e in orchestrator.audit.tail(max(1, min(n, 200)))]

    @app.get("/v1/events", dependencies=[Depends(require_token)])
    async def events(limit: int = 100, prefix: str | None = None) -> list[dict[str, Any]]:
        return [
            {"name": e.name, "ts": e.ts, "source": e.source, "data": _jsonable(e.data)}
            for e in bus.history(prefix=prefix, limit=max(1, min(limit, 500)))
        ]

    @app.post("/v1/say", dependencies=[Depends(require_token)])
    async def say(payload: dict[str, Any]) -> dict[str, Any]:
        """Envía una orden de texto al agente. Mismo policy engine que la CLI."""
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=422, detail="falta 'text'")
        if len(text) > 4000:
            raise HTTPException(status_code=422, detail="texto demasiado largo (máx. 4000)")
        result = orchestrator.handle(text, profile=payload.get("profile"))
        return {
            "reply": result.reply,
            "actions": [_jsonable(a) for a in result.actions],
            "provider": result.provider,
            "model": result.model,
            "cost_usd": result.cost_usd,
            "latency_ms": round(result.latency_ms, 1),
            "matched_locally": result.matched_locally,
            "suggestions": result.suggestions,
            "error": result.error,
        }

    @app.post("/v1/kill-switch", dependencies=[Depends(require_token)])
    async def kill_switch(payload: dict[str, Any]) -> dict[str, Any]:
        value = bool(payload.get("enabled", True))
        orchestrator.policy.set_kill_switch(value)
        orchestrator.audit.record("kill_switch", decision="on" if value else "off", source="api")
        return {"kill_switch": value}

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket) -> None:
        """Stream de eventos en vivo para el HUD."""
        supplied = websocket.query_params.get("token", "")
        if token and not secrets.compare_digest(supplied, token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue: list[Event] = []
        unsubscribe = bus.subscribe("*", queue.append)
        try:
            while True:
                if queue:
                    event = queue.pop(0)
                    await websocket.send_text(
                        json.dumps({"name": event.name, "ts": event.ts, "data": _jsonable(event.data)})
                    )
                else:
                    await asyncio.sleep(0.2)
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    return app
