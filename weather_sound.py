"""Original short synthesized interface cues, generated locally."""
import math
import struct
import wave

CUES = {
    'thinking': (
        ((0.00, .14, 420, 720), (.17, .16, 780, 610), (.36, .17, 640, 1050)),
        ((0.00, .13, 730, 500), (.17, .12, 500, 880), (.34, .20, 880, 1150)),
        ((0.00, .16, 510, 810), (.20, .13, 970, 750), (.38, .18, 750, 1060)),
    ),
    'weather': (
        ((0.00, .19, 540, 760), (.23, .19, 760, 1010), (.47, .24, 1010, 1280)),
        ((0.00, .16, 660, 900), (.20, .16, 850, 700), (.41, .25, 790, 1180)),
        ((0.00, .18, 480, 680), (.23, .13, 900, 1120), (.43, .22, 1100, 1450)),
    ),
}


def write_search_cue(path, sample_rate=22050, kind='weather', variant=0):
    """Generate a quiet, short mono 16-bit WAV; no downloads or voice samples."""
    notes = CUES[kind][variant % len(CUES[kind])]
    duration = .78
    frames = bytearray()
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        sample = 0.0
        for start, length, first, last in notes:
            offset = t - start
            if 0 <= offset < length:
                envelope = min(1.0, offset / .025, (length - offset) / .05)
                phase = 2 * math.pi * (first * offset + (last - first) * offset * offset / (2 * length))
                sample += .15 * envelope * (math.sin(phase) + .18 * math.sin(phase * 2))
        frames.extend(struct.pack('<h', round(max(-1, min(1, sample)) * 32767)))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)
