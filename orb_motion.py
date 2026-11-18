"""Frame-rate independent easing for the desktop orb."""
import math


def approach(current, target, elapsed, duration):
    """Exponentially approach a target without overshooting, even on slow frames."""
    if duration <= 0:
        return target
    elapsed = max(0.0, min(float(elapsed), 0.15))
    return current + (target - current) * (1.0 - math.exp(-elapsed / duration))
