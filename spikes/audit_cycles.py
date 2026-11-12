"""One-off measurement (not product code): the prototype's jaw opening repeated N times in one run.

Does the lip come back to the same shape each time the jaw closes, is each opening the same as the first,
and does any tet turn inside out? The lab reports that Ziva's mesh breaks when one transition is played back
and forth ten times; this is the same question asked of our physics layer alone (no landmark layer yet).
docs/13 E-08 quotes the numbers.

    uv run python spikes/audit_cycles.py make <scene.json> <out trajectory.json> [cycles]
    uv run asrp run <scene.json> <out trajectory.json>
    uv run python spikes/audit_cycles.py analyse <run folder> [cycles]

The motion: frames 0-14 still (gravity only), then `cycles` times: 18 frames opening to the placeholder's
12 degrees and 18 frames closing (tools/placeholder_jaw_motion.py's half-cosine and hinge).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

from asrp_core import run, scene, tetmesh, trajectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import placeholder_jaw_motion as placeholder  # noqa: E402

STILL, HALF = placeholder.STILL_UNTIL, placeholder.OPEN_AT - placeholder.STILL_UNTIL
DRIVER = "jaw01"


def angles_deg(cycles: int) -> list[float]:
    out = [0.0] * (STILL + 1)
    for _ in range(cycles):
        for i in range(1, 2 * HALF + 1):
            s = i / HALF if i <= HALF else (2 * HALF - i) / HALF
            out.append(placeholder.OPEN_DEG * (1 - math.cos(math.pi * s)) / 2)
    return out


def make(scene_path: Path, out: Path, cycles: int) -> None:
    s = scene.load(scene_path)
    hinge = next((d.hinge for d in s.drivers if d.name == DRIVER), None)
    if hinge is None:
        raise SystemExit(f"{scene_path} has no driver {DRIVER!r} with a hinge")
    sign = placeholder.opening_sign(s, scene_path.parent, DRIVER)
    angles = [sign * math.radians(a) for a in angles_deg(cycles)]
    trajectory.write(out, trajectory.Trajectory(
        fps=float(s.solver.fps.value), frames=len(angles),
        drivers={DRIVER: trajectory.hinge_transforms(hinge.pivot_mm, hinge.axis, angles)},
        source_tag="ours", settle_until_frame=STILL,
        source=f"placeholder (audit, ours): the T-06a opening repeated {cycles} times; spikes/audit_cycles.py"))
    print(f"wrote {out}: {len(angles)} frames")


def analyse(run_dir: Path, cycles: int) -> None:
    data = run.read_positions(run_dir / run.POSITIONS)
    sc = scene.load(run_dir / "scene.json")
    fps = float(sc.solver.fps.value)
    mesh, _ = tetmesh.load(run_dir / sc.soft_tissues[0].tet_mesh.path)
    index = {nid: i for i, nid in enumerate(data["node_ids"])}
    rows = [index[i + 1] for i in range(len(mesh.nodes))]
    frames = {round(t * fps): np.asarray(p)[rows] for t, p in zip(data["times_s"], data["positions"])}
    closed = [STILL + 2 * HALF * c for c in range(cycles + 1)]
    peaks = [STILL + HALF + 2 * HALF * c for c in range(cycles)]
    for label, first, later in (("closed", closed[0], closed[1:]), ("fully open", peaks[0], peaks[1:])):
        print(f"{label} frames against the first one (frame {first}): largest / mean node distance, mm")
        for f in later:
            d = np.linalg.norm(frames[f] - frames[first], axis=1)
            print(f"  frame {f:4d}: {d.max():.3e} / {d.mean():.3e}")
    rest = tetmesh.signed_volumes(mesh.nodes, mesh.tets)
    worst, where, inverted = 1.0, 0, 0
    for f, p in sorted(frames.items()):
        ratio = tetmesh.signed_volumes(p, mesh.tets) / rest
        inverted += int((ratio <= 0).sum())
        if ratio.min() < worst:
            worst, where = float(ratio.min()), f
    print(f"smallest tet volume / its rest volume over all frames: {worst:.3f} (frame {where}); "
          f"tets turned inside out, summed over frames: {inverted}")
    report = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))
    print(f"FEBio {report['timing']['febio_s']} s, {report['timing']['febio_s_per_frame']} s per frame, "
          f"{report['checks']['a']['numbers']['retries']} retries; run folder "
          f"{sum(f.stat().st_size for f in run_dir.rglob('*') if f.is_file()) / 2**20:.0f} MB")


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("make", "analyse"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "make":
        if len(sys.argv) < 4:
            raise SystemExit(__doc__)
        make(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 10)
    else:
        analyse(Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 10)


if __name__ == "__main__":
    main()
