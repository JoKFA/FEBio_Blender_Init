"""Time-step refinement of the head shake (T-28 audit, docs/13 E-10 items G and D).

    uv run python spikes/audit_head_shake_timestep.py --work <folder outside the repo, ASCII path>
        [--scene <scene.json> --shake <head_shake.json> --still <head_still.json>]
        [--workers 3] [--timeout 7200] [--stage run|analyse|all]

The question: the head-shake result (lips move at most 0.094 mm against the head) was computed with one solver step
per frame (dt = 1/30 s). Does it change when only the number of solver steps per frame changes, the motion, the scene
and the physical parameters held fixed? Nothing is tuned; no default is changed; the scene is copied per run setting.

Series (each substep count is run twice: the shake, and the still control, same settings, nothing moves):
  A  rhoi 0 (the generator's default, not written into the scene), no physical damping: substeps 1, 2, 4, 8, 16
  B  rhoi -2 (Newmark, "no numerical damping"), no physical damping:                     substeps 1, 2, 4, 8, 16
  C  the T-28 demonstration (C = 45 /s, rhoi 0.5, both ours):                            substeps 1, 2, 4, 8

Runs that fail are kept as results (frame and message). Finished runs are skipped on a second call, so the script can
be run again. If --scene/--shake/--still are not given they are rebuilt in <work>/inputs from data/lab_export and
tools/head_shake_motion.py. The numbers are written to data/preview/audit_head_shake_timestep.json; run folders stay in
<work> (not archived).

Measures per run: the run report's relative_to_head curve (per frame, the largest displacement of a free display vertex
against the head, minus the settled frame 14), its maximum during the shake (frames 16-46) and after it (47-86);
the shake-minus-still curve (curve difference) and the vector measure of spikes/audit_head_shake.py (per vertex,
(shake - what the head carries) - still, the largest over the free vertices); the tissue's step between frames 13 and 14
(largest node displacement, physics/positions.npy) = is the settle finished when the shake starts; the FEBio retries.
Convergence: inside a series, the largest frame-by-frame difference between the curve at n and at 2n substeps, and the
change of the peak value and its frame. No extrapolation.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from asrp_core import febio, provenance, run, simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "preview" / "audit_head_shake_timestep.json"
START, END = 16, 46  # the shake (frames); after it: END + 1 ...
SETTLE = 14
SERIES = {
    "A": {"rhoi": None, "damping": 0.0, "substeps": [1, 2, 4, 8, 16],
          "text": "rhoi 0 (the default, not written into the scene), no physical damping"},
    "B": {"rhoi": -2.0, "damping": 0.0, "substeps": [1, 2, 4, 8, 16],
          "text": "rhoi -2 (Newmark, no numerical damping), no physical damping"},
    "C": {"rhoi": 0.5, "damping": 45.0, "substeps": [1, 2, 4, 8],
          "text": "the T-28 demonstration: C = 45 /s, rhoi 0.5 (both ours, not the lab's)"},
}


def _clean(text: str, work: Path) -> str:
    for form in (str(work), work.as_posix(), str(work).replace("\\", "\\\\")):
        text = text.replace(form, "<work>")
    return re.sub(r"[A-Za-z]:[\\/][^\s\"']*", "<path>", text)


def ensure_inputs(args) -> tuple[Path, Path, Path]:
    if args.scene and args.shake and args.still:
        return Path(args.scene), Path(args.shake), Path(args.still)
    d = args.work / "inputs"
    scene = d / "scene" / "scene.json"
    if not scene.exists():
        subprocess.run([sys.executable, "-m", "asrp_core.cli", "import-asset", str(ROOT / "data" / "lab_export"),
                        str(d / "scene")], check=True, cwd=ROOT)
    shake, still = d / "head_shake.json", d / "head_still.json"
    if not shake.exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "head_shake_motion.py"), str(scene), str(shake)],
                       check=True, cwd=ROOT)
    if not still.exists():
        t = json.loads(shake.read_text(encoding="utf-8"))
        eye = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        t["drivers"] = {k: [list(eye) for _ in v] for k, v in t["drivers"].items()}
        t["source"] = "the head shake's length with nothing moving (control); " + t["source"]
        still.write_text(json.dumps(t, indent=1) + "\n", encoding="utf-8", newline="\n")
    return scene, shake, still


def configs() -> list[dict]:
    out = []
    for s, c in SERIES.items():
        for n in c["substeps"]:
            out.append({"series": s, "substeps": n, "damping": c["damping"], "rhoi": c["rhoi"], "tag": f"{s}{n:02d}"})
    return out


def make_scene(base: Path, cfg: dict, work: Path) -> Path:
    """A copy of the scene folder with only the solver parameters of this run changed."""
    dest = work / "scenes" / cfg["tag"]
    if not (dest / "scene.json").exists():
        shutil.copytree(base.parent, dest)
        data = json.loads((dest / "scene.json").read_text(encoding="utf-8"))
        sol = data["solver"]
        why = "time-step refinement study (spikes/audit_head_shake_timestep.py)"
        sol["substeps_per_frame"] = {"value": cfg["substeps"], "source": "ours", "note": why}
        sol["damping"] = {"value": cfg["damping"], "source": "ours", "note": why}
        if cfg["rhoi"] is not None:
            sol["numerical_damping_rhoi"] = {"value": cfg["rhoi"], "source": "ours", "note": why}
        (dest / "scene.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                         newline="\n")
    return dest / "scene.json"


def run_dir_of(work: Path, name: str) -> Path | None:
    found = sorted((work / "runs" / name).glob("*/" + simulate.REPORT)) if (work / "runs" / name).exists() else []
    return found[-1].parent if found else None


def run_one(job: tuple, work: Path, timeout: float) -> str:
    name, scene, traj = job
    if run_dir_of(work, name):
        return f"{name}: already done"
    log = work / "logs"
    log.mkdir(exist_ok=True)
    with open(log / f"{name}.txt", "w", encoding="utf-8") as f:
        subprocess.run([sys.executable, "-m", "asrp_core.cli", "run", str(scene), str(traj), "--runs-dir",
                        str(work / "runs" / name), "--name", name, "--timeout", str(timeout)],
                       stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
    return f"{name}: finished"


def run_all(args, scene, shake, still) -> None:
    jobs = []
    for cfg in sorted(configs(), key=lambda c: -c["substeps"]):  # the long ones first
        sc = make_scene(scene, cfg, args.work)
        jobs += [(f"{cfg['tag']}_shake", sc, shake), (f"{cfg['tag']}_still", sc, still)]
    with ThreadPoolExecutor(args.workers) as pool:
        for msg in pool.map(lambda j: run_one(j, args.work, args.timeout), jobs):
            print(msg, flush=True)


# --- analysis -----------------------------------------------------------------------------------------------------

def peak(curve, lo, hi):
    seg = curve[lo:hi + 1]
    i = int(np.argmax(seg))
    return {"max_mm": float(seg[i]), "frame": lo + i}


def read_run(work: Path, name: str, fps: float) -> dict | None:
    d = run_dir_of(work, name)
    if d is None:
        return None
    rep = json.loads((d / simulate.REPORT).read_text(encoding="utf-8"))
    rec = provenance.read(d)
    log = d / run.LOG_NAME
    text = log.read_text(errors="replace") if log.exists() else ""
    out = {"dir": d, "run_id": d.name, "status": rep["status"], "passed": rep["passed"],
           "checks": {k: c["passed"] for k, c in rep["checks"].items()},
           "check_messages_not_passed": {k: _clean(c["message"], work) for k, c in rep["checks"].items()
                                         if c["passed"] is not True},
           "retries": text.count("Retrying time step"),
           "febio_version": febio.version(log) if log.exists() else None,
           "solver_in_force": rep["generator"]["solver"],
           "complete": rep["status"] == "complete"}
    if not out["complete"]:
        fail = rec.get("failure") or {}
        out["failure"] = {"frame": fail.get("frame"), "message": _clean(str(fail.get("message")), work)}
        return out
    rel = rep["relative_to_head"]
    out["curve"] = np.array(rel["per_frame_max_mm"])
    out["reference_frame"] = rel["reference_frame"]
    out["max_mm"], out["max_frame"] = rel["max_mm"], rel["frame"]
    pos = run.read_positions(d / run.POSITIONS)
    logged = [round(t * fps) for t in pos["times_s"]]
    n_tissue = rep["generator"]["febio_nodes"]["tissue"]
    ids = list(pos["node_ids"])
    tissue = [ids.index(i) for i in range(1, n_tissue + 1)]
    by_frame = {f: np.asarray(p)[tissue] for f, p in zip(logged, pos["positions"])}
    out["settle_step_13_to_14_mm"] = float(np.linalg.norm(by_frame[14] - by_frame[13], axis=1).max())
    out["display"] = simulate.read_display(d / simulate.DISPLAY)["positions"]
    return out


def vector_measure(shake: dict, still: dict, traj: dict, held: set) -> np.ndarray:
    """spikes/audit_head_shake.py's measure: per frame, the largest over the free vertices of
    |(shake - carried by the head) - still| (mm); the head here is a pure translation along x."""
    a, b = shake["display"], still["display"]
    xs = np.array([m[3] for m in traj["drivers"]["head"]])
    free = np.array(sorted(set(range(a.shape[1])) - held))
    carried = np.zeros_like(a)
    carried[:, :, 0] = xs[:, None]
    return np.linalg.norm((a - carried - b)[:, free], axis=2).max(axis=1)


def summarise(cfg: dict, shake: dict | None, still: dict | None, traj: dict, held: set) -> dict:
    row = {"series": cfg["series"], "substeps": cfg["substeps"], "tag": cfg["tag"],
           "settings": {"substeps_per_frame": cfg["substeps"], "damping_C_per_s": cfg["damping"],
                        "rhoi": 0.0 if cfg["rhoi"] is None else cfg["rhoi"],
                        "rhoi_written_into_scene": cfg["rhoi"] is not None}}
    for kind, r in (("shake", shake), ("still", still)):
        if r is None:
            row[kind] = {"status": "not run"}
            continue
        e = {k: r[k] for k in ("run_id", "status", "passed", "checks", "check_messages_not_passed", "retries",
                               "solver_in_force", "febio_version")}
        if r["complete"]:
            c = r["curve"]
            e.update({"reference_frame": r["reference_frame"], "report_max_mm": r["max_mm"], "report_max_frame": r["max_frame"],
                      "during_shake": peak(c, START, END), "after_shake": peak(c, END + 1, len(c) - 1),
                      "last_frame_mm": float(c[-1]), "settle_step_13_to_14_mm": r["settle_step_13_to_14_mm"],
                      "relative_to_head_per_frame_mm": [round(float(v), 9) for v in c]})
        else:
            e["failure"] = r["failure"]
        row[kind] = e
    if shake and still and shake["complete"] and still["complete"]:
        diff = shake["curve"] - still["curve"]
        vec = vector_measure(shake, still, traj, held)
        row["shake_minus_still"] = {
            "curve_difference_during_shake": peak(diff, START, END),
            "curve_difference_after_shake": peak(diff, END + 1, len(diff) - 1),
            "curve_difference_per_frame_mm": [round(float(v), 9) for v in diff],
            "vector_measure_during_shake": peak(vec, START, END),
            "vector_measure_after_shake": peak(vec, END + 1, len(vec) - 1),
            "vector_measure_per_frame_mm": [round(float(v), 9) for v in vec],
        }
    return row


def convergence(rows: list[dict]) -> list[dict]:
    """Inside one series: n against 2n."""
    out = []
    by = {r["substeps"]: r for r in rows}
    for n in sorted(by):
        a, b = by.get(n), by.get(2 * n)
        if b is None:
            continue
        entry = {"coarser": n, "finer": 2 * n}
        for kind in ("shake", "still"):
            if "relative_to_head_per_frame_mm" in a[kind] and "relative_to_head_per_frame_mm" in b[kind]:
                ca = np.array(a[kind]["relative_to_head_per_frame_mm"])
                cb = np.array(b[kind]["relative_to_head_per_frame_mm"])
                d = np.abs(ca - cb)
                late = d[SETTLE + 1:]  # frames 15 on: the shake and after (frames 0-14 are the gravity settle itself)
                entry[kind] = {"max_curve_difference_mm": float(d.max()), "at_frame": int(d.argmax()),
                               "max_curve_difference_frames_15_on_mm": float(late.max()),
                               "at_frame_15_on": SETTLE + 1 + int(late.argmax()),
                               "finer_curve_max_mm": float(cb.max()),
                               "during_peak_mm": [a[kind]["during_shake"]["max_mm"], b[kind]["during_shake"]["max_mm"]],
                               "during_peak_frame": [a[kind]["during_shake"]["frame"], b[kind]["during_shake"]["frame"]],
                               "after_peak_mm": [a[kind]["after_shake"]["max_mm"], b[kind]["after_shake"]["max_mm"]],
                               "after_peak_frame": [a[kind]["after_shake"]["frame"], b[kind]["after_shake"]["frame"]]}
            else:
                entry[kind] = {"compared": False, "reason": "one of the two runs failed"}
        if "shake_minus_still" in a and "shake_minus_still" in b:
            va = np.array(a["shake_minus_still"]["vector_measure_per_frame_mm"])
            vb = np.array(b["shake_minus_still"]["vector_measure_per_frame_mm"])
            d = np.abs(va - vb)
            entry["shake_minus_still_vector_measure"] = {
                "max_curve_difference_mm": float(d.max()), "at_frame": int(d.argmax()),
                "during_peak_mm": [a["shake_minus_still"]["vector_measure_during_shake"]["max_mm"],
                                   b["shake_minus_still"]["vector_measure_during_shake"]["max_mm"]],
                "during_peak_frame": [a["shake_minus_still"]["vector_measure_during_shake"]["frame"],
                                      b["shake_minus_still"]["vector_measure_during_shake"]["frame"]],
                "after_peak_mm": [a["shake_minus_still"]["vector_measure_after_shake"]["max_mm"],
                                  b["shake_minus_still"]["vector_measure_after_shake"]["max_mm"]],
                "after_peak_frame": [a["shake_minus_still"]["vector_measure_after_shake"]["frame"],
                                     b["shake_minus_still"]["vector_measure_after_shake"]["frame"]]}
        out.append(entry)
    return out


def motion_between_frames(traj: dict) -> dict:
    """What the generator does between frames: generate.py writes the prescribed motion as LINEAR load curves with a
    point per frame, so inside a frame the body moves at constant speed and the speed jumps at every frame sample."""
    fps = traj["fps"]
    x = np.array([m[3] for m in traj["drivers"]["head"]])
    v = np.diff(x) * fps  # speed in each frame interval (mm/s): v[f] is frame f -> f+1
    jump = np.abs(np.diff(v))  # at frame sample f+1: |v[f+1] - v[f]|
    i = int(jump.argmax())
    return {"head_translation": "along x, the same for the head and jaw01 drivers",
            "interpolation_in_generate_py": "linear: every load curve of a rigid-body displacement has one point per frame "
                                            "(<interpolate>LINEAR</interpolate>), so with n substeps the body moves in n "
                                            "equal increments per frame at constant speed",
            "consequence": "the velocity jumps at every frame sample (zero in the still run); refining the time step does "
                           "not remove these jumps, it resolves them",
            "head_speed_max_mm_per_s": float(np.abs(v).max()), "head_speed_max_frame_interval": int(np.abs(v).argmax()),
            "velocity_jump_max_mm_per_s": float(jump.max()), "velocity_jump_max_at_frame": i + 1,
            "velocity_jump_ratio_to_max_speed": float(jump.max() / np.abs(v).max()),
            "frames_with_a_jump_above_1_percent_of_max_speed": int((jump > 0.01 * np.abs(v).max()).sum()),
            "note": "the output is written at frame ends only, so the response inside a frame is not seen"}


def analyse(args, scene, shake_path, still_path) -> None:
    traj = json.loads(Path(shake_path).read_text(encoding="utf-8"))
    sc = json.loads(Path(scene).read_text(encoding="utf-8"))
    held = {int(v) for at in sc["attachments"] for v, w in at["weights"] if w > 0}
    rows_by_series: dict[str, list] = {s: [] for s in SERIES}
    versions = set()
    for cfg in configs():
        sh, st = (read_run(args.work, f"{cfg['tag']}_{k}", traj["fps"]) for k in ("shake", "still"))
        for r in (sh, st):
            if r and r["febio_version"]:
                versions.add(r["febio_version"])
        rows_by_series[cfg["series"]].append(summarise(cfg, sh, st, traj, held))
        print(f"{cfg['tag']}: shake {rows_by_series[cfg['series']][-1]['shake'].get('status')}, "
              f"still {rows_by_series[cfg['series']][-1]['still'].get('status')}", flush=True)
    archive = {
        "format": "asrp-spike/1", "spike": "spikes/audit_head_shake_timestep.py",
        "command": "uv run python spikes/audit_head_shake_timestep.py --work <folder outside the repo>",
        "febio_version": sorted(versions), "motion_frames": traj["frames"],
        "motion": "tools/head_shake_motion.py (87 frames); the still control has the same length, nothing moves",
        "windows": {"during_shake_frames": [START, END], "after_shake_frames": [END + 1, traj["frames"] - 1],
                    "settle_frame": SETTLE},
        "measures": {
            "relative_to_head": "run report: per frame, the largest displacement of a free display vertex against the head, "
                                "minus the settled frame (geometric mm)",
            "curve_difference": "shake curve minus still curve, frame by frame",
            "vector_measure": "spikes/audit_head_shake.py's measure: per free vertex (shake - carried by the head) - still, "
                              "largest over the free vertices",
            "settle_step_13_to_14_mm": "largest tissue node displacement between frames 13 and 14, physics/positions.npy "
                                       "(geometric mm): the settle is finished when it is near zero",
            "retries": "FEBio 'Retrying time step' lines in the run log"},
        "motion_between_frames": motion_between_frames(traj),
        "series": {s: {"description": SERIES[s]["text"], "runs": rows_by_series[s], "convergence": convergence(rows_by_series[s])}
                   for s in SERIES},
    }
    OUT.write_text(json.dumps(archive, indent=1) + "\n", encoding="utf-8", newline="\n")
    print_tables(archive)


def print_tables(a: dict) -> None:
    print(json.dumps(a["motion_between_frames"], indent=1))
    for s, body in a["series"].items():
        print(f"\nSeries {s}: {body['description']}")
        print("n   shake                  during(mm@f)   after(mm@f)   S-S vec during/after   settle13-14   retries  vs next finer")
        conv = {c["coarser"]: c for c in body["convergence"]}
        for r in body["runs"]:
            sh, st = r["shake"], r["still"]
            if sh.get("status") != "complete":
                f = sh.get("failure", {})
                print(f"{r['substeps']:<3d} {sh.get('status')} at frame {f.get('frame')}: {f.get('message')}  (retries {sh.get('retries')})")
                continue
            ss = r.get("shake_minus_still", {})
            vd = ss.get("vector_measure_during_shake", {})
            va = ss.get("vector_measure_after_shake", {})
            c = conv.get(r["substeps"], {}).get("shake", {})
            print(f"{r['substeps']:<3d} passed={sh['passed']!s:5s}  {sh['during_shake']['max_mm']:.4f}@{sh['during_shake']['frame']:<3d}  "
                  f"{sh['after_shake']['max_mm']:.4f}@{sh['after_shake']['frame']:<3d}  "
                  f"{vd.get('max_mm', float('nan')):.4f}/{va.get('max_mm', float('nan')):.4f}  "
                  f"{sh['settle_step_13_to_14_mm']:.2e}  {sh['retries']}  "
                  f"{c.get('max_curve_difference_mm', float('nan')):.4f} (frames 15 on: "
                  f"{c.get('max_curve_difference_frames_15_on_mm', float('nan')):.4f})")
            if st.get("status") != "complete":
                print(f"    still run: {st.get('status')} {st.get('failure')}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--scene")
    p.add_argument("--shake")
    p.add_argument("--still")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--timeout", type=float, default=7200)
    p.add_argument("--stage", choices=("run", "analyse", "all"), default="all")
    args = p.parse_args()
    args.work = args.work.resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    if not str(args.work).isascii():
        raise SystemExit("the work folder path must be ASCII (FEBio)")
    scene, shake, still = ensure_inputs(args)
    if args.stage in ("run", "all"):
        run_all(args, scene, shake, still)
    if args.stage in ("analyse", "all"):
        analyse(args, scene, shake, still)


if __name__ == "__main__":
    main()
