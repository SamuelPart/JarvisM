"""Tests del matcher local (nivel N0 de la cascada, ADR-0003).

El matcher debe resolver mucho sin gastar tokens y, sobre todo, **callar** cuando
no está seguro: un falso positivo aquí ejecutaría una acción equivocada.
"""

from __future__ import annotations

import pytest

from jarvis.core.matcher import coverage_report, match


@pytest.mark.parametrize(
    "text,expected_skill",
    [
        ("¿qué hora es?", "time.now"),
        ("cuánta RAM me queda", "system.info"),
        ("estado del sistema", "system.info"),
        ("cuánto disco libre tengo", "system.disk"),
        ("el disco está lleno", "system.disk"),
        ("qué procesos consumen más memoria", "system.processes"),
        ("por qué va lento el equipo", "system.processes"),
        ("cómo está la batería", "system.battery"),
        ("qué temperatura tiene la cpu", "system.temperature"),
        ("qué puertos tengo abiertos", "system.listeners"),
        ("tengo actualizaciones pendientes", "system.updates_check"),
        ("qué puedes hacer", "system.capabilities"),
        ("abre firefox", "apps.launch"),
        ("abre el navegador", "apps.launch"),
        ("lanza la calculadora", "apps.launch"),
        ("qué ventanas tengo abiertas", "windows.list"),
        ("silencia el equipo", "media.volume"),
        ("quita el silencio", "media.volume"),
        ("sube el volumen", "media.volume"),
        ("pon el volumen al 30%", "media.volume"),
        ("baja el brillo al 20", "media.brightness"),
        ("busca los archivos *.pdf en /tmp", "files.search"),
        ("qué hay en el portapapeles", "clipboard.get"),
        ("lista mis notas", "notes.list"),
        ("abre https://github.com", "web.open"),
        ("busca en internet python asyncio", "web.search"),
    ],
)
def test_canonical_orders_resolve_without_llm(text: str, expected_skill: str) -> None:
    found = match(text)
    assert found is not None, f"no se resolvió: {text}"
    assert found.skill == expected_skill


@pytest.mark.parametrize(
    "text",
    [
        "explícame por qué mi script de python falla",
        "escribe un poema sobre Kali Linux",
        "resume este artículo sobre física cuántica",
        "compárame PostgreSQL con SQLite para mi caso",
        "cómo puedo mejorar el rendimiento de mi servidor web",
        "ayúdame a decidir qué framework usar",
    ],
)
def test_open_ended_questions_go_to_llm(text: str) -> None:
    """Estas deben llegar al modelo: resolverlas localmente sería un error grave."""
    assert match(text) is None, f"el matcher no debería resolver: {text}"


def test_confidence_threshold_is_respected() -> None:
    assert match("qué hora es", min_confidence=0.99) is not None
    assert match("abre firefox", min_confidence=0.99) is None


def test_arguments_are_extracted() -> None:
    found = match("pone el volumen al 45%")
    assert found is not None
    assert found.arguments.get("percent") == 45

    found = match("abre firefox")
    assert found is not None
    assert found.arguments.get("app") == "firefox"


def test_path_extraction_in_file_search() -> None:
    found = match("busca los archivos *.log en /var/tmp")
    assert found is not None
    assert found.arguments["path"] == "/var/tmp"
    assert found.arguments["pattern"] in {"*.log", ".log"}


def test_empty_and_absurd_input_is_ignored() -> None:
    assert match("") is None
    assert match("   ") is None
    assert match("x" * 500) is None
    assert match("hola") is None


def test_coverage_report_reports_rate() -> None:
    stats = coverage_report(["qué hora es", "abre firefox", "explícame la relatividad"])
    assert stats["total"] == 3
    assert stats["resolved"] == 2
    assert 0.6 < stats["rate"] < 0.7
