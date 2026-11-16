"""The lip shape for one training step, without Maya (T-31; docs/04 section 12.4).

The lab's training environment, every step, (1) turns the jaw joint, (2) moves the 300 landmarks to
absolute world positions, (3) reads the lip mesh's world vertices, without advancing time. `final_shape`
is those three things as one stateless function: numpy only, no FEBio, no Blender, no files written,
no global state, the same inputs always give the same output.

The convention is the lab's, on the way in and on the way out: scene units, Y up, world coordinates.
The conversion to mm, Z up happens inside, once, through asrp_core.asset.coords.

    from asrp_core import final_shape

    model = final_shape.rest_model("scene/scene.json")           # once; no FEBio run needed
    jaw = np.eye(3)
    for step in range(n_steps):
        jaw = relative_rotation(step) @ jaw      # the caller composes the per-step rotations; a turn about
                                                 # WORLD axes multiplies on the left (column vectors)
        positions = landmark_positions_after_step(step)           # (300, 3), absolute, oor_01..oor_300
        lips = final_shape.final_shape(model, jaw, positions)     # (10240, 3), the mesh's vertex order
        objective = ...

Two bases. `rest_model` takes the rest (bind) lips from the scene's mesh (base "rest"). This is the
entry for the lab's existing training: the 145 training results the lab saved (`deltaB_temp.pkl`,
`s_next`) all sit on the rest shape, with no gravity settle, and this function reproduces them to
0.000007 mm (measured 2026-11-13, docs/13 E-13). `load` takes the shape after the gravity-only settle
from a completed run (base "settled"); it is for new experiments that ask for it, NOT for the lab's
existing training: with it the AA result crosses the lab's lip convergence threshold.

Measured on the Ziva machine (Q20, docs/13 E-11): Ziva does not re-solve within the same frame when
the jaw turns. So the base does not depend on the jaw rotation; the jaw input is validated and then
has no effect on the result. `jaw_changes_base` accepts only "no"; there is no re-solve mode.
"""

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from asrp_core import scene as scene_module
from asrp_core import skinning
from asrp_core.asset import coords

ROTATION_TOLERANCE = 1e-6
SETTLED_FORMAT = "asrp-settled/1"
REPORT = "run_report.json"  # simulate.REPORT; not imported so this module stays light
JAW_CHANGES_BASE = ("no", "resolve")


class FinalShapeError(ValueError):
    """The inputs or the run folder cannot be used; the message says what is wrong and what to do."""


class SettledBaseWarning(UserWarning):
    """`load` was used: its base is the settled shape, which is NOT the base of the lab's existing training."""


@dataclass(frozen=True)
class LipModel:
    """Everything `final_shape` needs, loaded once. The arrays are read-only: a training loop that edits one in
    place gets an error instead of a silently different base on every later step."""

    names: tuple[str, ...]  # landmark names, in the scene's order (oor_01 .. oor_300)
    weights: np.ndarray  # (V, K)
    landmark_rest_scene: np.ndarray  # (K, 3) rest positions, the lab's convention (scene units, Y up)
    base_mm: np.ndarray  # (V, 3) the base shape, mm, Z up
    base: str  # "settled" or "rest": what base_mm is
    mm_per_scene_unit: float


# --- loading ---------------------------------------------------------------------------------------


def _read_json(path: Path, what: str, hint: str) -> dict:
    if not path.is_file():
        raise FinalShapeError(f"{what} {path} does not exist; {hint}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise FinalShapeError(f"{what} {path} is not valid JSON (line {e.lineno}: {e.msg}); {hint}") from None
    if not isinstance(data, dict):
        raise FinalShapeError(f"{what} {path} is not a JSON object; {hint}")
    return data


def _scene_parts(scene_path: Path) -> tuple[scene_module.Scene, skinning.Skin, np.ndarray]:
    """The scene, its landmark skin, and the landmarks' rest positions in scene units."""
    try:
        scene = scene_module.load(scene_path)
    except ValueError as e:
        raise FinalShapeError(f"{scene_path} cannot be read as a scene: {e}") from None
    if scene.landmarks is None:
        raise FinalShapeError(
            f"{scene_path} has no landmarks, so there is nothing to move; import the lab asset "
            "(asrp import-asset), which carries the 300 landmarks and their skin weights"
        )
    try:
        skin = skinning.load(scene_path.parent / scene.landmarks.weights.path)
    except skinning.SkinError as e:
        raise FinalShapeError(str(e)) from None
    names = list(scene.landmarks.names)
    if skin.names != names:
        raise FinalShapeError(
            f"the skin file lists {len(skin.names)} landmarks and the scene {len(names)}, and their names or "
            "order differ; re-import the asset so scene.json and the skin file come from the same export"
        )
    rest_mm = np.asarray(scene.landmarks.rest_positions_mm, dtype=np.float64)
    rest_scene = coords.from_mm_zup(rest_mm, scene.units.mm_per_scene_unit.value)
    return scene, skin, rest_scene


def load(run_dir, *, allow_failed_checks: bool = False, allow_unsettled: bool = False) -> LipModel:
    """Load the model from a COMPLETED run folder: its scene.json (landmarks, units), the skin file the
    scene references, and the shape after the gravity-only settle (physics/settled_frame<n>.json).
    The model's base is "settled". A run whose plausibility checks did not all pass is refused unless
    allow_failed_checks=True: its settled shape may be wrong, and nothing downstream would show it.

    NOT for the lab's existing training: the results the lab's training saved sit on the rest shape
    (`rest_model`). This entry is for new experiments that ask for a settled base, and it says so with a
    SettledBaseWarning. A run report without a `tissue_settled` field (an older run) is refused like one
    that says the tissue was still moving: whether the tissue had stopped is then not known; allow_unsettled=True
    accepts both."""
    warnings.warn(
        "final_shape.load: the base is the shape after the gravity-only settle. The lab's saved training results "
        "sit on the REST shape; for the lab's existing training use final_shape.rest_model(scene.json) "
        "(docs/13 E-13)", SettledBaseWarning, stacklevel=2)
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FinalShapeError(f"{run_dir} is not a folder; give the folder of a run made by asrp run")
    report = _read_json(run_dir / REPORT, "the run report", "this is not a finished run folder; run asrp run again")
    status = report.get("status")
    if status != "complete":
        raise FinalShapeError(
            f"the run in {run_dir} has status {status!r}, not 'complete', so it has no result to take the base "
            "shape from; use a run that finished, or run again"
        )
    if report.get("passed") is not True and not allow_failed_checks:
        failed = [key for key, c in (report.get("checks") or {}).items() if isinstance(c, dict) and c.get("passed") is False]
        raise FinalShapeError(
            f"the run in {run_dir} completed but its plausibility checks did not all pass (failed: "
            f"{', '.join(failed) or 'see run_report.json'}), so its settled shape is not a base to train on. Fix the "
            "run, or pass allow_failed_checks=True if you have looked at the report and accept it"
        )
    settled = report.get("settled_shape")
    if not isinstance(settled, dict) or not settled.get("available"):
        reason = settled.get("reason") if isinstance(settled, dict) else None
        raise FinalShapeError(
            f"the run in {run_dir} has no settled shape: {reason or 'run_report.json does not say why'}. "
            "Make the run with a trajectory whose settle_until_frame ends a stretch where nothing moves"
        )
    if settled.get("tissue_settled") is False and not allow_unsettled:
        raise FinalShapeError(
            f"the run in {run_dir} has a settled shape, but the tissue was still moving at that frame: "
            f"{settled.get('tissue_step_max_mm')!r} mm in the last frame of the settle, above the "
            f"{settled.get('tissue_settled_limit_mm')!r} mm limit. A base that is still moving gives a different lip "
            "shape depending on when it is read. Give the motion a longer settle, or pass allow_unsettled=True if you "
            "accept it"
        )
    if settled.get("tissue_settled") is not True and not allow_unsettled:  # absent: an older report, not known
        raise FinalShapeError(
            f"the run in {run_dir} does not say whether the tissue had stopped moving at the settled frame "
            "(run_report.json has no settled_shape.tissue_settled, so the run is from an older version). Run again "
            "with this version, or pass allow_unsettled=True if you accept a base that may still be moving"
        )
    frame = settled.get("frame")
    scene, skin, rest_scene = _scene_parts(run_dir / "scene.json")
    data = _read_json(run_dir / "physics" / f"settled_frame{frame}.json", "the settled shape",
                      "the run folder is damaged; run again")
    if data.get("format") != SETTLED_FORMAT:
        raise FinalShapeError(
            f"the settled shape in {run_dir} has format {data.get('format')!r}; this asrp reads {SETTLED_FORMAT!r}. "
            "Run again with this version"
        )
    try:
        base_mm = np.asarray(data["display"], dtype=np.float64)
    except (KeyError, TypeError, ValueError):
        raise FinalShapeError(f"the settled shape in {run_dir} has no usable 'display' array; run again") from None
    return _model(scene, skin, rest_scene, base_mm, "settled", where=f"the settled shape in {run_dir}")


def rest_model(scene_json_path) -> LipModel:
    """The model for the lab's existing training: the rest (bind) lips as the base, read from the scene's
    own lip mesh (the surface mesh the scene lists, mm, Z up). No FEBio run is needed. With it the function
    is the lab's formula (bind pose + weights @ translations) and reproduces the 145 lip results the lab's
    training program saved (worst 0.000007 mm, tests/test_lab_facts.py). The model's base is "rest".

    Which soft tissue is the lips is decided by identity, not by position or vertex count: the skin file names
    the Maya mesh its weights were made for (`mesh`), and the tissue taken is the one whose source object is that
    mesh (`mesh_<name>.obj`). A skin file that does not name its mesh (an older import) is matched by topology:
    exactly one tissue whose mesh has the weights' vertex count and whose faces stay inside it; with two or none
    the scene is refused rather than guessed."""
    scene_path = Path(scene_json_path)
    scene, skin, rest_scene = _scene_parts(scene_path)
    if not scene.soft_tissues:
        raise FinalShapeError(f"{scene_path} has no soft tissue, so there is no lip mesh to start from")
    v = skin.weights.shape[0]
    meshes = {}
    for tissue in scene.soft_tissues:
        mesh_path = scene_path.parent / tissue.mesh.path
        if not mesh_path.is_file():
            raise FinalShapeError(f"the mesh {mesh_path} of soft tissue {tissue.name!r} does not exist; re-import the asset")
        meshes[tissue.name] = (mesh_path, *coords.read_obj(mesh_path))  # the surface mesh is already mm, Z up
    if skin.mesh:
        wanted = f"mesh_{skin.mesh}.obj"
        found = [t for t in scene.soft_tissues if Path(t.source_obj.file).name == wanted]
        if len(found) != 1:
            raise FinalShapeError(
                f"the skin weights are for the mesh {skin.mesh!r}, and {len(found)} soft tissues of {scene_path} come "
                f"from {wanted} (the tissues come from "
                f"{', '.join(sorted({Path(t.source_obj.file).name for t in scene.soft_tissues}))}); this scene's "
                "lips cannot be told from another mesh, re-import the asset")
        tissue = found[0]
    else:
        found = [t for t in scene.soft_tissues if len(meshes[t.name][1]) == v
                 and all(0 <= i < v for f in meshes[t.name][2] for i in f)]
        if len(found) != 1:
            raise FinalShapeError(
                f"the skin file does not name its mesh, and {len(found)} soft tissues of {scene_path} have the "
                f"weights' {v} vertices with faces inside them; re-import the asset so the skin file says which "
                "mesh it is for")
        tissue = found[0]
    mesh_path, base_mm, _faces = meshes[tissue.name]
    return _model(scene, skin, rest_scene, base_mm, "rest", where=f"the lip mesh {mesh_path}")


def _model(scene, skin, rest_scene, base_mm, base, where) -> LipModel:
    v, k = skin.weights.shape
    if base_mm.shape != (v, 3):
        raise FinalShapeError(
            f"{where} has shape {base_mm.shape} but the skin weights are for {v} vertices, so (V, 3) = ({v}, 3) "
            "was expected; the files come from different imports, re-import the asset"
        )
    if not np.isfinite(base_mm).all():
        raise FinalShapeError(f"{where} holds a value that is not a finite number; run again")
    weights, rest_scene, base_mm = (np.array(a, dtype=np.float64) for a in (skin.weights, rest_scene, base_mm))
    for a in (weights, rest_scene, base_mm):
        a.setflags(write=False)
    return LipModel(tuple(scene.landmarks.names), weights, rest_scene, base_mm, base,
                    float(scene.units.mm_per_scene_unit.value))


# --- the function ------------------------------------------------------------------------------------


def _check_rotation(jaw_rotation) -> bool:
    """Refuse anything that is not a rotation; True when it is a real turn (not the identity)."""
    if jaw_rotation is None:
        return False
    try:
        r = np.asarray(jaw_rotation, dtype=np.float64)
    except (TypeError, ValueError):
        raise FinalShapeError("jaw_rotation must be a 3x3 rotation matrix of numbers (or None for no rotation)") from None
    if r.shape != (3, 3):
        raise FinalShapeError(f"jaw_rotation must be a 3x3 rotation matrix, got shape {r.shape}")
    if not np.isfinite(r).all():
        raise FinalShapeError("jaw_rotation holds a value that is not a finite number")
    if np.abs(r @ r.T - np.eye(3)).max() > ROTATION_TOLERANCE:
        raise FinalShapeError(
            f"jaw_rotation is not a rotation: its rows are not orthonormal (tolerance {ROTATION_TOLERANCE}); "
            "pass a 3x3 rotation matrix, composed by multiplying the per-step rotations"
        )
    det = float(np.linalg.det(r))
    if abs(det - 1.0) > ROTATION_TOLERANCE:
        raise FinalShapeError(
            f"jaw_rotation is not a rotation: its determinant is {det!r}, not +1 (a mirror is not allowed)"
        )
    return bool(np.abs(r - np.eye(3)).max() > ROTATION_TOLERANCE)


def final_shape(model: LipModel, jaw_rotation, landmark_positions, *, jaw_changes_base: str = "no") -> np.ndarray:
    """The lip vertices for one step. Inputs and output are in the lab's convention.

    model: from `load` or `rest_model`.
    jaw_rotation: 3x3 rotation matrix (world axes), the jaw's rotation relative to rest; None is identity.
        It is validated and does not change the result (see jaw_changes_base).
    landmark_positions: (K, 3) ABSOLUTE world positions, scene units, Y up, in the model's order
        (oor_01 .. oor_300).
    jaw_changes_base: only "no": the base shape does not depend on the jaw rotation. Measured on the
        Ziva machine (Q20, docs/13 E-11): turning the jaw within a frame does not make Ziva re-solve.
        "resolve" raises: there is no such mode.

    Returns (V, 3) float64: the world position (scene units, Y up) of every lip vertex, in the mesh's
    vertex order. Stateless and deterministic; the inputs are not modified and nothing is written."""
    if jaw_changes_base == "resolve":
        raise FinalShapeError(
            "jaw_changes_base='resolve' does not exist: Q20 was measured on the Ziva machine (docs/13 E-11), "
            "Ziva does not re-solve when the jaw turns within a frame, so the base shape does not depend on the "
            "jaw. Use jaw_changes_base='no' (the default)"
        )
    if jaw_changes_base not in JAW_CHANGES_BASE:
        raise FinalShapeError(f"jaw_changes_base must be one of {JAW_CHANGES_BASE}, got {jaw_changes_base!r}")
    _check_rotation(jaw_rotation)  # validated; it does not change the result (Q20, measured)
    k = len(model.names)
    try:
        positions = np.asarray(landmark_positions, dtype=np.float64)
    except (TypeError, ValueError):
        raise FinalShapeError(f"landmark_positions must be a ({k}, 3) array of numbers") from None
    if positions.shape != (k, 3):
        raise FinalShapeError(
            f"landmark_positions must have shape ({k}, 3): one absolute world position per landmark, in the "
            f"order {model.names[0]}..{model.names[-1]}; got {positions.shape}"
        )
    if not np.isfinite(positions).all():
        raise FinalShapeError("landmark_positions holds a value that is not a finite number")
    scale = model.mm_per_scene_unit
    translations_scene = positions - model.landmark_rest_scene
    translations_mm = coords.to_mm_zup(translations_scene, scale)  # linear, so right for differences
    shape_mm = skinning.deform(model.base_mm, model.weights, translations_mm)
    return coords.from_mm_zup(shape_mm, scale)
