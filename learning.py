"""Background learning of durable user facts.

Local storage, provider-assisted extraction, no retraining. Facts are kept in
the same 2000-character preferences profile the user can read, edit and clear
in Memoria. Disable automatic extraction with JARVIS_LEARNING=0; explicit
«recuerda que …» always works.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime

EXPLICIT_RE = re.compile(
    r'^\s*(?:recuerda|memoriza|anota|aprende)\s+(?:que\s+|lo siguiente\s*:\s*|esto\s*:\s*)?(?P<fact>.+?)\s*$',
    re.I | re.S)
LEARNED_PREFIX = '- ('
EXTRACTION_PROMPT = (
    'Eres un asistente de extracción. Lee esta conversación entre un usuario y su asistente y extrae SOLO hechos estables '
    'y duraderos sobre el usuario o sus preferencias, tal como él mismo los expresó (gustos, rutina, contexto personal, '
    'forma en que prefiere ser tratado, cosas que quiere que se recuerden). No inventes hechos ni incluyas: estados '
    'momentáneos, tareas, recordatorios, correos, consultas puntuales, ni nada que haya dicho el asistente. Devuelve '
    'ÚNICAMENTE un JSON válido con una lista de frases cortas en español, por ejemplo ["Prefiere respuestas breves"]. '
    'Si no hay nada, devuelve [].\n\nConversación:\n')


def explicit_fact(text):
    """Return the fact from «recuerda que …» or None."""
    if not isinstance(text, str):
        return None
    match = EXPLICIT_RE.match(text.strip())
    if not match:
        return None
    fact = ' '.join(match.group('fact').split()).rstrip(' .,;!?¿¡')
    return fact[:300] if fact else None


def parse_facts(raw, limit=5):
    """Tolerantly parse the model's fact list; returns short Spanish strings."""
    facts = []
    if not isinstance(raw, str):
        return facts
    candidates = [raw]
    start, end = raw.find('['), raw.rfind(']')
    if 0 <= start < end:
        candidates.insert(0, raw[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    fact = ' '.join(item.split()).strip(' -–—')
                    if 3 <= len(fact) <= 200:
                        facts.append(fact)
            break
    seen, unique = set(), []
    for fact in facts:
        key = fact.lower()
        if key not in seen:
            seen.add(key)
            unique.append(fact)
    return unique[:limit]


def merge_facts(memory, facts, date=None):
    """Append new durable facts to the profile; returns how many were added."""
    if not facts:
        return 0
    try:
        current = memory.get_preferences()
    except Exception:
        return 0
    lines = [line for line in current.splitlines() if line.strip()]
    known = set()
    for line in lines:
        known.add(line.lower())
        known.add(line.lstrip('- ').split(') ', 1)[-1].strip().lower())
    stamp = date or datetime.now().astimezone().strftime('%Y-%m-%d')
    added = []
    for fact in facts:
        fact = ' '.join(fact.split())[:200]
        key = fact.lower()
        if not fact or key in known:
            continue
        lines.append(f'- ({stamp}) {fact}')
        known.add(key)
        added.append(fact)
    if not added:
        return 0
    # With the 2000-char cap, drop the oldest learned bullets before the user's own text.
    def joined():
        return '\n'.join(lines)
    while len(joined()) > 2000:
        for index, line in enumerate(lines):
            if line.startswith(LEARNED_PREFIX):
                lines.pop(index)
                break
        else:
            lines.pop(0)
    try:
        memory.set_preferences(joined())
    except ValueError:
        return 0
    return len(added)


def _transcript(messages, budget=4000):
    lines = []
    for message in messages:
        role = 'Usuario' if message.get('role') == 'user' else 'Asistente'
        lines.append(f'{role}: {message.get("content", "")}')
    transcript = '\n'.join(lines)
    return transcript[-budget:] if len(transcript) > budget else transcript


def extract_facts(complete, messages):
    if not callable(complete):
        return []
    transcript = _transcript(messages)
    if not transcript.strip():
        return []
    try:
        raw = complete(EXTRACTION_PROMPT + transcript)
    except Exception:
        return []
    return parse_facts(raw)


def complete_with(brain, prompt):
    """One plain completion without tools; returns None on any failure."""
    try:
        from brain import Brain
        from nvidia_brain import NvidiaBrain
    except Exception:
        return None
    try:
        if isinstance(brain, Brain):
            from google.genai import types
            response = brain.client.models.generate_content(
                model=brain.model,
                contents=[types.Content(role='user', parts=[types.Part.from_text(text=prompt)])])
            texts = []
            for candidate in getattr(response, 'candidates', None) or []:
                content = getattr(candidate, 'content', None)
                for part in getattr(content, 'parts', None) or []:
                    text = getattr(part, 'text', None)
                    if text:
                        texts.append(text)
            return '\n'.join(texts) or None
        if isinstance(brain, NvidiaBrain):
            from nvidia_brain import NVIDIA_URL
            payload = {'model': brain.model,
                       'messages': [{'role': 'user', 'content': prompt}],
                       'temperature': 0, 'top_p': 1, 'max_tokens': 400, 'stream': False}
            response = brain.post(NVIDIA_URL, headers={'Authorization': 'Bearer ' + brain.api_key,
                                                       'Accept': 'application/json'}, json=payload, timeout=45)
            return response.json()['choices'][0]['message']['content']
    except Exception:
        return None
    return None


_counter = {'turns': 0}


def maybe_learn(memory, brain, every=5):
    """Run provider-assisted extraction every `every` remembered turns, in the background."""
    import os
    if os.getenv('JARVIS_LEARNING', '1').strip() == '0':
        return
    _counter['turns'] += 1
    if _counter['turns'] % every != 0:
        return

    def work():
        try:
            facts = extract_facts(lambda prompt: complete_with(brain, prompt), memory.recent(20))
            if facts:
                merge_facts(memory, facts)
        except Exception:
            pass

    threading.Thread(target=work, name='JARVIS aprendizaje', daemon=True).start()
