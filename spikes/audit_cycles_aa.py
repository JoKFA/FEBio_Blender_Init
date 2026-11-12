"""One-off measurement (not product code): the AA motion (physics plus landmark layer) played out and back ten times.

T-29. spikes/audit_cycles.py asked the question of the physics layer alone (docs/13 E-08). This asks it with the
landmark layer on top: the one-way AA motion files of tools/aa_standin.py (variant A and B) are turned into
a ten-round-trip motion and run with `asrp run`. With our own motion the landmark translations are absolute per-frame
values (not accumulated segments), so the return frames are exactly the rest frame by construction; this does NOT
answer the lab's observation about concatenated action files (docs/11 P-06). Nothing here changes a default.

    uv run python spikes/audit_cycles_aa.py make <one-way motion.json> <out motion.json> [cycles]
    uv run asrp run <scene.json> <out motion.json> --runs-dir <runs> --name <name>
    uv run python spikes/audit_cycles_aa.py analyse <run a> <run b> --out data/preview/aa_cycles_report.json

The motion: the one-way file's frames 0..settle (still), then `cycles` times: the one-way file's ramp (36 frames out,
ending on the last frame of the file) and the same ramp reversed (36 frames back, ending on the rest frame).
Jaw transforms and landmark translations are replayed as the file holds them, never accumulated.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from asrp_core import run, scene, tetmesh, trajectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_aa_folds  # noqa: E402

CYCLES = 10


def cycle_order(settle: int, ramp: int, cycles: int) -> list[int]:
    """For each frame of the long motion, the frame of the one-way file it replays.

    0..settle, then per cycle: settle+1 .. settle+ramp (out), then settle+ramp-1 .. settle (back, ending on rest)."""
    order = list(range(settle + 1))
    for _ in range(cycles):
        order += list(range(settle + 1, settle + ramp + 1))
        order += list(range(settle + ramp - 1, settle - 1, -1))
    return order


def build(one_way: trajectory.Trajectory, cycles: int = CYCLES, source: str | None = None) -> trajectory.Trajectory:
    """The long motion. The one-way file must have settle_until_frame and a ramp after it."""
    settle = one_way.settle_until_frame
    if settle is None:
        raise ValueError("the one-way motion has no settle_until_frame")
    ramp = one_way.frames - settle - 1
    if ramp < 2:
        raise ValueError("the one-way motion has no ramp after its settle frames")
    order = cycle_order(settle, ramp, cycles)
    drivers = {name: [list(map(float, transforms[i])) for i in order] for name, transforms in one_way.drivers.items()}
    landmarks = None
    if one_way.landmarks is not None:
        names, t = trajectory.landmark_translations(one_way)
        landmarks = {"names": names, "translations_mm": t[order].tolist()}
    return trajectory.Trajectory(
        fps=one_way.fps, frames=len(order), drivers=drivers, landmarks=landmarks, source_tag=one_way.source_tag,
        settle_until_frame=settle,
        source=source or f"{one_way.source}; repeated out and back {cycles} times (spikes/audit_cycles_aa.py)")


def frame_numbers(settle: int, ramp: int, cycles: int) -> tuple[list[int], list[int]]:
    """The frames on which the jaw is back at rest, and the frames at the open pose, one per cycle."""
    back = [settle + 2 * ramp * c for c in range(1, cycles + 1)]
    open_ = [settle + ramp + 2 * ramp * c for c in range(cycles)]
    return back, open_


def series(values: list[float]) -> dict:
    """A list of per-cycle numbers with its first, last, largest and the sign of a straight-line fit."""
    v = np.asarray(values, dtype=float)
    slope = float(np.polyfit(np.arange(1, len(v) + 1), v, 1)[0]) if len(v) > 1 else 0.0
    return {"values": [float(x) for x in v], "first": float(v[0]), "last": float(v[-1]), "largest": float(v.max()),
            "largest_at_cycle": int(v.argmax()) + 1, "slope_per_cycle": slope,
            "slope_sign": "flat" if abs(slope) <= 1e-9 * float(np.abs(v).max()) else "up" if slope > 0 else "down"}


def distances(shapes: np.ndarray, frames: list[int], reference: np.ndarray) -> tuple[list[float], list[float]]:
    d = [np.linalg.norm(shapes[f] - reference, axis=1) for f in frames]
    return [float(x.max()) for x in d], [float(x.mean()) for x in d]


def make(one_way_path: Path, out: Path, cycles: int) -> None:
    long = build(trajectory.read(one_way_path), cycles)
    trajectory.write(out, long)
    print(f"wrote {out}: {long.frames} frames")


def analyse_run(folder: Path, cycles: int) -> dict:
    report = json.loads((folder / "run_report.json").read_text(encoding="utf-8"))
    sc = scene.load(folder / "scene.json")
    mesh, _ = tetmesh.load(folder / sc.soft_tissues[0].tet_mesh.path)
    settle = report["settled_shape"]["frame"]
    total = report["frames"]
    ramp = (total - settle - 1) // (2 * cycles)
    back, open_ = frame_numbers(settle, ramp, cycles)

    data = run.read_positions(folder / run.POSITIONS)
    index = {nid: i for i, nid in enumerate(data["node_ids"])}
    rows = [index[i + 1] for i in range(len(mesh.nodes))]
    # positions.npy has no frame 0 (the rest pose): row i is frame i + 1, found by time as spikes/audit_cycles.py does
    fps = float(sc.solver.fps.value)
    row_of = {round(t * fps): i for i, t in enumerate(data["times_s"])}
    nodes = np.asarray(data["positions"])[:, rows]
    phys_max, phys_mean = distances(nodes, [row_of[f] for f in back], nodes[row_of[settle]])

    final = np.load(folder / "final" / "display.npy", allow_pickle=False)
    faces = np.array(json.loads((folder / "playback.json").read_text(encoding="utf-8"))["faces"])
    fin_max, fin_mean = distances(final, back, final[settle])
    open_max, open_mean = distances(final, open_, final[open_[0]])
    health = {f"cycle_{c}": audit_aa_folds.folds(final[0], final[open_[c - 1]], faces) for c in (1, cycles)}
    for h in health.values():
        h["edge ratio min / max"] = list(h["edge ratio min / max"])

    d = report["checks"]["d"]["numbers"]
    agg = report["return_to_settled"]
    return {
        "frames": total, "return_frames": back, "open_frames": open_,
        "checks": {k: {"passed": bool(c["passed"])} for k, c in report["checks"].items()},
        "all_passed": bool(report["passed"]), "not_run": report["not_run"],
        "check_d": {k: d[k] for k in ("min_volume_ratio", "min_volume_ratio_frame", "max_volume_ratio", "inverted_tets",
                                      "frames_with_inverted_tets", "tets", "frames")},
        "return_to_settled_report": {"returns_found": len(agg["frames"]), "max_mm": agg.get("max_mm"), "mean_mm": agg.get("mean_mm")},
        "physics_return_max_mm": series(phys_max), "physics_return_mean_mm": series(phys_mean),
        "final_return_max_mm": series(fin_max), "final_return_mean_mm": series(fin_mean),
        "final_open_max_mm": series(open_max), "final_open_mean_mm": series(open_mean),
        "mesh_health_open": health,
    }


def analyse(run_a: Path, run_b: Path, out: Path, cycles: int) -> None:
    result = {
        "format": "asrp-aa-cycles/1",
        "what": "the AA motion (variants A and B) out and back ten times; spikes/audit_cycles_aa.py",
        "cycles": cycles, "frames_per_half": None,
        "mesh_health_definition": "spikes/audit_aa_folds.py: faces of the lips whose normal points the other way against the rest "
                                  "lips (dot < 0), edges shorter than 0.5x their rest length, on final/display.npy at the open frame",
        "command": ["uv run python spikes/audit_cycles_aa.py make <work>/aa_a.json <work>/cycles_a.json",
                    "uv run python spikes/audit_cycles_aa.py make <work>/aa_b.json <work>/cycles_b.json",
                    "uv run asrp run <work>/scene/scene.json <work>/cycles_a.json --runs-dir <work>/runs --name aa-cycles-a",
                    "uv run asrp run <work>/scene/scene.json <work>/cycles_b.json --runs-dir <work>/runs --name aa-cycles-b",
                    "uv run python spikes/audit_cycles_aa.py analyse <run a> <run b> --out data/preview/aa_cycles_report.json"],
        "a": analyse_run(run_a, cycles), "b": analyse_run(run_b, cycles),
    }
    result["frames_per_half"] = (result["a"]["frames"] - 15) // (2 * cycles)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    preview = out.parent
    for key, folder in (("a", run_a), ("b", run_b)):
        text = (folder / "run_report.json").read_text(encoding="utf-8")
        (preview / f"aa_cycles_{key}_run_report.json").write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out} and the two run reports")
    print_tables(result)


def print_tables(r: dict) -> None:
    for key in ("a", "b"):
        x = r[key]
        print(f"\n== variant {key.upper()}: {x['frames']} frames; all checks passed: {x['all_passed']}; not run: {x['not_run']}")
        print("checks:", {k: v["passed"] for k, v in x["checks"].items()}, "check d:", x["check_d"])
        print("return_to_settled (report aggregate):", x["return_to_settled_report"])
        for name in ("physics_return_max_mm", "physics_return_mean_mm", "final_return_max_mm", "final_return_mean_mm",
                     "final_open_max_mm", "final_open_mean_mm"):
            s = x[name]
            print(f"{name}: " + " ".join(f"{v:.3e}" for v in s["values"]))
            print(f"    first {s['first']:.3e}  last {s['last']:.3e}  largest {s['largest']:.3e} (cycle {s['largest_at_cycle']})  "
                  f"slope {s['slope_per_cycle']:.3e}/cycle ({s['slope_sign']})")
        for c, h in x["mesh_health_open"].items():
            print(c, h)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("one_way", type=Path)
    m.add_argument("out", type=Path)
    m.add_argument("cycles", type=int, nargs="?", default=CYCLES)
    a = sub.add_parser("analyse")
    a.add_argument("run_a", type=Path)
    a.add_argument("run_b", type=Path)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--cycles", type=int, default=CYCLES)
    args = ap.parse_args()
    if args.cmd == "make":
        make(args.one_way, args.out, args.cycles)
    else:
        analyse(args.run_a, args.run_b, args.out, args.cycles)


if __name__ == "__main__":
    main()
