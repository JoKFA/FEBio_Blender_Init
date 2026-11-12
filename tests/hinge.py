"""A test helper: the turn about an axis that a hinge transform makes (the inverse of trajectory.hinge_transforms)."""

import math


def hinge_angle(transform, axis) -> float:
    """The signed angle (rad) of a transform's rotation part about `axis`, in (-pi, pi]. Any part of
    the rotation that is not about the axis, and the translation, are not looked at."""
    ax = [float(a) for a in axis]
    norm = math.sqrt(sum(a * a for a in ax))
    if norm == 0:
        raise ValueError("the hinge axis is the zero vector; give it a direction")
    m = transform
    a = [c / norm for c in ax]
    # A vector u perpendicular to the axis, and where the rotation puts it; the angle between u and
    # that image, measured in the plane perpendicular to the axis, is the turn about the axis.
    u = [a[1], -a[0], 0.0] if abs(a[2]) < 0.9 else [0.0, a[2], -a[1]]
    un = math.sqrt(sum(c * c for c in u))
    u = [c / un for c in u]
    r = [sum(m[4 * i + j] * u[j] for j in range(3)) for i in range(3)]
    dot = sum(x * y for x, y in zip(u, r))
    cross = [u[1] * r[2] - u[2] * r[1], u[2] * r[0] - u[0] * r[2], u[0] * r[1] - u[1] * r[0]]
    return math.atan2(sum(x * y for x, y in zip(cross, a)), dot)
