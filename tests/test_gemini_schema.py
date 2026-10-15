"""Regresión: Gemini rechazaba TODOS los turnos con herramientas (HTTP 400).

Reportado en vivo desde un Kali con clave `AQ.` real:

    failover gemini -> openai (bad_request: [gemini] bad_request: HTTP 400:
    Invalid JSON payload received. Unknown name "additionalProperties" at
    'tools[0].function_declarations[0].parameters': Cannot find field.)

Causa: `parameters` de una `functionDeclaration` es un subconjunto de OpenAPI 3.0
y no admite `additionalProperties`, que TODAS las skills declaran (y que es lo
correcto: sirve para validar los argumentos en local y para OpenAI). Resultado:
Gemini fallaba en el 100 % de los turnos de conversación, no en un caso raro.

El arreglo limpia el esquema justo antes de enviarlo, sin mutar el original.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis.providers.base import CompletionRequest, Message, ToolSpec
from jarvis.providers.gemini_provider import build_payload, sanitize_schema_for_gemini


def _json_keys(obj: Any) -> list[str]:
    """Todas las claves del esquema, a cualquier profundidad."""
    if isinstance(obj, dict):
        return list(obj) + [k for v in obj.values() for k in _json_keys(v)]
    if isinstance(obj, list):
        return [k for item in obj for k in _json_keys(item)]
    return []


def _request(tools: list[ToolSpec]) -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content="hola")], model="gemini-3.7-flash", tools=tools
    )


# --------------------------------------------------------------------------- #
# La limpieza
# --------------------------------------------------------------------------- #
def test_additional_properties_is_removed() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"],
        "additionalProperties": False,
    }
    clean = sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in clean
    # Lo que SÍ soporta Gemini se conserva intacto.
    assert clean["properties"]["path"] == {"type": "string", "minLength": 1}
    assert clean["required"] == ["path"]


def test_original_schema_is_not_mutated() -> None:
    """El esquema original debe seguir validando en local: no se toca."""
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    sanitize_schema_for_gemini(schema)
    assert schema["additionalProperties"] is False


def test_nested_schemas_are_cleaned_recursively() -> None:
    schema = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "object",
                "properties": {"name": {"type": "string", "additionalProperties": False}},
                "additionalProperties": False,
            },
            "items": {"type": "array", "items": {"type": "string"}, "additionalProperties": False},
        },
        "additionalProperties": False,
    }
    clean = sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in _json_keys(clean)


def test_const_becomes_enum() -> None:
    """Gemini no tiene `const`; un enum de un valor expresa lo mismo."""
    clean = sanitize_schema_for_gemini({"const": "apps"})
    assert clean == {"enum": ["apps"]}


def test_type_list_becomes_nullable() -> None:
    """`type: ["string", "null"]` es válido en JSON Schema, no en Gemini."""
    clean = sanitize_schema_for_gemini({"type": ["string", "null"]})
    assert clean == {"type": "string", "nullable": True}


def test_unsupported_structural_keys_are_dropped() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"x": {"type": "string"}},
        "if": {"type": "string"},
        "examples": ["a"],
        "type": "object",
    }
    assert sanitize_schema_for_gemini(schema) == {"type": "object"}


def test_non_dict_values_pass_through() -> None:
    assert sanitize_schema_for_gemini("texto") == "texto"
    assert sanitize_schema_for_gemini(None) is None
    assert sanitize_schema_for_gemini([{"additionalProperties": False}]) == [{}]


# --------------------------------------------------------------------------- #
# End-to-end: el payload que sale hacia la API
# --------------------------------------------------------------------------- #
def test_payload_has_no_unsupported_key_anywhere() -> None:
    tools = [
        ToolSpec(
            name="system.info",
            description="estado del sistema",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        ToolSpec(
            name="apps.launch",
            description="abre una app",
            parameters={
                "type": "object",
                "properties": {"app": {"type": "string", "minLength": 1}},
                "required": ["app"],
                "additionalProperties": False,
            },
        ),
    ]
    payload = build_payload(_request(tools))
    keys = _json_keys(payload["tools"])
    assert "additionalProperties" not in keys, "el payload hacia Gemini volvería a dar 400"
    # Y sigue siendo JSON serializable y con los nombres traducidos.
    json.dumps(payload)
    declared = payload["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in declared] == ["system_info", "apps_launch"]


def test_every_real_skill_schema_survives_gemini(settings, fake_adapter, audit) -> None:
    """El test que habría cazado el bug: TODAS las skills del catálogo real."""
    from jarvis.core.events import get_bus
    from jarvis.safety.policy import PolicyEngine
    from jarvis.skills.base import AutoApprove, SkillContext
    from jarvis.skills.registry import build_registry

    ctx = SkillContext(
        settings=settings,
        adapter=fake_adapter,
        policy=PolicyEngine(settings),
        audit=audit,
        bus=get_bus(),
        approval=AutoApprove(),
        workspace=settings.data_dir / "workspace",
    )
    skills = build_registry(ctx).all()
    assert len(skills) > 20, "el catálogo debe tener las skills reales registradas"
    for skill in skills:
        clean = sanitize_schema_for_gemini(skill.parameters)
        assert "additionalProperties" not in _json_keys(clean), f"{skill.name} rompería Gemini"
        json.dumps(clean)  # serializable
