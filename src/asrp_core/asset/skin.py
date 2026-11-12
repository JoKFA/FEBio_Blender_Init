"""The landmark skin file, converted for the core (T-09; docs/03 section 4).

The lab's export (data/lab_export/skin_skinCluster7.json plus joints.json) holds Maya's matrices: row
vectors (v' = v @ M, translation in entries 12-14), scene units, Y up. The core works with column
vectors written row by row (translation at 3, 7, 11), mm, Z up. `convert` writes the skin as
`asrp-skin/1` so that nothing after the import has to know Maya's conventions:

    {"format": "asrp-skin/1", "units": "mm", "axes": coords.AXES, "convention": "column vectors, row by row",
     "mesh": <the export's mesh name>, "names": [K landmark names, in the export's influence order],
     "rest_world": [K x 16], "bind_pre": [K x 16], "geom": [16],
     "weights": [[[index, weight], ...] per vertex],        # the export's sparse lists, unchanged
     "source": {"file": "skin_skinCluster7.json", "sha256": <of the raw export file>}}

A Maya matrix M becomes C @ M.T @ inv(C), where C is the 4x4 of `coords.to_mm_zup`. C is built by
calling that function on the origin and the unit vectors, so the axis rule exists in one place only.
"""

import numpy as np

from asrp_core.asset import coords

FORMAT = "asrp-skin/1"
CONVENTION = "column vectors, row by row"


class SkinConvertError(ValueError):
    """The export cannot be converted; the message says what is wrong and what to do."""


def conversion_matrix(mm_per_scene_unit: float) -> np.ndarray:
    """C (4, 4): homogeneous column-vector form of `coords.to_mm_zup` (scale, then turn the axes)."""
    origin = coords.to_mm_zup([[0.0, 0.0, 0.0]], mm_per_scene_unit)[0]
    axes = coords.to_mm_zup(np.eye(3), mm_per_scene_unit)  # row i: where scene axis i goes
    c = np.eye(4)
    c[:3, :3] = (axes - origin).T
    c[:3, 3] = origin
    return c


def maya_to_core(matrix, mm_per_scene_unit: float) -> np.ndarray:
    """One Maya matrix (16 numbers, row vectors, scene units, Y up) -> (4, 4) column vectors, mm, Z up."""
    m = np.asarray(matrix, dtype=np.float64)
    if m.shape != (16,) and m.shape != (4, 4):
        raise SkinConvertError(f"a matrix must hold 16 numbers, got shape {m.shape}; re-export the scene")
    c = conversion_matrix(mm_per_scene_unit)
    return c @ m.reshape(4, 4).T @ np.linalg.inv(c)


def convert(export_skin: dict, joints: dict, mm_per_scene_unit: float) -> dict:
    """The lab's skin export + joints.json -> an `asrp-skin/1` dict. The caller adds `source`'s sha256
    (it needs the raw file); `source.file` is left to the caller too."""
    names = list(export_skin["influences"])
    weights = export_skin["weights"]
    bind = export_skin["bind_pre_matrix"]
    for n in names:
        if n not in joints:
            raise SkinConvertError(f"joints.json has no landmark {n!r} named in the skin export; re-export both")
        if n not in bind:
            raise SkinConvertError(f"the skin export has no bind matrix for landmark {n!r}; re-export it")
    for v, pairs in enumerate(weights):
        for i, _weight in pairs:
            if not 0 <= i < len(names):
                raise SkinConvertError(f"vertex {v}: landmark index {i} is outside the {len(names)} landmarks")

    def flat(m: np.ndarray) -> list[float]:
        return [float(x) for x in m.reshape(16)]

    return {
        "format": FORMAT,
        "units": "mm",
        "axes": coords.AXES,
        "convention": CONVENTION,
        "mesh": export_skin["mesh"],
        "names": names,
        "rest_world": [flat(maya_to_core(joints[n]["world_matrix"], mm_per_scene_unit)) for n in names],
        "bind_pre": [flat(maya_to_core(bind[n], mm_per_scene_unit)) for n in names],
        "geom": flat(maya_to_core(export_skin["geom_matrix"], mm_per_scene_unit)),
        "weights": [[[int(i), float(w)] for i, w in pairs] for pairs in weights],
    }
