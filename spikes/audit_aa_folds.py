"""Count folded and squashed faces of the lips in the last frame of a run (docs/15 section 8, pictures).

    uv run python spikes/audit_aa_folds.py <run folder> [<run folder> ...]

For each run folder it reads the lip faces from playback.json and the display positions of the first and the
last frame: `physics/display.npy` (physics only) and, when the run has a landmark layer, `final/display.npy`.
It counts, against the rest lips: faces whose normal points the other way (dot product < 0), faces turned by
more than 60 degrees (dot < 0.5), edges longer than 2x or shorter than 0.5x their rest length, and the smallest
face area ratio. Only counts and ratios are printed; nothing is written and nothing is judged: the numbers say
that faces are folded or squashed, not whether it looks wrong, and a flipped face is not a proof of
self-intersection. The picture of the run (tools/render_prototype.py --last) is what the page describes.
"""

import json
import sys
from pathlib import Path

import numpy as np

from asrp_core.plausibility import folds  # the one implementation, shared with the run report


def main(folders: list[str]) -> None:
    if not folders:
        raise SystemExit(__doc__)
    for folder in map(Path, folders):
        faces = np.array(json.loads((folder / "playback.json").read_text(encoding="utf-8"))["faces"])
        for version in ("physics", "final"):
            path = folder / version / "display.npy"
            if not path.is_file():
                continue
            display = np.load(path, allow_pickle=False)
            print(f"{folder.name} {version}, last frame vs rest:")
            for key, value in folds(display[0], display[-1], faces).items():
                print(f"  {key}: {value}")


if __name__ == "__main__":
    main(sys.argv[1:])
