"""API local (REST + WebSocket) para el HUD y el panel web — Fase 6."""

__all__ = ["create_app"]


def __getattr__(name: str):
    if name == "create_app":
        from jarvis.server.app import create_app

        return create_app
    raise AttributeError(name)
