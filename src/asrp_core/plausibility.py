"""The plausibility checks every run on the lab's model gets (docs/07 section 3, T-06a).

Five checks, each a function of plain arrays so that a test can make it fail on purpose:

(a) `motion_completed`: FEBio reached the end of the motion with every frame logged. Steps FEBio cut and
    retried are a success, but they are counted and reported.
(b) `follows_bones`: on every frame, each node a hard attachment joined to a rigid body, and each hard
    display vertex (through the embedding), sits where that body's transform puts its rest position,
    within HARD_TOLERANCE_MM. Spring attachments are only reported (largest and mean deviation of their
    display vertices from the same place); they are meant to give.
(b2) `anchors_follow_bodies`: on every frame, each spring anchor node (the nodes joined to the jaw and to the
    lip-corner anchor rigid bodies, and to any other body a spring group goes to) sits where its rigid body's
    transform puts its rest position, within ANCHOR_TOLERANCE_MM (geometric mm, after dividing by k). This is
    the real-data check of the rigid motion itself: (b) only covers the lips that are on the fixed skull.
(c) `gravity_sag`: the display vertices no attachment holds, averaged over the last five frames of the
    gravity-only settle (the trajectory's settle_until_frame n: frames max(1, n-4)..n, never frame 0, the rest
    pose, whose sag is 0; one frame alone aliases the undamped ringing, docs/05 pit 2; not run when n is 0), have moved along the scene's gravity direction by about the amount
    the model predicts (`expected_sag`): rho |g| k L^2 / (2 E) geometric mm, the sag of a bar of length L
    hanging from one end under its own weight, with rho and E the soft tissue's density and Young's
    modulus, k the physics length scale and L the largest distance from a free display vertex to the
    nearest held one. It passes within a factor SAG_FACTOR either way (measured on the lips: 0.65 of the
    estimate, and proportional to 1/E like the estimate). This still only finds gross errors (a flipped
    sign, a unit off by 100, E or the density off by 10 times or more); it does not prove the scale.

(d) `tet_mesh_valid`: on every frame, every tet's signed volume has the sign it had at rest (ratio of its
    volume to its rest volume above 0). A tet turned inside out means the solution is not a real deformation
    and the display mesh it carries is wrong even though the run "converged". The same function reports the
    smallest and largest volume ratio.

`relative_motion` is not a check either: how far the free display vertices move against a rigid body (the head)
beyond a reference frame (the settled shape), per frame. Reported, not judged (T-28).

`surface_health` is not a check either (the five checks look only at the physics tet mesh): how many faces of the display
surface have turned over against the rest surface, and how far its edges have shrunk or grown, at the last frame and at the
worst frame. Reported, not judged. A turned-over face (normal against the rest normal) is not a proof of
self-intersection; intersections are not measured. `folds` is the same count for one frame.

`tissue_step` is also only reported: how far the tet nodes moved between two frames (the settle frame and the one
before it), so a reader can see whether the tissue was still moving when the settled shape was taken.

`return_to_settled` is not a check but a measurement: once the drivers are back at rest after the motion, how
far the tet nodes are from the shape they had after the gravity-only settle. Reported, not judged.

All positions are geometric mm (what `run` writes after dividing by k).
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from asrp_core import tetmesh
from asrp_core.asset import coords

HARD_TOLERANCE_MM = 1e-3
ANCHOR_TOLERANCE_MM = 1e-3
SAG_FACTOR = 10.0  # check (c) passes between estimate / SAG_FACTOR and estimate * SAG_FACTOR


@dataclass
class Check:
    name: str
    passed: bool | None  # None: could not be run (the reason is in message)
    message: str
    numbers: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"name": self.name, "passed": self.passed, "message": self.message, "numbers": self.numbers}


def motion_completed(status: str, frames: int, logged_frames: list[int], retries: int,
                     failure: str | None = None) -> Check:
    """(a). frames: the trajectory's frame count (0..frames-1); FEBio logs 1..frames-1 (pit 15)."""
    want = list(range(1, frames))
    numbers = {"status": status, "frames": frames, "frames_logged": len(logged_frames), "retries": retries}
    if status != "complete":
        return Check("motion completed", False, f"the run is {status}" + (f": {failure}" if failure else ""), numbers)
    if sorted(logged_frames) != want:
        missing = sorted(set(want) - set(logged_frames))
        return Check("motion completed", False, f"FEBio logged {len(logged_frames)} of the {len(want)} frames after frame 0"
                     + (f"; missing frame(s) {', '.join(map(str, missing[:10]))}" + (" ..." if len(missing) > 10 else "")
                        if missing else "; frames do not match"), numbers)
    return Check("motion completed", True, f"all {frames} frames; FEBio cut and retried a step {retries} times", numbers)


def _moved(transform, points: np.ndarray) -> np.ndarray:
    m = np.asarray(transform, dtype=float).reshape(4, 4)
    return points @ m[:3, :3].T + m[:3, 3]


IDENTITY = np.eye(4).ravel().tolist()


def follows_bones(groups: list[dict], rest_nodes: np.ndarray, node_frames: np.ndarray, rest_display: np.ndarray,
                  display_frames: np.ndarray, transforms: dict, tolerance: float = HARD_TOLERANCE_MM) -> Check:
    """(b). groups: [{"name", "kind", "target", "nodes": tet node indices, "vertices": display indices}].
    transforms: target -> per-frame transforms (None for a fixed body). node_frames (F, n, 3),
    display_frames (F, v, 3)."""
    frames = len(node_frames)
    worst_node = worst_vertex = 0.0
    hard_groups, springs = [], {}
    for g in groups:
        motion = transforms.get(g["target"]) or [IDENTITY] * frames
        nodes, verts = np.asarray(g["nodes"], dtype=int), np.asarray(g["vertices"], dtype=int)
        node_dev = np.array([np.linalg.norm(node_frames[f][nodes] - _moved(motion[f], rest_nodes[nodes]), axis=1).max()
                             if len(nodes) else 0.0 for f in range(frames)])
        vert_dev = np.stack([np.linalg.norm(display_frames[f][verts] - _moved(motion[f], rest_display[verts]), axis=1)
                             for f in range(frames)])
        if g["kind"] == "hard":
            hard_groups.append(g["name"])
            worst_node = max(worst_node, float(node_dev.max()))
            worst_vertex = max(worst_vertex, float(vert_dev.max()))
        else:
            springs[g["name"]] = {"max_mm": float(vert_dev.max()), "mean_mm": float(vert_dev.mean()),
                                  "worst_frame": int(np.unravel_index(np.argmax(vert_dev), vert_dev.shape)[0])}
    numbers = {"hard_groups": hard_groups, "hard_nodes_max_deviation_mm": worst_node,
               "hard_display_vertices_max_deviation_mm": worst_vertex, "tolerance_mm": tolerance,
               "frames": frames, "spring_display_deviation": springs}
    if not hard_groups:
        return Check("hard attachments follow their bones", None, "no hard attachment in this scene", numbers)
    ok = worst_node < tolerance and worst_vertex < tolerance
    return Check("hard attachments follow their bones", ok,
                 f"on all {frames} frames the hard nodes are at most {worst_node:.2e} mm and the hard display vertices "
                 f"{worst_vertex:.2e} mm from where their bone puts them (limit {tolerance:g} mm)", numbers)


def anchors_follow_bodies(rest: np.ndarray, targets: list[str], frames_pos: np.ndarray, transforms: dict,
                          tolerance: float = ANCHOR_TOLERANCE_MM) -> Check:
    """(b2). rest (a, 3): the anchor nodes' rest positions, geometric mm; targets: the rigid body each is joined to;
    frames_pos (F, a, 3): where FEBio put them (geometric mm); transforms: body -> per-frame transforms (None: fixed)."""
    frames = len(frames_pos)
    numbers = {"anchor_nodes": int(len(rest)), "frames": frames, "tolerance_mm": tolerance,
               "bodies": sorted(set(targets))}
    if not len(rest):
        return Check("spring anchors follow their rigid bodies", True, "no spring anchor in this scene; nothing to check",
                     numbers)
    target = np.array(targets)
    per_body = {}
    for body in sorted(set(targets)):
        idx = np.flatnonzero(target == body)
        motion = transforms.get(body) or [IDENTITY] * frames
        dev = max(float(np.linalg.norm(frames_pos[f][idx] - _moved(motion[f], rest[idx]), axis=1).max())
                  for f in range(frames))
        per_body[body] = {"anchor_nodes": int(len(idx)), "max_deviation_mm": dev}
    worst = max(v["max_deviation_mm"] for v in per_body.values())
    numbers |= {"max_deviation_mm": worst, "per_body": per_body}
    detail = "; ".join(f"{b}: {v['anchor_nodes']} nodes, {v['max_deviation_mm']:.2e} mm" for b, v in per_body.items())
    return Check("spring anchors follow their rigid bodies", worst < tolerance,
                 f"on all {frames} frames the {len(rest)} spring anchor nodes are at most {worst:.2e} mm from where their "
                 f"rigid body puts them (limit {tolerance:g} mm; {detail})", numbers)


@dataclass
class SagEstimate:
    sag_mm: float  # rho |g| k L^2 / (2 E), geometric mm
    free_length_mm: float  # L: the largest distance from a free display vertex to the nearest held one
    density_t_per_mm3: float
    youngs_modulus_mpa: float
    k: float


def free_length(rest_display: np.ndarray, free: np.ndarray, held: np.ndarray, chunk: int = 256) -> float:
    """L: the largest straight-line distance (geometric mm) from a free display vertex to the nearest held one,
    on the rest mesh. In chunks, so the free-by-held distance table never has to be in memory at once."""
    held_points = rest_display[held]
    worst = 0.0
    for start in range(0, len(free), chunk):
        block = rest_display[free[start:start + chunk]]
        nearest = np.sqrt(((block[:, None, :] - held_points[None, :, :]) ** 2).sum(axis=2)).min(axis=1)
        worst = max(worst, float(nearest.max()))
    return worst


def expected_sag(rest_display: np.ndarray, free: np.ndarray, held: np.ndarray, gravity, density: float,
                 youngs_modulus: float, k: float) -> SagEstimate | None:
    """The sag (c) expects, or None when there is nothing to estimate from (no held vertex, no free vertex or no
    gravity). density in t/mm^3, E in MPa, gravity in mm/s^2 (the units give N/mm^3 x mm^2 / (N/mm^2) = mm)."""
    g = float(np.linalg.norm(np.asarray(gravity, dtype=float)))
    if not len(held) or not len(free) or not g > 0:
        return None
    length = free_length(rest_display, free, held)
    return SagEstimate(density * g * k * length ** 2 / (2 * youngs_modulus), length, density, youngs_modulus, k)


def gravity_sag(rest_display: np.ndarray, display_frames: np.ndarray, free: np.ndarray, gravity,
                estimate: SagEstimate | None, frames: range, factor: float = SAG_FACTOR) -> Check:
    """(c). free: display vertex indices no attachment holds; gravity: the scene's physical gravity vector;
    estimate: from `expected_sag` (None: not run); frames: the frames to average (the end of the gravity-only
    settle). Passes when estimate / factor <= the measured mean sag <= estimate * factor."""
    numbers = {"free_vertices": int(len(free)), "frames": [frames.start, frames.stop - 1]}
    if len(display_frames) < frames.stop:
        return Check("gravity sag", None, f"the motion has {len(display_frames)} frames, the check needs frames "
                     f"{frames.start}-{frames.stop - 1}", numbers)
    g = np.asarray(gravity, dtype=float)
    if not np.linalg.norm(g) > 0 or not len(free) or estimate is None:
        return Check("gravity sag", None, "no gravity, no free vertex or no attachment to measure the free length from",
                     numbers)
    lo, hi = estimate.sag_mm / factor, estimate.sag_mm * factor
    numbers |= {"expected_sag_mm": estimate.sag_mm, "free_length_mm": estimate.free_length_mm,
                "range_mm": [lo, hi], "factor": factor, "k": estimate.k,
                "density_t_per_mm3": estimate.density_t_per_mm3, "E_mpa": estimate.youngs_modulus_mpa}
    down = g / np.linalg.norm(g)
    shift = np.mean([display_frames[f][free] for f in frames], axis=0) - rest_display[free]
    sag = float((shift @ down).mean())
    numbers |= {"mean_sag_along_gravity_mm": sag, "mean_dz_mm": float(shift[:, 2].mean())}
    ok = lo <= sag <= hi
    direction = "along gravity (down)" if sag > 0 else "against gravity (up)"
    return Check("gravity sag", ok, f"free vertices moved {abs(sag):.4f} mm {direction} on average over frames "
                 f"{frames.start}-{frames.stop - 1}; the model expects {estimate.sag_mm:.4f} mm (rho |g| k L^2 / 2E with "
                 f"L = {estimate.free_length_mm:.2f} mm) and the check passes from {lo:.3g} to {hi:.3g} mm down; it "
                 "catches a sign error or a gross error in E, density, gravity or units, not a small one", numbers)


def tet_mesh_valid(rest_nodes: np.ndarray, tets: np.ndarray, node_frames: np.ndarray) -> Check:
    """(d). rest_nodes (n, 3), tets (t, 4), node_frames (F, n, 3), geometric mm. Per frame, each tet's signed volume
    over its rest signed volume; the check fails if any ratio is not above 0 on any frame. A ratio that is not a
    finite number fails too (a missing or NaN position, or a tet whose rest volume is zero or not finite, which
    makes the ratio inf or NaN) and is counted in `inverted_tets`. Computed under `np.errstate`, so a flat rest tet
    gives a failed check, not a numpy RuntimeWarning."""
    rest = tetmesh.signed_volumes(rest_nodes, tets)
    lowest, lowest_frame, highest = np.inf, 0, -np.inf
    inverted, frames_with = 0, 0
    for f in range(len(node_frames)):
        with np.errstate(all="ignore"):
            ratio = tetmesh.signed_volumes(node_frames[f], tets) / rest
        ratio = np.where(np.isfinite(ratio), ratio, -np.inf)  # NaN, inf (flat rest tet) or missing: counts as inverted
        bad = int((ratio <= 0).sum())
        inverted += bad
        frames_with += bad > 0
        if ratio.min() < lowest:
            lowest, lowest_frame = float(ratio.min()), f
        highest = max(highest, float(ratio.max()))
    def finite(x):  # None, never NaN or inf, in the report: JSON has no such number
        return float(x) if np.isfinite(x) else None

    numbers = {"min_volume_ratio": finite(lowest), "min_volume_ratio_frame": lowest_frame,
               "max_volume_ratio": finite(highest),
               "inverted_tets": inverted, "frames_with_inverted_tets": frames_with, "tets": int(len(tets)),
               "frames": int(len(node_frames))}
    if inverted:
        return Check("the tet mesh stays valid", False,
                     f"{inverted} tet volumes are zero or turned inside out, on {frames_with} of {len(node_frames)} frames "
                     f"(smallest volume / rest volume {lowest:.3g} at frame {lowest_frame}); the display mesh carried by "
                     "them is wrong. Soften the motion, raise the substeps or remesh", numbers)
    return Check("the tet mesh stays valid", True,
                 f"on all {len(node_frames)} frames every one of the {len(tets)} tets keeps its orientation; volume / rest "
                 f"volume is between {lowest:.3f} (frame {lowest_frame}) and {highest:.3f}", numbers)


def relative_motion(rest_display: np.ndarray, display_frames: np.ndarray, free: np.ndarray, transforms,
                    reference_frame: int) -> dict:
    """Not a check (T-28): per frame, the largest distance of a free display vertex from where it was at
    `reference_frame`, both seen from a rigid body (each frame's position taken back through that frame's inverse
    transform of the body, so the body's own motion cancels). transforms: the body's per-frame transforms (None: at
    rest, so this is the motion in the world). Geometric mm. max_mm and frame are over the frames after the
    reference only. With the head as the body and the settled frame as the reference, this is how much the lips move
    against the head beyond the settle (the head shake's amplitude)."""
    frames = len(display_frames)
    motion = transforms or [IDENTITY] * frames
    if not len(free):
        return {"per_frame_max_mm": [0.0] * frames, "max_mm": 0.0, "frame": 0, "free_vertices": 0}

    def seen(f):
        m = np.asarray(motion[f], dtype=float).reshape(4, 4)
        return (display_frames[f][free] - m[:3, 3]) @ m[:3, :3]  # R^T (x - t), row by row

    ref = seen(reference_frame)
    per_frame = [float(np.linalg.norm(seen(f) - ref, axis=1).max()) for f in range(frames)]
    # The maximum is taken after the reference frame: before it, the curve is the settle itself (frame 0 is the rest
    # pose, its distance from the settled shape is the gravity sag), not motion against the head.
    after = per_frame[reference_frame + 1:]
    at = reference_frame + 1 + int(np.argmax(after)) if after else reference_frame
    return {"per_frame_max_mm": per_frame, "max_mm": per_frame[at], "frame": at, "free_vertices": int(len(free))}


def return_to_settled(node_frames: np.ndarray, settle: int, transforms: list, tolerance: float = 1e-9) -> dict:
    """Once every driver is back at rest, how far are the tet nodes from their positions at frame `settle`?
    transforms: the per-frame transforms of every moving body (None entries skipped). Over every frame after
    `settle` on which all of them are the identity within `tolerance`: the frame numbers, and the largest and
    the mean distance (geometric mm) of any node from where it was at `settle`."""
    eye = np.eye(4).ravel()
    moving = [np.asarray(t, dtype=float).reshape(len(t), 16) for t in transforms if t is not None]
    frames = [f for f in range(settle + 1, len(node_frames))
              if all(np.abs(t[f] - eye).max() <= tolerance for t in moving)]
    if not frames:
        return {"frames": []}
    dist = np.stack([np.linalg.norm(node_frames[f] - node_frames[settle], axis=1) for f in frames])
    return {"frames": frames, "max_mm": float(dist.max()), "mean_mm": float(dist.mean())}


TISSUE_SETTLED_LIMIT_MM = HARD_TOLERANCE_MM  # a node moving less than this in the last settle frame counts as still


def tissue_step(node_frames: np.ndarray, frame: int) -> dict:
    """Not a check: how far the tet nodes moved between frame - 1 and `frame`, geometric mm: the largest and the mean
    distance over the nodes, the two frame numbers, and `tissue_settled`: whether the largest step is below
    TISSUE_SETTLED_LIMIT_MM. The drivers being at rest (settled_shape.available) says the bones stopped; this says
    whether the tissue did. It does not change `passed`; asrp_core.final_shape refuses a base that is not settled."""
    step = np.linalg.norm(node_frames[frame] - node_frames[frame - 1], axis=1)
    return {"tissue_step_max_mm": float(step.max()), "tissue_step_mean_mm": float(step.mean()),
            "tissue_step_frames": [frame - 1, frame], "tissue_settled": bool(step.max() < TISSUE_SETTLED_LIMIT_MM),
            "tissue_settled_limit_mm": TISSUE_SETTLED_LIMIT_MM}


# --- the display surface against its rest shape (reported only) ---------------------------------------------------

def _cross(points: np.ndarray, faces: np.ndarray) -> tuple:
    """The cross product (b - a) x (c - a) of every triangle, as three arrays (..., m). points (..., 3, v): the
    coordinates in rows, which is what makes the arithmetic below run on long contiguous arrays."""
    a, b, c = (np.take(points, faces[:, i], axis=-1) for i in range(3))
    b -= a
    c -= a
    ux, uy, uz = b[..., 0, :], b[..., 1, :], b[..., 2, :]
    wx, wy, wz = c[..., 0, :], c[..., 1, :], c[..., 2, :]
    return uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx


def unique_edges(faces: np.ndarray) -> np.ndarray:
    """Every edge of a triangle list once, (e, 2) sorted vertex indices."""
    pairs = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1).astype(np.int64)
    key = np.unique(pairs[:, 0] * (int(pairs.max()) + 1) + pairs[:, 1])
    return np.stack([key // (int(pairs.max()) + 1), key % (int(pairs.max()) + 1)], axis=1)


def fold_counts(rest: np.ndarray, frames: np.ndarray, faces: np.ndarray, chunk: int = 8) -> dict:
    """Per frame, against the rest surface, with the same triangles: the number of faces whose normal points the other
    way (dot product with the rest normal < 0) and of faces turned by more than 60 degrees (dot < 0.5), the number of
    edges shorter than half or longer than twice their rest length, the smallest and largest edge length ratio and the
    smallest face area ratio. rest (v, 3), frames (F, v, 3), faces (m, 3) int. Each value is an array of F numbers.
    Done a few frames at a time (a long run does not need one huge array) on the coordinates laid out in rows.
    Edges or faces with zero rest length or area (no ratio exists) are left out of the ratios."""
    faces = np.asarray(faces)
    r = np.ascontiguousarray(rest.T)[None]  # (1, 3, v)
    n0 = _cross(r, faces)
    len0 = np.sqrt(n0[0] ** 2 + n0[1] ** 2 + n0[2] ** 2)[0]
    n0 = [x[0] / np.maximum(len0, 1e-12) for x in n0]  # the rest normals, unit length
    a0 = 0.5 * len0
    edges = unique_edges(faces)
    e0 = np.sqrt(((r[0][:, edges[:, 0]] - r[0][:, edges[:, 1]]) ** 2).sum(axis=0))
    keep_edge, keep_face = e0 > 0, a0 > 0

    def one(start: int) -> dict:
        block = np.ascontiguousarray(frames[start:start + chunk].transpose(0, 2, 1))  # (c, 3, v)
        cx, cy, cz = _cross(block, faces)
        length = np.sqrt(cx * cx + cy * cy + cz * cz)
        dot = (cx * n0[0] + cy * n0[1] + cz * n0[2]) / np.maximum(length, 1e-12)
        dist = np.take(block, edges[:, 0], axis=2)
        dist -= np.take(block, edges[:, 1], axis=2)
        ratio = np.sqrt(dist[:, 0] ** 2 + dist[:, 1] ** 2 + dist[:, 2] ** 2)[:, keep_edge] / e0[keep_edge]
        nan = np.full(len(block), np.nan)
        return {"flipped": (dot < 0).sum(axis=1), "turned": (dot < 0.5).sum(axis=1),
                "short": (ratio < 0.5).sum(axis=1), "long": (ratio > 2).sum(axis=1),
                "ratio_min": ratio.min(axis=1) if ratio.size else nan,
                "ratio_max": ratio.max(axis=1) if ratio.size else nan,
                "area_min": ((0.5 * length)[:, keep_face] / a0[keep_face]).min(axis=1) if keep_face.any() else nan}

    starts = range(0, len(frames), chunk)
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:  # numpy lets go of the GIL in big operations
        parts = list(pool.map(one, starts))
    result = {k: np.concatenate([part[k] for part in parts]) for k in parts[0]} if parts else {}
    result["faces"], result["edges"] = len(faces), len(edges)
    return result


def folds(rest: np.ndarray, shape: np.ndarray, faces: np.ndarray) -> dict:
    """Count folded and squashed faces of one shape against the rest shape (docs/15 section 8). A flipped face is not a proof of self-intersection."""
    c = fold_counts(rest, shape[None], faces)
    return {"faces": c["faces"], "flipped (dot < 0)": int(c["flipped"][0]), "turned > 60 deg (dot < 0.5)": int(c["turned"][0]),
            "edges > 2x": int(c["long"][0]), "edges < 0.5x": int(c["short"][0]),
            "edge ratio min / max": (round(float(c["ratio_min"][0]), 3), round(float(c["ratio_max"][0]), 3)),
            "smallest face area ratio": round(float(c["area_min"][0]), 3)}


def _frame_health(c: dict, f: int) -> dict:
    return {"flipped_faces": int(c["flipped"][f]), "edges_shorter_than_half": int(c["short"][f]),
            "edges_longer_than_double": int(c["long"][f]), "edge_ratio_min": float(c["ratio_min"][f]),
            "edge_ratio_max": float(c["ratio_max"][f]), "min_face_area_ratio": float(c["area_min"][f]),
            "faces": int(c["faces"]), "edges": int(c["edges"])}


def surface_health(rest: np.ndarray, frames: np.ndarray, faces) -> dict:
    """Not a check: the display surface against its rest shape, at the last frame and at the worst frame (the one with
    the most flipped faces; ties go to the most edges outside half..double their rest length, then to the earliest
    frame). `faces` are the mesh's own polygons, fanned into triangles. Same counts as `folds`. A flipped face means
    the surface has turned over there, not that it intersects itself."""
    c = fold_counts(rest, frames, coords.triangulate(faces))
    worst = int(np.argmax(c["flipped"] * (c["edges"] + 1) + c["short"] + c["long"]))
    return {"last": _frame_health(c, len(frames) - 1), "worst": {**_frame_health(c, worst), "frame": worst}}
