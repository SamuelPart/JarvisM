# ADR-0004 · `OSAdapter` en vez de comandos por plataforma dispersos

**Estado:** aceptado · **Fecha:** 2026-10-12

## Contexto
El requisito es explícito: el mismo asistente debe funcionar en Linux, Windows y macOS. La tentación
es escribir `if sys.platform == "linux": subprocess.run(["wmctrl", ...])` dentro de cada skill.
Eso produce skills que solo funcionan en un SO, `if/else` repetidos y tests imposibles.

## Decisión
Una interfaz `OSAdapter` con tres implementaciones (`LinuxAdapter`, `WindowsAdapter`, `MacOSAdapter`)
seleccionadas por `platform_factory()` en el arranque. Los skills hablan **solo** con el adapter.

```
skill.apps_launch  →  adapter.launch("firefox")  →  LinuxAdapter: busca .desktop / $PATH / gio
                                                  →  WindowsAdapter: App Paths / Start-Process
                                                  →  MacOSAdapter: open -a / mdfind
```

Cada capacidad devuelve `Capability(available: bool, hint: str)` cuando falta una herramienta
externa (`wmctrl`, `brightnessctl`, `pywin32`…), en vez de lanzar excepción.

## Justificación
1. **Testeabilidad:** los tests inyectan un `FakeAdapter` y verifican la lógica del skill sin SO real.
   Es la única forma de tener CI verde en las tres plataformas sin tres suites distintas.
2. **Detección en caliente:** en Linux hay 6 gestores de ventanas y 3 sistemas de audio. El adapter
   detecta con `shutil.which` y degrada; el skill no se entera.
3. **`jarvis doctor` sale gratis:** recorre las capacidades del adapter y pinta una matriz.
4. **Nuevas plataformas baratas:** BSD/WSL/Android-Termux = un adapter nuevo, cero cambios en skills.

## Consecuencias
- **A favor:** skills portables, CI en matriz 3×SO, diagnóstico honesto.
- **En contra:** el mínimo común denominador puede quedarse corto (p. ej. los workspaces virtuales
  no existen igual en los tres). Regla: **capacidad opcional declarada**, y el skill que la use
  comprueba `adapter.supports("workspaces")` y responde con una explicación, no con un error.
- **Prohibido:** `subprocess` fuera de `jarvis/platforms/` y de `skills/shell.py`. Se verifica con
  un test que hace grep del árbol (`tests/test_no_raw_subprocess.py`).
