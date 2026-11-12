"""The motion file, trajectory.json, and the hinge motion generator (T-05; docs/04 section 5.2).

Format `asrp-trajectory/1`, one JSON object:

    {
      "format_version": "asrp-trajectory/1",
      "fps": 30,                      # frames per second; must equal the scene's solver fps
      "frames": 46,                   # transforms per driver; frame 0 is the first entry
      "source": "free text: which controller output, or which generator, made this",
      "source_tag": "lab_setting" | "ziva_default" | "ours",   # optional: where the motion comes from, the
                                      #   same three tags as in scene.json; the run report shows it
                                      #   ("unstated" when absent, never guessed from the text)
      "drivers": {                    # keyed by driver name (a joint name for the lab asset,
        "jaw01": [[16 numbers], ...]  #   e.g. jaw01); scene.json says which bones follow which
      },
      "settle_until_frame": 14,       # optional: the last frame of the gravity-only settle (0 <= n < frames).
                                      #   Every driver the scene uses must be at rest (identity) on frames
                                      #   0..n. The run writes the settled shape at frame n and check (c)
                                      #   (gravity sag) averages frames max(1, n-4)..n (never frame 0, the rest
                                      #   pose); without it, or with n = 0, neither is done
      "landmarks": ...                # optional; its format is docs/04 section 5.2, T-09 reads and checks it
    }

Each transform is a 4x4 rigid transform in mm, Z up: the world transform of the driver relative
to its rest pose, so a bone that follows it moves its rest-pose points p to T @ p. Column-vector
convention (translation in the last column), written row by row, so the translation is at
indices 3, 7 and 11. Maya stores its matrices the other way (row vectors, translation at 12-14);
convert before writing one here (ADR-21).
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FORMAT_VERSION = "asrp-trajectory/1"
SOURCE_TAGS = ("lab_setting", "ziva_default", "ours")  # the same three values as scene.SOURCES
# How far a transform may be from rigid (rotation part orthonormal with determinant 1, last row
# 0 0 0 1). Round-trip through text keeps ~1e-16; this only lets through rounding, not a scale.
RIGID_TOLERANCE = 1e-6


class TrajectoryError(ValueError):
    """The file cannot be read as a trajectory; the message says what is wrong and what to do."""


@dataclass
class Trajectory:
    fps: float
    frames: int
    drivers: dict[str, list[list[float]]]
    source: str = ""
    landmarks: object = None  # format in docs/04 section 5.2; T-09 adds reading and checks; kept as read
    source_tag: str | None = None  # "lab_setting" | "ziva_default" | "ours"; None: the file does not say
    settle_until_frame: int | None = None  # last frame of the gravity-only settle; None: the file does not say
    extra: dict = field(default_factory=dict)  # unknown top-level keys, kept for the round trip

    def to_json(self) -> dict:
        data = {
            "format_version": FORMAT_VERSION,
            "fps": self.fps,
            "frames": self.frames,
            "source": self.source,
            "drivers": self.drivers,
        }
        if self.source_tag is not None:
            data["source_tag"] = self.source_tag
        if self.settle_until_frame is not None:
            data["settle_until_frame"] = self.settle_until_frame
        if self.landmarks is not None:
            data["landmarks"] = self.landmarks
        return {**data, **self.extra}


def hinge_transforms(pivot_mm, axis, angles_rad) -> list[list[float]]:
    """One rigid transform per angle: a right-handed turn by that angle about `axis` through
    `pivot_mm` (mm, Z up). Used to make a stand-in motion when there is no lab trajectory (T-06a,
    ADR-21) and to write the S1 example."""
    ax = [float(a) for a in axis]
    norm = math.sqrt(sum(a * a for a in ax))
    if norm == 0:
        raise ValueError("the hinge axis is the zero vector; give it a direction")
    x, y, z = (a / norm for a in ax)
    px, py, pz = (float(p) for p in pivot_mm)
    out = []
    for angle in angles_rad:
        c, s = math.cos(angle), math.sin(angle)
        t = 1 - c
        # Rodrigues' rotation matrix.
        r = [
            [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
        ]
        # Turning about the pivot: p' = R (p - pivot) + pivot, so the translation is pivot - R pivot.
        tx = px - (r[0][0] * px + r[0][1] * py + r[0][2] * pz)
        ty = py - (r[1][0] * px + r[1][1] * py + r[1][2] * pz)
        tz = pz - (r[2][0] * px + r[2][1] * py + r[2][2] * pz)
        out.append([*r[0], tx, *r[1], ty, *r[2], tz, 0.0, 0.0, 0.0, 1.0])
    return out


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


def _skew(w):
    return np.array([[0.0, -w[2], w[1]], [w[2], 0.0, -w[0]], [-w[1], w[0], 0.0]])


def _log_rotation(r) -> np.ndarray:
    """The rotation vector w (axis times angle, rad) of a rotation matrix; the angle is in [0, pi)."""
    vee = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    s = float(np.linalg.norm(vee)) / 2
    c = (float(np.trace(r)) - 1) / 2
    theta = math.atan2(s, c)
    if theta > math.pi - 1e-6:
        raise ValueError(
            "a rotation of 180 degrees or more from rest cannot be scaled; split the motion into smaller steps"
        )
    return vee / 2 if theta < 1e-8 else vee * (theta / (2 * s))


def _exp_rotation(w) -> np.ndarray:
    theta = float(np.linalg.norm(w))
    k = _skew(w)
    if theta < 1e-8:
        a, b = 1.0, 0.5
    else:
        a, b = math.sin(theta) / theta, (1 - math.cos(theta)) / theta**2
    return np.eye(3) + a * k + b * (k @ k)


def _left_jacobian(w) -> np.ndarray:
    """V(w) with exp(w, t) = (exp(w), V t): the matrix that turns the screw's translation part into the
    transform's translation."""
    theta = float(np.linalg.norm(w))
    k = _skew(w)
    if theta < 1e-8:
        return np.eye(3)
    return np.eye(3) + (1 - math.cos(theta)) / theta**2 * k + (theta - math.sin(theta)) / theta**3 * (k @ k)


def blend_transforms(parent_transforms, factor) -> list[list[float]]:
    """A derived driver's transforms (docs/04 section 5.1): for each of the parent's frames, a fraction of
    the whole rigid motion, exp(factor * log T) on SE(3). factor 0 is the identity, factor 1 is the parent.
    For a pure turn about a hinge this is the turn by factor times the angle about the same hinge; any
    translation and off-axis turning of the parent is scaled too. Blending twice adds the factors."""
    out = []
    for m in parent_transforms:
        rot = np.array([m[0:3], m[4:7], m[8:11]], dtype=float)
        t = np.array([m[3], m[7], m[11]], dtype=float)
        w = _log_rotation(rot)
        u = np.linalg.solve(_left_jacobian(w), t)
        fw = factor * w
        r2 = _exp_rotation(fw)
        t2 = _left_jacobian(fw) @ (factor * u)
        rows = [[*r2[i], t2[i]] for i in range(3)]
        out.append([float(v) for row in rows for v in row] + [0.0, 0.0, 0.0, 1.0])  # plain floats, never numpy's
    return out


def apply(transform, point) -> tuple[float, float, float]:
    """Move a point (mm) by one transform as stored here (column vectors, row by row)."""
    m = transform
    x, y, z = point
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )


def rigid_problem(m) -> str | None:
    """Why a 16-number transform is not a rigid transform, or None if it is one."""
    if len(m) != 16 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in m):
        return "it is not 16 finite numbers"
    if any(abs(a - b) > RIGID_TOLERANCE for a, b in zip(m[12:16], (0, 0, 0, 1))):
        return "its last row is not 0 0 0 1"
    rows = [m[0:3], m[4:7], m[8:11]]
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > RIGID_TOLERANCE:
                return "its rotation part stretches or shears (not orthonormal)"
    (a, b, c), (d, e, f), (g, h, i) = rows
    if a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) < 0:
        return "its rotation part is a mirror (determinant -1)"
    return None


def from_json(data) -> Trajectory:
    """Build a Trajectory from parsed JSON, refusing anything the solver could misread."""
    if not isinstance(data, dict):
        raise TrajectoryError("a trajectory file must hold one JSON object")
    version = data.get("format_version")
    if version != FORMAT_VERSION:
        raise TrajectoryError(
            f"format_version is {version!r}; this asrp reads {FORMAT_VERSION!r} only. "
            "Write the file in that format (docs/04 section 5.2) or update asrp."
        )
    fps, frames, drivers = data.get("fps"), data.get("frames"), data.get("drivers")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        raise TrajectoryError(f"fps must be a positive number of frames per second, got {fps!r}")
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        raise TrajectoryError(f"frames must be a whole number of frames, at least 1, got {frames!r}")
    if not isinstance(drivers, dict):
        raise TrajectoryError("'drivers' is missing: it must map each driver name to its transforms")
    for name, transforms in drivers.items():
        if not isinstance(transforms, list):
            raise TrajectoryError(f"driver {name!r}: expected a list of transforms, one per frame")
        if len(transforms) != frames:
            raise TrajectoryError(
                f"driver {name!r} has {len(transforms)} transforms but the file says frames = {frames}; "
                "every driver needs exactly one transform per frame"
            )
        for k, m in enumerate(transforms):
            why = rigid_problem(m) if isinstance(m, list) else "it is not a list of 16 numbers"
            if why:
                raise TrajectoryError(
                    f"driver {name!r}, frame {k}: not a rigid transform ({why}). Each frame must be "
                    "a 4x4 rotation plus translation in mm, written row by row, column vectors"
                )
    tag = data.get("source_tag")
    if tag is not None and tag not in SOURCE_TAGS:
        raise TrajectoryError(
            f"source_tag is {tag!r}; it must be one of {', '.join(SOURCE_TAGS)} (or leave it out if the "
            "origin of the motion is not known)"
        )
    settle = data.get("settle_until_frame")
    if settle is not None and (not isinstance(settle, int) or isinstance(settle, bool) or not 0 <= settle < frames):
        raise TrajectoryError(
            f"settle_until_frame is {settle!r}; it must be a whole frame number from 0 to {frames - 1} (the last "
            "frame of the gravity-only settle), or leave it out if the motion has no such settle"
        )
    known = {"format_version", "fps", "frames", "source", "source_tag", "settle_until_frame", "drivers", "landmarks"}
    return Trajectory(
        fps=fps,
        frames=frames,
        drivers={k: [list(m) for m in v] for k, v in drivers.items()},
        source=data.get("source", ""),
        landmarks=data.get("landmarks"),
        source_tag=tag,
        settle_until_frame=settle,
        extra={k: v for k, v in data.items() if k not in known},
    )


def read(path) -> Trajectory:
    path = Path(path)
    if not path.is_file():
        raise TrajectoryError(f"{path} does not exist; give the path of a trajectory.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TrajectoryError(f"{path} is not valid JSON (line {e.lineno}: {e.msg})") from None
    return from_json(data)


def write(path, trajectory: Trajectory) -> None:
    """One transform per line, so a diff shows which frames changed. Python's float repr
    round-trips exactly, so reading it back gives the same numbers."""
    data = trajectory.to_json()
    drivers = data.pop("drivers")
    lines = ["{"] + [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in data.items()]
    lines.append('  "drivers": {')
    names = list(drivers)
    for n, name in enumerate(names):
        lines.append(f"    {json.dumps(name)}: [")
        rows = [f"      [{', '.join(repr(float(v)) for v in m)}]" for m in drivers[name]]
        lines.append(",\n".join(rows))
        lines.append("    ]" + ("," if n < len(names) - 1 else ""))
    lines.append("  }")
    lines.append("}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
