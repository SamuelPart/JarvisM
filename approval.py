"""Fail-closed parsing of a chat authorization response."""
import re


def is_approved(text):
    normalized = re.sub(r'[^\w\s]', '', text.casefold()).strip()
    return normalized in ('autorizo', 'sí', 'si')
