"""T-09 acceptance on the real asset (not product code): does our landmark layer give the lab's numbers?

    uv run python tools/landmark_layer_check.py [lab data folder]

The lab data folder holds the lab's own files (oor_bind_pose.json, oor_skin_weights.json); the default
is $ASRP_LAB_DATA, else E:/Codebase/_lab/data. It stays outside the repo (ADR-28): this tool reads it
and writes only distances and counts to data/preview/landmark_layer_check.json.

It imports data/lab_export into a temporary folder (the real entry point), then checks:

1. conversion: with all landmarks at rest, general matrix skinning of the imported rest lips gives the
   rest lips back (largest vertex distance, mm);
2. the reduction: `skinning.deform` against `skinning.deform_matrices` when all 300 landmarks are moved
   at random (about 2 scene units) and when 5 are moved about 10 scene units (largest distance, mm);
3. the lab's formula, `bind_pose + weights @ translations` on the lab's own files, converted to mm, Z up,
   against `skinning.deform` on our imported lips and weights: largest and mean vertex distance (mm);
4. a control that must fail: the same comparison with the lab's weight columns shifted by one landmark.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from asrp_core import scene, skinning  # noqa: E402
from asrp_core.asset import coords, lab  # noqa: E402

DEFAULT_LAB_DATA = "E:/Codebase/_lab/data"
LAB_COMMIT = "506cd69"
LIMIT_MM = 1e-4  # the comparison with the lab's formula must stay under this
SEED = 0


def lab_data_folder(arg=None) -> Path:
    return Path(arg or os.environ.get("ASRP_LAB_DATA") or DEFAULT_LAB_DATA)


def import_lab_asset(out: Path):
    """Run the real importer on the committed export. Returns (skin, rest lips in mm, mm per scene unit)."""
    result = lab.import_asset(REPO / "data" / "lab_export", out, REPO / "data" / "tetmesh" / "lips.json")
    model = scene.load(result.scene_path)
    skin = skinning.load(out / model.landmarks.weights.path)
    lips, _ = coords.read_obj(out / model.soft_tissues[0].mesh.path)
    return skin, lips, model.units.mm_per_scene_unit.value


def run(lab_dir, workdir: Path) -> dict:
    lab_dir = Path(lab_dir)
    skin, lips, mm = import_lab_asset(workdir / "asset")
    k = len(skin.names)
    rng = np.random.default_rng(SEED)

    # 1. conversion: all landmarks at rest
    at_rest = skinning.deform_matrices(lips, skin, skin.rest_world)
    conversion = float(np.linalg.norm(at_rest - lips, axis=1).max())

    # 2. the reduction, on two cases
    t_all = rng.normal(scale=2.0, size=(k, 3))  # scene units
    t_few = np.zeros((k, 3))
    few = rng.choice(k, size=5, replace=False)
    t_few[few] = rng.normal(scale=10.0, size=(5, 3))
    reduction, max_motion = 0.0, 0.0
    for t_scene in (t_all, t_few):
        t_mm = coords.to_mm_zup(t_scene, mm)
        fast = skinning.deform(lips, skin.weights, t_mm)
        # The rest matrices undo each other only to the export's float precision (the conversion number
        # above), so the general form is compared as a change from its own rest result.
        general = lips + (skinning.deform_matrices(lips, skin, skinning.translations_to_world(skin, t_mm)) - at_rest)
        reduction = max(reduction, float(np.linalg.norm(fast - general, axis=1).max()))
        max_motion = max(max_motion, float(np.linalg.norm(t_mm, axis=1).max()))

    # 3 and 4. the lab's formula on the lab's files
    bind = np.asarray(json.loads((lab_dir / "oor_bind_pose.json").read_text(encoding="utf-8")), dtype=np.float64)
    w_lab = np.asarray(json.loads((lab_dir / "oor_skin_weights.json").read_text(encoding="utf-8")), dtype=np.float64)
    if w_lab.shape != (len(lips), k) or bind.shape != (len(lips), 3):
        raise SystemExit(f"lab files do not fit the asset: bind {bind.shape}, weights {w_lab.shape}")
    t_mm = coords.to_mm_zup(t_all, mm)
    ours = skinning.deform(lips, skin.weights, t_mm)

    def lab_result(weights):
        return coords.to_mm_zup(bind + weights @ t_all, mm)

    d = np.linalg.norm(ours - lab_result(w_lab), axis=1)
    control = np.linalg.norm(ours - lab_result(np.roll(w_lab, 1, axis=1)), axis=1)
    return {
        "vertices": int(len(lips)),
        "landmarks": int(k),
        "limit_mm": LIMIT_MM,
        "conversion_rest_max_mm": conversion,
        "deform_vs_deform_matrices_max_mm": reduction,
        "ours_vs_lab_formula_max_mm": float(d.max()),
        "ours_vs_lab_formula_mean_mm": float(d.mean()),
        "control_shifted_columns_max_mm": float(control.max()),
        "max_translation_applied_mm": max_motion,
        "seed": SEED,
        "lab_commit": LAB_COMMIT,
        "command": "uv run python tools/landmark_layer_check.py",
    }


def main() -> None:
    folder = lab_data_folder(sys.argv[1] if len(sys.argv) > 1 else None)
    if not (folder / "oor_skin_weights.json").is_file():
        sys.exit(f"{folder} has no oor_skin_weights.json; pass the lab data folder or set ASRP_LAB_DATA")
    with tempfile.TemporaryDirectory() as tmp:
        numbers = run(folder, Path(tmp))
    for key, value in numbers.items():
        print(f"{key}: {value}")
    ok = (numbers["conversion_rest_max_mm"] < 1e-3 and numbers["deform_vs_deform_matrices_max_mm"] < 1e-9
          and numbers["ours_vs_lab_formula_max_mm"] < LIMIT_MM and numbers["control_shifted_columns_max_mm"] > LIMIT_MM
          and numbers["vertices"] > 0 and numbers["landmarks"] > 0)
    target = REPO / "data" / "preview" / "landmark_layer_check.json"
    target.write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {target.relative_to(REPO).as_posix()}")
    print("landmark layer " + ("MATCHES the lab's formula" if ok else "FAILED: see the numbers above"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
