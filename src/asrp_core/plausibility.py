"""The plausibility checks every run on the lab's model gets (docs/07 section 3, T-06a).

Three checks, each a function of plain arrays so that a test can make it fail on purpose:

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
    gravity-only settle (the trajectory's settle_until_frame n: frames n-4..n; one frame alone aliases the
    undamped ringing, docs/05 pit 2), have moved along the scene's gravity direction by about the amount
    the model predicts (`expected_sag`): rho |g| k L^2 / (2 E) geometric mm, the sag of a bar of length L
    hanging from one end under its own weight, with rho and E the soft tissue's density and Young's
    modulus, k the physics length scale and L the largest distance from a free display vertex to the
    nearest held one. It passes within a factor SAG_FACTOR either way (measured on the lips: 0.65 of the
    estimate, and proportional to 1/E like the estimate). This still only finds gross errors (a flipped
    sign, a unit off by 100, E or the density off by 10 times or more); it does not prove the scale.

All positions are geometric mm (what `run` writes after dividing by k).
"""

from dataclasses import dataclass, field

import numpy as np

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
