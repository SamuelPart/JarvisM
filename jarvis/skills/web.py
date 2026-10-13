"""Skills de red: abrir URLs y buscar. Todo lo que sale a internet es T2."""

from __future__ import annotations

import re
import sys
from urllib.parse import quote_plus, urlparse

from jarvis.platforms._proc import spawn_detached
from jarvis.safety.policy import RiskTier
from jarvis.skills.base import Skill, SkillResult

# Solo http/https/file. Nada de javascript:, data:, file:// a rutas sensibles.
ALLOWED_SCHEMES = {"http", "https"}
URL_RX = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def normalize_url(value: str) -> str:
    """Convierte 'github.com' o 'python docs' en una URL utilizable."""
    text = value.strip()
    if not text:
        return ""
    if URL_RX.match(text):
        return text
    parsed = urlparse(text)
    if parsed.scheme in ALLOWED_SCHEMES and parsed.netloc:
        return text
    if parsed.scheme in {"javascript", "data", "vbscript", "file"}:
        return ""
    if re.match(r"^[\w.-]+\.[a-z]{2,}(:\d+)?(/\S*)?$", text, re.IGNORECASE):
        return f"https://{text}"
    return f"https://duckduckgo.com/?q={quote_plus(text)}"


def open_in_browser(url: str) -> tuple[bool, str]:
    """Abre con el navegador predeterminado del sistema."""
    if sys.platform == "darwin":
        pid, err = spawn_detached(["open", url])
    elif sys.platform.startswith("win"):
        pid, err = spawn_detached(["cmd", "/c", "start", "", url])
    else:
        opener = "xdg-open"
        pid, err = spawn_detached([opener, url])
        if pid is None:
            for fallback in ("gio", "sensible-browser", "firefox", "chromium"):
                cmd = [fallback, "open", url] if fallback == "gio" else [fallback, url]
                pid, err = spawn_detached(cmd)
                if pid is not None:
                    break
    if pid is None:
        return False, err or "no se encontró navegador"
    return True, url


class OpenUrlSkill(Skill):
    name = "web.open"
    description = (
        "Abre una URL o una búsqueda web en el navegador predeterminado. Acepta una URL completa "
        "('https://...'), un dominio ('github.com') o una consulta de búsqueda ('python asyncio "
        "tutorial'). Úsalo para 'abre X', 'busca en internet Y'. Esta acción sale a internet, "
        "así que normalmente requiere confirmación."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "minLength": 2,
                "description": "URL, dominio o texto a buscar.",
            }
        },
        "required": ["target"],
        "additionalProperties": False,
    }
    tier = RiskTier.T2  # salida a red
    requires_network = True

    def execute(self, target: str) -> SkillResult:
        url = normalize_url(target)
        if not url:
            return SkillResult.failure(
                f"No puedo abrir '{target}': solo se permiten URLs http/https o búsquedas."
            )
        ok, detail = open_in_browser(url)
        if not ok:
            return SkillResult.failure(f"No pude abrir el navegador ({detail}). URL: {url}")
        return SkillResult.success(f"Abriendo {url}", data={"url": url})


class WebSearchSkill(Skill):
    name = "web.search"
    description = (
        "Abre una página de resultados de búsqueda con la consulta dada. Es un atajo de web.open "
        "para cuando el usuario quiere investigar algo ('busca cómo se hace X')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 2},
            "engine": {
                "type": "string",
                "enum": ["duckduckgo", "google", "bing", "startpage"],
                "default": "duckduckgo",
                "description": "Motor de búsqueda. DuckDuckGo por defecto (más privado).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    tier = RiskTier.T2
    requires_network = True

    ENGINES = {
        "duckduckgo": "https://duckduckgo.com/?q={}",
        "google": "https://www.google.com/search?q={}",
        "bing": "https://www.bing.com/search?q={}",
        "startpage": "https://www.startpage.com/sp/search?query={}",
    }

    def execute(self, query: str, engine: str = "duckduckgo") -> SkillResult:
        template = self.ENGINES.get(engine, self.ENGINES["duckduckgo"])
        url = template.format(quote_plus(query))
        ok, detail = open_in_browser(url)
        if not ok:
            return SkillResult.failure(f"No pude abrir el navegador ({detail}). URL: {url}")
        return SkillResult.success(f"Buscando '{query}' en {engine}.", data={"url": url, "engine": engine})
