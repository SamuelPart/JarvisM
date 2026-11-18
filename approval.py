"""Fail-closed parsing of a chat authorization response.

Exact match against the closed list of affirmative words (case/punctuation
agnostic): «AUTORIZO», «sí», «si», «vale», «ok», «claro», «dale»… Anything
longer («sí pero no», «autorizo todo») or ambiguous is rejected. The system
refuses rather than guesses — consent must be unambiguous.
"""
import re

_YES_WORDS = {'autorizo', 'autoriza', 'sí', 'si', 's', 'vale', 'ok', 'okay', 'claro',
              'dale', 'adelante', 'de acuerdo', 'perfecto', 'correcto', 'afirmativo', 'por supuesto'}


def is_approved(text):
    normalized = re.sub(r'[^\w\s]', '', (text or '').casefold())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized in _YES_WORDS
