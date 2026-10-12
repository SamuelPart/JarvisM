"""`shell.run`: la única puerta a la shell. Tier T3 SIEMPRE.

Defensas en profundidad (ver docs/03):
  1. el policy engine ya aplicó la denylist dura antes de llegar aquí;
  2. aquí se vuelve a comprobar la denylist (por si alguien invoca el skill directo);
  3. se prohíben los encadenadores de comandos salvo allowlist;
  4. el binario debe estar en la allowlist del usuario o confirmarse explícitamente;
  5. timeout duro, salida truncada, sin TTY y sin `shell=True` cuando es evitable.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from jarvis.safety.policy import RiskTier, scan_command
from jarvis.skills.base import Skill, SkillResult

# Sustitución de comandos y redirecciones: prohibidas siempre. Permiten ejecutar
# algo distinto de lo que se ve y escribir fuera de la jaula.
FORBIDDEN_TOKENS = ("`", "$(", ">", "<", ">>", "&>", "${")

# Separadores permitidos. Si aparecen, se valida el binario de CADA segmento:
# `ps aux | grep x` es legítimo y auditable; `ls; rm -rf ~` no.
SEGMENT_SEPARATORS = ("&&", "||", ";", "|")


class ShellRunSkill(Skill):
    name = "shell.run"
    description = (
        "Ejecuta UN comando de shell y devuelve su salida. Úsalo SOLO cuando no exista un skill "
        "específico para lo que pide el usuario. Es la acción de mayor riesgo del sistema: "
        "siempre requiere confirmación explícita del usuario. No encadenes comandos: si hacen "
        "falta varios pasos, propón este skill varias veces y explica cada paso."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "minLength": 1,
                "maxLength": 800,
                "description": "Comando completo a ejecutar, p. ej. 'df -h' o 'git status'.",
            },
            "cwd": {
                "type": "string",
                "description": "Carpeta de trabajo. Por defecto, la carpeta actual del usuario.",
            },
            "reason": {
                "type": "string",
                "minLength": 4,
                "description": "POR QUÉ hace falta este comando. Se guarda en el audit log.",
            },
        },
        "required": ["command", "reason"],
        "additionalProperties": False,
    }
    tier = RiskTier.T3
    undoable = False

    def execute(self, command: str, reason: str = "", cwd: str | None = None) -> SkillResult:
        command = command.strip()
        if not command:
            return SkillResult.failure("Comando vacío.")

        # 2) re-chequeo de denylist dura dentro del skill (defensa en profundidad)
        hard = [h.label for h in scan_command(command) if h.hard]
        if hard:
            self.ctx.audit.record(
                "shell.blocked", tier="T3", skill=self.name, command=command, patterns=hard, reason=reason
            )
            return SkillResult.failure(
                f"Bloqueado por política: {', '.join(hard)}. No voy a ejecutar eso ni con confirmación."
            )

        # 3) sustitución de comandos y redirecciones: nunca
        forbidden = [t for t in FORBIDDEN_TOKENS if t in command]
        if forbidden:
            return SkillResult.failure(
                f"No puedo ejecutar comandos con redirecciones o sustituciones ({', '.join(forbidden)}). "
                "Pídeme cada paso por separado y te los propongo uno a uno."
            )

        # 4) validación del binario de CADA segmento del pipeline
        allowlist = {b.lower() for b in self.settings.policy.shell_allowlist}
        restricted = {b.lower() for b in self.settings.policy.restricted_binaries}
        binaries: list[str] = []
        for segment in split_segments(command):
            try:
                parts = shlex.split(segment, posix=sys.platform != "win32")
            except ValueError as exc:
                return SkillResult.failure(f"Comando mal formado: {exc}")
            parts = [p for p in parts if not _is_env_assignment(p)]
            while parts and parts[0] in {"sudo", "nohup", "time", "env", "command", "xargs"}:
                parts = parts[1:]
            if not parts:
                continue
            binary = Path(parts[0]).name.lower()
            binaries.append(binary)
            if binary in restricted and binary not in allowlist:
                return SkillResult.failure(
                    f"'{binary}' es un binario restringido en esta configuración. "
                    "Si quieres permitirlo, añádelo a policy.shell_allowlist en tu config."
                )
            if allowlist and binary not in allowlist:
                return SkillResult.failure(
                    f"'{binary}' no está en la allowlist de comandos ({len(allowlist)} permitidos). "
                    "Añádelo a policy.shell_allowlist si confías en él."
                )
        if not binaries:
            return SkillResult.failure("No pude identificar ningún comando ejecutable en la orden.")
        binary = binaries[0]

        workdir = Path(cwd).expanduser() if cwd else Path.home()
        if not workdir.is_dir():
            return SkillResult.failure(f"La carpeta {workdir} no existe.")
        if self.ctx.policy.is_excluded_path(workdir):
            return SkillResult.failure(f"{workdir} está protegida por la política de privacidad.")

        # 5) ejecución acotada
        from jarvis.platforms._proc import run_command

        timeout = self.settings.policy.shell_timeout_s
        if sys.platform == "win32":
            result = run_command(["cmd", "/c", command], timeout=timeout, cwd=workdir)
        else:
            result = run_command(["/bin/sh", "-c", command], timeout=timeout, cwd=workdir)

        max_bytes = self.settings.policy.shell_max_output_bytes
        output = result.stdout[:max_bytes]
        error = result.stderr[: max_bytes // 2]
        truncated = "\n… [salida truncada]" if len(result.stdout) > max_bytes else ""

        self.ctx.audit.record(
            "shell.executed",
            tier="T3",
            skill=self.name,
            decision="executed",
            command=command,
            binary=binary,
            cwd=str(workdir),
            code=result.code,
            reason=reason,
            bytes_out=len(result.stdout),
        )

        if result.code == 127:
            return SkillResult.failure(f"No encuentro el comando '{binaries[0]}'.")
        if result.code == 124:
            return SkillResult.failure(f"El comando superó el timeout de {timeout:.0f} s y se canceló.")
        if not result.ok:
            summary = (error or output or "sin salida").strip()
            return SkillResult(
                ok=False,
                message_for_user=f"El comando terminó con código {result.code}.",
                message_for_llm=f"código {result.code}\nSTDERR: {summary[:1500]}\nSTDOUT: {output[:1500]}",
                data={"code": result.code, "stdout": output, "stderr": error},
            )
        if not output.strip():
            return SkillResult.success(
                f"`{command}` terminó correctamente (sin salida).", data={"code": 0, "stdout": ""}
            )
        return SkillResult.success(
            f"Salida de `{command}`:\n{output}{truncated}",
            data={"code": 0, "stdout": output, "stderr": error},
            llm=f"{output}{truncated}",
        )


# --------------------------------------------------------------------------- #
# Helpers puros (testeables sin ejecutar nada)
# --------------------------------------------------------------------------- #
def split_segments(command: str) -> list[str]:
    """Divide por separadores de shell para validar cada binario por separado."""
    import re

    pattern = "|".join(re.escape(sep) for sep in SEGMENT_SEPARATORS)
    return [seg.strip() for seg in re.split(pattern, command) if seg.strip()]


def _is_env_assignment(token: str) -> bool:
    """`FOO=bar cmd ...`: las asignaciones previas no son el binario."""
    import re

    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token))
