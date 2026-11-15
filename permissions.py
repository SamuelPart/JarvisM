"""Limited opt-in for search and music; all other tools still require approval."""
import json
import os
import tempfile
from pathlib import Path

STATE = Path(__file__).resolve().parent / '.jarvis-state.json'
PREAPPROVED_TOOLS = frozenset({'web_search', 'music_search', 'play_music', 'stop_music'})


def read_state():
    try:
        value = json.loads(STATE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def set_network_permission(granted):
    state = read_state()
    state['network_actions_asked'] = True
    state['network_actions_accepted'] = granted is True
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=STATE.parent, delete=False) as file:
            name = file.name
            json.dump(state, file, ensure_ascii=False)
        os.replace(name, STATE)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def preapproved(name):
    return name in PREAPPROVED_TOOLS and read_state().get('network_actions_accepted') is True
