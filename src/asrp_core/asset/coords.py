"""The one place scene coordinates become the core's coordinates: mm, Z up (docs/03 section 10).

The lab's Maya scene is Y up with the face looking down -Z; the core and Blender are Z up. The
OBJ files from tools/maya_export.py are already scene coordinates (the export applied each mesh's
own transform, ADR-18), so the import only scales and turns the axes, in that order:

    scene (x, y, z) -> mm (x, y, z) * mm_per_scene_unit -> (x, -z, y)

It is a rotation, not a mirror: left and right stay put and the face ends up looking down +Y.
mm_per_scene_unit is a setting (provisionally 0.962, docs/11 Q3), never a constant here.

Every tool that needs this conversion calls `to_mm_zup` (T-02): a second copy that drifts would
put meshes and tet meshes in different places without any error.
"""

import numpy as np

AXES = "(x, y, z) -> (x, -z, y)"  # recorded in scene.json and tet meshes as the axis conversion


def to_mm_zup(points, mm_per_scene_unit: float) -> np.ndarray:
    """Points (n, 3) in scene units -> (n, 3) float64 in mm, Z up. For a direction (a hinge axis),
    pass mm_per_scene_unit = 1."""
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError(f"expected points as (n, 3), got shape {p.shape}")
    if not mm_per_scene_unit > 0:
        raise ValueError(f"mm_per_scene_unit must be positive, got {mm_per_scene_unit}")
    s = p * mm_per_scene_unit
    return np.stack([s[:, 0], -s[:, 2], s[:, 1]], axis=1)


def read_obj(path) -> tuple[np.ndarray, list[list[int]]]:
    """Vertices (n, 3) as written and faces as 0-based vertex lists (triangles or quads), in file
    order. Texture and normal indices are dropped."""
    vertices, faces = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                vertices.append([float(c) for c in line.split()[1:4]])
            elif line.startswith("f "):
                faces.append([int(c.split("/")[0]) - 1 for c in line.split()[1:]])
    return np.array(vertices, dtype=np.float64).reshape(-1, 3), faces


def triangulate(faces) -> np.ndarray:
    """Fan each face into triangles: (m, 3) int."""
    return np.array([(f[0], f[i], f[i + 1]) for f in faces for i in range(1, len(f) - 1)], dtype=np.int64).reshape(-1, 3)
