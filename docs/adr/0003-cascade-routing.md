# ADR-0003 · Cascade routing: matcher local → modelo barato → modelo caro

**Estado:** aceptado · **Fecha:** 2026-10-12

## Contexto
Un asistente de voz lanza muchas peticiones pequeñas al día. Si cada "¿qué hora es?" o "abre
firefox" pasa por un modelo frontier, el coste y la latencia se vuelven inaceptables
(200 turnos/día × $0.02 ≈ $120/mes y 3–8 s por turno).

## Decisión
Tres niveles en cascada; **cada nivel solo escala al siguiente si no puede resolver**:

```
N0  Matcher determinista local        ~5 ms    0 tokens    resuelve ~50-60 % del tráfico
    (regex + alias + intenciones canónicas: abrir app, hora, estado, volumen)
N1  Modelo barato / local             ~400 ms  ~500 tok    clasifica y resuelve lo sencillo
    (flash-lite, haiku, ollama)
N2  Modelo de razonamiento            ~2-4 s   ~3-6 k tok  solo planificación compleja,
    (sonnet, pro)                                        multi-paso o visión
```

Más dos aceleradores transversales:
- **Prompt caching** del system prompt + descripciones de skills (~2–4 k tokens idénticos por turno).
- **Caché semántica local** para consultas repetidas de estado con TTL corto.

## Justificación
1. Los precios por millón de tokens entre el nivel barato y el frontier difieren en **1–2 órdenes de
   magnitud**, y la salida (lo caro) se reduce drásticamente en tareas de clasificación.
2. La latencia de N0 es lo que hace que "abre firefox" se sienta instantáneo. Ningún LLM baja de
   ~300 ms ni en el mejor caso.
3. El free tier de Gemini limita por **peticiones por minuto**, no solo por día: gastar RPM en
   "¿qué hora es?" es tirar la cuota que necesitas para lo difícil.

## Consecuencias
- **A favor:** coste mensual típico 1.5–15 USD en lugar de 90–300 USD; latencia percibida mucho mejor.
- **En contra:** hay que mantener el matcher de N0 y aceptar que a veces falla y delega en N1
  (coste de un turno extra). El matcher **solo puede acelerar, nunca denegar**: si no hay certeza
  ≥ umbral, se delega. Nunca decide por su cuenta en acciones T2+.
- **Métrica obligatoria:** `router.escalation_rate` por nivel, visible en `jarvis cost`. Si N0
  resuelve <30 %, hay que ampliar alias, no subir el presupuesto.
