"""Persistent, scoped opt-ins; other tools still require approval."""
import json
import os
import tempfile
from pathlib import Path

STATE = Path(__file__).resolve().parent / '.jarvis-state.json'
PREAPPROVED_TOOLS = frozenset({'web_search', 'music_search', 'play_music', 'stop_music'})
GMAIL_TOOLS = frozenset({'search_gmail', 'read_gmail', 'send_gmail', 'reply_gmail', 'classify_gmail'})
AGENDA_TOOLS = frozenset({'current_time', 'list_reminders', 'list_calendar_events'})
# No blanket approval for arbitrary shell, GUI automation, or sending images.
AUTOMATION_TOOLS = frozenset({'open_url', 'open_app', 'system_stats', 'volume_brightness',
                              'files', 'create_reminder', 'configure_routine', 'run_routine', 'whatsapp_prepare'})



def read_state():
    try:
        value = json.loads(STATE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _write_state(state):
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=STATE.parent, delete=False) as file:
            name = file.name
            json.dump(state, file, ensure_ascii=False)
        os.replace(name, STATE)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _set_permission(prefix, granted):
    state = read_state()
    state[prefix + '_asked'] = True
    state[prefix + '_accepted'] = granted is True
    _write_state(state)

def set_automation_permission(granted):
    """One explicit, revocable opt-in for the documented automation scope."""
    state = read_state()
    state['automation_asked'] = True
    state['automation_accepted'] = granted is True
    if granted is True:
        for prefix in ('network_actions', 'gmail_actions', 'agenda_read', 'startup_briefing'):
            state[prefix + '_asked'] = True
            state[prefix + '_accepted'] = True
    else:
        # Avoid presenting several additional prompts immediately after declining.
        for prefix in ('network_actions', 'gmail_actions', 'agenda_read', 'startup_briefing'):
            if prefix + '_asked' not in state:
                state[prefix + '_asked'] = True
                state[prefix + '_accepted'] = False
    _write_state(state)


def set_network_permission(granted):
    _set_permission('network_actions', granted)


def set_gmail_permission(granted):
    _set_permission('gmail_actions', granted)


def set_agenda_permission(granted):
    _set_permission('agenda_read', granted)


def set_briefing_permission(granted):
    _set_permission('startup_briefing', granted)


def preapproved(name):
    state = read_state()
    return ((name in AUTOMATION_TOOLS and state.get('automation_accepted') is True) or
            (name in PREAPPROVED_TOOLS and state.get('network_actions_accepted') is True) or
            (name in GMAIL_TOOLS and state.get('gmail_actions_accepted') is True) or
            (name in AGENDA_TOOLS and state.get('agenda_read_accepted') is True) or
            (name == 'review_startup_logs' and state.get('startup_briefing_accepted') is True))
