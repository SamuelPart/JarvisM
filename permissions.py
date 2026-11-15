"""Persistent, scoped opt-ins; other tools still require approval."""
import json
import os
import tempfile
from pathlib import Path

STATE = Path(__file__).resolve().parent / '.jarvis-state.json'
PREAPPROVED_TOOLS = frozenset({'web_search', 'music_search', 'play_music', 'stop_music'})
GMAIL_TOOLS = frozenset({'search_gmail', 'read_gmail', 'send_gmail', 'reply_gmail', 'classify_gmail'})


def read_state():
    try:
        value = json.loads(STATE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _set_permission(prefix, granted):
    state = read_state()
    state[prefix + '_asked'] = True
    state[prefix + '_accepted'] = granted is True
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=STATE.parent, delete=False) as file:
            name = file.name
            json.dump(state, file, ensure_ascii=False)
        os.replace(name, STATE)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def set_network_permission(granted):
    _set_permission('network_actions', granted)


def set_gmail_permission(granted):
    _set_permission('gmail_actions', granted)


def preapproved(name):
    state = read_state()
    return ((name in PREAPPROVED_TOOLS and state.get('network_actions_accepted') is True) or
            (name in GMAIL_TOOLS and state.get('gmail_actions_accepted') is True))
