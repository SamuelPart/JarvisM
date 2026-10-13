"""Tests de arquitectura: verifican que las reglas del proyecto se cumplen.

Son tan importantes como los funcionales porque evitan la degradación silenciosa
del diseño (ADR-0004 y principio P2).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "jarvis"


def _py_files(*relative: str) -> list[Path]:
    files: list[Path] = []
    for item in relative:
        base = PKG / item
        files.extend(base.rglob("*.py") if base.is_dir() else [base])
    return [f for f in files if f.is_file()]


# --------------------------------------------------------------------------- #
# 1. subprocess solo en platforms/ y skills/shell.py (ADR-0004)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", ["core", "providers", "skills", "safety", "config", "proactive"])
def test_no_subprocess_outside_platform_layer(module: str) -> None:
    offenders: list[str] = []
    for path in _py_files(module):
        if path.name == "shell.py":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(?:from|import)\s+subprocess\b", text, re.MULTILINE):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "subprocess solo puede aparecer en jarvis/platforms/ y jarvis/skills/shell.py. "
        f"Infractores: {offenders}"
    )


#: `shell=True` como ARGUMENTO real (no la mención en un docstring explicativo).
SHELL_TRUE_CALL = re.compile(r"[,(]\s*shell\s*=\s*True")


@pytest.mark.parametrize(
    "relative",
    [
        "skills/shell.py",
        "platforms/_proc.py",
        "platforms/linux.py",
        "platforms/windows.py",
        "platforms/macos.py",
    ],
)
def test_no_shell_true_anywhere(relative: str) -> None:
    text = (PKG / relative).read_text(encoding="utf-8")
    assert not SHELL_TRUE_CALL.search(text), f"{relative} usa shell=True"


# --------------------------------------------------------------------------- #
# 2. El LLM no ejecuta: no hay exec/eval en el core
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", ["core", "providers", "skills", "safety", "proactive"])
def test_no_dynamic_execution(module: str) -> None:
    offenders: list[str] = []
    for path in _py_files(module):
        text = path.read_text(encoding="utf-8")
        for pattern in (r"\bexec\s*\(", r"\beval\s*\(", r"\bos\.system\s*\("):
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(ROOT)}:{pattern}")
    assert not offenders, f"ejecución dinámica prohibida: {offenders}"


def test_no_pickle_or_marshal_in_core() -> None:
    offenders: list[str] = []
    for path in _py_files("core", "safety", "skills"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\b(?:pickle|marshal)\.", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders


# --------------------------------------------------------------------------- #
# 3. No hay secretos ni rutas de usuario hardcodeadas
# --------------------------------------------------------------------------- #
def test_no_hardcoded_secrets() -> None:
    suspicious = re.compile(r"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,})")
    offenders = [
        str(p.relative_to(ROOT)) for p in _py_files(".") if suspicious.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders


def test_no_hardcoded_home_paths() -> None:
    offenders: list[str] = []
    for path in _py_files("."):
        text = path.read_text(encoding="utf-8")
        if re.search(r"['\"]/(?:home|Users)/[a-z]+", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders


def test_no_plain_http_to_apis() -> None:
    """Las claves nunca viajan en claro salvo a localhost (Ollama)."""
    for path in _py_files("providers"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'"(http://[^"]+)"', text):
            url = match.group(1)
            assert "127.0.0.1" in url or "localhost" in url, f"{path.name}: {url} debería ser https"


# --------------------------------------------------------------------------- #
# 4. Nada de modelos hardcodeados en el core (P10)
# --------------------------------------------------------------------------- #
def test_models_are_not_hardcoded_in_core() -> None:
    """El core no debe nombrar modelos concretos: solo perfiles lógicos."""
    pattern = re.compile(
        r"['\"](?:gpt-[0-9o]|claude-(?:opus|sonnet|haiku)-[0-9]|gemini-[0-9])", re.IGNORECASE
    )
    offenders: list[str] = []
    for path in _py_files("core", "skills", "safety", "proactive"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"los nombres de modelo deben vivir en config.toml: {offenders}"


def test_default_config_declares_the_profiles() -> None:
    text = (PKG / "resources" / "config.default.toml").read_text(encoding="utf-8")
    for profile in ("model_cheap", "model_general", "model_reasoner", "model_offline"):
        assert profile in text


# --------------------------------------------------------------------------- #
# 5. Estructura del paquete
# --------------------------------------------------------------------------- #
def test_package_layout_is_complete() -> None:
    expected = {
        "cli.py",
        "diagnostics.py",
        "config/settings.py",
        "config/personas.py",
        "core/orchestrator.py",
        "core/router.py",
        "core/memory.py",
        "core/events.py",
        "core/matcher.py",
        "providers/base.py",
        "providers/registry.py",
        "skills/base.py",
        "skills/registry.py",
        "skills/shell.py",
        "platforms/base.py",
        "platforms/linux.py",
        "platforms/windows.py",
        "platforms/macos.py",
        "safety/policy.py",
        "safety/audit.py",
        "proactive/watchdog.py",
        "resources/config.default.toml",
    }
    missing = [name for name in expected if not (PKG / name).exists()]
    assert not missing, f"faltan módulos: {missing}"


def test_every_subpackage_has_init() -> None:
    for directory in PKG.rglob("*"):
        if directory.is_dir() and any(directory.glob("*.py")) and directory.name != "resources":
            assert (directory / "__init__.py").exists(), f"falta __init__.py en {directory}"


def test_docs_are_present() -> None:
    for name in [
        "PLAN.md",
        "README.md",
        "docs/01-arquitectura.md",
        "docs/02-roadmap.md",
        "docs/03-seguridad-y-permisos.md",
        "docs/04-guia-kali-linux.md",
        "docs/05-proveedores-ia.md",
        "docs/06-backlog-ideas.md",
        "docs/adr/0001-python-httpx-sin-sdks.md",
        "docs/adr/0002-llm-propone-policy-dispone.md",
        "docs/adr/0003-cascade-routing.md",
        "docs/adr/0004-osadapter.md",
    ]:
        assert (ROOT / name).exists(), f"falta documentación: {name}"
