"""Create the selected provider; no implicit cross-provider fallback."""
import os
from brain import Brain
from nvidia_brain import NvidiaBrain, DEFAULT_MODEL


def create_brain(controller, approve):
    provider = os.getenv('JARVIS_PROVIDER', 'gemini').strip().lower()
    name = os.getenv('JARVIS_NAME', 'Señor')
    if provider == 'gemini':
        return Brain(os.getenv('GEMINI_API_KEY'), controller, approve, name=name,
                     model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
    if provider == 'nvidia':
        return NvidiaBrain(os.getenv('NVIDIA_API_KEY'), controller, approve, name=name,
                           model=os.getenv('NVIDIA_MODEL', DEFAULT_MODEL))
    raise ValueError('JARVIS_PROVIDER debe ser gemini o nvidia.')
