"""One-off measurement (not product code): can prototype two reach the lab's AA mouth shape, and what does the
target say about the lip-corner anchor?

Prototype two (docs/09 section 1, T-27) will turn the jaw to the AA target's angle, let the physics carry the
lips, and fit 300 landmark translations so that physics + landmark skinning lands on the lab's AA target shape.
Before that is built, this measures whether the plan can work, with a plain least-squares fit:

- the jaw's rigid motion is fitted from the target file's jaw mesh (frame "0" to frame "1");
- the scene is run with that motion (frames 0-14 still, then 36 frames to the target) for several values of
  the lip-corner anchor's fraction (0, 0.25, 0.5, 0.75, 1);
- for each run, and for "no physics at all" (the rest lips), the landmark translations d that bring
  W d closest to (target - lips) are solved (W: the 10,240 x 300 skin weights), and it prints how far the lips
  are from the target before the landmarks, how far after, and how far the landmarks had to move.

The fraction that needs the least landmark motion is where the physics explains most of the target by itself.
That is a hint about the fraction, not a measurement of Ziva: the target is the lab's final shape (physics plus
their landmarks), and may be an artist's pose (docs/03 section 13.7).

    uv run python spikes/audit_aa_fit.py <scene folder> <dataV22_phoneme_AA_for_d2.py> <an empty work folder>

The target file is the lab's (read with ast.literal_eval, never executed, never copied into the repo, ADR-28):
`a3-stochastic-V1/a1-blendshape-guided-animation-pipeline/database/dataV22_phoneme_AA_for_d2.py` in their
source repository. docs/13 E-09 quotes the numbers.
"""

import ast
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate, trajectory
from asrp_core.asset import coords
from asrp_core.doctor import febio_exe

FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
SETTLE, STEPS = 14, 36
RIDGE = 1e-8  # keeps the fit well posed and changes nothing visible; relative to the mean diagonal of W^T W
RIDGES = (1e-8, 1e-4, 1e-3, 1e-2, 1e-1)  # the regularisation strengths tried at the end
DEFAULT_FRACTION = 0.5


def target_array(text: str, name: str) -> np.ndarray:
    found = re.search(rf"^{re.escape(name)}\s*=\s*(.*)$", text, re.M)
    if not found:
        raise SystemExit(f"the target file has no {name}")
    return np.array(ast.literal_eval(found.group(1)), dtype=float)


def rigid_fit(a: np.ndarray, b: np.ndarray) -> tuple[list[float], float]:
    """The rigid transform (16 numbers, column vectors, row by row) that takes points a to b, and its residual."""
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    r = vt.T @ np.diag([1.0, 1.0, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    t = cb - r @ ca
    residual = float(np.linalg.norm(a @ r.T + t - b, axis=1).max())
    return [*r[0], t[0], *r[1], t[1], *r[2], t[2], 0.0, 0.0, 0.0, 1.0], residual


def fit(weights: np.ndarray, gap: np.ndarray, ridge: float = RIDGE) -> tuple[np.ndarray, np.ndarray]:
    """Landmark translations d (300, 3) minimising |W d - gap|^2 + ridge x m x |d|^2, and what is left (v, 3);
    m is the mean diagonal of W^T W, so ridge is a plain number (0.01 = one per cent of a landmark's own weight)."""
    gram = weights.T @ weights
    normal = gram + ridge * float(np.trace(gram)) / len(gram) * np.eye(len(gram))
    d = np.linalg.solve(normal, weights.T @ gap)
    return d, gap - weights @ d


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    source, target_file, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    scene = json.loads((source / "scene.json").read_text(encoding="utf-8"))
    mm = scene["units"]["mm_per_scene_unit"]["value"]
    fps = float(scene["solver"]["fps"]["value"])
    text = target_file.read_text(encoding="utf-8")
    jaw0, jaw1 = (coords.to_mm_zup(target_array(text, f"x_middleres_Jaw{i}"), mm) for i in (0, 1))
    lips0, lips1 = (coords.to_mm_zup(target_array(text, f"x_middleres_OrbicularisOris{i}"), mm) for i in (0, 1))
    rest, _ = coords.read_obj(source / scene["soft_tissues"][0]["mesh"]["path"])
    rest = np.asarray(rest, dtype=float)
    print(f"target file's starting lips against the scene's rest lips: largest distance "
          f"{np.linalg.norm(lips0 - rest, axis=1).max():.2e} mm")
    jaw_move, residual = rigid_fit(jaw0, jaw1)
    r = np.array([jaw_move[0:3], jaw_move[4:7], jaw_move[8:11]])
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(r) - 1) / 2))))
    print(f"jaw: a rigid motion of {angle:.3f} degrees fits the target's jaw to {residual:.2e} mm")

    skin = json.loads((source / scene["landmarks"]["weights"]["path"]).read_text(encoding="utf-8"))
    weights = np.zeros((len(rest), len(skin["influences"])))
    for v, pairs in enumerate(skin["weights"]):
        for i, w in pairs:
            weights[v, i] = w

    # frames 0..SETTLE still, then STEPS frames along a half cosine to the target motion
    fractions = [0.0] * (SETTLE + 1) + [(1 - math.cos(math.pi * i / STEPS)) / 2 for i in range(1, STEPS + 1)]
    jaw_frames = [trajectory.blend_transforms([jaw_move], f)[0] for f in fractions]
    jaw_driver = next(d["name"] for d in scene["drivers"] if d.get("hinge"))

    rows = [("no physics (rest lips)", rest)]
    settled = [rest]  # per row: the lips at the end of the gravity-only settle (jaw still closed)
    exe = febio_exe()
    for fraction in FRACTIONS:
        folder = work / f"scene_{fraction:g}"
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(source, folder)
        data = json.loads((folder / "scene.json").read_text(encoding="utf-8"))
        for driver in data["drivers"]:
            if driver.get("blend"):
                driver["blend"]["factor"]["value"] = fraction
        (folder / "scene.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
        trajectory.write(folder / "aa.json", trajectory.Trajectory(
            fps=fps, frames=len(jaw_frames), drivers={jaw_driver: jaw_frames}, source_tag="ours",
            settle_until_frame=SETTLE,
            source=f"audit (ours): jaw to the AA target's rigid motion ({angle:.3f} degrees); spikes/audit_aa_fit.py"))
        run = simulate.run_scene(folder / "scene.json", folder / "aa.json", work / "runs", exe, f"aa-{fraction:g}")
        if run.status != "complete":
            raise SystemExit(f"fraction {fraction:g}: run {run.status}: {run.report['checks']['a']['message']}")
        display = simulate.read_display(run.run_dir / simulate.DISPLAY)["positions"]
        rows.append((f"physics, anchor fraction {fraction:g}", display[-1]))
        settled.append(display[SETTLE])
        print(f"ran fraction {fraction:g}: FEBio {run.report['timing']['febio_s']} s, plausibility "
              f"{'passed' if run.passed else 'NOT passed'}", flush=True)

    moved = np.linalg.norm(lips1 - rest, axis=1)
    print(f"\nthe target moves the lips by at most {moved.max():.2f} mm (mean {moved.mean():.2f} mm) from rest\n")
    print(f"{'lips before the landmarks':32} {'to target: largest':>18} {'mean':>7}   {'after the fit: largest':>22} {'mean':>7}"
          f"   {'landmark motion: largest':>24} {'mean':>7}   (mm)")
    for label, lips in rows:
        gap = lips1 - lips
        d, left = fit(weights, gap)
        before, after, effort = (np.linalg.norm(x, axis=1) for x in (gap, left, d))
        print(f"{label:32} {before.max():18.3f} {before.mean():7.3f}   {after.max():22.3f} {after.mean():7.3f}"
              f"   {effort.max():24.3f} {effort.mean():7.3f}")

    # The two ways to put the AA shape together (ADR-40), for every anchor fraction:
    # A: the landmark translations are fitted against the SETTLED lips (jaw closed), then added to the physics
    #    result with the jaw open: the lab's pipeline as we read it (training does not advance the physics).
    # B: they are fitted against the physics result itself, so the final shape is as near the target as it can be.
    print("\nthe two ways to put the shape together; distance of the FINAL shape from the target, and how far the "
          "landmarks move (mm):\n")
    print(f"{'physics run':32} {'A final: largest':>16} {'mean':>7} {'A landmarks: largest':>20} {'mean':>7}   "
          f"{'B final: largest':>16} {'mean':>7} {'B landmarks: largest':>20} {'mean':>7}")
    finals = {}
    for (label, lips), calm, fraction in zip(rows[1:], settled[1:], FRACTIONS):
        d_a, _ = fit(weights, lips1 - calm)
        final_a = lips + weights @ d_a
        d_b, _ = fit(weights, lips1 - lips)
        final_b = lips + weights @ d_b
        finals[fraction] = (final_a, final_b, lips)
        off_a, off_b = (np.linalg.norm(lips1 - f, axis=1) for f in (final_a, final_b))
        go_a, go_b = (np.linalg.norm(d, axis=1) for d in (d_a, d_b))
        print(f"{label:32} {off_a.max():16.3f} {off_a.mean():7.3f} {go_a.max():20.3f} {go_a.mean():7.3f}   "
              f"{off_b.max():16.3f} {off_b.mean():7.3f} {go_b.max():20.3f} {go_b.mean():7.3f}")

    # What regularising the fit costs: what is left against how far the landmarks move.
    print("\nregularised fits (ridge relative to a landmark's own weight); what is left and how far the landmarks "
          "move (mm):\n")
    print(f"{'ridge':>8}   {'against the rest lips: left largest':>35} {'mean':>7} {'landmarks largest':>18} {'mean':>7}   "
          f"{'B at fraction ' + format(DEFAULT_FRACTION, 'g') + ': left largest':>35} {'mean':>7} {'landmarks largest':>18} {'mean':>7}")
    for ridge in RIDGES:
        line = f"{ridge:8.0e}  "
        for base in (rest, finals[DEFAULT_FRACTION][2]):
            d, left = fit(weights, lips1 - base, ridge)
            off, go = np.linalg.norm(left, axis=1), np.linalg.norm(d, axis=1)
            line += f" {off.max():35.3f} {off.mean():7.3f} {go.max():18.3f} {go.mean():7.3f}  "
        print(line)

    # How much of the jaw's motion do the lips make, group by group: in the target, and in each physics run?
    # "Riding the jaw" = where a vertex would go if it were glued to the jaw. The follow ratio is the
    # least-squares factor s in (vertex motion) = s x (riding the jaw): 1 follows the jaw fully, 0 not at all.
    r3 = np.array([jaw_move[0:3], jaw_move[4:7], jaw_move[8:11]])
    riding = rest @ r3.T + np.array([jaw_move[3], jaw_move[7], jaw_move[11]]) - rest

    def follow(motion: np.ndarray, vertices: np.ndarray) -> float:
        return float((motion[vertices] * riding[vertices]).sum() / (riding[vertices] ** 2).sum())

    groups = [(a["name"], np.array([int(v) for v, w in a["weights"] if w > 0])) for a in scene["attachments"]]
    held = np.unique(np.concatenate([v for _, v in groups]))
    groups += [("vertices no attachment holds", np.setdiff1d(np.arange(len(rest)), held)), ("all vertices", np.arange(len(rest)))]
    physics = rows[1:]
    print(f"\nfollow ratio against riding the jaw ({angle:.2f} degrees), and the mean distance moved (mm):\n")
    print(f"{'group':30} {'vertices':>8} {'riding the jaw':>14} {'target moves':>12} {'target follow':>13}  "
          + " ".join(f"{'a=' + format(f, 'g'):>7}" for f in FRACTIONS) + f" {'A final':>8} {'B final':>8}"
          + f"   (a = anchor fraction of the physics run; A and B: the final shapes at a = {DEFAULT_FRACTION:g})")
    final_a, final_b, _ = finals[DEFAULT_FRACTION]
    for name, v in groups:
        print(f"{name:30} {len(v):8d} {np.linalg.norm(riding[v], axis=1).mean():14.2f} "
              f"{np.linalg.norm((lips1 - rest)[v], axis=1).mean():12.2f} {follow(lips1 - rest, v):13.2f}  "
              + " ".join(f"{follow(lips - rest, v):7.2f}" for _, lips in physics)
              + f" {follow(final_a - rest, v):8.2f} {follow(final_b - rest, v):8.2f}")


if __name__ == "__main__":
    main()
