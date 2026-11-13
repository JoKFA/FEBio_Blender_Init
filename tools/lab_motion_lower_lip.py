"""How far does the lab's motion move the lip through the landmark layer alone? (docs/12 part 2, E-17; P-07)

    uv run python tools/lab_motion_lower_lip.py <keys_*.json from ziva_trip_probe.dump_keys | combined_checkpoints.pkl>

Prints, for the lower-lip vertices attached to the jaw and the upper-lip vertices attached to the skull, the
displacement the landmark translations give them (weights @ translations), in mm. It reports numbers only.
The .pkl is read with a restricted unpickler: plain containers and numpy arrays, anything else is refused.
"""
import argparse
import io
import json
import pickle
import sys
from pathlib import Path

import numpy as np

LANDMARKS = 300
ALLOWED = {("builtins", n) for n in ("list", "tuple", "dict", "float", "int", "complex", "set", "frozenset")} | {
    (m, n) for m in ("numpy.core.multiarray", "numpy._core.multiarray") for n in ("_reconstruct", "scalar")} | {
    ("numpy", "ndarray"), ("numpy", "dtype"), ("numpy.core.numeric", "_frombuffer"), ("numpy._core.numeric", "_frombuffer")}


class Restricted(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"refused {module}.{name}: only plain containers and numpy arrays are read")
        return super().find_class(module, name)


def offsets_from_pkl(data: bytes):
    """(frames, 300, 3) cumulative landmark offsets in scene units, and the jaw's Euler offsets (frames, 3)."""
    steps = [np.asarray(s, dtype=np.float64).ravel() for s in Restricted(io.BytesIO(data)).load()]
    if not steps or any(len(s) < LANDMARKS * 3 + 3 for s in steps):
        raise ValueError(f"expected a list of vectors of at least {LANDMARKS * 3 + 3} numbers, got "
                         f"{len(steps)} steps of lengths {sorted(set(len(s) for s in steps))[:5]}")
    stack = np.stack([s[:LANDMARKS * 3 + 3] for s in steps])
    return stack[:, :LANDMARKS * 3].reshape(len(steps), LANDMARKS, 3), stack[:, LANDMARKS * 3:]


def offsets_from_keys(keys: dict, influences):
    """The same from a dump_keys file: local translate minus the first frame, turned by the parent's matrix."""
    out = np.zeros((len(keys["frames"]), len(influences), 3))
    rotations = {p: np.asarray(m, dtype=np.float64).reshape(4, 4)[:3, :3] for p, m in keys["parent_world_matrix"].items()}
    by_short = {name.split("|")[-1].split(":")[-1]: name for name in keys["values"]}
    for i, name in enumerate(influences):
        if name not in by_short:
            raise ValueError(f"landmark {name} is not in the keys file")
        local = np.asarray(keys["values"][by_short[name]], dtype=np.float64)[:, :3]
        parent = keys["parent_of"][by_short[name]]
        out[:, i] = (local - local[0]) @ rotations[parent] if parent else local - local[0]  # Maya: row vectors
    jaw = np.asarray(keys["values"][by_short["jaw01"]], dtype=np.float64)[:, 3:] if "jaw01" in by_short else None
    return out, None if jaw is None else jaw - jaw[0]


def vertex_displacement(weights, offsets, vertices):
    """(frames, len(vertices), 3): sum over influences of weight times the landmark's offset."""
    out = np.zeros((offsets.shape[0], len(vertices), 3))
    for k, v in enumerate(vertices):
        for influence, weight in weights[v]:
            out[:, k] += weight * offsets[:, influence]
    return out


def report(offsets, jaw, export: Path, mm_per_unit: float):
    skin = json.loads((export / "skin_skinCluster7.json").read_text(encoding="utf-8"))
    groups = json.loads((export / "lip_attachments.json").read_text(encoding="utf-8"))["groups"]
    rows = []
    for group in groups:
        vertices = [v[0] if isinstance(v, list) else v for v in group["vertices"]]  # stored as [vertex, weight]
        if not vertices:
            continue
        d = np.linalg.norm(vertex_displacement(skin["weights"], offsets, vertices), axis=2) * mm_per_unit
        rows.append({"group": f"{group['attachment']} {group['label']}", "vertices": len(vertices),
                     "last_frame_mean_mm": float(d[-1].mean()), "last_frame_max_mm": float(d[-1].max()),
                     "any_frame_max_mm": float(d.max())})
    travel = np.linalg.norm(offsets, axis=2) * mm_per_unit
    return {"frames": int(offsets.shape[0]), "landmark_travel_last_frame_max_mm": float(travel[-1].max()),
            "landmarks_moving_over_0.01_mm": int((travel.max(axis=0) > 0.01).sum()),
            "jaw_euler_offset_last_frame_deg": None if jaw is None else [float(x) for x in jaw[-1]], "groups": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("motion", type=Path)
    parser.add_argument("--export", type=Path, default=Path("data/lab_export"))
    parser.add_argument("--mm-per-scene-unit", type=float, default=0.962,
                        help="0.962, the value our scenes use (ADR-31)")
    args = parser.parse_args(argv)
    if args.motion.suffix.lower() == ".json":
        skin = json.loads((args.export / "skin_skinCluster7.json").read_text(encoding="utf-8"))
        offsets, jaw = offsets_from_keys(json.loads(args.motion.read_text(encoding="utf-8")), skin["influences"])
    else:
        offsets, jaw = offsets_from_pkl(args.motion.read_bytes())
    result = report(offsets, jaw, args.export, args.mm_per_scene_unit)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    print("For comparison: our physics carries the lower lip about 13 mm further than the lab's AA target "
          "(docs/15 section 8). This tool does not say which reading is right.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
