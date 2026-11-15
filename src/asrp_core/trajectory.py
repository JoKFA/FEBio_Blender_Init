"""The motion file, trajectory.json, and the hinge motion generator (T-05; docs/04 section 5.2).

Format `asrp-trajectory/1`, one JSON object:

    {
      "format_version": "asrp-trajectory/1",
      "fps": 30,                      # frames per second; must equal the scene's solver fps
      "frames": 46,                   # transforms per driver; frame 0 is the first entry
      "source": "free text: which controller output, or which generator, made this",
      "title": "Jaw opens 12 degrees (test motion)",   # optional: the name the Blender panel shows, one line of at
                                      #   most 60 characters; without it the panel shows the file name
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
      "landmarks": {                  # optional: the landmark layer's motion (T-09, docs/04 section 5.2)
        "names": ["oor_01", ...],     #   K unique landmark names, as listed in scene.json
        "translations_mm": [          #   one entry per frame; each holds K [x, y, z] triples, the landmark's
          [[x, y, z], ...], ...       #   translation relative to its rest position, mm, Z up
        ]
      }                               #   a landmark the file does not name does not move
    }

Each transform is a 4x4 rigid transform in mm, Z up: the world transform of the driver relative
to its rest pose, so a bone that follows it moves its rest-pose points p to T @ p. Column-vector
convention (translation in the last column), written row by row, so the translation is at
indices 3, 7 and 11. Maya stores its matrices the other way (row vectors, translation at 12-14);
convert before writing one here (ADR-21).
"""

import io
import json
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from asrp_core.asset import coords

FORMAT_VERSION = "asrp-trajectory/1"
SOURCE_TAGS = ("lab_setting", "ziva_default", "ours")  # the same three values as scene.SOURCES
# How far a transform may be from rigid (rotation part orthonormal with determinant 1, last row
# 0 0 0 1). Round-trip through text keeps ~1e-16; this only lets through rounding, not a scale.
RIGID_TOLERANCE = 1e-6
TITLE_MAX = 60  # characters of the optional "title": the panel's motion list shows it at the sidebar's default width


class TrajectoryError(ValueError):
    """The file cannot be read as a trajectory; the message says what is wrong and what to do."""


@dataclass
class Trajectory:
    fps: float
    frames: int
    drivers: dict[str, list[list[float]]]
    source: str = ""
    landmarks: object = None  # the validated "landmarks" section as read (None: absent); see landmark_translations
    source_tag: str | None = None  # "lab_setting" | "ziva_default" | "ours"; None: the file does not say
    settle_until_frame: int | None = None  # last frame of the gravity-only settle; None: the file does not say
    title: str | None = None  # the name the panel shows; None: the file has none (the panel shows the file name)
    extra: dict = field(default_factory=dict)  # unknown top-level keys, kept for the round trip

    def to_json(self) -> dict:
        data = {
            "format_version": FORMAT_VERSION,
            "fps": self.fps,
            "frames": self.frames,
            "source": self.source,
            "drivers": self.drivers,
        }
        if self.title is not None:
            data["title"] = self.title
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


def relative_blend_transforms(base_transforms, parent_transforms, factor) -> list[list[float]]:
    """A derived driver relative to another one (docs/04 section 5.1): per frame
    T = T_base exp(factor log(T_base^-1 T_of)), i.e. `factor` of the parent's motion as seen from the base. factor 0
    follows the base, factor 1 the parent; with the base at rest it is `blend_transforms`."""
    relative = []
    for b, p in zip(base_transforms, parent_transforms):
        relative.append((np.linalg.inv(np.array(b, dtype=float).reshape(4, 4)) @ np.array(p, dtype=float).reshape(4, 4))
                        .ravel().tolist())
    out = []
    for b, r in zip(base_transforms, blend_transforms(relative, factor)):
        m = np.array(b, dtype=float).reshape(4, 4) @ np.array(r, dtype=float).reshape(4, 4)
        out.append([float(v) for v in m.ravel()])
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


def _check_landmarks(section, frames: int) -> None:
    if not isinstance(section, dict):
        raise TrajectoryError("'landmarks' must be an object with 'names' and 'translations_mm'")
    for key in ("names", "translations_mm"):
        if key not in section:
            raise TrajectoryError(
                f"landmarks: '{key}' is missing; give 'names' (a list) and 'translations_mm' (one list per frame)"
            )
    names, per_frame = section["names"], section["translations_mm"]
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        raise TrajectoryError("landmarks.names must be a list of non-empty strings")
    seen = set()
    for n in names:
        if n in seen:
            raise TrajectoryError(f"landmarks.names lists {n!r} twice; give each landmark once")
        seen.add(n)
    if not isinstance(per_frame, list) or len(per_frame) != frames:
        found = len(per_frame) if isinstance(per_frame, list) else type(per_frame).__name__
        raise TrajectoryError(
            f"landmarks.translations_mm has {found} frames but the file says frames = {frames}; "
            "give exactly one list of translations per frame"
        )
    for f, row in enumerate(per_frame):
        if not isinstance(row, list) or len(row) != len(names):
            found = len(row) if isinstance(row, list) else type(row).__name__
            raise TrajectoryError(
                f"landmarks.translations_mm, frame {f}: {found} entries for {len(names)} landmarks; "
                "give one [x, y, z] per name, in the order of 'names'"
            )
        for i, t in enumerate(row):
            ok = (isinstance(t, list) and len(t) == 3
                  and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in t))
            if not ok:
                raise TrajectoryError(
                    f"landmarks.translations_mm, frame {f}, landmark {names[i]!r}: expected three finite numbers "
                    f"[x, y, z] in mm, got {t!r}"
                )


def landmark_translations(trajectory: Trajectory) -> tuple[list[str], np.ndarray] | None:
    """The landmark names and their translations as a (frames, K, 3) float64 array, mm relative to rest,
    Z up; None when the trajectory has no landmark section."""
    if trajectory.landmarks is None:
        return None
    names = list(trajectory.landmarks["names"])
    t = np.asarray(trajectory.landmarks["translations_mm"], dtype=np.float64)
    return names, t.reshape(trajectory.frames, len(names), 3)


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
    title = data.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX
                              or title != title.strip() or any(ord(c) < 32 for c in title)):
        raise TrajectoryError(
            f"title is {title!r}; it must be one line of text, 1 to {TITLE_MAX} characters, without spaces at either end "
            "(or leave it out: the panel then shows the file name)"
        )
    settle = data.get("settle_until_frame")
    if settle is not None and (not isinstance(settle, int) or isinstance(settle, bool) or not 0 <= settle < frames):
        raise TrajectoryError(
            f"settle_until_frame is {settle!r}; it must be a whole frame number from 0 to {frames - 1} (the last "
            "frame of the gravity-only settle), or leave it out if the motion has no such settle"
        )
    if data.get("landmarks") is not None:
        _check_landmarks(data["landmarks"], frames)
    known = {"format_version", "fps", "frames", "source", "source_tag", "settle_until_frame", "drivers", "landmarks",
             "title"}
    return Trajectory(
        fps=fps,
        frames=frames,
        drivers={k: [list(m) for m in v] for k, v in drivers.items()},
        source=data.get("source", ""),
        landmarks=data.get("landmarks"),
        source_tag=tag,
        settle_until_frame=settle,
        title=title,
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
    landmarks = data.pop("landmarks", None)
    lines = ["{"] + [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in data.items()]
    if landmarks is not None:  # one frame per line, like the drivers
        lines.append('  "landmarks": {')
        for key, value in landmarks.items():  # keys this version does not know are kept, like the top-level ones
            if key not in ("names", "translations_mm"):
                lines.append(f"    {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
        lines.append(f'    "names": {json.dumps(landmarks["names"], ensure_ascii=False)},')
        lines.append('    "translations_mm": [')
        lines.append(",\n".join(f"      {json.dumps(row)}" for row in landmarks["translations_mm"]))
        lines.append("    ]")
        lines.append("  },")
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


# --- the lab's motion files (T-34; docs/03 section 7) ----------------------------------------------------------
#
# A lab motion file (combined_checkpoints.pkl) is a list of steps. Each step is 3603 numbers: the translations of
# the 300 lip landmarks (900), the jaw joint's Euler angles in degrees (3), then 900 each for the left eye, the
# right eye and the forehead. The numbers are offsets from the START of that segment; the file does not hold the
# starting pose. Only a segment that starts at rest can therefore be turned into a trajectory on its own.

LAB_STEP_NUMBERS = 3603
LAB_LIP_LANDMARKS = 300
LAB_FIRST_MOTION_FRAME = 15  # frames 0-14 are the gravity-only settle; step i falls on frame 15 + i
LAB_HOLD_FRAMES = 10  # the last pose is held this long, as in the Ziva reference runs (frames 37-46 for 22 steps)
LAB_WORLD_AXIS = (1.0, 0.0, 0.0)  # the lab's interface turns the jaw about world X by the file's pitch
# A pickle can name any callable and Python would call it on load. Letting numpy's own names through is not enough
# either: with numpy.dtype and numpy's _reconstruct a file can build an array whose bytes numpy then treats as
# pointers to Python objects, and reading it crashes the process (found by an outside review, 2026-11-13). So
# NOTHING of numpy runs while the file is unpickled. The five names an array or a number in a pickle needs are
# answered by the small stand-ins below, which only record what the file says; the arrays are then built here, from
# the file's raw bytes, and only for plain number types.
_NUMBER_TYPES = frozenset({"f2", "f4", "f8", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8", "b1"})
_BYTE_ORDERS = frozenset({"<", ">", "=", "|"})
_MAX_ARRAY_BYTES = 1 << 30


class _NotData(pickle.UnpicklingError):
    """The file holds something other than plain containers and arrays of numbers."""


class _DtypeNote:
    """What the file says where a numpy.dtype would be: a number type and a byte order, nothing else."""

    def __init__(self, code=None, *_):
        if not isinstance(code, str) or code not in _NUMBER_TYPES:
            raise _NotData(f"an array of type {code!r}; only plain number types are read")
        self.code, self.order = code, "="

    def __setstate__(self, state):
        # numpy's dtype state: (version, byte order, subarray, names, fields, item size, alignment, flags[, metadata])
        if (not isinstance(state, tuple) or len(state) < 8 or state[1] not in _BYTE_ORDERS
                or any(part is not None for part in state[2:5])):
            raise _NotData("an array type with fields, a subarray or an unknown byte order; only plain numbers are read")
        self.order = state[1]

    def numpy(self) -> np.dtype:
        return np.dtype(self.code).newbyteorder(self.order)


def _array_from(raw, dtype, shape, fortran=False) -> np.ndarray:
    """A numeric array from the file's own bytes; every size is checked before numpy touches them."""
    if not isinstance(dtype, _DtypeNote):
        raise _NotData("an array without a plain number type")
    if not isinstance(raw, (bytes, bytearray, memoryview, pickle.PickleBuffer)):
        raise _NotData(f"an array whose content is a {type(raw).__name__}, not bytes")
    if (not isinstance(shape, tuple) or len(shape) > 8
            or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in shape)):
        raise _NotData(f"an array of shape {shape!r}")
    raw, kind = bytes(raw), dtype.numpy()
    count = math.prod(shape)
    if len(raw) > _MAX_ARRAY_BYTES or count * kind.itemsize != len(raw):
        raise _NotData(f"an array that says shape {shape} of {kind} but holds {len(raw)} bytes")
    return np.frombuffer(raw, dtype=kind).reshape(shape, order="F" if fortran else "C").astype(kind.newbyteorder("="))


class _ArrayNote:
    """What the file says where a numpy.ndarray would be; `value` is the array once its state has been read."""

    value = None

    def __setstate__(self, state):
        # numpy's array state: (version, shape, dtype, is Fortran order, raw bytes)
        if not isinstance(state, tuple) or len(state) != 5:
            raise _NotData("an array in a form this reader does not know")
        _, shape, dtype, fortran, raw = state
        self.value = _array_from(raw, dtype, shape, bool(fortran))


def _note_reconstruct(cls=None, *_):  # stands in for numpy's _reconstruct(ndarray, (0,), b"b")
    if cls is not _ArrayNote:
        raise _NotData("a numpy object that is not a plain array")
    return _ArrayNote()


def _note_frombuffer(raw=None, dtype=None, shape=None, order="C", *_):  # numpy's _frombuffer (pickle protocol 5)
    note = _ArrayNote()
    note.value = _array_from(raw, dtype, tuple(shape) if isinstance(shape, (tuple, list)) else shape, order == "F")
    return note


def _note_scalar(dtype=None, raw=None, *_):  # numpy's scalar(dtype, bytes): one number
    return _array_from(raw, dtype, (1,))[0].item()


def _note_latin1(text=None, encoding="latin1", *_):  # _codecs.encode: how pickle protocol 2 writes an array's bytes
    if not isinstance(text, str) or encoding not in ("latin1", "latin-1"):
        raise _NotData("bytes written in a form this reader does not know")
    return text.encode("latin1")


def _note_empty_bytes(*args):  # bytes(): how pickle protocol 2 writes an empty array's bytes
    if args:
        raise _NotData("bytes written in a form this reader does not know")
    return b""


_PICKLE_STAND_INS = {
    ("_codecs", "encode"): _note_latin1,
    ("__builtin__", "bytes"): _note_empty_bytes,
    ("builtins", "bytes"): _note_empty_bytes,
    **{(m, "_reconstruct"): _note_reconstruct for m in ("numpy.core.multiarray", "numpy._core.multiarray")},
    **{(m, "scalar"): _note_scalar for m in ("numpy.core.multiarray", "numpy._core.multiarray")},
    **{(m, "_frombuffer"): _note_frombuffer for m in ("numpy.core.numeric", "numpy._core.numeric")},
    ("numpy", "ndarray"): _ArrayNote,
    ("numpy", "dtype"): _DtypeNote,
}


class _DataOnlyUnpickler(pickle.Unpickler):
    """Lists, tuples, dicts, numbers, strings and arrays of numbers; anything else in the file is refused. No
    name in the file is ever looked up in a module: the few numpy names get the stand-ins above."""

    def find_class(self, module, name):
        try:
            return _PICKLE_STAND_INS[(module, name)]
        except KeyError:
            raise _NotData(f"the file asks Python to load {module}.{name}") from None


def _plain(value, depth: int = 0):
    """The unpickled structure with every array note replaced by its array."""
    if depth > 16:
        raise _NotData("containers nested deeper than any lab file")
    if isinstance(value, _ArrayNote):
        if value.value is None:
            raise _NotData("an array without content")
        return value.value
    if isinstance(value, (_DtypeNote, type)) or callable(value):
        raise _NotData("a type or a function where data should be")
    if isinstance(value, (list, tuple)):
        return type(value)(_plain(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return {_plain(k, depth + 1): _plain(v, depth + 1) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes)):
        return value
    raise _NotData(f"a {type(value).__name__} where data should be")


def read_lab_data(path, what: str = "lab data file"):
    """One of the lab's pickle files as plain Python data: lists, tuples, dicts, numbers, strings and numeric
    numpy arrays. The file is read as DATA: nothing it names is imported or called, numpy does not take part in
    unpickling it, and an array is built only from a plain number type and bytes of exactly the right length.
    Anything else in the file is refused with a TrajectoryError. Use it only on files that come straight from the
    lab."""
    path = Path(path)
    if not path.is_file():
        raise TrajectoryError(f"{path} does not exist; give the path of a {what}")
    return lab_data_from_bytes(path.read_bytes(), path, what)


def lab_data_from_bytes(data: bytes, path="the file", what: str = "lab data file"):
    """`read_lab_data` for bytes already in memory (for a caller that hashes the bytes it reads); `path` is only
    used in the error message."""
    try:
        return _plain(_DataOnlyUnpickler(io.BytesIO(data)).load())
    except _NotData as e:
        raise TrajectoryError(
            f"{path} is not a plain {what} ({e}); only lists and numpy arrays of numbers are read. "
            "Nothing from the file was run. If the lab changed the file's format, the reader has to be extended "
            "on purpose (src/asrp_core/trajectory.py)") from None
    except Exception as e:  # a damaged or truncated file: EOFError, ValueError, ... depending on where it breaks
        raise TrajectoryError(f"{path} cannot be read as a {what} ({type(e).__name__}: {e}); "
                              "fetch the file again") from None


def read_lab_motion(path) -> np.ndarray:
    """A lab motion file as a (steps, 3603) float64 array, read as data through `read_lab_data`. Once a motion is
    written as trajectory.json nothing reads the pickle again."""
    path = Path(path)
    data = read_lab_data(path, "lab motion file (combined_checkpoints.pkl)")
    if not isinstance(data, (list, tuple)) or not data:
        raise TrajectoryError(f"{path} holds a {type(data).__name__}, not a list of steps; a lab motion file is a "
                              "list with one vector per step")
    try:
        steps = np.stack([np.asarray(step, dtype=np.float64).ravel() for step in data])
    except (ValueError, TypeError):
        raise TrajectoryError(f"{path}: the steps are not vectors of numbers of one length; a lab motion file has "
                              f"{LAB_STEP_NUMBERS} numbers per step") from None
    if steps.shape[1] != LAB_STEP_NUMBERS:
        raise TrajectoryError(
            f"{path}: each step has {steps.shape[1]} numbers, a lab motion file has {LAB_STEP_NUMBERS} "
            "(300 lip landmarks x 3, 3 jaw angles, then 900 each for the two eyes and the forehead)")
    if not np.isfinite(steps).all():
        raise TrajectoryError(f"{path} holds a number that is not finite; fetch the file again")
    return steps


def from_lab_motion(steps, *, driver: str, pivot_mm, landmark_names, mm_per_scene_unit: float, fps,
                    hold_frames: int = LAB_HOLD_FRAMES, source: str = "") -> Trajectory:
    """One lab segment THAT STARTS AT REST as a trajectory: frames 0-14 at rest (the gravity-only settle), step i
    on frame 15 + i, then the last pose held for `hold_frames` frames (22 steps give the 47 frames of the Ziva
    reference runs).

    The jaw: the lab's interface turns the jaw joint about world X by the file's pitch, the first of the three jaw
    angles, in degrees (this is also how the motion was played into Ziva on 2026-11-12). World X is the same
    line before and after the change of axes, so the driver is a right-handed turn by that signed angle about
    +X through `pivot_mm` (the joint's position, mm, Z up). A file that turns the jaw about another axis is
    refused rather than read partly.

    The landmarks: columns 0-899 are the translations of the 300 lip landmarks from their rest positions, scene
    units, Y up; they become mm, Z up through asset.coords and nothing else. `landmark_names` are the scene's 300
    names in the file's column order. The other 2700 numbers belong to tissues this scene does not have; they are
    not read.

    The file does not say where its segment starts, so the caller must know that it starts at rest: a segment
    from another pose (AA back to neutral, say) would be played from the wrong start without any error here."""
    steps = np.asarray(steps, dtype=np.float64)
    if steps.ndim != 2 or steps.shape[1] != LAB_STEP_NUMBERS or not len(steps):
        raise TrajectoryError(f"expected (steps, {LAB_STEP_NUMBERS}) numbers, got shape {steps.shape}; "
                              "read the file with read_lab_motion")
    names = list(landmark_names)
    if len(names) != LAB_LIP_LANDMARKS:
        raise TrajectoryError(f"the scene lists {len(names)} landmarks, the lab motion moves {LAB_LIP_LANDMARKS}; "
                              "import the lab asset again so the scene carries the lab's 300 lip landmarks")
    if not isinstance(hold_frames, int) or isinstance(hold_frames, bool) or hold_frames < 0:
        raise TrajectoryError(f"hold_frames is {hold_frames!r}; it must be a whole number of frames, 0 or more")
    jaw = steps[:, 3 * LAB_LIP_LANDMARKS:3 * LAB_LIP_LANDMARKS + 3]
    if np.abs(jaw[:, 1:]).max() != 0.0:
        raise TrajectoryError(
            "this lab motion turns the jaw about more than its pitch (the second or third jaw angle is not 0). "
            "Only the pitch about world X is converted so far; a motion like this is not converted partly "
            "(docs/09 T-10)")
    rest = [0.0] * LAB_FIRST_MOTION_FRAME
    angles = rest + [math.radians(a) for a in jaw[:, 0]] + [math.radians(jaw[-1, 0])] * hold_frames
    zero = np.zeros((LAB_FIRST_MOTION_FRAME, LAB_LIP_LANDMARKS, 3))
    moved = np.stack([coords.to_mm_zup(step[:3 * LAB_LIP_LANDMARKS].reshape(LAB_LIP_LANDMARKS, 3), mm_per_scene_unit)
                      for step in steps])
    translations = np.concatenate([zero, moved, np.repeat(moved[-1:], hold_frames, axis=0)])
    return Trajectory(
        fps=fps, frames=len(angles),
        drivers={driver: hinge_transforms(pivot_mm, LAB_WORLD_AXIS, angles)},
        landmarks={"names": names, "translations_mm": translations.tolist()},
        source_tag="lab_setting", settle_until_frame=LAB_FIRST_MOTION_FRAME - 1,
        source=(f"{source + ': ' if source else ''}a lab motion of {len(steps)} steps that starts at rest; frames 0-"
                f"{LAB_FIRST_MOTION_FRAME - 1} at rest, step i on frame {LAB_FIRST_MOTION_FRAME} + i, the last pose "
                f"held {hold_frames} frames; {driver} turns about world X by the file's pitch (last "
                f"{jaw[-1, 0]:.5f} degrees); the {LAB_LIP_LANDMARKS} lip landmarks move by the file's offsets; the "
                "eyes' and the forehead's offsets are not used"),
    )
