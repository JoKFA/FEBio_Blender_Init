"""Write the head shake of T-28 as a normal trajectory.json (docs/03 section 13.8, docs/09 T-28).

    uv run python tools/head_shake_motion.py <scene.json> <out trajectory.json>

What the lab's script sets (automation/passive_dynamics_test.py, read-only reference, ADR-28): keys on the `tx` of the
jaw and skull bone meshes, value 0 at frames 0 and 16, then three loops of 10 frames, each with keys a quarter loop
apart: +5, 0, -5, 0 scene units (so keys at 18.5, 21, 23.5, 26, ..., 46), and the script then sets the in and out
tangent types of these keys to Maya's "auto". The script ends at frame 86 (40 frames after the shake). Here both the
head driver and the jaw driver translate along x by the same amount (Maya's X is our x, docs/03 section 10), the
amplitude is 5 scene units times the scene's mm_per_scene_unit.

How the curve between keys is computed (Maya's "auto" tangent is not published; this is our reading of it, an
assumption): a cubic Hermite curve through the keys, the tangent at a key is zero when the key is a local extreme or
a plateau of the key values (equal to a neighbour) and at the first and last key, and otherwise the slope through
its two neighbours, (v[i+1] - v[i-1]) / (t[i+1] - t[i-1]), limited to 3 x the smaller of the two neighbouring
secants so the curve does not overshoot the keys. Before the first and after the last key the value holds. The
trajectory gets the curve's value at every whole frame; between frames the generator moves the bodies linearly.

settle_until_frame is 14 (the motion starts after frame 16; the gravity-only settle ends at frame 14);
source_tag "ours": the keys are the lab's, the curve between them is our reading of Maya's auto tangents.
"""

import sys
from pathlib import Path

from asrp_core import scene, trajectory

HEAD = "head"
JAW = "jaw01"
START, LOOPS, FRAMES_PER_LOOP, AFTER = 16, 3, 10, 40
AMPLITUDE_UNITS = 5.0
SETTLE = 14


def keys() -> list[tuple[float, float]]:
    """(frame, value in scene units): the lab script's keys, in order."""
    out = [(0.0, 0.0), (float(START), 0.0)]
    f = float(START)
    q = FRAMES_PER_LOOP / 4.0
    for _ in range(LOOPS):
        out += [(f + q, AMPLITUDE_UNITS), (f + 2 * q, 0.0), (f + 3 * q, -AMPLITUDE_UNITS)]
        f += FRAMES_PER_LOOP
        out.append((f, 0.0))
    return out


def tangents(k: list[tuple[float, float]]) -> list[float]:
    out = []
    for i, (_, v) in enumerate(k):
        if i == 0 or i == len(k) - 1:
            out.append(0.0)
            continue
        (t0, v0), (t1, v1) = k[i - 1], k[i + 1]
        if (v - v0) * (v1 - v) <= 0:  # a local extreme, or equal to a neighbour: flat
            out.append(0.0)
            continue
        slope = (v1 - v0) / (t1 - t0)
        left, right = (v - v0) / (k[i][0] - t0), (v1 - v) / (t1 - k[i][0])
        limit = 3 * min(abs(left), abs(right))
        out.append(max(-limit, min(limit, slope)))
    return out


def value(frame: float, k=None, m=None) -> float:
    """The curve at a frame, scene units."""
    k = k or keys()
    m = m or tangents(k)
    if frame <= k[0][0]:
        return k[0][1]
    if frame >= k[-1][0]:
        return k[-1][1]
    for i in range(len(k) - 1):
        (t0, v0), (t1, v1) = k[i], k[i + 1]
        if t0 <= frame <= t1:
            h = t1 - t0
            s = (frame - t0) / h
            h00, h10 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s
            h01, h11 = -2 * s**3 + 3 * s**2, s**3 - s**2
            return h00 * v0 + h10 * h * m[i] + h01 * v1 + h11 * h * m[i + 1]
    raise AssertionError("unreachable")


def frames() -> int:
    return START + LOOPS * FRAMES_PER_LOOP + AFTER + 1  # 0..86, as the lab script's END_FRAME


def build(scene_path: Path) -> trajectory.Trajectory:
    s = scene.load(scene_path)
    names = {d.name for d in s.drivers}
    for need in (HEAD, JAW):
        if need not in names:
            raise SystemExit(f"{scene_path} has no driver {need!r}; import the asset again (T-28 adds the head driver)")
    mm = float(s.units.mm_per_scene_unit.value)
    k, m = keys(), tangents(keys())
    xs = [value(f, k, m) * mm for f in range(frames())]
    moves = [[1.0, 0.0, 0.0, x, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0] for x in xs]
    return trajectory.Trajectory(
        fps=s.solver.fps.value, frames=frames(), drivers={HEAD: moves, JAW: [list(r) for r in moves]},
        source_tag="ours", settle_until_frame=SETTLE, title="Prototype 2: head shake (test motion)",
        source=(f"head shake (T-28, ours): {HEAD} and {JAW} translate along x, keys of the lab's "
                f"passive_dynamics_test.py (0 at frames 0 and {START}, {LOOPS} loops of {FRAMES_PER_LOOP} frames, "
                f"+-{AMPLITUDE_UNITS:g} scene units = +-{AMPLITUDE_UNITS * mm:.4g} mm), cubic Hermite with our reading of "
                f"Maya's auto tangents, then {AFTER} frames at rest; the keys at the extremes fall on half frames (as in the lab's "
                f"script), so sampled once per frame the head goes at most {max(abs(x) for x in xs):.3g} mm; "
                f"tools/head_shake_motion.py"),
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    motion = build(Path(sys.argv[1]))
    trajectory.write(Path(sys.argv[2]), motion)
    peak = max(abs(m[3]) for m in motion.drivers[HEAD])
    print(f"wrote {sys.argv[2]}: {motion.frames} frames at {motion.fps} fps, {HEAD} and {JAW} shake along x, "
          f"largest offset {peak:.4f} mm")


if __name__ == "__main__":
    main()
