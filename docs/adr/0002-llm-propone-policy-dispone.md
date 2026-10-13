# ADR-0002 · El LLM propone, el policy engine dispone

**Estado:** aceptado · **Fecha:** 2026-10-12

## Contexto
La forma habitual de dar capacidades a un agente es dejar que el modelo genere código o comandos
y ejecutarlos (`exec`, `eval`, `bash -c "$respuesta"`). Es potente y es **la causa número uno de
incidentes graves** en agentes: una inyección de prompt en una página web o en un README se
convierte en ejecución arbitraria en tu máquina.

## Decisión
El modelo **nunca** produce código ejecutable. Produce exclusivamente *tool calls* tipados contra
un catálogo cerrado de skills con JSON Schema. Entre la propuesta y la ejecución hay siempre un
`PolicyEngine` determinista, escrito en Python, con tests, que puede: permitir, exigir aprobación,
o denegar.

```
LLM → ToolCall{skill, args} → PolicyEngine.evaluate() → Skill.run()
                                     ↑
                        aquí NO entra nada del LLM salvo
                        el nombre del skill y sus argumentos validados
```

## Justificación
1. **Superficie de ataque acotada:** el modelo solo puede elegir entre N skills conocidos y
   argumentos que pasan validación de esquema. No puede inventar `rm -rf /` porque no existe un
   skill que acepte eso, y `shell.run` (el único que se le parece) es T3 con denylist.
2. **Los tiers viven en código, no en el prompt.** Un prompt es texto que el modelo puede intentar
   contradecir; una constante de Python no. Por eso `skill.tier` se declara en la clase y el
   engine lo lee de ahí, ignorando cualquier "nivel de riesgo" que aparezca en el texto.
3. **Auditabilidad:** podemos responder "¿por qué hizo esto?" con una decisión determinista
   reproducible, no con "el modelo lo decidió".
4. **Testeable con propiedad:** `hypothesis` puede generar millones de argumentos y afirmar que
   ninguno atraviesa T3 sin approval. Eso no se puede probar sobre un `exec`.

## Consecuencias
- **A favor:** seguridad demostrable; cada capacidad nueva es una clase revisable en un PR.
- **En contra:** menos flexible que un agente que escribe código. Se compensa con `shell.run` (T3,
  allowlist de binarios, parsing del comando, timeout) y con skills de terceros (tier mínimo T2).
- **Invariante que debe mantenerse:** *ninguna información proveniente de datos externos puede
  bajar un tier ni saltarse una aprobación.* Solo la config del usuario y el código lo hacen.
