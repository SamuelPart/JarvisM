"""CLI de JarvisM (Typer + Rich).

Pensada para que cada comando sea útil por sí solo y para que `doctor` explique
exactamente qué falta en la máquina del usuario. Ver docs/04-guia-kali-linux.md.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from jarvis import __version__
from jarvis.config.settings import get_settings, reload_settings
from jarvis.core.orchestrator import Orchestrator
from jarvis.skills.base import AutoApprove
from jarvis.ui.tui import ConsoleApproval, console, print_json, print_turn, tier_badge

app = typer.Typer(
    name="jarvis",
    help="JarvisM · asistente de voz y agente de sistema multiplataforma con gobernanza de acciones.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
err_console = Console(stderr=True)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _configure_logging(verbose: bool = False) -> None:
    settings = get_settings()
    level = logging.DEBUG if verbose else getattr(logging, settings.logging.level, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if settings.logging.file_enabled:
        try:
            settings.ensure_dirs()
            from logging.handlers import RotatingFileHandler

            handlers.append(
                RotatingFileHandler(
                    settings.log_file,
                    maxBytes=settings.logging.max_bytes,
                    backupCount=settings.logging.backups,
                    encoding="utf-8",
                )
            )
        except OSError:
            pass
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", handlers=handlers, force=True
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _plural(count: int, singular: str, plural: str) -> str:
    """`1 habilidad registrada` / `27 habilidades registradas`.

    Detalle pequeño, pero un asistente que dice "1 habilidades" pierde credibilidad
    en la primera frase que pronuncia.
    """
    return f"{count} {singular if count == 1 else plural}"


def _parse_arg(raw: str) -> tuple[str, Any]:
    """`top_n=5` -> ('top_n', 5). Acepta JSON para listas y objetos."""
    if "=" not in raw:
        raise typer.BadParameter(f"argumento sin '=': {raw!r} (usa clave=valor)")
    key, value = raw.split("=", 1)
    key = key.strip().lstrip("-")
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


def _build_orchestrator(
    *,
    yes: bool = False,
    offline: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Orchestrator:
    settings = get_settings()
    if provider:
        settings.router.default_chain = [
            provider,
            *[p for p in settings.router.default_chain if p != provider],
        ]
    if model:
        settings.router.model_general = model
    approval: Any = ConsoleApproval() if not yes else AutoApprove()
    if yes:
        from jarvis.core.orchestrator import _YesApproval

        approval = _YesApproval()
        err_console.print(
            "[yellow]--yes activo: se aprobarán automáticamente las acciones "
            "que requieran confirmación. Úsalo solo con comandos que ya revisaste.[/yellow]"
        )
    return Orchestrator(settings, approval=approval, offline=offline)


# --------------------------------------------------------------------------- #
# version / doctor
# --------------------------------------------------------------------------- #
@app.command()
def version() -> None:
    """Muestra la versión y el modo de operación."""
    settings = get_settings()
    mode = "OFFLINE" if settings.effective_offline() else "online"
    console.print(f"JarvisM [bold]{__version__}[/bold] · modo {mode} · Python {sys.version.split()[0]}")


@app.command()
def doctor(
    providers: bool = typer.Option(False, "--providers", help="Hace un health check real contra cada API."),
    as_json: bool = typer.Option(False, "--json", help="Salida en JSON para scripts."),
    security: bool = typer.Option(False, "--security", help="Solo las comprobaciones de seguridad."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Logs de depuración."),
) -> None:
    """Diagnóstico completo del entorno: qué funciona, qué falta y cómo arreglarlo."""
    _configure_logging(verbose)
    from jarvis.diagnostics import LEVEL_FAIL, LEVEL_OK, LEVEL_WARN, run_diagnostics
    from jarvis.platforms.factory import get_adapter

    settings = get_settings()
    report = run_diagnostics(settings, get_adapter(), providers=providers)
    if security:
        report.checks = [
            c
            for c in report.checks
            if any(
                k in c.name
                for k in (
                    "privilegios",
                    "permisos",
                    ".env",
                    "audit",
                    "presupuesto",
                    "auto-approve",
                    "capacidad:not_root",
                )
            )
        ]
    if as_json:
        print_json(report.to_dict())
        raise typer.Exit(code=0 if report.ok else 1)

    icons = {LEVEL_OK: "[green]✔[/green]", LEVEL_WARN: "[yellow]▲[/yellow]", LEVEL_FAIL: "[red]✘[/red]"}
    table = Table(title=f"JarvisM {__version__} · diagnóstico en {report.platform}", show_lines=False)
    table.add_column("", width=3)
    table.add_column("comprobación", style="bold")
    table.add_column("detalle", overflow="fold")
    table.add_column("qué hacer", style="dim", overflow="fold", max_width=48)
    for check in report.checks:
        table.add_row(icons[check.level], check.name, check.detail, check.hint)
    console.print(table)
    summary = (
        f"[green]{sum(1 for c in report.checks if c.level == LEVEL_OK)} ok[/green] · "
        f"[yellow]{report.warnings} avisos[/yellow] · [red]{report.failures} fallos[/red]"
    )
    console.print(summary)
    if not report.ok:
        console.print("[red]Hay fallos que impiden el funcionamiento correcto.[/red]")
    raise typer.Exit(code=0 if report.ok else 1)


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
@app.command()
def chat(
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="gemini | openai | anthropic | ollama | echo"
    ),
    model: str | None = typer.Option(None, "--model", "-m", help="Sobrescribe el modelo del perfil general."),
    profile: str | None = typer.Option(
        None, "--profile", help="cheap | general | reasoner | vision | offline"
    ),
    offline: bool = typer.Option(False, "--offline", help="Fuerza modo sin red (Ollama + matcher local)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Aprueba automáticamente (¡peligroso!)."),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Renderiza Markdown en la respuesta."
    ),
    once: str | None = typer.Option(None, "--once", "-o", help="Procesa una sola frase y termina."),
    show_meta: bool = typer.Option(True, "--meta/--no-meta", help="Muestra proveedor, coste y latencia."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Conversación interactiva con Jarvis (texto). La voz llega en la Fase 3."""
    _configure_logging(verbose)
    orch = _build_orchestrator(yes=yes, offline=offline or None, provider=provider, model=model)
    identity = orch.settings.identity

    if once:
        result = orch.handle(once, profile=profile)
        print_turn(result, show_meta=show_meta, markdown=markdown)
        orch.close()
        raise typer.Exit(code=0 if result.ok or result.actions else 1)

    console.print(
        f"[bold cyan]{identity.name}[/bold cyan] listo "
        f"({identity.language} · tono {identity.tone} · modo "
        f"{'OFFLINE' if orch.offline else 'online'}). Escribe [bold]/help[/bold] o Ctrl+D para salir."
    )
    try:
        while True:
            try:
                text = console.input("[bold green]tú ▸[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Hasta la próxima.[/dim]")
                break
            if not text:
                continue
            if text.startswith("/"):
                if _handle_slash(text, orch):
                    continue
                break
            started = time.perf_counter()
            with console.status("[cyan]pensando…[/cyan]", spinner=orch.settings.ui.spinner):
                result = orch.handle(text, profile=profile)
            result.latency_ms = result.latency_ms or (time.perf_counter() - started) * 1000
            console.print(f"[bold magenta]{identity.name} ▸[/bold magenta]")
            print_turn(result, show_meta=show_meta, markdown=markdown)
    finally:
        orch.close()


def _handle_slash(command: str, orch: Orchestrator) -> bool:
    """Comandos internos del chat. True = seguir en el bucle."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in {"/exit", "/quit", "/q", "/salir"}:
        return False
    if cmd in {"/help", "/ayuda"}:
        console.print(
            "/help          esta ayuda\n"
            "/skills        catálogo de habilidades con su nivel de riesgo\n"
            "/run <skill>   ejecuta un skill directamente (k=v por argumento)\n"
            "/cost          gasto y tokens de hoy\n"
            "/undo          deshace la última acción reversible\n"
            "/audit         últimas 10 entradas del registro de auditoría\n"
            "/context       contexto del sistema que se está enviando al modelo\n"
            "/kill          activa el kill switch (bloquea toda ejecución)\n"
            "/unkill        desactiva el kill switch\n"
            "/exit          salir"
        )
        return True
    if cmd == "/skills":
        _print_skills_table(orch)
        return True
    if cmd == "/run":
        tokens = arg.split()
        if not tokens:
            console.print("[red]uso: /run nombre.skill clave=valor[/red]")
            return True
        args = dict(_parse_arg(t) for t in tokens[1:])
        record = orch.run_skill(tokens[0], args)
        icon = "✅" if record.ok else "⛔"
        console.print(f"{icon} [{record.tier}] {record.skill}: {record.message}")
        return True
    if cmd == "/cost":
        _print_cost(orch)
        return True
    if cmd == "/undo":
        console.print(orch.undo_last())
        return True
    if cmd == "/audit":
        for entry in orch.audit.tail(10):
            console.print(
                f"[dim]{time.strftime('%H:%M:%S', time.localtime(entry.ts))}[/dim] "
                f"{entry.kind} {entry.skill or ''} {entry.decision or ''}"
            )
        return True
    if cmd == "/context":
        console.print(orch.system_prompt())
        return True
    if cmd == "/kill":
        orch.policy.set_kill_switch(True)
        console.print("[bold red]Kill switch ACTIVO: no se ejecutará ninguna acción.[/bold red]")
        return True
    if cmd == "/unkill":
        orch.policy.set_kill_switch(False)
        console.print("[green]Kill switch desactivado.[/green]")
        return True
    console.print(f"[yellow]comando desconocido: {cmd} (prueba /help)[/yellow]")
    return True


def _print_skills_table(orch: Orchestrator) -> None:
    available = len(orch.registry.usable(offline=orch.offline))
    table = Table(title=f"Habilidades disponibles ({available})")
    table.add_column("skill", style="bold")
    table.add_column("riesgo", justify="center")
    table.add_column("deshace")
    table.add_column("red")
    table.add_column("descripción", overflow="fold", max_width=70)
    for skill in orch.registry.all():
        available, _ = skill.available_here()
        style = "" if available else "dim strike"
        table.add_row(
            _text(skill.name, style),
            str(tier_badge(skill.tier.value)),
            "sí" if skill.undoable else "—",
            "sí" if skill.requires_network else "—",
            _text(skill.description.split(". ")[0], style),
        )
    console.print(table)


def _text(text: str, style: str = "") -> Any:
    from rich.text import Text

    return Text(text, style=style)


def _print_cost(orch: Orchestrator) -> None:
    snapshot = orch.budget.snapshot()
    table = Table(title="Presupuesto y consumo")
    for key, value in snapshot.items():
        table.add_row(key, str(value))
    table.add_row("sesión (USD)", f"{orch.memory.cost_usd:.5f}")
    table.add_row("turnos", str(orch.turn_count))
    for provider, stats in orch.router.stats.items():
        table.add_row(
            f"proveedor {provider}",
            f"{stats['calls']} llamadas · {stats['tokens']} tokens · {stats['cost_usd']:.5f} USD",
        )
    console.print(table)


# --------------------------------------------------------------------------- #
# skills / run / policy
# --------------------------------------------------------------------------- #
@app.command()
def skills(
    as_json: bool = typer.Option(False, "--json"),
    tier: str | None = typer.Option(None, "--tier", help="Filtra por nivel de riesgo (T0..T3)."),
) -> None:
    """Lista el catálogo de habilidades con su nivel de riesgo y plataforma."""
    _configure_logging()
    orch = Orchestrator(get_settings())
    rows = orch.registry.describe_table()
    if tier:
        rows = [r for r in rows if r["tier"] == tier.upper()]
    if as_json:
        print_json(rows)
        orch.close()
        return
    table = Table(title=_plural(len(rows), "habilidad registrada", "habilidades registradas"))
    table.add_column("skill", style="bold")
    table.add_column("riesgo", justify="center")
    table.add_column("plataformas")
    table.add_column("deshace")
    table.add_column("red")
    table.add_column("descripción", overflow="fold", max_width=64)
    for row in rows:
        table.add_row(
            row["name"],
            str(tier_badge(row["tier"])),
            row["platforms"],
            row["undoable"],
            row["network"],
            row["description"],
        )
    console.print(table)
    console.print(
        "[dim]T0 lectura inocua · T1 escritura reversible · T2 irreversible/red · "
        "T3 privilegiado o destructivo[/dim]"
    )
    orch.close()


@app.command()
def run(
    skill: str = typer.Argument(..., help="Nombre del skill, p. ej. system.disk"),
    args: list[str] = typer.Argument(None, help="Argumentos clave=valor (acepta JSON)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Aprueba automáticamente."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Muestra la decisión de política sin ejecutar."),
    as_json: bool = typer.Option(False, "--json"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Ejecuta un skill directamente (útil para probar y para scripts)."""
    _configure_logging()
    orch = Orchestrator(get_settings(), approval=ConsoleApproval(), offline=offline or None)
    arguments = dict(_parse_arg(a) for a in (args or []))

    if dry_run:
        target = orch.registry.get(skill)
        if target is None:
            console.print(f"[red]skill desconocido: {skill}[/red]")
            raise typer.Exit(1)
        ok, schema_error = orch.registry.validate_arguments(skill, arguments)
        verdict = orch.policy.evaluate(
            skill,
            arguments,
            target.tier,
            skill_exists=True,
            platforms=set(target.platforms),
            undoable=target.undoable,
            known_skills=orch.registry.names(),
        )
        payload = {
            "skill": skill,
            "arguments": arguments,
            "base_tier": target.tier.value,
            "schema_ok": ok,
            "schema_error": schema_error,
            "verdict": verdict.explain(),
            "would_execute": verdict.allowed_without_approval and ok,
        }
        if as_json:
            print_json(payload)
        else:
            console.print(_panel(payload))
        orch.close()
        raise typer.Exit(0)

    record = orch.run_skill(skill, arguments, yes=yes)
    if as_json:
        print_json(
            {
                "skill": record.skill,
                "tier": record.tier,
                "decision": record.decision,
                "ok": record.ok,
                "message": record.message,
                "reasons": record.reasons,
                "duration_ms": round(record.duration_ms, 1),
            }
        )
    else:
        icon = "✅" if record.ok else ("⛔" if record.decision == "deny" else "⚠️")
        console.print(
            f"{icon} [bold]{record.skill}[/bold] {tier_badge(record.tier)!s} "
            f"[dim]({record.decision}, {record.duration_ms:.0f} ms)[/dim]"
        )
        console.print(record.message)
        if record.reasons and not record.ok:
            console.print(f"[dim]motivos: {'; '.join(record.reasons)}[/dim]")
    orch.close()
    raise typer.Exit(0 if record.ok else 1)


def _panel(payload: dict[str, Any]) -> Any:
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    for key, value in payload.items():
        body.append(f"{key}: ", style="bold")
        body.append(f"{value}\n")
    return Panel(body, title="dry-run (nada se ha ejecutado)", border_style="cyan")


@app.command()
def policy(
    skill: str | None = typer.Argument(None, help="Skill a inspeccionar."),
    args: list[str] = typer.Argument(None),
    explain: bool = typer.Option(False, "--explain", "-e"),
) -> None:
    """Explica qué decidiría el policy engine para un skill y unos argumentos."""
    _configure_logging()
    orch = Orchestrator(get_settings())
    if skill is None:
        table = Table(title="Resumen de la política activa")
        cfg = orch.settings.policy
        table.add_row("auto-approve máximo", cfg.auto_approve_max_tier)
        table.add_row("timeout de aprobación", f"{cfg.approval_timeout_s} s")
        table.add_row("confirmación escrita en T3", str(cfg.require_typed_confirmation_for_t3))
        table.add_row("jaula de rutas", ", ".join(cfg.jail_roots) or "(vacía)")
        table.add_row("allowlist de shell", f"{len(cfg.shell_allowlist)} binarios")
        table.add_row("binarios restringidos", f"{len(cfg.restricted_binaries)}")
        table.add_row("kill switch", str(orch.policy.kill_switch))
        console.print(table)
        orch.close()
        return
    target = orch.registry.get(skill)
    if target is None:
        console.print(f"[red]skill desconocido: {skill}[/red]")
        orch.close()
        raise typer.Exit(1)
    arguments = dict(_parse_arg(a) for a in (args or []))
    verdict = orch.policy.evaluate(
        skill,
        arguments,
        target.tier,
        skill_exists=True,
        platforms=set(target.platforms),
        undoable=target.undoable,
        known_skills=orch.registry.names(),
    )
    console.print(f"[bold]{skill}[/bold] tier base {tier_badge(target.tier.value)!s} → {verdict.explain()}")
    if explain and verdict.reasons:
        for reason in verdict.reasons:
            console.print(f"  · {reason}")
    orch.close()


# --------------------------------------------------------------------------- #
# audit / cost / undo
# --------------------------------------------------------------------------- #
@app.command()
def audit(
    tail: int = typer.Option(20, "--tail", "-n", help="Número de entradas a mostrar."),
    verify: bool = typer.Option(False, "--verify", help="Recalcula la cadena de hashes."),
    kind: str | None = typer.Option(None, "--kind", help="Filtra por tipo de entrada."),
    purge_days: int | None = typer.Option(
        None, "--purge-older-than", help="Borra entradas más antiguas (días)."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Registro de auditoría append-only con cadena de hashes."""
    _configure_logging()
    from jarvis.safety.audit import AuditLog

    settings = get_settings()
    log_ = AuditLog(settings.audit_db)
    try:
        if verify:
            valid, message = log_.verify()
            icon = "[green]✔[/green]" if valid else "[red]✘[/red]"
            console.print(f"{icon} {message}")
            raise typer.Exit(0 if valid else 1)
        if purge_days is not None:
            deleted = log_.purge_older_than(purge_days)
            console.print(f"Eliminadas {deleted} entradas de más de {purge_days} días.")
            return
        entries = log_.tail(tail, kind=kind)
        if as_json:
            print_json([e.to_dict() for e in entries])
            return
        table = Table(title=f"Últimas {len(entries)} de {log_.count()} entradas")
        table.add_column("#", justify="right", style="dim")
        table.add_column("hora")
        table.add_column("evento", style="bold")
        table.add_column("skill")
        table.add_column("tier")
        table.add_column("decisión")
        table.add_column("detalle", overflow="fold", max_width=60)
        for entry in entries:
            detail = json.dumps(entry.detail, ensure_ascii=False, default=str)
            table.add_row(
                str(entry.seq),
                time.strftime("%m-%d %H:%M:%S", time.localtime(entry.ts)),
                entry.kind,
                entry.skill or "—",
                entry.tier or "—",
                entry.decision or "—",
                detail[:300],
            )
        console.print(table)
    finally:
        log_.close()


@app.command()
def cost(
    today: bool = typer.Option(True, "--today/--all", help="Gasto del día en curso."),
) -> None:
    """Gasto estimado y tokens consumidos (contabilidad local)."""
    _configure_logging()
    orch = Orchestrator(get_settings())
    snapshot = orch.budget.snapshot()
    if today:
        console.print(
            f"Hoy ({snapshot['day']}): [bold]{snapshot['usd_today']:.5f} USD[/bold] de "
            f"{snapshot['usd_limit']:.2f} USD ({snapshot['usd_pct']}%) · "
            f"{snapshot['tokens_today']:,} tokens · {snapshot['llm_calls_today']} llamadas · "
            f"{snapshot['actions_last_hour']} acciones en la última hora"
        )
    else:
        _print_cost(orch)
    console.print(
        "[dim]Nota: la contabilidad es local y aproximada; el dato oficial es el panel de tu proveedor.[/dim]"
    )
    orch.close()


@app.command()
def undo() -> None:
    """Deshace la última acción reversible de la sesión actual."""
    _configure_logging()
    orch = Orchestrator(get_settings())
    console.print(orch.undo_last())
    orch.close()


# --------------------------------------------------------------------------- #
# watch
# --------------------------------------------------------------------------- #
@app.command()
def watch(
    once: bool = typer.Option(False, "--once", help="Una sola pasada y termina."),
    interval: int | None = typer.Option(None, "--interval", "-i", help="Segundos entre pasadas."),
    quiet: bool = typer.Option(False, "--quiet", help="Ignora las horas silenciosas."),
    as_json: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Watchdog proactivo: vigila el sistema y emite sugerencias cuando algo va mal."""
    _configure_logging(verbose)
    from jarvis.proactive.watchdog import Watchdog

    settings = get_settings()
    if quiet:
        settings.watchdog.quiet_hours = []
    orch = Orchestrator(settings)
    watchdog = Watchdog(settings, orch.adapter)
    console.print(
        f"[bold]Watchdog activo[/bold] cada {interval or settings.watchdog.interval_s} s · "
        f"cooldown {settings.watchdog.cooldown_s // 3600} h · Ctrl+C para parar."
    )
    try:
        alerts = watchdog.run(once=once, interval_s=interval)
    except KeyboardInterrupt:
        alerts = []
        watchdog.stop()
    if as_json:
        print_json(
            [
                {"monitor": a.monitor, "severity": a.severity.value, "title": a.title, "detail": a.detail}
                for a in alerts
            ]
        )
    else:
        if not alerts:
            console.print("[green]Todo en orden: ninguna alerta en esta pasada.[/green]")
        for alert in alerts:
            console.print(alert.as_suggestion())
    console.print(
        f"[dim]{json.dumps(watchdog.summary()['suppressed_by_cooldown'])} alertas "
        f"suprimidas por cooldown[/dim]"
    )
    orch.close()


# --------------------------------------------------------------------------- #
# bench / config / serve / token
# --------------------------------------------------------------------------- #
@app.command()
def bench(
    corpus: Path | None = typer.Option(None, "--corpus", help="Archivo con una frase por línea."),
) -> None:
    """Mide la cobertura del matcher local (nivel N0: 0 tokens, ~5 ms)."""
    _configure_logging()
    from jarvis.core.matcher import coverage_report, match

    default_corpus = [
        "qué hora es",
        "cuánta RAM me queda",
        "estado del sistema",
        "cuánto disco libre tengo",
        "qué procesos consumen más",
        "abre firefox",
        "abre el navegador",
        "abre la terminal",
        "sube el volumen al 40",
        "silencia el equipo",
        "pon el brillo al 30",
        "busca los archivos *.pdf en ~",
        "qué ventanas tengo abiertas",
        "estado de la batería",
        "qué temperatura tiene la cpu",
        "qué puertos tengo abiertos",
        "tengo actualizaciones pendientes",
        "qué hay en el portapapeles",
        "lista mis notas",
        "abre https://github.com",
        "busca en internet python asyncio",
        # Estas NO deberían resolverse localmente (requieren razonamiento):
        "explícame por qué mi script de python falla",
        "escribe un poema sobre Kali",
        "resume este artículo y guárdalo en notas",
    ]
    samples = default_corpus
    if corpus and corpus.is_file():
        samples = [line.strip() for line in corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    table = Table(title=f"Matcher local sobre {len(samples)} frases")
    table.add_column("frase", overflow="fold", max_width=50)
    table.add_column("skill")
    table.add_column("conf.")
    for sample in samples:
        found = match(sample)
        table.add_row(
            sample,
            found.skill if found else "[dim]— (va al LLM)[/dim]",
            f"{found.confidence:.2f}" if found else "",
        )
    console.print(table)
    stats = coverage_report(samples)
    console.print(
        f"Resueltas sin LLM: [bold]{stats['rate'] * 100:.0f}%[/bold] "
        f"({int(stats['resolved'])}/{int(stats['total'])})"
    )


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Imprime la configuración efectiva."),
    paths: bool = typer.Option(False, "--paths", help="Muestra las rutas de datos y configuración."),
    get: str | None = typer.Option(None, "--get", help="Lee una clave, p. ej. router.profile"),
) -> None:
    """Inspecciona la configuración efectiva (con los secretos redactados)."""
    settings = reload_settings()
    if paths:
        console.print(f"config usuario : {settings.config_dir / 'config.toml'}")
        console.print(f"config proyecto: {Path.cwd() / 'jarvis.toml'}")
        console.print(f"datos          : {settings.data_dir}")
        console.print(f"logs           : {settings.log_file}")
        console.print(f"auditoría      : {settings.audit_db}")
        console.print(f"memoria        : {settings.memory_db}")
        console.print(f"capas aplicadas: {' ← '.join(settings.sources) or 'defaults'}")
        return
    data = json.loads(settings.model_dump_json())
    for provider in ("openai", "anthropic", "gemini", "ollama"):
        if provider in data.get("providers", {}) and data["providers"][provider].get("api_key"):
            data["providers"][provider]["api_key"] = "***REDACTADO***"
    if get:
        node: Any = data
        for part in get.split("."):
            if not isinstance(node, dict) or part not in node:
                console.print(f"[red]clave no encontrada: {get}[/red]")
                raise typer.Exit(1)
            node = node[part]
        console.print(json.dumps(node, ensure_ascii=False, indent=2))
        return
    if show:
        console.print_json(json.dumps(data, ensure_ascii=False))
        return
    console.print("[dim]usa --show, --paths o --get clave.subclave[/dim]")


@app.command()
def serve(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interfaz de escucha. Deja 127.0.0.1 salvo que sepas lo que haces."
    ),
    port: int = typer.Option(8765, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Recarga automática (desarrollo)."),
) -> None:
    """Arranca la API local (REST + WebSocket) que consumirá el HUD y el panel web."""
    _configure_logging()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        err_console.print(
            f"[bold red]Aviso:[/bold red] vas a exponer JarvisM en {host}. "
            "Cualquier proceso de esa red podrá darle órdenes. Solo hazlo con token y firewall."
        )
    try:
        import uvicorn
    except ImportError:
        err_console.print("[red]Falta el extra de UI: pip install -e '.[ui]'[/red]")
        raise typer.Exit(1) from None
    uvicorn.run("jarvis.server.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def token() -> None:
    """Muestra el token de la API local (o lo genera si no existe)."""
    _configure_logging()
    settings = get_settings()
    token_file = settings.data_dir / "api.token"
    if token_file.exists():
        console.print(token_file.read_text(encoding="utf-8").strip())
        return
    import secrets

    value = secrets.token_urlsafe(32)
    settings.ensure_dirs()
    token_file.write_text(value, encoding="utf-8")
    token_file.chmod(0o600)
    console.print(value)
    console.print(f"[dim]guardado en {token_file}[/dim]")


def main() -> None:
    """Entry point. Captura Ctrl+C de forma limpia."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        err_console.print("\n[dim]Interrumpido.[/dim]")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
