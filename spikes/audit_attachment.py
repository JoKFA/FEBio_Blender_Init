"""One-off measurement (not product code): how much do the attachment rules we chose change the result?

Two things decide the lip's shape in the prototype and neither has outside evidence (docs/11): the fraction of
the jaw's motion the lip-corner anchor follows (0.5, A-35) and the base stiffness of the spring attachments
(100 x E x h, T-07's provisional rule). This runs one scene (a folder made by `asrp import-asset`) with one
motion five times: as it is, with the anchor's fraction at 0.3 and 0.7, and with every spring's base stiffness
divided and multiplied by 10. For each variant it prints how far the display vertices are from the baseline's
at the frame where the baseline moves most, the tet volume ratios of check (d), and the largest spring slip.
docs/13 E-09 quotes the numbers.

    uv run python spikes/audit_attachment.py <scene folder> <trajectory.json> <an empty work folder>

The work folder gets one copy of the scene and one run folder per variant (git-ignored, e.g. runs/audit).
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate
from asrp_core.doctor import febio_exe

# (label, anchor fraction or None to keep it, factor on every spring's base stiffness)
VARIANTS = (("baseline", None, 1.0), ("anchor fraction 0.3", 0.3, 1.0), ("anchor fraction 0.7", 0.7, 1.0),
            ("springs / 10", None, 0.1), ("springs x 10", None, 10.0))


def edit(scene_json: Path, fraction: float | None, stiffness_factor: float) -> str:
    """Set every derived driver's blend factor and scale every spring attachment's base stiffness; returns a
    short description of what the scene holds afterwards."""
    data = json.loads(scene_json.read_text(encoding="utf-8"))
    fractions, stiffnesses = [], []
    for driver in data["drivers"]:
        if driver.get("blend"):
            if fraction is not None:
                driver["blend"]["factor"]["value"] = fraction
            fractions.append(driver["blend"]["factor"]["value"])
    for attachment in data["attachments"]:
        if attachment["kind"] == "spring":
            attachment["stiffness"]["value"] *= stiffness_factor
            stiffnesses.append(attachment["stiffness"]["value"])
    if not fractions or not stiffnesses:
        raise SystemExit(f"{scene_json} has no derived driver or no spring attachment; nothing to vary")
    scene_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return f"fraction {fractions[0]:g}, base stiffness {stiffnesses[0]:.4g} N/mm"


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    source, trajectory, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    if not (source / "scene.json").is_file() or not trajectory.is_file():
        raise SystemExit("give a scene folder (with scene.json) and a trajectory.json")
    exe = febio_exe()
    results = []
    for n, (label, fraction, factor) in enumerate(VARIANTS):
        folder = work / f"scene_{n}"
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(source, folder)
        holds = edit(folder / "scene.json", fraction, factor)
        r = simulate.run_scene(folder / "scene.json", trajectory, work / "runs", exe, f"attachment-{n}")
        display = simulate.read_display(r.run_dir / simulate.DISPLAY)["positions"] if r.status == "complete" else None
        results.append((label, holds, r, display))
        print(f"ran {label}: {holds}; run {r.status}, plausibility {'passed' if r.passed else 'NOT passed'}, "
              f"FEBio {r.report['timing'].get('febio_s')} s", flush=True)
    base = results[0][3]
    if base is None:
        raise SystemExit("the baseline run did not complete")
    frame = int(np.argmax(np.linalg.norm(base - base[0], axis=2).max(axis=1)))
    moved = np.linalg.norm(base[frame] - base[0], axis=1)
    print(f"\nbaseline moves most at frame {frame}: largest {moved.max():.2f} mm, mean {moved.mean():.2f} mm\n")
    print(f"{'variant':22} {'largest mm':>10} {'mean mm':>8} {'% of largest motion':>19}  {'volume ratio min':>16} {'max':>6}  "
          f"{'largest slip/delta':>18}   (display distance from baseline at frame {frame})")
    for label, _, r, display in results:
        if display is None:
            print(f"{label:22} run {r.status}: {r.report['checks']['a']['message']}")
            continue
        d = np.linalg.norm(display[frame] - base[frame], axis=1)
        numbers = r.report["checks"]["d"]["numbers"]
        slip = max((s["ratio"] for s in r.report.get("spring_slip", {}).values()), default=float("nan"))
        print(f"{label:22} {d.max():10.4f} {d.mean():8.4f} {100 * d.max() / moved.max():18.1f}%  "
              f"{numbers['min_volume_ratio']:16.3f} {numbers['max_volume_ratio']:6.3f}  {slip:18.3g}")


if __name__ == "__main__":
    main()
