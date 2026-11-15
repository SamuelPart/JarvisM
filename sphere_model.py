"""Geometry for a continuously moving, bristled particle sphere."""
import math


def sphere_points(count=4200):
    """Evenly distribute normals on a sphere with a Fibonacci spiral."""
    points = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(count):
        y = 1 - 2 * (i + 0.5) / count
        radial = math.sqrt(max(0.0, 1 - y * y))
        angle = i * golden
        points.append((radial * math.cos(angle), y, radial * math.sin(angle)))
    return points


def projected_particles(points, phase, speaking=False, reduced=False):
    """Return projected bristles. Audio movement is decorative, not lip sync."""
    angle = phase * 0.17
    ca, sa = math.cos(angle), math.sin(angle)
    strength = (0.055 if speaking else 0.022) * (0.48 if reduced else 1.0)
    particles = []
    for x, y, z in points:
        rx, rz = x * ca + z * sa, z * ca - x * sa
        if rz < -0.08:
            continue
        az = math.atan2(y, rx)
        wave = (math.sin(3 * az + phase * 0.8) * 0.58 +
                math.sin(6 * az - phase * 1.1 + rz * 3) * 0.42)
        surface = 1.0 + strength * wave + 0.025 * math.sin(phase * 0.8 + y * 4 + rx * 2)
        px, py = rx * 99 * surface, y * 99 * surface
        # Radial needles are longer at the silhouette, as in the reference.
        edge = math.sqrt(max(0.0, 1 - min(1.0, rz * rz)))
        length = (1.5 + 5 * edge) * (1.25 if speaking else 1.0)
        dx, dy = rx * length, y * length
        shade = 0.30 + 0.45 * max(0.0, -0.65 * rx - 0.65 * y + 0.3 * rz) + 0.32 * edge
        particles.append((rz, px, py, px + dx, py + dy, min(1.0, shade)))
    return sorted(particles, key=lambda item: item[0])
