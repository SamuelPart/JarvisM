"""Deterministic geometry and decorative animation for the particle face."""
import math
import random


def face_points(seed=2026, count=1900):
    rng = random.Random(seed)
    points = []
    while len(points) < count:
        x, y = rng.uniform(-76, 76), rng.uniform(-103, 103)
        # A narrower jaw below full temples, with a rounded cranium and chin.
        width = 75 * (0.78 + 0.22 * min(1.0, max(0.0, (25 - y) / 100)))
        r = (x / width) ** 2 + (y / 103) ** 2
        if r >= 1:
            continue
        # Leave dark sockets so eyes remain readable in the particle cloud.
        if any(((x - center) / 19) ** 2 + ((y + 25) / 10) ** 2 < 1 for center in (-29, 29)):
            continue
        # Leave the mouth interior dark; animated lips are drawn separately.
        if (x / 24) ** 2 + ((y - 51) / 8) ** 2 < 1:
            continue
        depth = math.sqrt(1 - r)
        cheek = math.exp(-((abs(x) - 45) / 18) ** 2 - ((y - 8) / 25) ** 2)
        nose = math.exp(-(x / 12) ** 2 - ((y - 2) / 27) ** 2)
        light = min(1.0, 0.20 + 0.39 * depth + 0.20 * cheek + 0.27 * nose + rng.random() * 0.22)
        points.append((x, y, light, rng.uniform(0, math.tau), rng.uniform(0.45, 1.0)))
    return points


def ambient_points(seed=118, count=135):
    rng = random.Random(seed)
    return [(rng.uniform(-145, 145), rng.uniform(-125, 125), rng.uniform(0.25, 0.75),
             rng.uniform(0, math.tau), rng.uniform(0.35, 0.8)) for _ in range(count)]


def motion(phase, mode, animation):
    if animation == 'desactivada':
        return {'sway': 0.0, 'blink': 1.0, 'mouth': 2.5, 'brow': -3.0 if mode == 'approval' else 0.0}
    blink_phase = phase % (math.pi * 7)
    blink = max(0.07, 1.0 - max(0.0, 1.0 - abs(blink_phase - 1.0) / 0.17))
    mouth = 2.5
    if mode == 'speaking':
        mouth = 3 + 7 * (0.5 + 0.5 * math.sin(phase * 6.3)) * (0.6 + 0.4 * math.sin(phase * 2.7) ** 2)
    return {'sway': 1.5 * math.sin(phase * 0.38), 'blink': blink, 'mouth': mouth,
            'brow': -3.0 if mode == 'approval' else 1.5 if mode == 'thinking' else 0.0}
