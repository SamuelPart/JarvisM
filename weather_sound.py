"""Original, short synthetic interface cue; no audio assets or network needed."""
import math
import struct
import wave


def write_search_cue(path, sample_rate=22050):
    """Generate three quiet electronic pips as a mono 16-bit WAV."""
    duration = 0.78
    frames = bytearray()
    notes = ((0.00, 0.19, 540, 760), (0.23, 0.19, 760, 1010), (0.47, 0.24, 1010, 1280))
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
