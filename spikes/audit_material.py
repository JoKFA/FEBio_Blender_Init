"""One-off measurement (not product code): how much does the soft tissue's stiffness change the result?

Runs one scene (a folder made by `asrp import-asset`) with one motion three times: as it is, with the soft
tissue's Young's modulus E times 10, and E divided by 10 (the scene folder is copied for each variant and only
E in its scene.json is edited). For each variant it prints the verdict and the mean sag of check (c) (does the
check's range follow the material?), and how far the display vertices are from the baseline's at the frame
where the baseline moves most (largest distance of any display vertex from its rest position). docs/13 E-08
and ADR-37 item 3 quote the numbers; it answers whether the placeholder E (15 kPa, a value we chose) matters.

    uv run python spikes/audit_material.py <scene folder> <trajectory.json> <an empty work folder>

The work folder gets one copy of the scene and one run folder per variant (git-ignored, e.g. runs/b4/audit).
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate
from asrp_core.doctor import febio_exe

VARIANTS = (("baseline (E as is)", 1.0), ("E x 10", 10.0), ("E / 10", 0.1))


def edit_young(scene_json: Path, factor: float) -> float:
    """Multiply the (one) soft tissue's E_mpa in this scene.json by factor; returns the new E."""
    data = json.loads(scene_json.read_text(encoding="utf-8"))
    [tissue] = data["soft_tissues"]
    tissue["material"]["E_mpa"]["value"] *= factor
    scene_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return tissue["material"]["E_mpa"]["value"]


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    source, trajectory, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    if not (source / "scene.json").is_file() or not trajectory.is_file():
        raise SystemExit("give a scene folder (with scene.json) and a trajectory.json")
    exe = febio_exe()
    results = []
    for label, factor in VARIANTS:
        folder = work / f"scene_{factor:g}"
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(source, folder)
        young = edit_young(folder / "scene.json", factor)
        r = simulate.run_scene(folder / "scene.json", trajectory, work / "runs", exe, f"material-{factor:g}")
        display = simulate.read_display(r.run_dir / simulate.DISPLAY)["positions"]
        results.append((label, young, r, display))
        print(f"ran {label}: E = {young:g} MPa, run {r.status}, FEBio {r.report['timing']['febio_s']} s", flush=True)
    base = results[0][3]
    frame = int(np.argmax(np.linalg.norm(base - base[0], axis=2).max(axis=1)))
    print(f"\nbaseline moves most at frame {frame} (a display vertex is {np.linalg.norm(base[frame] - base[0], axis=1).max():.2f} "
          "mm from its rest position there)\n")
    print(f"{'variant':20} {'E (MPa)':>9}  {'check c':8} {'sag mm':>8} {'expected mm':>12}  "
          f"{'largest mm':>11} {'mean mm':>9}   (display distance from baseline at frame {frame})")
    for label, young, r, display in results:
        c = r.report["checks"]["c"]
        verdict = {True: "PASS", False: "FAIL", None: "NOT RUN"}[c["passed"]]
        sag = c["numbers"].get("mean_sag_along_gravity_mm")
        expected = c["numbers"].get("expected_sag_mm")
        d = np.linalg.norm(display[frame] - base[frame], axis=1)
        print(f"{label:20} {young:9.4g}  {verdict:8} {sag if sag is None else format(sag, '8.4f'):>8} "
              f"{expected if expected is None else format(expected, '12.4f'):>12}  {d.max():11.4f} {d.mean():9.4f}")


if __name__ == "__main__":
    main()
