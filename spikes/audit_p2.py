"""Audit measurements for prototype two (docs/13 E-10; read-only, nothing written; the lab target stays outside the repo).
uv run python spikes/audit_p2.py <repo> <lab AA target file> <run A> <run B> [<extra run folders for the settle question>...]"""
import ast
import json
import re
import sys
from pathlib import Path

import numpy as np

repo, target_file, run_a, run_b, *others = map(Path, sys.argv[1:])
sys.path.insert(0, str(repo / "src"))
sys.path.insert(0, str(repo / "spikes"))
from audit_aa_folds import folds  # noqa: E402

from asrp_core.asset import coords  # noqa: E402

text = target_file.read_text(encoding="utf-8")


def lab(name):
    m = re.search(rf"^{name}\s*=\s*(.+)$", text, re.M)
    assert m, name
    return np.array(ast.literal_eval(m.group(1)), dtype=float).reshape(-1, 3)


faces = np.array(json.loads((run_a / "playback.json").read_text(encoding="utf-8"))["faces"])
tri = coords.triangulate(faces.tolist()) if faces.shape[1] != 3 else faces
mm = json.loads((run_a / "scene.json").read_text(encoding="utf-8"))["units"]["mm_per_scene_unit"]["value"]
rest_lab, target = coords.to_mm_zup(lab("x_middleres_OrbicularisOris0"), mm), coords.to_mm_zup(lab("x_middleres_OrbicularisOris1"), mm)
phys = np.load(run_a / "physics" / "display.npy")
print("1. folds against each one's own rest shape; faces", len(tri), "(triangles used:", faces.shape, "->", tri.shape, ")")
print("   our rest vs lab rest, max distance mm:", float(np.linalg.norm(phys[0] - rest_lab, axis=1).max()))
rows = {"lab AA target": (rest_lab, target), "physics only (last frame)": (phys[0], phys[-1]),
        "A final": (phys[0], np.load(run_a / "final" / "display.npy")[-1]),
        "B final": (phys[0], np.load(run_b / "final" / "display.npy")[-1])}
for name, (r, s) in rows.items():
    f = folds(r, s, tri)
    print(f"   {name:28} flipped {f['flipped (dot < 0)']:3d}  edges<0.5x {f['edges < 0.5x']:4d}  edges>2x {f['edges > 2x']:3d}  "
          f"edge ratio {f['edge ratio min / max']}  min area ratio {f['smallest face area ratio']}")

print("2. is the tissue still at the frame called 'settled'? tet nodes, frame n vs n-1 (positions.npy row i = frame i+1)")
for run in [run_a, *others]:
    rep = json.loads((run / "run_report.json").read_text(encoding="utf-8"))
    s = rep.get("settled_shape", {})
    n = s.get("frame")
    p = np.load(run / "physics" / "positions.npy")
    params = {r["where"]: r["value"] for r in rep["parameters"] if "damping" in r["where"] or "rhoi" in r["where"]}
    if not n:
        print(f"   {run.name}: no settled frame ({s})")
        continue
    step = np.linalg.norm(p[n - 1] - p[n - 2], axis=1)
    sag = np.linalg.norm(p[n - 1] - p[0], axis=1)  # frame n vs frame 1
    later = np.linalg.norm(p[-1] - p[n - 1], axis=1) if rep["frames"] > n + 1 else None
    print(f"   {run.name}: settled.available {s.get('available')} frame {n}; frame {n} vs {n-1}: max {step.max():.2e} mm; "
          f"frame {n} vs frame 1: max {sag.max():.3e} mm; damping settings {params}"
          + (f"; last frame vs frame {n}: max {later.max():.2e} mm" if later is not None else ""))
