"""Presentación en terminal (Rich) y aprobación interactiva.

Aquí vive el `ApprovalHandler` de la CLI: es el componente que convierte una
decisión `REQUIRE_APPROVAL` del policy engine en una pregunta comprensible
para el usuario, con el nivel de riesgo visible y timeout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from jarvis.core.orchestrator import ActionRecord, TurnResult
from jarvis.safety.policy import RiskTier
from jarvis.skills.base import ApprovalHandler

console = Console()
error_console = Console(stderr=True)

TIER_STYLE = {
    "T0": "green",
    "T1": "cyan",
    "T2": "yellow",
    "T3": "bold red",
}


def tier_badge(tier: str | RiskTier) -> Text:
    value = tier.value if isinstance(tier, RiskTier) else str(tier)
    return Text(f"[{value}]", style=TIER_STYLE.get(value, "white"))


class ConsoleApproval(ApprovalHandler):
    """Pide confirmación por teclado. Nunca aprueba por defecto."""

    def __init__(self, *, assume_no: bool = False, quiet: bool = False) -> None:
        self.assume_no = assume_no
        self.quiet = quiet

    def request(
        self,
        *,
        skill: str,
        arguments: dict[str, Any],
        tier: RiskTier,
        reasons: list[str],
        typed_confirmation: bool,
        timeout_s: int,
    ) -> bool:
        if self.assume_no:
            return False
        args = json.dumps(arguments, ensure_ascii=False, indent=2)[:1200]
        body = Text()
        body.append("Habilidad: ", style="bold")
        body.append(f"{skill}\n")
        body.append("Riesgo: ", style="bold")
        body.append_text(tier_badge(tier))
        body.append(f"  ({_tier_meaning(tier)})\n")
        if reasons:
            body.append("Motivos: ", style="bold")
            body.append("; ".join(reasons[:4]) + "\n")
        body.append("Argumentos:\n", style="bold")
        body.append(args)
        if tier is RiskTier.T3:
            body.append(
                "\n⚠ Acción de máximo riesgo. Revisa el comando EXACTO antes de aceptar.",
                style="bold red",
            )
        console.print(
            Panel(
                body, title="Jarvis necesita tu aprobación", border_style=TIER_STYLE.get(tier.value, "yellow")
            )
        )

        if typed_confirmation:
            console.print(f"Escribe la palabra [bold]APRUEBO[/bold] para continuar (timeout {timeout_s} s).")
            answer = _read_line(timeout_s)
            return answer.strip().upper() == "APRUEBO"
        console.print(f"[s]í / [n]o (timeout {timeout_s} s, por defecto NO): ")
        answer = _read_line(timeout_s).strip().lower()
        return answer in {"s", "si", "sí", "y", "yes", "ok", "dale"}


def _read_line(timeout_s: int) -> str:
    """Lee una línea con timeout. Si expira o no hay TTY, devuelve '' (= NO)."""
    if not sys.stdin or not sys.stdin.isatty():
        # Sin TTY (pipe, systemd, API) no se puede aprobar de forma interactiva:
        # por seguridad, se deniega. El modo no interactivo usa `--yes` explícito.
        return ""
    if sys.platform == "win32" or timeout_s <= 0:
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return ""
    import select

    console.print("", end="")
    sys.stdout.flush()
    ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not ready:
        error_console.print("[yellow]Tiempo de espera agotado: acción NO aprobada.[/yellow]")
        return ""
    try:
        return sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return ""


def _tier_meaning(tier: RiskTier) -> str:
    return {
        RiskTier.T0: "lectura inocua",
        RiskTier.T1: "escritura reversible",
        RiskTier.T2: "irreversible o salida a red",
        RiskTier.T3: "privilegiado o destructivo",
    }[tier]


# --------------------------------------------------------------------------- #
# Render de resultados
# --------------------------------------------------------------------------- #
def print_turn(result: TurnResult, *, show_meta: bool = True, markdown: bool = False) -> None:
    if markdown and result.reply:
        console.print(Markdown(result.reply))
    elif result.reply:
        console.print(result.reply)
    if result.actions and show_meta:
        table = Table(show_header=True, header_style="bold dim", box=None, pad_edge=False)
        table.add_column("skill")
        table.add_column("tier")
        table.add_column("decisión")
        table.add_column("resultado")
        for action in result.actions:
            icon = "✅" if action.ok else ("⛔" if action.decision == "deny" else "⚠️")
            table.add_row(
                action.skill,
                str(tier_badge(action.tier)),
                action.decision,
                f"{icon} {_first_line(action.message)[:100]}",
            )
        console.print(table)
    if show_meta and (result.summary_line()):
        console.print(f"[dim]{result.summary_line()}[/dim]")
    for suggestion in result.suggestions:
        console.print(f"[magenta]💡 {suggestion}[/magenta]")
    if result.error and not result.actions:
        error_console.print(f"[dim]diagnóstico: {result.error}[/dim]")


def print_actions(actions: list[ActionRecord]) -> None:
    if not actions:
        return
    for action in actions:
        icon = "✅" if action.ok else ("⛔" if action.decision == "deny" else "⚠️")
        console.print(f"{icon} [{action.tier}] {action.skill}: {_first_line(action.message)}")


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if text and text.strip() else ""


def print_json(data: Any) -> None:
    console.print_json(json.dumps(data, ensure_ascii=False, default=str))
