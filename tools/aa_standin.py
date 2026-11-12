"""Fit 300 landmark translations so the neutral-to-AA mouth shape can be made now (T-27).

TEMPORARY STAND-IN: this is replaced by the T-10 conversion once D2 arrives. D2 is the lab's real landmark
motion, which lives on a machine we cannot reach yet; until then this tool fits the translations ourselves from
the lab's AA target shape. Where landmarks go is the lab controller's job, not our product's, so this stays in
tools/ and never moves into src/asrp_core/.

    uv run python tools/aa_standin.py --work <work folder, outside the repo, ASCII path>
        [--target <dataV22_phoneme_AA_for_d2.py>] [--export data/lab_export] [--report data/preview/aa_standin_report.json]

The target file is the lab's (read with ast.literal_eval, never executed, never copied into the repo, ADR-28);
by default it is <ASRP_LAB_DATA or E:/Codebase/_lab/data>/dataV22_phoneme_AA_for_d2.py.

What it does, in order (docs/09 T-27, docs/13 E-09, ADR-39, ADR-40):
1. reads the jaw and lip shapes of the target (`...0` rest, `...1` target), fits the jaw01 rotation;
2. writes the jaw motion (frames 0-14 still, 36 frames of half cosine to the target angle);
3. imports the lab asset into <work>/scene and runs the physics once with the default scene;
4. fits the landmark translations by ridge least squares, two ways:
   - A ("jia"): against the settled shape (frame 14, jaw closed), applied on top of the open-jaw physics. This is
     the lab procedure as we read it (training does not advance the physics); the final shape does NOT reach
     the target, and that is the expected result, not a bug;
   - B ("yi"): against the last physics frame, so the final shape lands as near the target as the fit allows;
5. writes <work>/aa_a.json and <work>/aa_b.json (the jaw motion plus a `landmarks` section that follows the
   same half cosine from exactly zero at frames 0-14);
6. repeats the physics for the lip-corner anchor fractions 0, 0.25, 0.5, 0.75, 1 (a copied scene with the
   blend factor edited; no default anywhere changes);
7. writes the archive file (numbers and verdicts only: no lab coordinates, nothing per vertex).

It does not run `asrp run` with the landmark motions; `asrp check` is run on both.
"""

import argparse
import ast
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate, skinning, trajectory
from asrp_core.asset import coords
from asrp_core.doctor import febio_exe

REPO = Path(__file__).resolve().parents[1]
TARGET_NAME = "dataV22_phoneme_AA_for_d2.py"
LAB_COMMIT = "506cd69"
FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
SETTLE, STEPS = 14, 36  # frames 0..14 still, then 36 frames to the target: 51 frames
RIDGE = 1e-3  # relative to the mean diagonal of W^T W (the spike's measure; E-09)
HIST_EDGES = (0.0, 1.0, 2.0, 5.0, 10.0, 20.0, math.inf)
HIST_LABELS = ("0-1", "1-2", "2-5", "5-10", "10-20", ">20")
CHECKS = ("a", "b", "b2", "c", "d")


# ---------------------------------------------------------------- pure functions (unit tested)

def target_array(text: str, name: str) -> np.ndarray:
    """The assignment `name = [[x, y, z], ...]` in the target file's text, read with ast.literal_eval."""
    found = re.search(rf"^{re.escape(name)}\s*=\s*(.*)$", text, re.M)
    if not found:
        raise SystemExit(f"the target file has no {name}")
    return np.array(ast.literal_eval(found.group(1)), dtype=float)


def rigid_fit(a: np.ndarray, b: np.ndarray) -> tuple[list[float], float]:
    """The rigid transform (16 numbers, column vectors, row by row) that takes points a to b, and its largest residual."""
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    r = vt.T @ np.diag([1.0, 1.0, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    t = cb - r @ ca
    residual = float(np.linalg.norm(a @ r.T + t - b, axis=1).max())
    return [*r[0], t[0], *r[1], t[1], *r[2], t[2], 0.0, 0.0, 0.0, 1.0], residual


def rotation_degrees(move: list[float]) -> float:
    """The angle (degrees) of the rotation part of a 16-number transform."""
    r = np.array([move[0:3], move[4:7], move[8:11]])
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(r) - 1) / 2))))


def ramp_fractions(settle: int = SETTLE, steps: int = STEPS) -> list[float]:
    """Per frame, how far along the motion is: exactly 0 for frames 0..settle, then a half cosine to exactly 1
    after `steps` more frames."""
    return [0.0] * (settle + 1) + [(1 - math.cos(math.pi * i / steps)) / 2 for i in range(1, steps + 1)]


def ramp_translations(translations: np.ndarray, fractions: list[float]) -> np.ndarray:
    """(K, 3) fitted translations -> (frames, K, 3): each frame is the fitted values times that frame's fraction."""
    t = np.asarray(translations, dtype=float)
    return np.asarray(fractions, dtype=float)[:, None, None] * t[None]


def ridge_fit(weights: np.ndarray, gap: np.ndarray, ridge: float = RIDGE) -> tuple[np.ndarray, np.ndarray]:
    """Landmark translations d (K, 3) minimising |W d - gap|^2 + ridge x m x |d|^2, and what is left (V, 3).

    m is the mean diagonal of W^T W, so `ridge` is a plain number (0.01 = one per cent of a landmark's own
    weight). ridge 0 is the plain least-squares solution (minimum norm if W is rank deficient)."""
    if ridge == 0:
        d = np.linalg.lstsq(weights, gap, rcond=None)[0]
    else:
        gram = weights.T @ weights
        normal = gram + ridge * float(np.trace(gram)) / len(gram) * np.eye(len(gram))
        d = np.linalg.solve(normal, weights.T @ gap)
    return d, gap - weights @ d


def histogram(values: np.ndarray) -> dict[str, int]:
    """Counts of values in 0-1, 1-2, 2-5, 5-10, 10-20 and above 20 (lower edge included)."""
    counts = [int(((values >= lo) & (values < hi)).sum()) for lo, hi in zip(HIST_EDGES[:-1], HIST_EDGES[1:])]
    return dict(zip(HIST_LABELS, counts))


def follow_ratio(motion: np.ndarray, riding: np.ndarray, vertices: np.ndarray) -> float:
    """The least-squares factor s in (vertex motion) = s x (riding the jaw) over `vertices`: 1 follows the jaw
    fully, 0 not at all."""
    return float((motion[vertices] * riding[vertices]).sum() / (riding[vertices] ** 2).sum())


def distance_stats(shape: np.ndarray, target: np.ndarray) -> dict[str, float]:
    d = np.linalg.norm(target - shape, axis=1)
    return {"max_mm": float(d.max()), "mean_mm": float(d.mean())}


def travel_stats(translations: np.ndarray) -> dict:
    n = np.linalg.norm(translations, axis=1)
    return {"max_mm": float(n.max()), "mean_mm": float(n.mean()), "histogram": histogram(n)}


# ---------------------------------------------------------------- the tool

def read_target(path: Path, mm: float) -> dict[str, np.ndarray]:
    text = path.read_text(encoding="utf-8")
    out = {}
    for key, name in (("jaw0", "x_middleres_Jaw0"), ("jaw1", "x_middleres_Jaw1"),
                      ("lips0", "x_middleres_OrbicularisOris0"), ("lips1", "x_middleres_OrbicularisOris1")):
        out[key] = coords.to_mm_zup(target_array(text, name), mm)
    return out


def write_scene_copy(source: Path, folder: Path, fraction: float | None) -> Path:
    """A copy of the scene folder; with `fraction`, the corner anchor's blend factor edited to it."""
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(source, folder)
    path = folder / "scene.json"
    if fraction is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        for driver in data["drivers"]:
            if driver.get("blend"):
                driver["blend"]["factor"]["value"] = fraction
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def run_physics(scene_path: Path, motion_path: Path, runs: Path, name: str, exe: Path) -> dict:
    run = simulate.run_scene(scene_path, motion_path, runs, exe, name)
    if run.status != "complete":
        raise SystemExit(f"run {name}: {run.status}: {run.report['checks']['a']['message']}")
    display = simulate.read_display(run.run_dir / simulate.DISPLAY)["positions"]
    checks = {k: bool(run.report["checks"][k]["passed"]) for k in CHECKS if k in run.report["checks"]}
    print(f"ran {name}: plausibility {'passed' if run.passed else 'NOT passed'} {checks}", flush=True)
    return {"settled": np.array(display[SETTLE]), "last": np.array(display[-1]), "checks": checks,
            "passed": bool(run.passed), "run_dir": str(run.run_dir)}


def fit_both(weights, target, settled, last, ridge=RIDGE):
    """Variant A (against the settled shape) and variant B (against the last physics frame)."""
    d_a, _ = ridge_fit(weights, target - settled, ridge)
    d_b, _ = ridge_fit(weights, target - last, ridge)
    return d_a, d_b


def shape_report(physics: dict, weights, target: np.ndarray, rest: np.ndarray, ridge: float) -> dict:
    """Distances and landmark travel for physics only, A and B, for one physics run."""
    last = physics["last"]
    d_a, d_b = fit_both(weights, target, physics["settled"], last, ridge)
    final_a, final_b = skinning.deform(last, weights, d_a), skinning.deform(last, weights, d_b)
    return {"physics_only": distance_stats(last, target),
            "a": {"final": distance_stats(final_a, target), "landmarks": travel_stats(d_a)},
            "b": {"final": distance_stats(final_b, target), "landmarks": travel_stats(d_b)},
            "_d": (d_a, d_b), "_final": (final_a, final_b)}


def normalised_all_vertices(shape: np.ndarray, target: np.ndarray, rest: np.ndarray) -> float:
    """sqrt(sum |target - shape|^2) / sqrt(sum |target - rest|^2) over all vertices. The lab's term has this
    form (evaluator.py:336-340 and :1112) but takes only its sampled control vertices; see the report."""
    return float(np.linalg.norm(target - shape) / np.linalg.norm(target - rest))


def groups_of(scene_json: dict, count: int) -> list[tuple[str, np.ndarray]]:
    by_name = {a["name"]: np.array([int(v) for v, w in a["weights"] if w > 0]) for a in scene_json["attachments"]}
    corners = np.unique(np.concatenate([v for k, v in by_name.items() if "corner" in k]))
    held = np.unique(np.concatenate(list(by_name.values())))
    return [("upper lip", by_name["upper_lip_on_skull"]), ("lower lip", by_name["lower_lip_on_jaw"]),
            ("corners", corners), ("vertices no attachment holds", np.setdiff1d(np.arange(count), held)),
            ("all vertices", np.arange(count))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", required=True, help="work folder outside the repo (ASCII path)")
    ap.add_argument("--target", help=f"the lab's {TARGET_NAME} (default: $ASRP_LAB_DATA/{TARGET_NAME})")
    ap.add_argument("--export", default=str(REPO / "data" / "lab_export"))
    ap.add_argument("--report", default=str(REPO / "data" / "preview" / "aa_standin_report.json"))
    args = ap.parse_args()
    work = Path(args.work).resolve()
    target_file = Path(args.target) if args.target else Path(os.environ.get("ASRP_LAB_DATA", "E:/Codebase/_lab/data")) / TARGET_NAME
    work.mkdir(parents=True, exist_ok=True)

    # 3a. the default scene
    scene_dir = work / "scene"
    shutil.rmtree(scene_dir, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "asrp_core.cli", "import-asset", args.export, str(scene_dir)], check=True,
                   stdout=subprocess.DEVNULL)
    scene_json = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    mm = scene_json["units"]["mm_per_scene_unit"]["value"]
    fps = float(scene_json["solver"]["fps"]["value"])
    default_fraction = next(d["blend"]["factor"]["value"] for d in scene_json["drivers"] if d.get("blend"))

    # 1. the target and the jaw
    t = read_target(target_file, mm)
    rest, _ = coords.read_obj(scene_dir / scene_json["soft_tissues"][0]["mesh"]["path"])
    rest = np.asarray(rest, dtype=float)
    target = t["lips1"]
    start_gap = float(np.linalg.norm(t["lips0"] - rest, axis=1).max())
    jaw_move, residual = rigid_fit(t["jaw0"], t["jaw1"])
    angle = rotation_degrees(jaw_move)
    print(f"jaw: a rigid motion of {angle:.3f} degrees fits the target's jaw to {residual:.2e} mm; "
          f"the target's starting lips are {start_gap:.2e} mm from the scene's rest lips")

    # 2. the jaw motion
    fractions = ramp_fractions()
    jaw_driver = next(d["name"] for d in scene_json["drivers"] if d.get("hinge"))
    jaw_frames = [trajectory.blend_transforms([jaw_move], f)[0] for f in fractions]
    source = (f"stand-in (ours): fitted from the lab's AA target shape, not the lab's controller output; jaw01 turns "
              f"{angle:.3f} degrees by a half cosine over {STEPS} frames after the {SETTLE}-frame settle; "
              f"tools/aa_standin.py, replaced by the T-10 conversion once D2 arrives")
    jaw_motion = trajectory.Trajectory(fps=fps, frames=len(jaw_frames), drivers={jaw_driver: jaw_frames},
                                       source_tag="ours", settle_until_frame=SETTLE, source=source)
    jaw_path = work / "aa_jaw.json"
    trajectory.write(jaw_path, jaw_motion)

    skin = skinning.load(scene_dir / scene_json["landmarks"]["weights"]["path"])
    weights = skin.weights
    names = list(scene_json["landmarks"]["names"])
    if names != skin.names:
        raise SystemExit("the scene's landmark names differ from the skin file's")
    exe, runs = febio_exe(), work / "runs"

    # 3. physics (default scene) and 6. the sweep
    results = {}
    for fraction in FRACTIONS:
        if fraction == default_fraction:
            results[fraction] = run_physics(scene_dir / "scene.json", jaw_path, runs, f"aa-default-{fraction:g}", exe)
        else:
            path = write_scene_copy(scene_dir, work / "sweep" / f"scene_{fraction:g}", fraction)
            results[fraction] = run_physics(path, jaw_path, runs, f"aa-{fraction:g}", exe)
    main_run = results[default_fraction]

    # 4. the fits (default scene)
    reports = {f: shape_report(r, weights, target, rest, RIDGE) for f, r in results.items()}
    rep = reports[default_fraction]
    d_a, d_b = rep["_d"]
    final_a, final_b = rep["_final"]
    last, settled = main_run["last"], main_run["settled"]
    zero = {}
    for key, base in (("a", settled), ("b", last)):
        d0, _ = ridge_fit(weights, target - base, 0.0)
        zero[key] = {"max_landmark_mm_ridge0": float(np.linalg.norm(d0, axis=1).max()),
                     "residual_ridge0": distance_stats(weights @ d0, target - base),
                     "residual_ridge": distance_stats(weights @ (rep["_d"][0 if key == "a" else 1]), target - base)}

    # 5. the motion files
    for tag, d in (("a", d_a), ("b", d_b)):
        landmarks = {"names": names, "translations_mm": ramp_translations(d, fractions).tolist()}
        motion = trajectory.Trajectory(fps=fps, frames=len(jaw_frames), drivers={jaw_driver: jaw_frames},
                                       source_tag="ours", settle_until_frame=SETTLE, landmarks=landmarks,
                                       source=source + f"; landmarks: variant {tag.upper()}, ridge {RIDGE:g}")
        trajectory.write(work / f"aa_{tag}.json", motion)
    checked = {}
    for tag in ("a", "b"):
        done = subprocess.run([sys.executable, "-m", "asrp_core.cli", "check", str(scene_dir / "scene.json"),
                               str(work / f"aa_{tag}.json")], capture_output=True, text=True)
        checked[tag] = done.returncode == 0
        print(f"asrp check aa_{tag}.json: {done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr.strip()}")

    # 7. the numbers
    normalised = {"physics_only": normalised_all_vertices(last, target, rest),
                  "a": normalised_all_vertices(final_a, target, rest), "b": normalised_all_vertices(final_b, target, rest)}
    moved = np.linalg.norm(target - rest, axis=1)
    riding_matrix = np.array([jaw_move[0:3], jaw_move[4:7], jaw_move[8:11]])
    riding = rest @ riding_matrix.T + np.array([jaw_move[3], jaw_move[7], jaw_move[11]]) - rest
    follow = {}
    for name, v in groups_of(scene_json, len(rest)):
        follow[name] = {"vertices": int(len(v)), "riding_mm": float(np.linalg.norm(riding[v], axis=1).mean()),
                        "target": follow_ratio(target - rest, riding, v), "physics_only": follow_ratio(last - rest, riding, v),
                        "a_final": follow_ratio(final_a - rest, riding, v), "b_final": follow_ratio(final_b - rest, riding, v),
                        "target_moves_mm": float(np.linalg.norm((target - rest)[v], axis=1).mean())}
    sweep = {}
    for fraction in FRACTIONS:
        r, s = reports[fraction], results[fraction]
        sweep[f"{fraction:g}"] = {"physics_only": r["physics_only"], "a": r["a"], "b": r["b"],
                                  "checks": s["checks"], "all_checks_passed": s["passed"]}
    pub = {k: v for k, v in rep.items() if not k.startswith("_")}
    report = {
        "format": "asrp-aa-standin-report/1",
        "note": "numbers and verdicts only. A stand-in for D2 (the lab's landmark motion); replaced by the T-10 conversion once D2 arrives. "
                "Variant A is expected to miss the target (docs/09 T-27, ADR-40); the fit guarantees reaching the target only for B and does not show the physics is right.",
        "command_line": " ".join(["uv run python tools/aa_standin.py", *sys.argv[1:]]),
        "lab_repo_commit": LAB_COMMIT,
        "counts": {"vertices": int(len(rest)), "landmarks": int(len(names)), "frames": len(jaw_frames),
                   "settle_until_frame": SETTLE, "ramp_frames": STEPS},
        "jaw": {"angle_degrees": angle, "rigid_fit_residual_mm": residual, "target_start_vs_rest_mm": start_gap},
        "ridge": {"value": RIDGE, "meaning": "times the mean diagonal of W^T W"},
        "anchor_fraction_default": default_fraction,
        "target_moves_from_rest_mm": {"max": float(moved.max()), "mean": float(moved.mean())},
        "distance_to_target": {"physics_only": pub["physics_only"], "a": pub["a"]["final"], "b": pub["b"]["final"]},
        "normalised_distance": None,
        "normalised_distance_reason": (
            "the lab term is the euclidean distance to the target divided by the euclidean distance at the start, "
            "taken over the lab's sampled control vertices (evaluator.py:336-340, :1092-1112; MeshDistanceCalculator "
            "in utils/distance_calculator.py); the vertex set is a concatenation of the lab's sampled lists and the "
            "start state is the payload's s_next, neither of which is pinned down here, so the exact value is not reported"),
        "normalised_distance_all_vertices": {
            "definition": "sqrt(sum |target - shape|^2) / sqrt(sum |target - rest|^2) over all vertices (same form, every vertex)",
            **normalised},
        "landmark_translations": {"a": pub["a"]["landmarks"], "b": pub["b"]["landmarks"]},
        "ridge_effect": {
            "a": {"max_landmark_mm_with_ridge": pub["a"]["landmarks"]["max_mm"], **zero["a"]},
            "b": {"max_landmark_mm_with_ridge": pub["b"]["landmarks"]["max_mm"], **zero["b"]}},
        "follow_ratio": follow,
        "anchor_sweep": sweep,
        "asrp_check_passed": checked,
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print_summary(report)
    print(f"\nwork folder {work}\nmotion files {work / 'aa_a.json'} and {work / 'aa_b.json'}\narchive {out}")
    if not all(checked.values()):
        raise SystemExit("asrp check failed for a motion file")


def print_summary(r: dict) -> None:
    c = r["counts"]
    print(f"\n{c['vertices']} vertices, {c['landmarks']} landmarks, {c['frames']} frames; jaw {r['jaw']['angle_degrees']:.3f} degrees "
          f"(residual {r['jaw']['rigid_fit_residual_mm']:.1e} mm); ridge {r['ridge']['value']:g}; default anchor fraction {r['anchor_fraction_default']:g}")
    print(f"the target moves the lips by at most {r['target_moves_from_rest_mm']['max']:.2f} mm (mean {r['target_moves_from_rest_mm']['mean']:.2f})")
    print("\ndistance of the final shape from the target (mm), at the last frame:")
    print(f"{'':14}{'max':>9}{'mean':>9}{'normalised (all vertices)':>28}")
    for k, label in (("physics_only", "physics only"), ("a", "A (jia)"), ("b", "B (yi)")):
        d = r["distance_to_target"][k]
        print(f"{label:14}{d['max_mm']:9.3f}{d['mean_mm']:9.3f}{r['normalised_distance_all_vertices'][k]:28.4f}")
    print("\nlanding translations (mm), ridge " + f"{r['ridge']['value']:g}" + ":")
    print(f"{'':6}{'max':>9}{'mean':>9}   histogram " + " ".join(HIST_LABELS))
    for k in ("a", "b"):
        t = r["landmark_translations"][k]
        print(f"{k.upper():6}{t['max_mm']:9.2f}{t['mean_mm']:9.2f}   " + " ".join(f"{t['histogram'][h]:>5}" for h in HIST_LABELS))
    print("\nridge effect (max landmark translation mm; fit residual max / mean mm):")
    for k in ("a", "b"):
        e = r["ridge_effect"][k]
        print(f"{k.upper()}: ridge 0 -> {e['max_landmark_mm_ridge0']:.2f}, ridge {r['ridge']['value']:g} -> {e['max_landmark_mm_with_ridge']:.2f}; "
              f"residual ridge 0 {e['residual_ridge0']['max_mm']:.3f} / {e['residual_ridge0']['mean_mm']:.3f}, "
              f"with ridge {e['residual_ridge']['max_mm']:.3f} / {e['residual_ridge']['mean_mm']:.3f}")
    print("\nfollow ratio against riding the jaw:")
    print(f"{'group':30}{'vertices':>9}{'riding mm':>10}{'target':>8}{'physics':>8}{'A final':>8}{'B final':>8}")
    for name, f in r["follow_ratio"].items():
        print(f"{name:30}{f['vertices']:9d}{f['riding_mm']:10.2f}{f['target']:8.2f}{f['physics_only']:8.2f}{f['a_final']:8.2f}{f['b_final']:8.2f}")
    print("\nanchor fraction sweep (mm): distance to target max/mean, landmark travel max/mean")
    print(f"{'fraction':>8} {'physics max':>11}{'mean':>7} | {'A final max':>11}{'mean':>7}{'A lm max':>9}{'mean':>7} | "
          f"{'B final max':>11}{'mean':>7}{'B lm max':>9}{'mean':>7} | checks")
    for fr, s in r["anchor_sweep"].items():
        verdict = " ".join(f"{k}:{'ok' if v else 'FAIL'}" for k, v in s["checks"].items())
        print(f"{fr:>8} {s['physics_only']['max_mm']:11.2f}{s['physics_only']['mean_mm']:7.2f} | "
              f"{s['a']['final']['max_mm']:11.2f}{s['a']['final']['mean_mm']:7.2f}{s['a']['landmarks']['max_mm']:9.2f}{s['a']['landmarks']['mean_mm']:7.2f} | "
              f"{s['b']['final']['max_mm']:11.2f}{s['b']['final']['mean_mm']:7.2f}{s['b']['landmarks']['max_mm']:9.2f}{s['b']['landmarks']['mean_mm']:7.2f} | {verdict}")


if __name__ == "__main__":
    main()
