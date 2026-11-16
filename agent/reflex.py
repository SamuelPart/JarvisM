"""Sistema 1 — fast, structured decisions. No free text, no tool execution.

Separated from text generation on purpose: a reflex returns a strictly typed
value a machine can act on (enum yes/no, list selection, bounded score) so the
system can react without waiting for or hallucinating long model output.
Deterministic rules today; the same interface can later delegate to a small
local classifier without changing callers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ReflexKind(Enum):
    YES_NO = 'yes_no'
    SELECT = 'select'
    SCORE = 'score'
    UNKNOWN = 'unknown'


@dataclass
class ReflexResult:
    kind: ReflexKind
    value: object           # True/False | 0-based index | int score | None
    confidence: float       # 0.0–1.0
    raw: str = ''

    def to_dict(self):
        return {'kind': self.kind.value, 'value': self.value, 'confidence': self.confidence, 'raw': self.raw}


_YES = ('sí', 'si', 's', 'claro', 'vale', 'ok', 'okay', 'adelante', 'hazlo', 'eso', 'perfecto',
        'correcto', 'afirmativo', 'por supuesto', 'de acuerdo', 'dale')
_NO = ('no', 'nunca', 'jamás', 'jamas', 'negativo', 'cancela', 'olvida', 'paso', 'mejor no')
_ORDINALS = {'primero': 0, 'primera': 0, 'segundo': 1, 'segunda': 1, 'tercero': 2, 'tercera': 2,
             'cuarto': 3, 'cuarta': 3, 'quinto': 4, 'quinta': 4, 'sexto': 5, 'séptimo': 6,
             'septimo': 6, 'octavo': 7, 'noveno': 8, 'décimo': 9, 'decimo': 9, 'último': -1, 'ultimo': -1}
_NUMWORDS = {'uno': 0, 'dos': 1, 'tres': 2, 'cuatro': 3, 'cinco': 4, 'seis': 5, 'siete': 6,
             'ocho': 7, 'nueve': 8, 'diez': 9}


def _clean(text):
    return re.sub(r'\s+', ' ', (text or '').strip().lower()).strip(' .!¡?¿')


def classify_yes_no(text):
    clean = _clean(text)
    if clean in _YES:
        return ReflexResult(ReflexKind.YES_NO, True, 0.99, clean)
    if clean in _NO:
        return ReflexResult(ReflexKind.YES_NO, False, 0.99, clean)
    if re.match(r'^(sí|si)\b', clean):
        return ReflexResult(ReflexKind.YES_NO, True, 0.8, clean)
    if re.match(r'^no\b', clean):
        return ReflexResult(ReflexKind.YES_NO, False, 0.8, clean)
    return ReflexResult(ReflexKind.UNKNOWN, None, 0.0, clean)


def classify_select(text, options):
    """Pick an index from `options` using ordinals, digits or name matching."""
    clean = _clean(text)
    if not options:
        return ReflexResult(ReflexKind.UNKNOWN, None, 0.0, clean)
    # Exact digit (1-based for humans, clamped to the list).
    match = re.search(r'\b(\d{1,2})\b', clean)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(options):
            return ReflexResult(ReflexKind.SELECT, index, 0.95, clean)
    for word, index in _ORDINALS.items():
        if re.search(r'\b' + re.escape(word) + r'\b', clean):
            real = len(options) + index if index == -1 else index
            if 0 <= real < len(options):
                return ReflexResult(ReflexKind.SELECT, real, 0.9, clean)
    match = re.search(r'\b(' + '|'.join(_NUMWORDS) + r')\b', clean)
    if match:
        index = _NUMWORDS[match.group(1)]
        if 0 <= index < len(options):
            return ReflexResult(ReflexKind.SELECT, index, 0.9, clean)
    for index, option in enumerate(options):
        option_clean = _clean(str(option))
        if option_clean and (option_clean in clean or clean in option_clean):
            return ReflexResult(ReflexKind.SELECT, index, 0.75, clean)
    return ReflexResult(ReflexKind.UNKNOWN, None, 0.0, clean)


def classify_score(text, max_score=10):
    """Strictly bounded score (e.g. 1–10); anything out of range is UNKNOWN."""
    clean = _clean(text)
    match = re.search(r'\b(\d{1,2})\b', clean)
    if not match:
        for word, number in _NUMWORDS.items():
            if re.search(r'\b' + word + r'\b', clean):
                if number + 1 <= max_score:
                    return ReflexResult(ReflexKind.SCORE, number + 1, 0.9, clean)
        return ReflexResult(ReflexKind.UNKNOWN, None, 0.0, clean)
    value = int(match.group(1))
    if not 0 <= value <= max_score:
        return ReflexResult(ReflexKind.UNKNOWN, None, 0.0, clean)
    return ReflexResult(ReflexKind.SCORE, value, 0.95, clean)


def classify(text, options=None, max_score=10):
    """Generic entry point: tries select (if options), score and yes/no in order."""
    if options:
        result = classify_select(text, options)
        if result.kind is ReflexKind.SELECT:
            return result
        return classify_yes_no(text)  # allow yes/no with a list shown (e.g. «sí, el segundo» won't reach here)
    yes_no = classify_yes_no(text)
    if yes_no.kind is ReflexKind.YES_NO:
        return yes_no
    return classify_score(text, max_score)
