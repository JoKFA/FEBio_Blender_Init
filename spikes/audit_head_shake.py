"""One-off measurement (not product code): how much do the lips move against the head when the head is shaken?

ADR-39 sets the head shake's acceptance to "runs and reports the amplitude" on an estimate (0.01 to 0.05 mm) that
had not been run. This runs it with what exists today, as a first number for T-28: the lab's head shake
(docs/03 section 13.8: the skull and the jaw translate along x, 3 back-and-forth cycles of 10 frames from frame
16, amplitude 5 scene units, then 40 frames) written as a sine, on a copy of an imported scene in which the skull
follows a new driver `head` and the lip-corner anchor follows it too (the jaw stays closed, so everything rigid
moves alike).

The solver settings are today's (the generator's numerical damping at its strongest), so fast motion is damped
more than it would be in a tuned run: read the result as an order of magnitude. Each case is run twice, with the
shake and with the head still, and the two are subtracted, so what is left is the shake's effect alone (the
gravity settle is in both).

    uv run python spikes/audit_head_shake.py <scene folder> <an empty work folder>

Prints, for 1 and for 4 substeps per frame: the largest and the mean distance of the free display vertices from
where the head carries them, during the shake and after it. docs/13 E-09 quotes the numbers.
"""

import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

from asrp_core import simulate, trajectory
from asrp_core.doctor import febio_exe

START, CYCLES, PERIOD, AFTER = 16, 3, 10, 40
AMPLITUDE_UNITS = 5.0
SETTLE = 14
HEAD = "head"


def head_x(frame: int, amplitude_mm: float) -> float:
    if START <= frame <= START + CYCLES * PERIOD:
        return amplitude_mm * math.sin(2 * math.pi * (frame - START) / PERIOD)
    return 0.0


def prepare(source: Path, folder: Path, substeps: int) -> tuple[float, float, np.ndarray]:
    """Copy the scene; make the skull, the upper teeth and the anchors follow `head`; set the substeps.
    Returns (shake amplitude in mm, fps, indices of the display vertices no attachment holds)."""
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(source, folder)
    path = folder / "scene.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["drivers"].append({"name": HEAD, "hinge": None})
    for bone in data["bones"]:
        if bone["motion"] == "fixed":
            bone["motion"], bone["driver"] = "prescribed", HEAD
    for anchor in data.get("anchors", []):
        anchor["driver"] = HEAD
    data["solver"]["substeps_per_frame"]["value"] = substeps
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    held = {int(v) for a in data["attachments"] for v, w in a["weights"] if w > 0}
    tissue = data["soft_tissues"][0]["mesh"]["path"]
    count = sum(1 for line in (folder / tissue).read_text(encoding="utf-8").splitlines() if line.startswith("v "))
    free = np.array(sorted(set(range(count)) - held))
    return AMPLITUDE_UNITS * data["units"]["mm_per_scene_unit"]["value"], float(data["solver"]["fps"]["value"]), free


def motion(path: Path, fps: float, amplitude_mm: float, drivers: list[str]) -> list[float]:
    frames = START + CYCLES * PERIOD + AFTER + 1
    xs = [head_x(f, amplitude_mm) for f in range(frames)]
    moves = [[1.0, 0.0, 0.0, x, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0] for x in xs]
    trajectory.write(path, trajectory.Trajectory(
        fps=fps, frames=frames, drivers={d: moves for d in drivers}, source_tag="ours", settle_until_frame=SETTLE,
        source=f"audit (ours): head translation along x, amplitude {amplitude_mm:.3f} mm, {CYCLES} cycles of {PERIOD} "
               f"frames from frame {START}; spikes/audit_head_shake.py"))
    return xs


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    source, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    exe = febio_exe()
    for substeps in (1, 4):
        folder = work / f"scene_{substeps}"
        amplitude, fps, free = prepare(source, folder, substeps)
        jaw_drivers = [d["name"] for d in json.loads((folder / "scene.json").read_text(encoding="utf-8"))["drivers"]
                       if d.get("hinge")]
        shown = {}
        for case, a in (("shake", amplitude), ("still", 0.0)):
            xs = motion(folder / f"{case}.json", fps, a, [HEAD, *jaw_drivers])
            r = simulate.run_scene(folder / "scene.json", folder / f"{case}.json", work / "runs", exe, f"{case}-{substeps}")
            if r.status != "complete":
                raise SystemExit(f"{case} with {substeps} substeps: run {r.status}: {r.report['checks']['a']['message']}")
            shown[case] = (simulate.read_display(r.run_dir / simulate.DISPLAY)["positions"], xs, r)
            print(f"ran {case}, {substeps} substep(s) per frame: FEBio {r.report['timing']['febio_s']} s, "
                  f"plausibility {'passed' if r.passed else 'NOT passed'}", flush=True)
        (shake, xs, _), (still, _, _) = shown["shake"], shown["still"]
        carried = np.zeros_like(shake)
        carried[:, :, 0] = np.array(xs)[:, None]
        relative = np.linalg.norm((shake - carried - still)[:, free], axis=2)  # (frames, free vertices)
        end = START + CYCLES * PERIOD
        peak_accel = amplitude * (2 * math.pi * fps / PERIOD) ** 2
        print(f"  head moves +-{amplitude:.2f} mm; peak acceleration {peak_accel:.0f} mm/s2 in geometric mm")
        print(f"  free vertices against where the head carries them, {substeps} substep(s):")
        print(f"    during the shake (frames {START}-{end}): largest {relative[START:end + 1].max():.4f} mm, "
              f"mean {relative[START:end + 1].mean():.4f} mm")
        print(f"    after it (frames {end + 1}-{len(xs) - 1}): largest {relative[end + 1:].max():.4f} mm, "
              f"at the last frame {relative[-1].max():.2e} mm")


if __name__ == "__main__":
    main()
