"""Particle geometry sampled from the user's reference, animated procedurally."""
import json
import math
from pathlib import Path

REFERENCE = Path(__file__).resolve().parent / 'assets' / 'face_reference_points.json'


def face_points():
    with REFERENCE.open(encoding='utf-8') as file:
        return [tuple(point) for point in json.load(file)]


def motion(phase, mode, animation):
    if animation == 'desactivada':
        return {'sway': 0.0, 'blink': 1.0, 'mouth': 0.0, 'brow': 0.0}
    blink_phase = phase % (math.pi * 7)
    blink = max(0.1, 1.0 - max(0.0, 1.0 - abs(blink_phase - 1.0) / 0.17))
    mouth = 0.0
    if mode == 'speaking':
        mouth = 3 * (0.5 + 0.5 * math.sin(phase * 6.3)) * (0.6 + 0.4 * math.sin(phase * 2.7) ** 2)
    return {'sway': 1.3 * math.sin(phase * 0.38), 'blink': blink, 'mouth': mouth,
            'brow': -1.5 if mode == 'approval' else 0.8 if mode == 'thinking' else 0.0}


def deform(x, y, state):
    """Move existing particles locally, without drawing artificial feature outlines."""
    eye_shift = 0.0
    for eye_x in (-25, 23):
        influence = math.exp(-((x - eye_x) / 15) ** 2 - ((y + 20) / 9) ** 2)
        eye_shift += (1 - state['blink']) * (-(y + 20) * influence)
    mouth_influence = math.exp(-((x + 8) / 24) ** 2 - ((y - 42) / 13) ** 2)
    mouth_shift = state['mouth'] * math.tanh((y - 42) / 3) * mouth_influence
    brow_influence = math.exp(-((abs(x) - 25) / 16) ** 2 - ((y + 34) / 10) ** 2)
    return x + state['sway'], y + eye_shift + mouth_shift + state['brow'] * brow_influence
