"""Personal autonomous assistant architecture (Sistema 1 / Sistema 2).

New, additive layer on top of the existing JARVIS desktop assistant. It does
not replace the working modules (memory.py, action_log.py, persistent_brain.py,
permissions.py…); it composes them under an explicit four-pillar design:

  core      (Sistema 2)  slow, deliberate planner: objective → subtasks → execution
  memory    (memoria)    persistent, structured, local-first long-term memory
  reflex    (Sistema 1)  fast, typed decisions (enums/bool/list/score), no open text
  tools     (actuación)  registry of external actions with confirmation gates
  servers   (cuerpo)     REST/webhooks surface; nothing is auto-started

Nothing in this package acts without the same explicit authorisation used
elsewhere in JARVIS (permissions.py / approver callback).
"""

__version__ = '0.1.0'
