"""Check a Maya export against the .mb it came from, and check each mesh can enclose a volume.

    uv run python tools/check_lab_export.py data/lab_export "assets/<scene>.mb"
    uv run python tools/check_lab_export.py --self-test data/lab_export "assets/<scene>.mb"

Maya wrote the OBJ files; this reads the vertex blobs straight out of the .mb with no Maya
involved. Agreement vertex by vertex shows the vertices, their order and our .mb reader are right.
What it cannot show on its own: the world matrix comes from Maya's own report, so the two routes
share it. The independent guard on that is the jaw size, measured from the OBJ against the paper.
Landmark weights and joints are NOT compared here: they only have Maya's self-check, until T-09's
exact check against the Ziva reference.

--self-test breaks the data in memory in each way this check claims to catch, and exits non-zero
unless every one of them is caught.

Stdlib only. Migration tool, not product code (docs ADR-18). Exits non-zero on a mismatch.
"""

import json
import math
import mmap
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mb_inventory  # noqa: E402

TOLERANCE = 0.001  # scene units, T-02 acceptance
JAW_SCENE_Z = 155.92
HEALTHY = {  # name -> (open edges, bad edges, pieces), as measured on 2026-10-30 (docs/03 section 12)
    "middleres_OrbicularisOris": (0, 0, 1),
    "middleres_Jaw": (0, 0, 1),
    "middleres_skull": (0, 0, 1),
    "middleres_TeethUp": (0, 0, 16),
    "middleres_TeethDown": (0, 0, 16),
}


def parse_obj(path):
    """Vertices as (x, y, z) tuples and faces as 0-based index tuples, in file order."""
    vertices, faces = [], []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                vertices.append(tuple(float(c) for c in line.split()[1:4]))
            elif line.startswith("f "):
                faces.append(tuple(int(c.split("/")[0]) - 1 for c in line.split()[1:]))
    return vertices, faces


def apply_matrix(points, m):
    """Maya convention: row vector times matrix, 16 numbers row by row."""
    return [(x * m[0] + y * m[4] + z * m[8] + m[12],
             x * m[1] + y * m[5] + z * m[9] + m[13],
             x * m[2] + y * m[6] + z * m[10] + m[14]) for x, y, z in points]


def worst_distance(a, b):
    """Largest distance between matching points. Lists of different lengths never match."""
    if len(a) != len(b) or not a:
        return math.inf
    return max(math.dist(p, q) for p, q in zip(a, b))


def mesh_health(vertex_count, faces):
    """Can this surface enclose a volume? Tetrahedral meshing needs it to (docs T-04)."""
    edges = {}
    parent = list(range(vertex_count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    used = set()
    for face in faces:
        used.update(face)
        for a, b in zip(face, face[1:] + face[:1]):
            key = (min(a, b), max(a, b))
            edges[key] = edges.get(key, 0) + 1
            parent[find(a)] = find(b)
    return {
        "vertices": vertex_count,
        "faces": len(faces),
        "unused_vertices": vertex_count - len(used),
        "boundary_edges": sum(1 for n in edges.values() if n == 1),
        "non_manifold_edges": sum(1 for n in edges.values() if n > 2),
        "components": len({find(i) for i in used}),
    }


def health_problem(name, health):
    """A message if this mesh is not in the state we measured, else None."""
    got = (health["boundary_edges"], health["non_manifold_edges"], health["components"])
    if got != HEALTHY[name] or health["unused_vertices"]:
        return f"{name}: open/bad/pieces {got}, expected {HEALTHY[name]}"
    return None


def read_mb_vertices(path, shapes):
    """Rest vertices of the named mesh shapes, straight from the .mb (object coordinates)."""
    found = {}
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        entries = []
        mb_inventory.walk(mm, 20, 16 + struct.unpack(">Q", mm[8:16])[0], 20, 1, entries)
        for i, (kind, depth, _, _, _) in enumerate(entries[:-1]):
            next_entry = entries[i + 1]
            if kind != "GROUP" or next_entry[3] != b"CREA":
                continue
            name = bytes(mm[next_entry[2] + 17 : next_entry[2] + 16 + next_entry[4]]).split(b"\0")[0].decode()
            if name not in shapes:
                continue
            j = i + 2
            while j < len(entries) and entries[j][1] > depth:
                if entries[j][3] == b"MESH":
                    pos, size = entries[j][2], entries[j][4]
                    payload = bytes(mm[pos + 16 : pos + 16 + size])
                    body = payload[len(mb_inventory.cstr(payload).encode()) + 2 :]
                    count = struct.unpack(">I", body[:4])[0]
                    xyz = struct.unpack(f">{count}f", body[4 : 4 + 4 * count])
                    found[name] = list(zip(xyz[0::3], xyz[1::3], xyz[2::3]))
                j += 1
    return found


def corrupt(kind, name, vertices, faces, world_matrix):
    """One way of breaking a mesh on purpose, for --self-test."""
    if kind == "swap two lip vertices" and name == "middleres_OrbicularisOris":
        vertices = list(vertices)
        vertices[100], vertices[5000] = vertices[5000], vertices[100]
    if kind == "apply the transform twice" and name == "middleres_Jaw":
        vertices = apply_matrix(vertices, world_matrix)
    if kind == "delete half the lip faces" and name == "middleres_OrbicularisOris":
        faces = faces[: len(faces) // 2]
    return vertices, faces


def run_check(export, report, from_mb, breakage=None):
    """Print the table; return True if everything agrees."""
    meshes = report["meshes"]
    ok = True
    jaw_z = None
    print(f"{'mesh':28s} {'verts':>6s} {'worst diff':>11s} {'open edges':>10s} {'bad edges':>9s} {'pieces':>6s}")
    for name, info in meshes.items():
        vertices, faces = parse_obj(export / f"mesh_{name}.obj")
        vertices, faces = corrupt(breakage, name, vertices, faces, info["world_matrix"])
        expected = apply_matrix(from_mb.get(name + "ShapeOrig", []), info["world_matrix"])
        diff = worst_distance(vertices, expected)
        h = mesh_health(len(vertices), faces)
        print(f"{name:28s} {len(vertices):6d} {diff:11.7f} {h['boundary_edges']:10d} "
              f"{h['non_manifold_edges']:9d} {h['components']:6d}")
        ok &= diff <= TOLERANCE and health_problem(name, h) is None
        if name == "middleres_Jaw":
            jaw_z = max(v[2] for v in vertices) - min(v[2] for v in vertices)
    jaw_ok = abs(jaw_z - JAW_SCENE_Z) < 0.01
    print(f"\njaw z size {jaw_z:.2f} measured from the OBJ (expected {JAW_SCENE_Z})")
    print("LAB EXPORT CHECK " + ("PASSED" if ok and jaw_ok else "FAILED"))
    return ok and jaw_ok


def main(export_dir, scene, self_test=False):
    export = Path(export_dir)
    report = json.loads((export / "mesh_report.json").read_text())
    from_mb = read_mb_vertices(scene, {name + "ShapeOrig" for name in report["meshes"]})
    print(f"export: {report['scene']}\ncheck against: {Path(scene).name}\n")
    if not self_test:
        if not run_check(export, report, from_mb):
            sys.exit(1)
        return
    missed = []
    for kind in ("swap two lip vertices", "apply the transform twice", "delete half the lip faces"):
        print(f"\n--- on purpose: {kind}")
        if run_check(export, report, from_mb, kind):
            missed.append(kind)
    if missed:
        sys.exit(f"SELF TEST FAILED: not caught: {missed}")
    print("\nSELF TEST PASSED: all 3 breakages caught")


if __name__ == "__main__":
    arguments = [a for a in sys.argv[1:] if a != "--self-test"]
    if len(arguments) != 2:
        sys.exit(__doc__)
    main(arguments[0], arguments[1], "--self-test" in sys.argv)
