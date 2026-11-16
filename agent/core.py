"""Sistema 2 — the slow, deliberate planner and executor.

Honest scope: decomposition requires an LLM and is injected (GeminiDecomposer);
without one, plan() degrades to a single-step plan rather than inventing
subtasks. Execution is explicit (never triggered by the planner itself), every
step goes through the tool registry, and dangerous steps need a human approval
callback — the model cannot grant itself permission. Finished plans are
recorded in the persistent memory as decisions.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum

from agent.memory import PersistentMemory
from agent.tools import ToolRegistry, build_default_registry


class StepStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    BLOCKED = 'blocked'  # waiting for human confirmation / unknown tool


@dataclass
class Step:
    description: str
    tool: str | None = None
    args: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: dict | None = None
    needs_confirmation: bool = False

    def to_dict(self):
        return {'description': self.description, 'tool': self.tool, 'args': self.args,
                'status': self.status.value, 'needs_confirmation': self.needs_confirmation,
                'result': self.result}


@dataclass
class Plan:
    goal: str
    steps: list[Step] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self):
        return {'id': self.id, 'goal': self.goal, 'steps': [step.to_dict() for step in self.steps]}


def naive_decompose(goal):
    """Fallback: no LLM available → a single explicit step, never invented subtasks."""
    return [{'description': goal, 'tool': None, 'args': {}}]


class GeminiDecomposer:
    """Asks the configured Gemini model to split a goal into ≤8 typed steps."""

    def __init__(self, model='gemini-2.5-flash'):
        self.model = model

    def __call__(self, goal):
        import os
        from google import genai
        from google.genai import types
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return naive_decompose(goal)  # no key → honest fallback, not fabricated steps
        client = genai.Client(api_key=api_key)
        prompt = (
            'Divide el siguiente objetivo del usuario en una lista JSON de pasos independientes. '
            'Responde SOLO con un array JSON: [{"description": str, "tool": str|null, "args": object}]. '
            'Máximo 8 pasos. Si un paso no requiere una herramienta, usa tool null. '
            f'Objetivo: {goal}'
        )
        response = client.models.generate_content(
            model=self.model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json'))
        try:
            data = json.loads(response.text)
        except (ValueError, AttributeError):
            return naive_decompose(goal)
        steps = []
        for item in data[:8] if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get('description'), str):
                steps.append({'description': item['description'][:300],
                              'tool': item.get('tool') if isinstance(item.get('tool'), str) else None,
                              'args': item.get('args') if isinstance(item.get('args'), dict) else {}})
        return steps or naive_decompose(goal)


class Orchestrator:
    def __init__(self, registry=None, memory=None, decomposer=None, approve=None):
        self.registry = registry or build_default_registry()
        self.memory = memory if memory is not None else PersistentMemory()
        self.decomposer = decomposer or naive_decompose
        self.approve = approve or (lambda name, args: False)  # default: deny, ask explicitly
        self._lock = threading.Lock()

    def plan(self, goal):
        if not goal or not goal.strip():
            raise ValueError('El objetivo no puede estar vacío.')
        raw_steps = self.decomposer(goal.strip())
        steps = []
        for item in raw_steps:
            tool = item.get('tool')
            spec = self.registry.get(tool) if tool else None
            needs = bool(spec.danger) if spec else False
            steps.append(Step(description=item['description'], tool=tool,
                              args=item.get('args') or {},
                              needs_confirmation=needs))
        return Plan(goal=goal.strip(), steps=steps)

    def execute(self, plan):
        """Run a plan explicitly; record the outcome in long-term memory."""
        results = []
        for step in plan.steps:
            step.status = StepStatus.RUNNING
            if step.tool is None:
                step.status = StepStatus.DONE  # informational step: nothing to execute
                step.result = {'status': 'ok', 'note': 'Paso informativo; sin herramienta.'}
                results.append(step)
                continue
            if self.registry.get(step.tool) is None:
                step.status = StepStatus.BLOCKED
                step.result = {'status': 'error', 'error': f'Herramienta no registrada: {step.tool}'}
                results.append(step)
                continue
            confirmed = self.approve(step.tool, step.args) if step.needs_confirmation else False
            if step.needs_confirmation and not confirmed:
                step.status = StepStatus.BLOCKED
                step.result = {'status': 'needs_confirmation',
                               'error': f'«{step.tool}» requiere tu confirmación explícita.'}
                results.append(step)
                continue
            result = self.registry.execute(step.tool, step.args, confirmed=confirmed)
            step.result = result
            step.status = StepStatus.DONE if result.get('status') == 'ok' else StepStatus.FAILED
            results.append(step)
        self.memory.record_decision(
            f'plan {plan.id} · {plan.goal[:120]} · ' +
            ', '.join(f'{step.description[:60]}→{step.status.value}' for step in plan.steps))
        return plan
