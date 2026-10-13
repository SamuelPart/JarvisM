"""Tests de los skills, con un adapter falso: cero contacto con el sistema real."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.safety.policy import PolicyEngine, RiskTier
from jarvis.skills.base import AutoApprove, SkillContext, SkillRegistry
from jarvis.skills.registry import DEFAULT_SKILLS, build_registry


@pytest.fixture()
def registry(settings, fake_adapter, audit) -> SkillRegistry:
    from jarvis.core.events import get_bus

    ctx = SkillContext(
        settings=settings,
        adapter=fake_adapter,
        policy=PolicyEngine(settings),
        audit=audit,
        bus=get_bus(),
        approval=AutoApprove(),
        workspace=settings.data_dir / "workspace",
    )
    return build_registry(ctx)


# --------------------------------------------------------------------------- #
# Estructura del catálogo
# --------------------------------------------------------------------------- #
def test_all_skills_load(registry: SkillRegistry) -> None:
    assert len(registry.all()) == len(DEFAULT_SKILLS)


def test_every_skill_has_description_and_schema(registry: SkillRegistry) -> None:
    for skill in registry.all():
        assert skill.description.strip(), f"{skill.name} sin descripción"
        assert skill.parameters.get("type") == "object", f"{skill.name} sin esquema object"
        assert skill.tier in set(RiskTier), f"{skill.name} con tier inválido"


def test_shell_is_the_only_t3(registry: SkillRegistry) -> None:
    t3 = {s.name for s in registry.all() if s.tier is RiskTier.T3}
    assert t3 == {"shell.run"}


def test_risky_skills_are_high_tier(registry: SkillRegistry) -> None:
    assert registry.get("web.open").tier is RiskTier.T2
    assert registry.get("windows.close").tier is RiskTier.T2
    assert registry.get("system.info").tier is RiskTier.T0


def test_duplicate_registration_fails(registry: SkillRegistry) -> None:
    from jarvis.skills.system_info import TimeSkill

    with pytest.raises(ValueError, match="duplicado"):
        registry.register(TimeSkill(registry.get("system.info").ctx))


def test_schema_validation_rejects_bad_arguments(registry: SkillRegistry) -> None:
    ok, error = registry.validate_arguments("apps.launch", {})
    assert not ok
    assert "app" in error

    ok, _ = registry.validate_arguments("apps.launch", {"app": "firefox"})
    assert ok

    ok, error = registry.validate_arguments("system.processes", {"top_n": 9999})
    assert not ok


# --------------------------------------------------------------------------- #
# Skills concretos
# --------------------------------------------------------------------------- #
def test_system_info_reports_fake_hardware(registry: SkillRegistry) -> None:
    result = registry.run("system.info", {})
    assert result.ok
    assert "TestLinux" in result.message_for_user
    assert "16" in result.message_for_user  # 16384 MB -> ~16 GB


def test_disk_skill_warns_when_critical(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.disk_used_pct = 96.0
    result = registry.run("system.disk", {})
    assert result.ok
    assert "crítico" in result.message_for_user.lower()


def test_apps_launch_resolves_spanish_alias(registry: SkillRegistry, fake_adapter) -> None:
    result = registry.run("apps.launch", {"app": "navegador"})
    assert result.ok
    assert fake_adapter.launched[0][0] in {"firefox", "firefox-esr", "google-chrome"}
    assert result.undo is not None  # T1 debe ser reversible


def test_apps_launch_failure_is_honest(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.launch_ok = False
    result = registry.run("apps.launch", {"app": "noexiste"})
    assert not result.ok
    assert "No pude abrir" in result.message_for_user


def test_files_search_respects_excluded_paths(registry: SkillRegistry, settings) -> None:
    settings.privacy.exclude_paths = [str(settings.data_dir)]
    result = registry.run("files.search", {"pattern": "*.py", "path": str(settings.data_dir)})
    assert not result.ok
    assert "privacidad" in result.message_for_user


def test_files_search_finds_real_files(registry: SkillRegistry, tmp_path) -> None:
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "b.txt").write_text("hola")
    result = registry.run("files.search", {"pattern": "*.py", "path": str(tmp_path)})
    assert result.ok
    assert "a.py" in result.message_for_user
    assert "b.txt" not in result.message_for_user


def test_files_read_redacts_secrets(registry: SkillRegistry, tmp_path) -> None:
    secret = tmp_path / "config.env"
    secret.write_text("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz\nOTRA=cosa")
    result = registry.run("files.read", {"path": str(secret)})
    assert result.ok
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in result.message_for_user
    assert "REDACTADO" in result.message_for_user


def test_clipboard_set_registers_undo(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.clipboard = "lo de antes"
    result = registry.run("clipboard.set", {"text": "lo nuevo"})
    assert result.ok
    assert fake_adapter.clipboard == "lo nuevo"
    assert result.undo is not None
    result.undo()
    assert fake_adapter.clipboard == "lo de antes"


def test_clipboard_get_redacts(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.clipboard = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    result = registry.run("clipboard.get", {})
    assert result.ok
    assert "ghp_" not in result.message_for_user


def test_volume_sets_and_undoes(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.volumes = [50]
    result = registry.run("media.volume", {"percent": 20})
    assert result.ok
    assert fake_adapter.volumes[-1] == 20
    result.undo()
    assert fake_adapter.volumes[-1] == 50


def test_notes_create_writes_inside_workspace(registry: SkillRegistry, settings) -> None:
    result = registry.run("notes.create", {"title": "Idea", "body": "probar el watchdog"})
    assert result.ok
    path = result.data["path"]
    assert str(settings.data_dir) in path
    assert "probar el watchdog" in Path(path).read_text(encoding="utf-8")


def test_time_skill_returns_text(registry: SkillRegistry) -> None:
    result = registry.run("time.now", {})
    assert result.ok
    assert "Son las" in result.message_for_user


def test_capabilities_skill_lists_missing(registry: SkillRegistry, fake_adapter) -> None:
    fake_adapter.capability_overrides = {"wmctrl": False}
    result = registry.run("system.capabilities", {})
    assert result.ok
    assert result.data is not None


def test_unknown_skill_returns_failure(registry: SkillRegistry) -> None:
    result = registry.run("no.existe", {})
    assert not result.ok
    assert "desconocido" in result.message_for_user


def test_skill_exception_is_contained(registry: SkillRegistry) -> None:
    """Un skill que explota no debe tumbar el agente."""

    class Boom(registry.get("time.now").__class__):  # reutilizamos la clase base vía instancia
        name = "test.boom"
        description = "explota a propósito para verificar el aislamiento de errores."

        def execute(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom")

    skill = Boom(registry.get("time.now").ctx)
    registry.register(skill)
    result = registry.run("test.boom", {})
    assert not result.ok
    assert "boom" in result.message_for_user
