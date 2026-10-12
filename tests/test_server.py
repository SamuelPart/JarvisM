"""Tests de la API local (Fase 6).

Lo importante aquí no es que los endpoints devuelvan datos, sino que **la API no
sea un canal privilegiado**: sin token no se pasa, y una orden enviada por HTTP
atraviesa el mismo policy engine que la CLI.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi", reason="los tests del servidor requieren el extra [ui]")

pytestmark = pytest.mark.integration


@pytest.fixture()
def client(monkeypatch, tmp_path, fake_adapter):
    """Cliente con datos aislados y adapter falso (ni red ni sistema real)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    from jarvis.config.settings import reload_settings

    reload_settings()

    import jarvis.platforms.factory as factory
    from jarvis.server import app as app_module

    monkeypatch.setattr(factory, "get_adapter", lambda: fake_adapter)
    monkeypatch.setattr(app_module, "get_adapter", lambda: fake_adapter)

    application = app_module.create_app()
    with TestClient(application) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {app_module.load_token(reload_settings())}"})
        yield test_client


def test_health_needs_no_token(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["kill_switch"] is False


@pytest.mark.parametrize(
    "path",
    ["/v1/system", "/v1/disks", "/v1/processes", "/v1/skills", "/v1/budget", "/v1/audit"],
)
def test_endpoints_require_token(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Authorization": "Bearer token-inventado"})
    assert response.status_code == 401


def test_endpoints_reject_missing_token(client: TestClient) -> None:
    response = client.get("/v1/system", headers={"Authorization": ""})
    assert response.status_code == 401


def test_system_endpoint_returns_fake_data(client: TestClient) -> None:
    payload = client.get("/v1/system").json()
    assert payload["os_name"] == "TestLinux"
    assert payload["hostname"] == "testhost"


def test_skills_endpoint_exposes_risk_tiers(client: TestClient) -> None:
    rows = client.get("/v1/skills").json()
    names = {r["name"]: r["tier"] for r in rows}
    assert names["shell.run"] == "T3"
    assert names["system.info"] == "T0"


def test_say_runs_through_the_policy_engine(client: TestClient) -> None:
    """Una orden por HTTP debe comportarse igual que por la CLI."""
    response = client.post("/v1/say", json={"text": "¿qué hora es?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["matched_locally"] is True
    assert "Son las" in payload["reply"]
    assert payload["actions"][0]["tier"] == "T0"


def test_say_denies_dangerous_shell_command(client: TestClient) -> None:
    response = client.post(
        "/v1/say",
        json={"text": 'ejecuta el comando "rm -rf /" para limpiar todo'},
    )
    assert response.status_code == 200
    payload = response.json()
    # Puede venir del matcher o del modelo, pero nunca debe ejecutarse.
    assert all(a["decision"] == "deny" for a in payload["actions"]) if payload["actions"] else True


def test_say_validates_payload(client: TestClient) -> None:
    assert client.post("/v1/say", json={}).status_code == 422
    assert client.post("/v1/say", json={"text": ""}).status_code == 422
    assert client.post("/v1/say", json={"text": "x" * 5000}).status_code == 422


def test_kill_switch_blocks_actions_and_is_audited(client: TestClient) -> None:
    assert client.post("/v1/kill-switch", json={"enabled": True}).json()["kill_switch"] is True

    payload = client.post("/v1/say", json={"text": "¿qué hora es?"}).json()
    assert payload["actions"][0]["decision"] == "deny"

    entries = client.get("/v1/audit?n=20").json()
    assert any(e["kind"] == "kill_switch" for e in entries)

    assert client.post("/v1/kill-switch", json={"enabled": False}).json()["kill_switch"] is False


def test_events_endpoint_exposes_the_bus(client: TestClient) -> None:
    client.post("/v1/say", json={"text": "¿qué hora es?"})
    events = client.get("/v1/events?limit=50").json()
    names = {e["name"] for e in events}
    assert "policy.decision" in names
    assert "turn.completed" in names


def test_capabilities_endpoint(client: TestClient) -> None:
    caps = client.get("/v1/capabilities").json()
    assert any(c["name"] == "clipboard" for c in caps)


def test_websocket_requires_valid_token(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=malo") as ws:
        ws.receive_text()


def test_websocket_streams_events(client: TestClient) -> None:
    with client.websocket_connect(
        f"/ws?token={client.headers['Authorization'].removeprefix('Bearer ')}"
    ) as ws:
        client.post("/v1/say", json={"text": "¿qué hora es?"})
        received = [ws.receive_json() for _ in range(3)]
    assert any(item["name"] in {"policy.decision", "turn.completed"} for item in received)
