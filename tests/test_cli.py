"""Tests de la CLI (Typer) y de la coherencia entre los defaults de código y TOML.

Se usa `CliRunner` para invocar los comandos de verdad: si un comando se rompe al
importar o al construir el orquestador, aquí salta antes de que lo vea el usuario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomllib
from typer.testing import CliRunner

from jarvis.cli import app
from jarvis.config.settings import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_EXCLUDE_PATHS,
    DEFAULT_JAIL_ROOTS,
    DEFAULT_RESTRICTED_BINARIES,
    DEFAULT_SHELL_ALLOWLIST,
    Settings,
)

runner = CliRunner()


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """Aísla HOME/config/datos para que la CLI no toque nada real."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    from jarvis.config.settings import reload_settings

    reload_settings()
    return tmp_path


# --------------------------------------------------------------------------- #
# Coherencia de defaults (código vs TOML)
# --------------------------------------------------------------------------- #
def test_model_defaults_match_toml() -> None:
    """Los defaults de `Settings()` y el TOML no deben divergir jamás.

    Si divergen, quien construya `Settings()` a mano tendría una política
    distinta (y probablemente más permisiva) que quien cargue el TOML.
    """
    with DEFAULT_CONFIG_PATH.open("rb") as fh:
        toml = tomllib.load(fh)
    model = Settings()

    assert toml["policy"]["auto_approve_max_tier"] == model.policy.auto_approve_max_tier
    assert toml["budget"]["usd_per_day"] == model.budget.usd_per_day
    assert toml["budget"]["hard_stop"] == model.budget.hard_stop
    assert toml["privacy"]["offline"] == model.privacy.offline
    assert toml["privacy"]["redact_secrets"] == model.privacy.redact_secrets
    assert toml["server"]["host"] == model.server.host
    assert toml["router"]["max_steps_per_turn"] == model.router.max_steps_per_turn
    assert toml["watchdog"]["cooldown_s"] == model.watchdog.cooldown_s
    assert toml["voice"]["enabled"] == model.voice.enabled


def test_security_lists_match_toml() -> None:
    with DEFAULT_CONFIG_PATH.open("rb") as fh:
        toml = tomllib.load(fh)
    assert toml["policy"]["jail_roots"] == DEFAULT_JAIL_ROOTS
    assert toml["policy"]["shell_allowlist"] == DEFAULT_SHELL_ALLOWLIST
    assert toml["policy"]["restricted_binaries"] == DEFAULT_RESTRICTED_BINARIES
    assert toml["privacy"]["exclude_paths"] == DEFAULT_EXCLUDE_PATHS


def test_bare_settings_is_already_restrictive() -> None:
    """Un `Settings()` recién construido debe ser seguro, no permisivo."""
    settings = Settings()
    assert settings.policy.auto_approve_max_tier == "T1"
    assert settings.policy.jail_roots
    assert settings.policy.restricted_binaries
    assert "sudo" in settings.policy.restricted_binaries
    assert settings.privacy.exclude_paths
    assert settings.server.host == "127.0.0.1"


def test_router_fallback_models_match_toml() -> None:
    with DEFAULT_CONFIG_PATH.open("rb") as fh:
        toml = tomllib.load(fh)
    assert toml["router"]["fallback_models"] == Settings().router.fallback_models


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "JarvisM" in result.stdout


def test_help_lists_core_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("doctor", "chat", "run", "skills", "policy", "audit", "watch", "serve", "bench"):
        assert command in result.stdout


def test_doctor_json_output(isolated) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    assert "checks" in payload
    assert payload["version"]
    assert payload["ok"] is not False or payload["failures"] >= 0
    names = {c["name"] for c in payload["checks"]}
    assert "python" in names
    assert "privilegios" in names
    assert any(name.startswith("capacidad:") for name in names)


def test_doctor_security_only(isolated) -> None:
    result = runner.invoke(app, ["doctor", "--json", "--security"])
    payload = json.loads(result.stdout)
    names = {c["name"] for c in payload["checks"]}
    assert "privilegios" in names
    assert "presupuesto diario" in names
    assert not any(name.startswith("proveedor:") for name in names)


def test_skills_json_lists_risk_tiers(isolated) -> None:
    result = runner.invoke(app, ["skills", "--json"])
    rows = json.loads(result.stdout)
    assert any(r["name"] == "shell.run" and r["tier"] == "T3" for r in rows)
    assert any(r["name"] == "system.info" and r["tier"] == "T0" for r in rows)


def test_skills_tier_filter(isolated) -> None:
    result = runner.invoke(app, ["skills", "--json", "--tier", "T3"])
    rows = json.loads(result.stdout)
    assert [r["name"] for r in rows] == ["shell.run"]


def test_run_dry_run_denies_dangerous_command(isolated) -> None:
    result = runner.invoke(
        app, ["run", "shell.run", "command=rm -rf /", "reason=prueba de seguridad", "--dry-run", "--json"]
    )
    payload = json.loads(result.stdout)
    assert payload["schema_ok"] is True
    assert "DENY" in payload["verdict"]
    assert payload["would_execute"] is False


def test_run_dry_run_allows_safe_read(isolated) -> None:
    result = runner.invoke(app, ["run", "system.info", "--dry-run", "--json"])
    payload = json.loads(result.stdout)
    assert payload["would_execute"] is True


def test_run_read_only_skill_executes(isolated) -> None:
    result = runner.invoke(app, ["run", "system.info", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["tier"] == "T0"


def test_run_denied_command_exits_nonzero(isolated) -> None:
    result = runner.invoke(app, ["run", "shell.run", "command=rm -rf /", "reason=prueba", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"


def test_run_invalid_arguments_reports_schema_error(isolated) -> None:
    result = runner.invoke(app, ["run", "apps.launch", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "inválidos" in payload["message"]


def test_policy_summary(isolated) -> None:
    result = runner.invoke(app, ["policy"])
    assert result.exit_code == 0
    assert "auto-approve máximo" in result.stdout
    assert "T1" in result.stdout


def test_policy_explain_for_shell(isolated) -> None:
    result = runner.invoke(app, ["policy", "shell.run", "--explain", "command=ls -la", "reason=x"])
    assert result.exit_code == 0
    assert "T3" in result.stdout


def test_audit_empty_then_verify(isolated) -> None:
    result = runner.invoke(app, ["audit", "--verify"])
    assert result.exit_code == 0
    assert "íntegra" in result.stdout or "0 entradas" in result.stdout


def test_audit_after_action_then_verify(isolated) -> None:
    runner.invoke(app, ["run", "system.info"])
    verify = runner.invoke(app, ["audit", "--verify"])
    assert verify.exit_code == 0
    assert "íntegra" in verify.stdout

    tail = runner.invoke(app, ["audit", "--json", "--tail", "5"])
    entries = json.loads(tail.stdout)
    assert any(e["kind"] == "policy.decision" for e in entries)


def test_bench_reports_matcher_coverage(isolated, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("qué hora es\nabre firefox\nexplícame la relatividad\n", encoding="utf-8")
    result = runner.invoke(app, ["bench", "--corpus", str(corpus)])
    assert result.exit_code == 0
    assert "Resueltas sin LLM" in result.stdout
    assert "67%" in result.stdout  # 2 de 3


def test_config_paths_shows_locations(isolated) -> None:
    result = runner.invoke(app, ["config", "--paths"])
    assert result.exit_code == 0
    assert "auditoría" in result.stdout
    assert "capas aplicadas" in result.stdout


def test_config_get_single_key(isolated) -> None:
    result = runner.invoke(app, ["config", "--get", "policy.auto_approve_max_tier"])
    assert result.exit_code == 0
    assert "T1" in result.stdout


def test_config_show_redacts_api_keys(isolated, monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "clave-secreta-de-prueba-1234567890")
    from jarvis.config.settings import reload_settings

    reload_settings()
    result = runner.invoke(app, ["config", "--show"])
    assert result.exit_code == 0
    assert "clave-secreta-de-prueba-1234567890" not in result.stdout


def test_token_is_created_with_secure_permissions(isolated) -> None:
    result = runner.invoke(app, ["token"])
    assert result.exit_code == 0
    token = result.stdout.strip().splitlines()[0]
    assert len(token) > 20

    token_file = Path(isolated) / "data" / "jarvis" / "api.token"
    candidates = list(Path(isolated).rglob("api.token"))
    assert candidates, "no se creó el fichero de token"
    if token_file.exists() or candidates[0].stat().st_mode:
        assert candidates[0].stat().st_mode & 0o777 == 0o600


def test_chat_once_uses_matcher_without_llm(isolated) -> None:
    result = runner.invoke(app, ["chat", "--once", "¿qué hora es?", "--no-meta"])
    assert result.exit_code == 0
    assert "Son las" in result.stdout


def test_watch_once_reports_status(isolated) -> None:
    result = runner.invoke(app, ["watch", "--once"])
    assert result.exit_code == 0
    assert "Watchdog" in result.stdout


def test_cost_command(isolated) -> None:
    result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0
    assert "USD" in result.stdout
