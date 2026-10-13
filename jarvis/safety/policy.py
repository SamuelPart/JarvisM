"""Policy Engine: la única autoridad que decide si una acción se ejecuta.

Ver ADR-0002 y docs/03-seguridad-y-permisos.md. El LLM propone ToolCalls; este
módulo los evalúa de forma determinista. Ninguna información proveniente del
modelo o de datos externos puede bajar un tier ni saltarse una aprobación.

Orden de evaluación (corto-circuito):
    kill switch -> skill conocido/plataforma -> esquema -> denylist -> jaula de rutas
    -> presupuesto -> rate limit -> tier + reglas del usuario
"""

from __future__ import annotations

import enum
import fnmatch
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.config.settings import PolicyConfig, Settings, expand_path


# --------------------------------------------------------------------------- #
# Tiers
# --------------------------------------------------------------------------- #
class RiskTier(str, enum.Enum):
    T0 = "T0"  # lectura local inocua
    T1 = "T1"  # escritura local reversible
    T2 = "T2"  # irreversible local o salida a red -> confirmación
    T3 = "T3"  # privilegiado / destructivo / ofensivo -> confirmación fuerte

    @property
    def rank(self) -> int:
        """Ordinal comparable (0..3).

        Se usa `rank` explícitamente en lugar de sobrecargar `<`: `RiskTier`
        hereda de `str`, así que un `__lt__` con firma propia violaría la
        sustitución de Liskov y mypy lo detecta con razón. Comparar por `rank`
        además deja claro en el código que estamos ordenando por riesgo.
        """
        return int(self.value[1])

    @classmethod
    def parse(cls, value: str | RiskTier) -> RiskTier:
        if isinstance(value, cls):
            return value
        return cls(str(value).strip().upper())


class Decision(str, enum.Enum):
    ALLOW = "allow"
    ALLOW_WITH_LOG = "allow_with_log"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(slots=True)
class PolicyVerdict:
    decision: Decision
    tier: RiskTier
    reasons: list[str] = field(default_factory=list)
    escalated_from: RiskTier | None = None
    requires_typed_confirmation: bool = False

    @property
    def allowed_without_approval(self) -> bool:
        return self.decision in (Decision.ALLOW, Decision.ALLOW_WITH_LOG)

    def explain(self) -> str:
        base = f"{self.decision.value.upper()} (tier {self.tier.value})"
        if self.escalated_from and self.escalated_from != self.tier:
            base += f" [elevado desde {self.escalated_from.value}]"
        if self.reasons:
            base += ": " + "; ".join(self.reasons)
        return base


# --------------------------------------------------------------------------- #
# Denylist: patrones que jamás se ejecutan, ni con `--yes`
# --------------------------------------------------------------------------- #
HARD_DENY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rm -rf sobre raíz/home", re.compile(r"\brm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(?:/|~|\$HOME)(?:\s|$)")),
    ("dd sobre dispositivo", re.compile(r"\bdd\b[^\n]*\bof=/dev/")),
    ("mkfs sobre dispositivo", re.compile(r"\bmkfs(?:\.\w+)?\s+/dev/")),
    ("fork bomb", re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:")),
    ("pipe remoto a shell", re.compile(r"\b(?:curl|wget|fetch)\b[^\n]*\|\s*(?:ba|z|k|fi)?sh\b")),
    ("chmod 777 recursivo en raíz", re.compile(r"\bchmod\s+(?:-R\s+)?(?:a\+rwx|0?777)\s+/(?:\s|$)")),
    ("redirección a dispositivo de bloque", re.compile(r">\s*/dev/(?:sd[a-z]|nvme\d|hd[a-z]|disk\d)")),
    ("wipe/shred de dispositivo", re.compile(r"\b(?:wipefs|shred)\s+[^\n]*/dev/")),
    ("borrado de la tabla de particiones", re.compile(r"\b(?:fdisk|parted|gdisk)\b[^\n]*/dev/")),
    ("vaciado de logs del sistema", re.compile(r">\s*/var/log/")),
    ("desactivar el firewall", re.compile(r"\b(?:ufw\s+disable|iptables\s+-F|firewall-cmd\s+--panic-on)")),
    ("sobrescritura de arranque", re.compile(r"\b(?:grub-install|update-grub)\b[^\n]*--no-preserve-root")),
    ("chattr inmutable en raíz", re.compile(r"\bchattr\s+\+i\s+/")),
    ("exfiltración de claves privadas", re.compile(r"\b(?:cat|less|tail|base64)\s+[^\n]*\.ssh/id_[a-z]+")),
    ("lectura de shadow", re.compile(r"/etc/(?:shadow|gshadow)\b")),
)

SOFT_WARN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("uso de sudo/su", re.compile(r"\b(?:sudo|su|doas|pkexec)\b")),
    ("apagado o reinicio", re.compile(r"\b(?:shutdown|reboot|halt|poweroff|init\s+[06])\b")),
    ("eliminación recursiva", re.compile(r"\brm\s+-[a-zA-Z]*r")),
    (
        "instalación de paquetes",
        re.compile(
            r"\b(?:apt|apt-get|dnf|yum|pacman|zypper|brew|winget)\s+(?:install|remove|purge|update|upgrade)\b"
        ),
    ),
    ("modificación de permisos", re.compile(r"\b(?:chmod|chown)\b")),
    ("salida a red", re.compile(r"\b(?:curl|wget|nc|netcat|ssh|scp|rsync|nmap)\b")),
    ("docker/contenedores", re.compile(r"\bdocker\b[^\n]*(?:rm|rmi|prune|system\s+prune)")),
    ("git que publica", re.compile(r"\bgit\s+(?:push|reset\s+--hard|clean\s+-[a-z]*f)")),
    ("kill de procesos", re.compile(r"\bkill(?:all)?\b")),
)


@dataclass(slots=True)
class PatternHit:
    label: str
    hard: bool


def scan_command(command: str) -> list[PatternHit]:
    """Busca patrones peligrosos en un comando. Puro: testeable sin SO."""
    hits = [PatternHit(label, True) for label, rx in HARD_DENY_PATTERNS if rx.search(command)]
    hits += [PatternHit(label, False) for label, rx in SOFT_WARN_PATTERNS if rx.search(command)]
    return hits


# --------------------------------------------------------------------------- #
# Secretos: redacción antes de enviar a un proveedor o de persistir
# --------------------------------------------------------------------------- #
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("clave tipo OpenAI", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("clave AWS access id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("bloque PEM", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    (
        "assignment de password",
        re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api_?key)\b\s*[:=]\s*\S{6,}"),
    ),
)


def redact(text: str) -> tuple[str, int]:
    """Enmascara secretos. Devuelve (texto limpio, nº de sustituciones)."""
    count = 0
    for label, rx in SECRET_PATTERNS:
        text, n = rx.subn(f"[REDACTADO:{label}]", text)
        count += n
    return text, count


# --------------------------------------------------------------------------- #
# Budget guard
# --------------------------------------------------------------------------- #
class BudgetGuard:
    """Contabilidad diaria de tokens/coste y horaria de acciones."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._day = time.strftime("%Y-%m-%d")
        self.tokens_today = 0
        self.usd_today = 0.0
        self.calls_today = 0
        self._action_times: deque[float] = deque(maxlen=1000)
        self._warned = False

    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day = today
            self.tokens_today = 0
            self.usd_today = 0.0
            self.calls_today = 0
            self._warned = False

    def check(self) -> tuple[bool, str]:
        self._roll_day()
        budget = self.settings.budget
        if not budget.hard_stop:
            return True, ""
        if budget.usd_per_day > 0 and self.usd_today >= budget.usd_per_day:
            return False, f"presupuesto diario agotado ({self.usd_today:.4f}/{budget.usd_per_day} USD)"
        if budget.tokens_per_day > 0 and self.tokens_today >= budget.tokens_per_day:
            return False, f"tope de tokens diario alcanzado ({self.tokens_today}/{budget.tokens_per_day})"
        if self._actions_last_hour() >= budget.actions_per_hour:
            return False, f"límite de {budget.actions_per_hour} acciones/hora alcanzado"
        return True, ""

    def at_warning_threshold(self) -> bool:
        self._roll_day()
        budget = self.settings.budget
        if budget.usd_per_day <= 0:
            return False
        pct = (self.usd_today / budget.usd_per_day) * 100
        if pct >= budget.warn_at_pct and not self._warned:
            self._warned = True
            return True
        return False

    def _actions_last_hour(self) -> int:
        cutoff = time.time() - 3600
        while self._action_times and self._action_times[0] < cutoff:
            self._action_times.popleft()
        return len(self._action_times)

    def record_action(self) -> None:
        self._action_times.append(time.time())

    def record_llm(self, tokens: int, usd: float) -> None:
        self._roll_day()
        self.tokens_today += max(0, tokens)
        self.usd_today += max(0.0, usd)
        self.calls_today += 1

    def snapshot(self) -> dict[str, Any]:
        self._roll_day()
        budget = self.settings.budget
        pct = (self.usd_today / budget.usd_per_day * 100) if budget.usd_per_day > 0 else 0.0
        return {
            "day": self._day,
            "usd_today": round(self.usd_today, 5),
            "usd_limit": budget.usd_per_day,
            "usd_pct": round(pct, 1),
            "tokens_today": self.tokens_today,
            "llm_calls_today": self.calls_today,
            "actions_last_hour": self._actions_last_hour(),
            "actions_limit_hour": budget.actions_per_hour,
        }


# --------------------------------------------------------------------------- #
# Policy Engine
# --------------------------------------------------------------------------- #
class PolicyEngine:
    def __init__(self, settings: Settings, *, kill_switch: bool = False) -> None:
        self.settings = settings
        self.policy: PolicyConfig = settings.policy
        self.budget = BudgetGuard(settings)
        self.kill_switch = kill_switch
        self._auto_max = RiskTier.parse(self.policy.auto_approve_max_tier)
        #: Se reconstruyen si la configuración cambia en caliente (p. ej. un perfil
        #: o un `reload`), sin pagar el coste de expandir rutas en cada evaluación.
        self._paths_signature: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        self._jail_roots: list[Path] = []
        self._excluded: list[Path] = []
        self._refresh_paths()
        self._auto_max = RiskTier.parse(self.policy.auto_approve_max_tier)

    def _refresh_paths(self) -> None:
        """Reexpande jaula y exclusiones solo si la configuración cambió."""
        signature = (tuple(self.policy.jail_roots), tuple(self.settings.privacy.exclude_paths))
        if signature == self._paths_signature:
            return
        self._paths_signature = signature
        self._jail_roots = [expand_path(p) for p in self.policy.jail_roots]
        self._excluded = [expand_path(p) for p in self.settings.privacy.exclude_paths]
        self._restricted = {b.lower() for b in self.policy.restricted_binaries}
        self._allowlisted_shell = {b.lower() for b in self.policy.shell_allowlist}

    # -- utilidades ------------------------------------------------------- #
    def set_kill_switch(self, value: bool) -> None:
        self.kill_switch = value

    def supports_platform(self, platforms: set[str] | None) -> bool:
        if not platforms:
            return True
        import sys

        current = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
        return current in {p.lower() for p in platforms}

    def is_excluded_path(self, path: str | Path) -> bool:
        self._refresh_paths()
        try:
            resolved = expand_path(str(path))
        except OSError:
            return True  # ruta rara = tratar como sensible
        return any(resolved == ex or ex in resolved.parents for ex in self._excluded)

    def is_inside_jail(self, path: str | Path) -> bool:
        self._refresh_paths()
        if not self._jail_roots:
            return False
        try:
            resolved = expand_path(str(path))
        except OSError:
            return False
        return any(resolved == root or root in resolved.parents for root in self._jail_roots)

    # -- evaluación ------------------------------------------------------- #
    def evaluate(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        base_tier: RiskTier,
        *,
        skill_exists: bool = True,
        platforms: set[str] | None = None,
        undoable: bool = False,
        known_skills: set[str] | None = None,
    ) -> PolicyVerdict:
        reasons: list[str] = []
        tier = base_tier

        # 1. Kill switch: nada se ejecuta.
        if self.kill_switch:
            return PolicyVerdict(Decision.DENY, tier, ["kill switch activo"])

        # 2. Skill registrado y disponible en esta plataforma.
        if not skill_exists:
            return PolicyVerdict(Decision.DENY, tier, [f"skill desconocido: {skill_name}"])
        if known_skills is not None and skill_name not in known_skills:
            return PolicyVerdict(Decision.DENY, tier, [f"skill no registrado: {skill_name}"])
        if not self.supports_platform(platforms):
            return PolicyVerdict(Decision.DENY, tier, ["skill no disponible en esta plataforma"])

        # 3. Presupuesto.
        ok, why = self.budget.check()
        if not ok:
            return PolicyVerdict(Decision.DENY, tier, [why])

        # 4. Rutas excluidas: denegación absoluta, sin escalada posible.
        for value in _iter_string_values(arguments):
            if _looks_like_path(value) and self.is_excluded_path(value):
                return PolicyVerdict(Decision.DENY, tier, [f"ruta protegida por privacidad: {value}"])

        # 5. Denylist dura + elevación por patrones blandos.
        #    La denylist dura se comprueba sobre TODOS los argumentos: un patrón
        #    peligroso escondido en cualquier campo es un patrón peligroso.
        #    Los patrones "blandos" solo se miran en el comando real, para no
        #    elevar el tier por una palabra inocente en una descripción.
        command = str(arguments.get("command", "")) if isinstance(arguments, dict) else ""
        all_values = " ".join(_iter_string_values(arguments))
        hard_hits = [h for h in (scan_command(all_values) if all_values else []) if h.hard]
        soft_hits = [h for h in (scan_command(command) if command else []) if not h.hard]
        if hard_hits:
            return PolicyVerdict(
                Decision.DENY,
                RiskTier.T3,
                ["patrón prohibido: " + ", ".join(h.label for h in hard_hits)],
            )
        if soft_hits:
            reasons.extend(f"patrón sensible: {h.label}" for h in soft_hits)
            privileged_labels = {"uso de sudo/su", "apagado o reinicio"}
            if any(h.label in privileged_labels for h in soft_hits):
                tier = max(tier, RiskTier.T3, key=lambda t: t.rank)
            else:
                tier = max(tier, RiskTier.T2, key=lambda t: t.rank)

        # 6. Binarios restringidos (muy relevante en Kali).
        binary = _first_token(command) if command else ""
        if binary and binary.lower() in self._restricted:
            reasons.append(f"binario restringido: {binary}")
            tier = RiskTier.T3
        elif (
            binary
            and command
            and self.policy.shell_allowlist
            and binary.lower() not in self._allowlisted_shell
        ):
            reasons.append(f"binario fuera de la allowlist: {binary}")
            tier = max(tier, RiskTier.T2, key=lambda t: t.rank)

        # 7. Jaula de rutas: escribir fuera eleva el tier.
        escalated_from = None
        for key, value in (arguments or {}).items():
            if not _looks_like_path(str(value)):
                continue
            writes = key in {"path", "target", "dest", "destination", "to", "output", "file", "filepath"}
            if writes and not self.is_inside_jail(value):
                if tier.rank < RiskTier.T2.rank:
                    escalated_from = tier
                    tier = RiskTier.T2
                reasons.append(f"escritura fuera de la jaula de rutas ({key}={value})")

        # 8. Decisión final según tier y preferencia del usuario.
        if tier.rank <= self._auto_max.rank:
            decision = Decision.ALLOW_WITH_LOG if (tier == RiskTier.T1 or not undoable) else Decision.ALLOW
        else:
            decision = Decision.REQUIRE_APPROVAL
            reasons.append(
                f"tier {tier.value} requiere confirmación (auto-approve máximo {self._auto_max.value})"
            )

        return PolicyVerdict(
            decision=decision,
            tier=tier,
            reasons=reasons,
            escalated_from=escalated_from,
            requires_typed_confirmation=(
                tier == RiskTier.T3 and self.policy.require_typed_confirmation_for_t3
            ),
        )

    # -- rate limiting ---------------------------------------------------- #
    def check_rate(
        self, skill_name: str, recent: list[float], *, window_s: int = 60, max_calls: int = 5
    ) -> bool:
        """True si el skill está dentro de su ventana de rate limit."""
        cutoff = time.time() - window_s
        calls = [t for t in recent if t >= cutoff]
        return len(calls) < max_calls

    # -- patrones de archivo --------------------------------------------- #
    def matches_excluded_glob(self, name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatch(name, p) for p in patterns)


# --------------------------------------------------------------------------- #
# Helpers puros
# --------------------------------------------------------------------------- #
def _iter_string_values(obj: Any) -> list[str]:
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                walk(v)

    walk(obj)
    return out


def _looks_like_path(value: str) -> bool:
    if not value or len(value) > 4096:
        return False
    v = value.strip()
    if " " in v and not (v.startswith(("~", "/")) or ":" in v):
        return False
    return v.startswith(("/", "~", "./", "../")) or bool(re.match(r"^[A-Za-z]:[\\/]", v))


def _first_token(command: str) -> str:
    """Extrae el binario invocado, saltando asignaciones de entorno y sudo."""
    tokens = command.strip().split()
    skip_env = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if skip_env.match(tok) or tok in {"sudo", "nohup", "time", "env", "command"}:
            i += 1
            continue
        return Path(tok).name
    return ""
