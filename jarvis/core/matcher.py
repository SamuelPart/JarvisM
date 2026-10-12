"""Matcher determinista de órdenes canónicas (nivel N0 de la cascada, ADR-0003).

Objetivo: resolver las peticiones más frecuentes SIN llamar a ningún LLM.
Coste 0 tokens, latencia ~5 ms. Regla de diseño: el matcher **solo acelera,
nunca deniega**; si la confianza no llega al umbral, devuelve None y el
orquestador delega en el modelo.

Los skills propuestos siguen pasando por el policy engine igual que los del LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jarvis.safety.policy import RiskTier

STOPWORDS = {
    "por",
    "favor",
    "para",
    "que",
    "qué",
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "de",
    "del",
    "me",
    "mi",
    "se",
    "al",
    "a",
    "en",
    "y",
    "o",
    "te",
    "tu",
    "ya",
    "ahora",
    "mismo",
    "puedes",
    "podrias",
    "podrías",
    "quiero",
    "necesito",
    "jarvis",
    "oye",
    "eh",
    "hey",
    "mira",
}


@dataclass(slots=True)
class Match:
    skill: str
    arguments: dict[str, Any]
    confidence: float
    rule: str
    tier_hint: RiskTier | None = None
    notes: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[\wáéíóúñü.-]+", text.lower(), flags=re.UNICODE)
    return [w for w in words if w not in STOPWORDS]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip("?¡!.,;:"))


def _extract_quoted(text: str) -> str | None:
    m = re.search(r"[\"'“«]([^\"'”»]{2,120})[\"'”»]", text)
    return m.group(1) if m else None


def _extract_url(text: str) -> str | None:
    m = re.search(r"(?:https?://|www\.)[^\s,;]+", text, re.IGNORECASE)
    if m:
        return m.group(0)
    m = re.search(r"\b[\w-]+(?:\.[\w-]+)+\b(?!\.)", text)
    return m.group(0) if m else None


def _extract_percent(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:%|por\s*ciento)", text)
    return int(m.group(1)) if m else None


def _extract_path(text: str) -> str | None:
    m = re.search(r"(?:~|/|\./|\.\./|[A-Za-z]:\\)[^\s,;'\"]+", text)
    return m.group(0) if m else None


# --------------------------------------------------------------------------- #
# Reglas: (nombre, regex, constructor de Match)
# --------------------------------------------------------------------------- #
def _match_time(text: str) -> Match | None:
    if re.search(r"\b(qu[eé] hora|hora es|qu[eé] d[ií]a|fecha de hoy|qu[eé] d[ií]a es)\b", text):
        return Match("time.now", {}, 0.99, "time")
    return None


def _match_system(text: str) -> Match | None:
    if re.search(
        r"\b(cu[aá]nta ram|memoria (libre|disponible|usada)|estado del (sistema|equipo|pc|ordenador)|c[oó]mo est[aá] (el equipo|la m[aá]quina|el sistema)|system info)\b",  # noqa: E501
        text,
    ):
        return Match("system.info", {}, 0.95, "system.info")
    # Ojo con la precisión: "el disco de este equipo" a secas NO es una orden de
    # consultar el disco (podría ser una pregunta abierta). Exigimos intención clara.
    if re.search(
        r"\b(cu[aá]nto (disco|espacio|sitio)|espacio (libre|en disco)|disco (est[aá] )?(casi )?(lleno|al l[ií]mite|al \d{1,3}%)"  # noqa: E501
        r"|cu[aá]nto me queda de disco|libre en el disco)\b",
        text,
    ):
        return Match("system.disk", {}, 0.94, "system.disk")
    if re.search(
        r"\b(procesos|qu[eé] (consume|est[aá] consumiendo)|cpu (alta|al 100)|va lento|lento el (equipo|pc))\b",  # noqa: E501
        text,
    ):
        sort = "cpu" if re.search(r"\bcpu\b", text) else "mem"
        return Match("system.processes", {"sort_by": sort, "top_n": 8}, 0.9, "processes")
    if re.search(r"\b(bater[ií]a|carga restante|cu[aá]nto (queda|dura) de bater)\b", text):
        return Match("system.battery", {}, 0.93, "battery")
    if re.search(r"\b(temperatura|calentando|sobre?calienta)\b", text):
        return Match("system.temperature", {}, 0.92, "temperature")
    if re.search(r"\b(puertos (abiertos|en escucha)|qu[eé] puertos|escuchando)\b", text):
        return Match("system.listeners", {}, 0.9, "listeners")
    if re.search(r"\b(actualizaciones|updates pendientes|paquetes por actualizar)\b", text):
        return Match("system.updates_check", {}, 0.88, "updates")
    if re.search(r"\b(qu[eé] puedes hacer|capacidades|qu[eé] tienes disponible)\b", text):
        return Match("system.capabilities", {}, 0.9, "capabilities")
    return None


#: Palabras que indican que el objeto de "abre X" NO es una aplicación.
#: Un falso positivo aquí abriría lo que no toca; preferimos delegar en el LLM.
_NON_APP_TOKENS = {
    "archivo",
    "carpeta",
    "pdf",
    "documento",
    "imagen",
    "foto",
    "video",
    "web",
    "internet",
    "url",
    "página",
    "pagina",
    "http",
    "https",
    "lo",
    "que",
    "esa",
    "ese",
    "esto",
    "eso",
    "aquello",
    "algo",
    "cualquier",
    "cualquiera",
    "nada",
    "esto:",
    "sitio",
}


def _plausible_app_name(target: str) -> bool:
    """Heurística conservadora: ¿esto parece el nombre de una aplicación?"""
    words = target.split()
    if not words or len(words) > 3 or len(target) > 40:
        return False
    lowered = {w.strip(".,;:!?") for w in words}
    return not (lowered & _NON_APP_TOKENS)


def _match_apps(text: str) -> Match | None:
    m = re.search(
        r"\b(?:abre|abrir|lanza|lanzar|ejecuta|inicia|arranca|open)\s+(?:el |la |los |las |un |una )?(.+)$",
        text,
    )
    if not m:
        return None
    target = m.group(1).strip().rstrip(".!,")
    target = re.sub(r"\b(en segundo plano|ahora|ya|r[aá]pido|por favor)\b", "", target).strip()
    if not target or _extract_url(target) or not _plausible_app_name(target):
        return None
    return Match("apps.launch", {"app": target}, 0.9, "apps.launch")


def _match_windows(text: str) -> Match | None:
    if re.search(r"\b(ventanas abiertas|qu[eé] ventanas|lista (de )?ventanas)\b", text):
        return Match("windows.list", {}, 0.9, "windows.list")
    m = re.search(r"\b(?:ve a|cambia a|enfoca|ponme en)\s+(?:la ventana de\s+)?(.+)$", text)
    if m and re.search(r"\bventana\b", text):
        return Match("windows.focus", {"title": m.group(1).strip()}, 0.8, "windows.focus")
    return None


def _match_volume(text: str) -> Match | None:
    if re.search(r"\b(silencia|quita el sonido|mute)\b", text):
        return Match("media.volume", {"mute": True}, 0.93, "mute")
    if re.search(r"\b(quita el silencio|activa el sonido|unmute)\b", text):
        return Match("media.volume", {"mute": False}, 0.9, "unmute")
    pct = _extract_percent(text)
    if pct is not None and re.search(r"\bvolumen\b", text):
        return Match("media.volume", {"percent": pct}, 0.94, "volume.abs")
    if re.search(r"\b(sube|aumenta|s[uú]bele)\b.*\bvolumen\b|\bvolumen\b.*\b(sube|aumenta)\b", text):
        delta = pct if pct else 10
        return Match("media.volume", {"delta": delta}, 0.88, "volume.up")
    if re.search(r"\b(baja|reduce|b[aá]jale)\b.*\bvolumen\b|\bvolumen\b.*\b(baja|reduce)\b", text):
        delta = -(pct if pct else 10)
        return Match("media.volume", {"delta": delta}, 0.88, "volume.down")
    if re.search(r"\bbrillo\b", text):
        value = pct if pct is not None else 60
        return Match("media.brightness", {"percent": value}, 0.9, "brightness")
    return None


def _match_files(text: str) -> Match | None:
    m = re.search(r"\b(busca|buscarme|encuentra|localiza|d[oó]nde est[aá])\b.*?([\w.*-]+\.\w{1,6})\b", text)
    if m:
        pattern = m.group(2)
        if (
            not pattern.startswith("*")
            and "." in pattern
            and not re.search(r"\b(el|la|un|una)\b\s*\S*\.\w+$", text)
        ):
            pattern = f"*{pattern}"
        path = _extract_path(text) or "."
        return Match("files.search", {"pattern": pattern, "path": path}, 0.87, "files.search")
    m = re.search(r"\b(abre|abrir)\s+(?:el |la |los |las )?(~?/[\w./-]+|[A-Za-z]:\\[\w\\.\\-]+)$", text)
    if m:
        return Match("files.open", {"path": m.group(1)}, 0.88, "files.open")
    m = re.search(
        r"\b(lee|leer|muestra el contenido|resume el archivo)\b.*?(~?/[\w./-]+|\S+\.(?:txt|md|log|py|json|ya?ml|toml|conf|ini))\b",  # noqa: E501
        text,
    )
    if m:
        return Match("files.read", {"path": m.group(1)}, 0.85, "files.read")
    return None


def _match_web(text: str) -> Match | None:
    url = _extract_url(text)
    if url and re.search(r"\b(abre|abrir|ve a|entra en|open)\b", text):
        return Match("web.open", {"target": url}, 0.9, "web.open.url")
    m = re.search(r"\b(?:busca en (?:internet|la web|google)|googlea|search)\s+(.+)$", text)
    if m:
        return Match("web.search", {"query": m.group(1).strip()}, 0.88, "web.search")
    return None


def _match_clipboard(text: str) -> Match | None:
    if re.search(
        r"\b(qu[eé] (hay|tengo) en el (portapapeles|clipboard)|lee el (portapapeles|clipboard)|pegado)\b",
        text,
    ):
        return Match("clipboard.get", {}, 0.9, "clipboard.get")
    return None


def _match_notes(text: str) -> Match | None:
    if re.search(r"\b(lista|muestra|enseña)\s+(mis\s+)?notas\b", text):
        return Match("notes.list", {}, 0.9, "notes.list")
    m = re.search(r"\b(apunta|anota|guarda (esta )?nota|toma nota)\b[:\s]+(.+)$", text, re.DOTALL)
    if m:
        body = m.group(2).strip()
        title = body.split(".")[0][:60]
        return Match("notes.create", {"title": title, "body": body}, 0.86, "notes.create")
    return None


RULES = (
    _match_time,
    _match_system,
    _match_volume,
    _match_apps,
    _match_windows,
    _match_files,
    _match_web,
    _match_clipboard,
    _match_notes,
)


def match(text: str, *, min_confidence: float = 0.86) -> Match | None:
    """Devuelve el Match de mayor confianza que supere el umbral, o None."""
    normalized = _norm(text)
    if not normalized or len(normalized) > 400:
        return None
    best: Match | None = None
    for rule in RULES:
        try:
            candidate = rule(normalized)
        except re.error:  # pragma: no cover - defensivo
            continue
        if candidate and (best is None or candidate.confidence > best.confidence):
            best = candidate
    if best is None or best.confidence < min_confidence:
        return None
    return best


def coverage_report(samples: list[str]) -> dict[str, float]:
    """Utilidad de evaluación: qué porcentaje de un corpus resuelve N0."""
    if not samples:
        return {"total": 0.0, "resolved": 0.0, "rate": 0.0}
    resolved = sum(1 for s in samples if match(s) is not None)
    return {
        "total": float(len(samples)),
        "resolved": float(resolved),
        "rate": round(resolved / len(samples), 3),
    }
