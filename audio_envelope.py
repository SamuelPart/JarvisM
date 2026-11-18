"""Compact, local RMS envelope for the audio already sent to the speaker."""
from array import array
import math


def pcm_envelope(raw, sample_rate, channels, window_ms=50):
    """Return normalized levels for native-endian signed 16-bit PCM windows."""
    if sample_rate <= 0 or channels <= 0 or window_ms <= 0 or len(raw) % 2:
        raise ValueError('Formato de audio no válido')
    samples = array('h')
    samples.frombytes(raw)
    window = max(channels, int(sample_rate * window_ms / 1000) * channels)
    levels = []
    for start in range(0, len(samples), window):
        # Sampling every fourth frame keeps this inexpensive for long answers.
        segment = samples[start:start + window:4 * channels]
        if not segment:
            levels.append(0.0)
        else:
            rms = math.sqrt(sum(float(v) * v for v in segment) / len(segment)) / 32768
            levels.append(min(1.0, rms * 4.0))
    return levels


def level_at(levels, position_ms, window_ms=50):
    if position_ms < 0 or not levels:
        return 0.0
    index = int(position_ms // window_ms)
    return levels[index] if index < len(levels) else 0.0
