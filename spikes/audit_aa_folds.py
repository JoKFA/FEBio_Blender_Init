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


def normals_and_areas(points: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    cross = np.cross(b - a, c - a)
    length = np.linalg.norm(cross, axis=1)
    return cross / np.maximum(length, 1e-12)[:, None], 0.5 * length


def edge_lengths(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    edges = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    return np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)


def folds(rest: np.ndarray, shape: np.ndarray, faces: np.ndarray) -> dict:
    n0, a0 = normals_and_areas(rest, faces)
    n1, a1 = normals_and_areas(shape, faces)
    dot = (n0 * n1).sum(axis=1)
    ratio = edge_lengths(shape, faces) / edge_lengths(rest, faces)
    return {"faces": len(faces), "flipped (dot < 0)": int((dot < 0).sum()), "turned > 60 deg (dot < 0.5)": int((dot < 0.5).sum()),
            "edges > 2x": int((ratio > 2).sum()), "edges < 0.5x": int((ratio < 0.5).sum()),
            "edge ratio min / max": (round(float(ratio.min()), 3), round(float(ratio.max()), 3)),
            "smallest face area ratio": round(float((a1 / a0).min()), 3)}


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
