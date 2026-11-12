"""One-off measurement (not product code): is the exported landmark skin data usable as it is?

The landmark layer (T-09) and prototype two's fit (T-27) rest on data/lab_export/skin_skinCluster7.json and
joints.json. This checks, in the export's own scene units and Maya matrix order (row vectors, translation in
entries 12-14), before any conversion is written:

1. every landmark's bind matrix undoes its rest world matrix (bind_pre x world = identity);
2. every lip vertex's weights sum to 1;
3. with all landmarks at rest, skinning the rest lip mesh gives back the rest lip mesh;
4. with landmarks only translated, a vertex moves by the weighted sum of the translations (the layer is linear
   in the landmark translations, which is what makes the fit a least-squares problem, ADR-39).

    uv run python spikes/audit_skin_identity.py [export folder, default data/lab_export]

docs/13 E-09 quotes the numbers. Prints FAILED and exits 1 if any of the four is off by more than the limits
below; T-09's own acceptance (0.001 mm after conversion to mm, Z up) is stricter in what it covers.
"""

import json
import sys
from pathlib import Path

import numpy as np

from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]
MM_PER_SCENE_UNIT = 0.962
LIMIT_UNITS = 1e-6  # scene units; 1e-6 units is about 1e-6 mm


def matrix(m) -> np.ndarray:
    return np.array(m, dtype=float).reshape(4, 4)


def skin(vertices: np.ndarray, weights, transforms: np.ndarray) -> np.ndarray:
    """Linear blend skinning in Maya's convention: v' = sum_i w_i (v @ M_i), v as a row (x, y, z, 1)."""
    homogeneous = np.concatenate([vertices, np.ones((len(vertices), 1))], axis=1)
    out = np.zeros((len(vertices), 4))
    for v, pairs in enumerate(weights):
        for i, w in pairs:
            out[v] += w * (homogeneous[v] @ transforms[i])
    return out[:, :3]


def main() -> None:
    export = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "data" / "lab_export"
    data = json.loads((export / "skin_skinCluster7.json").read_text(encoding="utf-8"))
    joints = json.loads((export / "joints.json").read_text(encoding="utf-8"))
    names, weights = data["influences"], data["weights"]
    rest, _ = coords.read_obj(export / f"mesh_{data['mesh'].removesuffix('Shape')}.obj")
    rest = np.asarray(rest, dtype=float)
    print(f"{data['cluster']} on {data['mesh']}: {len(names)} landmarks, {len(weights)} vertices (mesh has {len(rest)})")

    world = np.stack([matrix(joints[n]["world_matrix"]) for n in names])
    bind = np.stack([matrix(data["bind_pre_matrix"][n]) for n in names])
    at_rest = bind @ world  # row vectors: v @ bind_pre @ world
    identity_error = float(np.abs(at_rest - np.eye(4)).max())
    print(f"1. bind_pre x world against the identity: largest entry difference {identity_error:.3e}")

    sums = np.array([sum(w for _, w in pairs) for pairs in weights])
    counts = np.array([len(pairs) for pairs in weights])
    print(f"2. weight sums: min {sums.min():.9f}, max {sums.max():.9f}; landmarks per vertex: mean {counts.mean():.1f}, "
          f"max {counts.max()}, vertices with none: {int((counts == 0).sum())}")

    skinned = skin(rest, weights, at_rest)
    rest_error = float(np.linalg.norm(skinned - rest, axis=1).max())
    print(f"3. skinning the rest mesh with all landmarks at rest: largest vertex distance {rest_error:.3e} scene units "
          f"({rest_error * MM_PER_SCENE_UNIT:.3e} mm)")

    rng = np.random.default_rng(0)
    shifts = rng.normal(scale=2.0, size=(len(names), 3))  # a couple of scene units each, every landmark moved
    moved_world = world.copy()
    moved_world[:, 3, :3] += shifts
    moved = skin(rest, weights, bind @ moved_world)
    expected = rest.copy()
    for v, pairs in enumerate(weights):
        for i, w in pairs:
            expected[v] += w * shifts[i]
    linear_error = float(np.linalg.norm(moved - expected, axis=1).max())
    print(f"4. all landmarks translated at random (about 2 scene units): skinned position against rest + sum of "
          f"weight x translation: largest distance {linear_error:.3e} scene units")

    ok = (identity_error < LIMIT_UNITS and abs(sums.min() - 1) < 1e-6 and abs(sums.max() - 1) < 1e-6
          and rest_error < LIMIT_UNITS and linear_error < LIMIT_UNITS and len(weights) == len(rest))
    print("skin data " + ("USABLE: all four hold" if ok else "FAILED: see the numbers above"))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
