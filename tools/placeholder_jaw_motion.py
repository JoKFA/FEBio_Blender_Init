"""Write the placeholder jaw motion of T-06a as a normal trajectory.json (no lab motion yet, D2).

    uv run python tools/placeholder_jaw_motion.py <scene.json> <out trajectory.json>

Frames 0-14 the jaw stays still (gravity only, as in the lab's pipeline); frames 14-32 it opens to
OPEN_DEG about the jaw driver's hinge (the scene's jaw01 pivot and axis), frames 32-50 it closes
again; 51 frames at the scene's fps (30). The angle follows a half cosine in each half, so the jaw
starts and stops without a jump in speed. 12 degrees is a value we chose (docs/09 T-06a card).

Which way is "open" is read off the geometry, not assumed: the sign is the one that moves the
centre of the bones that follow the driver down (-Z). The motion goes through
asrp_core.trajectory.hinge_transforms (ADR-21), so the solver sees per-frame rigid transforms
like any other trajectory.
"""

import math
import sys
from pathlib import Path

import numpy as np

from asrp_core import scene, trajectory
from asrp_core.asset import coords

OPEN_DEG = 12.0
STILL_UNTIL = 14  # last frame of the gravity-only settle (frames 0..14)
OPEN_AT = 32  # fully open
FRAMES = 51  # 0..50: closed again at the last frame


def angles_deg(open_deg: float = OPEN_DEG) -> list[float]:
    """The placeholder's hinge angle (degrees, magnitude) per frame."""
    out = []
    for f in range(FRAMES):
        if f <= STILL_UNTIL:
            s = 0.0
        elif f <= OPEN_AT:
            s = (f - STILL_UNTIL) / (OPEN_AT - STILL_UNTIL)
        else:
            s = (FRAMES - 1 - f) / (FRAMES - 1 - OPEN_AT)
        out.append(open_deg * (1 - math.cos(math.pi * s)) / 2)
    return out


def opening_sign(s: scene.Scene, base: Path, driver: str) -> float:
    """+1 or -1: the turn about the hinge that moves the followers' centre down."""
    hinge = next(d.hinge for d in s.drivers if d.name == driver)
    points = np.concatenate([coords.read_obj(base / b.mesh.path)[0] for b in s.bones if b.driver == driver])
    centre = points.mean(axis=0)
    [turned] = trajectory.hinge_transforms(hinge.pivot_mm, hinge.axis, [math.radians(1.0)])
    return 1.0 if trajectory.apply(turned, centre)[2] < centre[2] else -1.0


def build(scene_path: Path, driver: str = "jaw01", open_deg: float = OPEN_DEG) -> trajectory.Trajectory:
    s = scene.load(scene_path)
    hinge = next((d.hinge for d in s.drivers if d.name == driver), None)
    if hinge is None:
        raise SystemExit(f"{scene_path} has no driver {driver!r} with a hinge")
    sign = opening_sign(s, scene_path.parent, driver)
    angles = [sign * math.radians(a) for a in angles_deg(open_deg)]
    return trajectory.Trajectory(
        fps=s.solver.fps.value, frames=FRAMES,
        drivers={driver: trajectory.hinge_transforms(hinge.pivot_mm, hinge.axis, angles)},
        source_tag="ours", settle_until_frame=STILL_UNTIL,
        source=(f"placeholder (T-06a, ours): {driver} still for frames 0-{STILL_UNTIL}, opens to {open_deg:g} degrees "
                f"at frame {OPEN_AT}, closed again at frame {FRAMES - 1}; tools/placeholder_jaw_motion.py"),
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    motion = build(Path(sys.argv[1]))
    trajectory.write(Path(sys.argv[2]), motion)
    peak = max(abs(a) for a in angles_deg())
    print(f"wrote {sys.argv[2]}: {motion.frames} frames at {motion.fps} fps, jaw01 opens to {peak:g} degrees at frame {OPEN_AT}")


if __name__ == "__main__":
    main()
