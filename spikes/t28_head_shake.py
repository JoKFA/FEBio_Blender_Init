"""T-28 stage 3: summarise the head-shake runs into data/preview/t28_head_shake_report.json (numbers only from the runs).

    uv run python spikes/t28_head_shake.py <shake run> <still run> <demo run> [<before run> <after run>]

<shake run>: the lips with tools/head_shake_motion.py and today's solver settings (rhoi 0, no physical damping);
<still run>: the same scene and 87 frames with nothing moving (the control: what the settle alone does);
<demo run>: the same motion with a physical damping trial value and a lower numerical damping (both ours);
<before run>, <after run>: optional, the stage 2 proof (the stand-in jaw motion before and after the T-28 code,
`--threads 1`): the files are compared byte for byte, and the positions numerically.

Per run: the five checks, and `relative_to_head` from run_report.json (per frame, the largest displacement of the
free display vertices relative to the head, minus the settled frame 14). Also, for comparison with
spikes/audit_head_shake.py, the spike's own measure: the shake run minus the still run, relative to where the head
carries the vertices (a pure translation here), largest over the free vertices, during the shake (frames 16-46)
and after it. The run reports are copied next to the archive.
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "preview"
START, END = 16, 46
COMPARED = ("model.feb", "playback.json", "playback.pc2", "physics/display.npy", "physics/positions.npy",
            "physics/display.json", "physics/positions.json", "physics/settled_frame14.json", "physics/settled_frame14.obj")


def report(run: Path) -> dict:
    return json.loads((run / simulate.REPORT).read_text(encoding="utf-8"))


def summary(run: Path) -> dict:
    r = report(run)
    head = r.get("relative_to_head", {})
    curve = head.get("per_frame_max_mm", [])
    return {
        "run_id": r["run_id"], "status": r["status"], "passed": r["passed"],
        "checks": {k: c["passed"] for k, c in r["checks"].items()},
        "solver": r["generator"]["solver"],
        "relative_to_head": {k: v for k, v in head.items() if k != "per_frame_max_mm"},
        "relative_to_head_during_shake_max_mm": max(curve[START:END + 1]) if curve else None,
        "relative_to_head_after_shake_max_mm": max(curve[END + 1:]) if curve else None,
        "relative_to_head_last_frame_mm": curve[-1] if curve else None,
        "relative_to_head_per_frame_mm": curve,
    }


def spike_measure(shake: Path, still: Path) -> dict:
    """spikes/audit_head_shake.py's measure: (shake - head translation) - still, free vertices."""
    a = simulate.read_display(shake / simulate.DISPLAY)["positions"]
    b = simulate.read_display(still / simulate.DISPLAY)["positions"]
    traj = json.loads((shake / "trajectory.json").read_text(encoding="utf-8"))
    xs = np.array([m[3] for m in traj["drivers"]["head"]])
    scene = json.loads((shake / "scene.json").read_text(encoding="utf-8"))
    held = {int(v) for at in scene["attachments"] for v, w in at["weights"] if w > 0}
    free = np.array(sorted(set(range(a.shape[1])) - held))
    carried = np.zeros_like(a)
    carried[:, :, 0] = xs[:, None]
    rel = np.linalg.norm((a - carried - b)[:, free], axis=2).max(axis=1)
    return {"during_shake_max_mm": float(rel[START:END + 1].max()), "after_shake_max_mm": float(rel[END + 1:].max()),
            "last_frame_mm": float(rel[-1]), "per_frame_mm": rel.tolist(),
            "largest_head_offset_mm": float(np.abs(xs).max())}


def compare(before: Path, after: Path) -> dict:
    out = {}
    for name in COMPARED:
        out[name] = "identical" if (before / name).read_bytes() == (after / name).read_bytes() else "different"
    for name in ("physics/positions.npy", "physics/display.npy"):
        out[f"{name} max difference mm"] = float(np.abs(np.load(before / name) - np.load(after / name)).max())
    out["scene.json"] = "identical" if (before / "scene.json").read_bytes() == (after / "scene.json").read_bytes() \
        else "different (the importer writes the head driver, relative_to and the skull following the head)"
    return out


def main() -> None:
    if len(sys.argv) not in (4, 6):
        raise SystemExit(__doc__)
    shake, still, demo = (Path(p) for p in sys.argv[1:4])
    archive = {
        "format": "asrp-spike/1", "spike": "spikes/t28_head_shake.py",
        "motion": "tools/head_shake_motion.py (keys of the lab's script, our reading of Maya's auto tangents)",
        "measure": "relative_to_head: per frame, the largest displacement of the free display vertices relative to the "
                   "skull, minus the settled frame 14 (geometric mm)",
        "shake_default": summary(shake), "still_default": summary(still), "demo": summary(demo),
        "demo_settings": {"solver.damping (mass damping C, 1/s)": 45.0, "solver.numerical_damping_rhoi": 0.5,
                          "source": "ours, not the lab's (D6); a demonstration, chosen before the run, not searched",
                          "why": "zeta about 0.05 for a 14 ms lip mode (docs/05 pit 2): 2 x 0.05 x 2 pi / 0.014 s = 45 /s; "
                                 "rhoi 0.5 is one of spikes/audit_head_shake.py's values; substeps stay 1"},
        "spike_measure_default": spike_measure(shake, still),
        "earlier_spike_sine_rhoi0_1substep_mm": {"during": 0.088, "after": 0.106,
                                                 "source": "docs/13 E-09, spikes/audit_head_shake.py"},
    }
    if len(sys.argv) == 6:
        archive["stage2_before_after"] = compare(Path(sys.argv[4]), Path(sys.argv[5]))
    for key, run in (("shake_default", shake), ("still_default", still), ("demo", demo)):
        shutil.copyfile(run / simulate.REPORT, OUT / f"t28_{key}_run_report.json")
    (OUT / "t28_head_shake_report.json").write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8", newline="\n")
    for key in ("shake_default", "still_default", "demo"):
        s = archive[key]
        print(f"{key:14s} {s['status']} passed={s['passed']} checks={s['checks']} max={s['relative_to_head']['max_mm']:.4f} mm "
              f"at frame {s['relative_to_head']['frame']}; during {s['relative_to_head_during_shake_max_mm']:.4f}, after "
              f"{s['relative_to_head_after_shake_max_mm']:.4f}, last {s['relative_to_head_last_frame_mm']:.4f}")
    m = archive["spike_measure_default"]
    print(f"spike measure (shake - still): during {m['during_shake_max_mm']:.4f} mm, after {m['after_shake_max_mm']:.4f} mm, "
          f"last {m['last_frame_mm']:.2e}; head offset up to {m['largest_head_offset_mm']:.4f} mm")
    if "stage2_before_after" in archive:
        print(json.dumps(archive["stage2_before_after"], indent=1))


if __name__ == "__main__":
    main()
