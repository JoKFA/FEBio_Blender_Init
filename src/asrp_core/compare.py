"""How far two results are apart (T-34; docs/07 section 4.2). numpy only: no file formats, no Ziva, no FEBio.

Everything here takes shapes of the SAME mesh in the SAME coordinates (the core's: mm, Z up) as arrays of
(frames, vertices, 3) or (vertices, 3). Turning another program's output into that is the caller's job, through
asrp_core.asset.coords. Nothing here judges: the functions return numbers, and whether a difference is acceptable
is not decided in this project by a threshold (ADR-17).

The three numbers per frame are the ones docs/07 section 4.2 asks for: the mean distance over the vertices, the
distance 95 % of the vertices are below, and the largest.
"""

import numpy as np


class CompareError(ValueError):
    """The two things cannot be compared as given; the message says why."""


def _frames(a, what: str) -> np.ndarray:
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 2:
        a = a[None]
    if a.ndim != 3 or a.shape[2] != 3 or 0 in a.shape:
        raise CompareError(f"{what} must be (frames, vertices, 3) or (vertices, 3) with at least one vertex, got "
                           f"shape {a.shape}")
    return a


def _group(values: np.ndarray, vertices, what: str) -> np.ndarray:
    """values (frames, vertices, ...) limited to a vertex group given as indices or as a boolean mask."""
    if vertices is None:
        return values
    pick = np.asarray(vertices)
    if pick.size == 0 or (pick.dtype == bool and not pick.any()):
        raise CompareError(f"the vertex group is empty; {what} over no vertices is not a number")
    return values[:, pick if pick.dtype == bool else pick.astype(np.int64)]


def distances(a, b) -> np.ndarray:
    """Per frame and vertex, the straight-line distance between a and b: (frames, vertices). The two must have the
    same frames and the same vertices in the same order; a frame or vertex count that differs is an error, never
    cut to the shorter one."""
    a, b = _frames(a, "the first shape"), _frames(b, "the second shape")
    if a.shape != b.shape:
        raise CompareError(f"the two results differ in size: {a.shape[0]} frames of {a.shape[1]} vertices against "
                           f"{b.shape[0]} frames of {b.shape[1]} vertices. Compare the same frames of the same mesh")
    return np.linalg.norm(a - b, axis=2)


def per_frame(a, b, vertices=None) -> dict:
    """The difference between two results, frame by frame: {"frames", "vertices", "mean_mm": [...], "p95_mm": [...],
    "max_mm": [...], "worst": {...}}. `vertices` (indices or a boolean mask) limits it to a group. "worst" holds the
    largest of each of the three numbers over all frames and the frame it falls on."""
    d = _group(distances(a, b), vertices, "a difference")
    mean, p95, top = d.mean(axis=1), np.percentile(d, 95, axis=1), d.max(axis=1)
    worst = {}
    for name, values in (("mean_mm", mean), ("p95_mm", p95), ("max_mm", top)):
        at = int(np.argmax(values))
        worst[name] = {"value": float(values[at]), "frame": at}
    return {"frames": int(d.shape[0]), "vertices": int(d.shape[1]), "mean_mm": mean.tolist(), "p95_mm": p95.tolist(),
            "max_mm": top.tolist(), "worst": worst}


def displacement(frames, reference_frame: int = 0, direction=None, vertices=None) -> dict:
    """How far a result has moved from one of its own frames, frame by frame: {"max_mm", "mean_mm"} and, with a
    `direction` (any length; it is normalised), "along_mm": the mean of the displacement's component along it.
    With gravity's direction this is the sag: its largest, its mean, and its mean in the direction of gravity."""
    f = _frames(frames, "the result")
    if not 0 <= reference_frame < len(f):
        raise CompareError(f"reference frame {reference_frame} is outside the result's frames 0 to {len(f) - 1}")
    moved = _group(f - f[reference_frame], vertices, "a displacement")
    length = np.linalg.norm(moved, axis=2)
    out = {"reference_frame": int(reference_frame), "vertices": int(moved.shape[1]),
           "max_mm": length.max(axis=1).tolist(), "mean_mm": length.mean(axis=1).tolist()}
    if direction is not None:
        n = np.asarray(direction, dtype=np.float64)
        if n.shape != (3,) or not np.linalg.norm(n) > 0:
            raise CompareError(f"direction must be three numbers that are not all zero, got {direction!r}")
        out["along_mm"] = (moved @ (n / np.linalg.norm(n))).mean(axis=1).tolist()
    return out


def seen_from(frames, body_transforms) -> np.ndarray:
    """The result as seen from a rigid body: each frame's points taken back through that frame's transform of the
    body (4x4, column vectors, mm; one per frame, as in trajectory.json), so the body's own motion drops out.
    Returns (frames, vertices, 3)."""
    f = _frames(frames, "the result")
    if len(body_transforms) != len(f):
        raise CompareError(f"the result has {len(f)} frames but the body has {len(body_transforms)} transforms")
    out = np.empty_like(f)
    for i, t in enumerate(body_transforms):
        m = np.asarray(t, dtype=np.float64).reshape(4, 4)
        out[i] = (f[i] - m[:3, 3]) @ m[:3, :3]  # the inverse of p -> R p + t, for rows of points
    return out


def wobble(frames, body_transforms, reference_frame: int, vertices=None) -> dict:
    """How much a result moves against a rigid body beyond where it was at `reference_frame`: per frame, the
    largest distance (over the vertices) between the point seen from the body now and seen from the body then.
    {"reference_frame", "vertices", "per_frame_max_mm", "max_mm", "frame"}; max_mm and frame are over the frames
    after the reference only."""
    rel = seen_from(frames, body_transforms)
    if not 0 <= reference_frame < len(rel):
        raise CompareError(f"reference frame {reference_frame} is outside the result's frames 0 to {len(rel) - 1}")
    moved = _group(np.linalg.norm(rel - rel[reference_frame], axis=2), vertices, "a wobble")
    top = moved.max(axis=1)
    after = top[reference_frame + 1:]
    at = reference_frame + 1 + int(np.argmax(after)) if len(after) else reference_frame
    return {"reference_frame": int(reference_frame), "vertices": int(moved.shape[1]),
            "per_frame_max_mm": top.tolist(), "max_mm": float(top[at]), "frame": int(at)}


def decay(per_frame_max_mm, stop_frame: int, limit_mm: float, window: int | None = None) -> dict:
    """After the motion stops at `stop_frame`: how many frames later the wobble is FIRST below `limit_mm`, and from
    how many frames later it STAYS below it to the end of what was watched. They differ when the wobble comes back.
    Only `window` frames after the stop are looked at (default: all there are); with two results of different
    length, give both the same window. A number that is not reached inside the window is None: "not reached in
    the window", never a guess. {"stop_frame", "limit_mm", "window", "first_below", "stays_below"}."""
    values = np.asarray(per_frame_max_mm, dtype=np.float64)
    if not 0 <= stop_frame < len(values):
        raise CompareError(f"stop frame {stop_frame} is outside the frames 0 to {len(values) - 1}")
    after = values[stop_frame:]
    if window is not None:
        if window < 0 or stop_frame + window >= len(values):
            raise CompareError(f"a window of {window} frames after frame {stop_frame} needs frames up to "
                               f"{stop_frame + window}, the result ends at frame {len(values) - 1}")
        after = after[: window + 1]
    below = after < limit_mm
    first = int(np.argmax(below)) if below.any() else None
    stays = None
    if below[-1]:
        above = np.flatnonzero(~below)
        stays = int(above[-1]) + 1 if len(above) else 0
    return {"stop_frame": int(stop_frame), "limit_mm": float(limit_mm), "window": int(len(after) - 1),
            "first_below": first, "stays_below": stays}


def flipped_faces(rest, shape, faces) -> np.ndarray:
    """Which triangles of `shape` point the other way than in `rest` (their normals' dot product is below zero): a
    boolean mask over the faces. The same rule as plausibility.fold_counts counts by; this one says WHICH faces,
    so two results can be compared face by face."""
    rest, shape, faces = np.asarray(rest, dtype=np.float64), np.asarray(shape, dtype=np.float64), np.asarray(faces)
    if rest.shape != shape.shape or rest.ndim != 2 or rest.shape[1] != 3:
        raise CompareError(f"rest and shape must both be (vertices, 3), got {rest.shape} and {shape.shape}")

    def normals(points):
        a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
        return np.cross(b - a, c - a)

    n0 = normals(rest)
    length = np.linalg.norm(n0, axis=1)
    dot = np.einsum("ij,ij->i", normals(shape), n0 / np.maximum(length, 1e-12)[:, None])
    return (dot < 0) & (length > 0)


# --- T-11: the two numbers that do not need Ziva (ADR-25; docs/07 section 4.2) -------------------------------


def distance_to_target(frames, target, vertices=None) -> dict:
    """How far each frame of a result is from ONE target shape (the artist's target pose): the same three numbers
    per frame as `per_frame` ("frames", "vertices", "mean_mm", "p95_mm", "max_mm", "worst"). `target` is
    (vertices, 3) and is held against every frame; the vertex order and the units are the caller's to match."""
    f = _frames(frames, "the result")
    t = _frames(target, "the target pose")
    if t.shape[0] != 1:
        raise CompareError(f"the target pose is one shape of (vertices, 3), got {t.shape[0]} frames")
    return per_frame(f, np.broadcast_to(t, f.shape), vertices)


def rigid_prediction(reference_points, transform, reference_transform=None) -> np.ndarray:
    """Where points would move if they were glued to a rigid body: the body's transform at some frame (4x4, column
    vectors, mm) taken from its transform at the reference frame (identity when not given), applied to the
    points as they were at the reference frame. Returns the displacement, (vertices, 3)."""
    p = np.asarray(reference_points, dtype=np.float64)
    t = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    if reference_transform is not None:
        t = t @ np.linalg.inv(np.asarray(reference_transform, dtype=np.float64).reshape(4, 4))
    return p @ t[:3, :3].T + t[:3, 3] - p


def follow_ratio(frames, body_transforms, reference_frame: int, vertices, min_motion_mm: float = 1e-3) -> dict:
    """The follow ratio of a group of vertices (docs/07 section 4.2): u is the group's displacement from the
    reference frame, r what it would be if the group were glued to the body (`rigid_prediction`, same reference
    frame), and the ratio is sum(u . r) / sum(r . r), the signed least-squares factor: 1 follows the body fully,
    0 not at all, a negative number goes the other way.

    One number per frame. A frame where the body has not moved from the reference (its largest rigid displacement
    over the group is below `min_motion_mm`, so the denominator is zero or noise) has None, never a number:
    "not applicable". {"reference_frame", "vertices", "per_frame": [ratio | None], "moved_mean_mm": [...],
    "rigid_mean_mm": [...]}: the last two are the mean distance the group moved and the body's prediction."""
    f = _frames(frames, "the result")
    if len(body_transforms) != len(f):
        raise CompareError(f"the result has {len(f)} frames but the body has {len(body_transforms)} transforms")
    if not 0 <= reference_frame < len(f):
        raise CompareError(f"reference frame {reference_frame} is outside the result's frames 0 to {len(f) - 1}")
    group = _group(f, vertices, "a follow ratio")
    ref = group[reference_frame]
    ratios, moved_mean, rigid_mean = [], [], []
    for i in range(len(f)):
        u = group[i] - ref
        r = rigid_prediction(ref, body_transforms[i], body_transforms[reference_frame])
        moved_mean.append(float(np.linalg.norm(u, axis=1).mean()))
        rigid_mean.append(float(np.linalg.norm(r, axis=1).mean()))
        moves = float(np.linalg.norm(r, axis=1).max()) >= min_motion_mm
        ratios.append(float((u * r).sum() / (r * r).sum()) if moves else None)
    return {"reference_frame": int(reference_frame), "vertices": int(group.shape[1]), "per_frame": ratios,
            "moved_mean_mm": moved_mean, "rigid_mean_mm": rigid_mean}
