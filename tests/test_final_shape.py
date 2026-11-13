"""final_shape (T-31; docs/04 section 12.4): the lab's training step without Maya.

THIS FIRST VERSION IS SELF-CONSISTENCY ONLY. The tests show that the function is the skinning kernel
(T-09) with the unit conversion done once at its boundary, that on the bind pose it equals the lab's own
formula (bind pose + weights @ translations) on the lab's own files, and that it refuses bad inputs.
They cannot show that it agrees with Maya: that needs a Ziva export (D3) and the answer to Q20 (does Ziva
re-solve within the same frame when the jaw turns), both in docs/11.
"""

import dataclasses
import json
from pathlib import Path

import local_paths
import numpy as np
import pytest

from asrp_core import final_shape as fs
from asrp_core import scene, skinning
from asrp_core.asset import coords, lab

# `load` warns that its base is not the lab's training base; one test asserts that, the others need not repeat it.
pytestmark = pytest.mark.filterwarnings("ignore::asrp_core.final_shape.SettledBaseWarning")

REPO = Path(__file__).resolve().parents[1]
LAB_DATA = local_paths.lab_data()  # None when this machine does not say where the lab's files are
HAVE_EXPORT = (REPO / "data" / "lab_export" / "mesh_report.json").is_file() and (
    REPO / "data" / "tetmesh" / "lips.json").is_file()
HAVE_LAB = LAB_DATA is not None and (LAB_DATA / "oor_skin_weights.json").is_file() and (
    LAB_DATA / "oor_bind_pose.json").is_file()
SCALE = 0.962


def synthetic(base="settled", v=40, k=6, seed=3) -> fs.LipModel:
    rng = np.random.default_rng(seed)
    w = rng.random((v, k))
    w[rng.random((v, k)) < 0.5] = 0.0
    w[:, 0] += 0.1
    w /= w.sum(axis=1, keepdims=True)
    return fs.LipModel([f"oor_{i + 1:02d}" for i in range(k)], w, rng.normal(size=(k, 3)) * 20,
                       rng.normal(size=(v, 3)) * 30, base, SCALE)


def moved(model: fs.LipModel, seed=5, amount=2.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return model.landmark_rest_scene + rng.normal(size=model.landmark_rest_scene.shape) * amount


def rotation(angle=0.4, axis=(1.0, 2.0, 0.5)) -> np.ndarray:
    a = np.asarray(axis) / np.linalg.norm(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


# --- the conversion pair -----------------------------------------------------------------------------


def test_from_mm_zup_undoes_to_mm_zup():
    rng = np.random.default_rng(0)
    p = rng.normal(size=(500, 3)) * 100
    back = coords.from_mm_zup(coords.to_mm_zup(p, SCALE), SCALE)
    assert back.shape == (500, 3) and np.abs(back - p).max() < 1e-12
    again = coords.to_mm_zup(coords.from_mm_zup(p, SCALE), SCALE)
    assert np.abs(again - p).max() < 1e-12
    assert coords.from_mm_zup([[2.0, -6.0, 4.0]], 2.0).tolist() == [[1.0, 2.0, 3.0]]  # the by-hand case of to_mm_zup


def test_from_mm_zup_wants_points_and_a_positive_scale():
    with pytest.raises(ValueError, match=r"\(n, 3\)"):
        coords.from_mm_zup([1, 2, 3], 1.0)
    with pytest.raises(ValueError, match="positive"):
        coords.from_mm_zup([[1, 2, 3]], 0.0)


# --- 1. the same as the kernel ---------------------------------------------------------------------------


def test_synthetic_model_equals_the_kernel_point_by_point():
    model = synthetic()
    positions = moved(model)
    out = fs.final_shape(model, None, positions)
    # The same thing written out in the core's units, with the kernel from T-09.
    t_mm = coords.to_mm_zup(positions - model.landmark_rest_scene, SCALE)
    expected_mm = skinning.deform(model.base_mm, model.weights, t_mm)
    assert out.shape == (40, 3) and out.dtype == np.float64
    assert np.abs(coords.to_mm_zup(out, SCALE) - expected_mm).max() < 1e-12
    assert np.abs(expected_mm - model.base_mm).max() > 1.0  # the landmarks really moved the vertices


# --- 2. at rest ---------------------------------------------------------------------------------------------


def test_landmarks_at_rest_give_the_base_in_scene_units():
    model = synthetic()
    out = fs.final_shape(model, None, model.landmark_rest_scene)
    assert np.abs(out - coords.from_mm_zup(model.base_mm, SCALE)).max() < 1e-9


# --- 4. the jaw ------------------------------------------------------------------------------------------------


def test_any_valid_jaw_rotation_leaves_the_result_unchanged():
    model = synthetic()
    positions = moved(model)
    plain = fs.final_shape(model, None, positions)
    for r in (np.eye(3), rotation(), rotation(2.9, (0, 0, 1)), rotation(-1.0, (1, 0, 0))):
        assert fs.final_shape(model, r, positions, jaw_changes_base="no").tobytes() == plain.tobytes()


def test_there_is_no_resolve_mode_and_the_error_says_q20_was_measured():
    model = synthetic()
    with pytest.raises(fs.FinalShapeError, match="Q20") as e:
        fs.final_shape(model, np.eye(3), moved(model), jaw_changes_base="resolve")
    assert "does not exist" in str(e.value) and "measured" in str(e.value)


def test_another_jaw_option_is_an_error():
    model = synthetic()
    with pytest.raises(fs.FinalShapeError, match="jaw_changes_base must be one of"):
        fs.final_shape(model, np.eye(3), moved(model), jaw_changes_base="maybe")


@pytest.mark.parametrize("matrix,message", [
    (np.diag([1.0, 1.0, -1.0]), "determinant"),  # a mirror
    (np.eye(3) * 2.0, "not a rotation"),  # a scale
    (rotation() + 1e-3, "not a rotation"),
    (np.eye(4), "3x3"),
    (np.full((3, 3), np.nan), "finite"),
    ("rotate", "numbers"),
])
def test_a_non_rotation_is_an_error(matrix, message):
    model = synthetic()
    with pytest.raises(fs.FinalShapeError, match=message):
        fs.final_shape(model, matrix, moved(model))


# --- 5. inputs untouched, shapes ---------------------------------------------------------------------------


def test_the_inputs_are_not_mutated_and_the_call_is_repeatable():
    model = synthetic()
    positions, r = moved(model), rotation()
    before = (positions.copy(), r.copy(), model.base_mm.copy(), model.weights.copy(), model.landmark_rest_scene.copy())
    first = fs.final_shape(model, r, positions)
    second = fs.final_shape(model, r, positions)
    after = (positions, r, model.base_mm, model.weights, model.landmark_rest_scene)
    assert all(a.tobytes() == b.tobytes() for a, b in zip(before, after, strict=True))
    assert first.tobytes() == second.tobytes()
    first[:] = 0  # the result is the caller's own array
    assert second.any() and model.base_mm.any()


@pytest.mark.parametrize("positions", [np.zeros((5, 3)), np.zeros((6, 2)), np.zeros(18), np.zeros((1, 6, 3))])
def test_wrong_landmark_shapes_say_the_expected_shape(positions):
    with pytest.raises(fs.FinalShapeError, match=r"shape \(6, 3\)"):
        fs.final_shape(synthetic(), None, positions)


def test_landmarks_that_are_not_numbers_are_an_error():
    model = synthetic()
    bad = moved(model)
    bad[2, 1] = np.inf
    with pytest.raises(fs.FinalShapeError, match="finite"):
        fs.final_shape(model, None, bad)
    with pytest.raises(fs.FinalShapeError, match=r"\(6, 3\)"):
        fs.final_shape(model, None, [["a", "b", "c"]] * 6)


# --- 6. load, on a hand-made run folder ----------------------------------------------------------------------
# Not a FEBio-made folder: the files are written here with the formats simulate.py writes. Done by hand on a
# real lips run, see the T-31 report.


def make_run(folder: Path, *, status="complete", settled=None, with_landmarks=True, sag=-0.7, passed=True,
             scene_names=None) -> tuple[Path, fs.LipModel]:
    """A tiny run folder: scene.json with 4 landmarks and a lip mesh of 6 vertices, its skin file, the report
    and the settled shape. Returns the folder and the model that `load` should give back."""
    rng = np.random.default_rng(11)
    v, k = 6, 4
    names = [f"oor_{i + 1:02d}" for i in range(k)]
    w = rng.random((v, k))
    w /= w.sum(axis=1, keepdims=True)
    rest_mm = rng.normal(size=(v, 3)) * 10
    rest_scene = rng.normal(size=(k, 3)) * 10
    (folder / "landmarks").mkdir(parents=True)
    (folder / "meshes").mkdir()
    (folder / "physics").mkdir()
    eye = [np.eye(4).ravel().tolist()] * k
    skin = {"format": "asrp-skin/1", "units": "mm", "axes": coords.AXES, "convention": "column vectors, row by row",
            "mesh": "lips", "names": names, "rest_world": eye, "bind_pre": eye, "geom": np.eye(4).ravel().tolist(),
            "weights": [[[i, float(w[r, i])] for i in range(k)] for r in range(v)]}
    (folder / "landmarks" / "skin_mm.json").write_text(json.dumps(skin), encoding="utf-8", newline="\n")
    (folder / "meshes" / "lips.obj").write_text(
        "".join(f"v {float(x)!r} {float(y)!r} {float(z)!r}\n" for x, y, z in rest_mm) + "f 1 2 3\nf 4 5 6\n", encoding="ascii", newline="\n")
    # scene.json: start from a valid scene so every other section is well formed, then add the landmarks.
    import cube_scene as cs

    cs.write(folder / "box")
    model = scene.load(folder / "box" / "scene.json")
    sha = lambda p: scene.FileRef(p, __import__("hashlib").sha256((folder / p).read_bytes()).hexdigest())  # noqa: E731
    model.units.mm_per_scene_unit = scene.Param(SCALE, "ours", "test")
    model.landmarks = scene.Landmarks(scene_names or names, coords.to_mm_zup(rest_scene, SCALE).tolist(),
                                      sha("landmarks/skin_mm.json")) if with_landmarks else None
    for name in ("tissue_tet.json", "skull.obj", "plate.obj"):
        (folder / name).write_bytes((folder / "box" / name).read_bytes())
    model.soft_tissues[0].mesh = sha("meshes/lips.obj")
    scene.write(folder / "scene.json", model)
    base = rest_mm + np.array([0.0, 0.0, sag])
    (folder / "physics" / "settled_frame14.json").write_text(json.dumps({
        "format": "asrp-settled/1", "units": "mm", "frame": 14, "time_s": 14 / 30, "note": "test",
        "tet_nodes": [], "display": base.tolist()}), encoding="utf-8", newline="\n")
    report = {"format": "asrp-run-report/1", "status": status, "passed": passed,
              "checks": {"c": {"name": "gravity sag", "passed": passed, "message": "test"}},
              "settled_shape": settled or {"available": True, "frame": 14}}
    (folder / "run_report.json").write_text(json.dumps(report), encoding="utf-8", newline="\n")
    return folder, fs.LipModel(names, w, rest_scene, base, "settled", SCALE)


def test_load_reads_the_scene_the_skin_and_the_settled_shape(tmp_path):
    folder, expected = make_run(tmp_path / "run")
    model = fs.load(folder)
    assert model.base == "settled" and list(model.names) == list(expected.names) and model.mm_per_scene_unit == SCALE
    assert np.abs(model.weights - expected.weights).max() < 1e-12
    assert np.abs(model.landmark_rest_scene - expected.landmark_rest_scene).max() < 1e-12
    assert np.abs(model.base_mm - expected.base_mm).max() < 1e-12
    positions = moved(expected)
    assert np.abs(fs.final_shape(model, None, positions) - fs.final_shape(expected, None, positions)).max() < 1e-12
    # rest landmarks give the settled base, not the rest mesh: here it sags by 0.7 mm
    at_rest = coords.to_mm_zup(fs.final_shape(model, None, model.landmark_rest_scene), SCALE)
    rest_mesh, _ = coords.read_obj(folder / "meshes" / "lips.obj")
    assert abs(np.abs(at_rest - rest_mesh).max() - 0.7) < 1e-9


def test_rest_model_takes_the_scene_mesh_as_the_base(tmp_path):
    folder, expected = make_run(tmp_path / "run")
    model = fs.rest_model(folder / "scene.json")
    rest_mesh, _ = coords.read_obj(folder / "meshes" / "lips.obj")
    assert model.base == "rest" and np.abs(model.base_mm - rest_mesh).max() < 1e-12


def test_load_says_why_a_run_cannot_be_used(tmp_path):
    folder, _ = make_run(tmp_path / "failed", status="failed")
    with pytest.raises(fs.FinalShapeError, match="not 'complete'"):
        fs.load(folder)
    folder, _ = make_run(tmp_path / "nosettle", settled={"available": False, "frame": None,
                                                         "reason": "the motion starts on or before frame 14"})
    with pytest.raises(fs.FinalShapeError, match="the motion starts on or before frame 14"):
        fs.load(folder)
    folder, _ = make_run(tmp_path / "nolandmarks", with_landmarks=False)
    with pytest.raises(fs.FinalShapeError, match="no landmarks"):
        fs.load(folder)
    with pytest.raises(fs.FinalShapeError, match="run_report.json"):
        fs.load(tmp_path)
    with pytest.raises(fs.FinalShapeError, match="not a folder"):
        fs.load(tmp_path / "missing")


# --- 3. the real asset and the lab's own files -------------------------------------------------------------


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    if not HAVE_EXPORT:
        pytest.skip("needs data/lab_export and data/tetmesh/lips.json (the committed export)")
    if not HAVE_LAB:
        pytest.skip("NOT VERIFIED: needs the lab's own files; " + local_paths.HOW_TO_SET)
    out = tmp_path_factory.mktemp("asset")
    result = lab.import_asset(REPO / "data" / "lab_export", out, REPO / "data" / "tetmesh" / "lips.json")
    return fs.rest_model(result.scene_path)


def lab_arrays():
    bind = np.asarray(json.loads((LAB_DATA / "oor_bind_pose.json").read_text(encoding="utf-8")), dtype=np.float64)
    weights = np.asarray(json.loads((LAB_DATA / "oor_skin_weights.json").read_text(encoding="utf-8")), dtype=np.float64)
    return bind, weights


def test_real_asset_equals_the_kernel_with_a_settled_like_base(real):
    assert real.base == "rest" and real.weights.shape == (10240, 300) and len(real.names) == 300
    base = real.base_mm + np.random.default_rng(2).normal(size=real.base_mm.shape) * 0.3  # stands in for a sag
    model = dataclasses.replace(real, base_mm=base, base="settled")
    positions = moved(model, seed=9)
    out = fs.final_shape(model, rotation(), positions)
    expected = skinning.deform(base, model.weights, coords.to_mm_zup(positions - model.landmark_rest_scene, SCALE))
    assert out.shape == (10240, 3)
    assert np.abs(coords.to_mm_zup(out, SCALE) - expected).max() < 1e-12
    assert np.abs(expected - base).max() > 1.0


def test_real_asset_at_rest_gives_the_base(real):
    out = fs.final_shape(real, None, real.landmark_rest_scene)
    assert np.abs(out - coords.from_mm_zup(real.base_mm, real.mm_per_scene_unit)).max() < 1e-9


def test_the_bind_pose_model_equals_the_labs_formula_on_the_labs_files(real):
    bind, lab_weights = lab_arrays()
    assert bind.shape == (10240, 3) and lab_weights.shape == (10240, 300)
    positions = real.landmark_rest_scene + np.random.default_rng(0).normal(size=(300, 3)) * 2.0
    # The landmark REST positions are ours on both sides: the lab files hold no landmark positions, so this test
    # checks their weights, their bind mesh and the vertex order, not where the landmarks rest (tests/test_asset.py
    # checks those against the export).
    translations = positions - real.landmark_rest_scene
    assert np.abs(translations).max() > 1.0  # counts above zero: the landmarks really moved
    ours = fs.final_shape(real, None, positions)
    # The lab's formula, entirely in scene units with their arrays (docs/03 section 13.3).
    lab_result = bind + lab_weights @ translations
    worst = float(np.linalg.norm(ours - lab_result, axis=1).max())
    print(f"final_shape vs the lab formula: max vertex distance {worst:.3e} scene units over {len(ours)} vertices")
    assert worst < 1e-4
    shifted = bind + np.roll(lab_weights, 1, axis=1) @ translations  # control: must be far off
    control = float(np.linalg.norm(ours - shifted, axis=1).max())
    print(f"control (their weight columns shifted by one landmark): max vertex distance {control:.3e}")
    assert control > 1e-4


def test_the_jaw_input_does_not_change_the_real_result(real):
    positions = moved(real, seed=4)
    assert fs.final_shape(real, rotation(), positions).tobytes() == fs.final_shape(real, None, positions).tobytes()


# --- review additions -------------------------------------------------------------------------------------------


def test_a_run_whose_checks_failed_is_refused_unless_asked_for(tmp_path):
    folder, _ = make_run(tmp_path / "bad", passed=False)
    with pytest.raises(fs.FinalShapeError, match="plausibility checks did not all pass.*failed: c"):
        fs.load(folder)
    assert fs.load(folder, allow_failed_checks=True).base == "settled"


def test_a_scene_and_a_skin_that_disagree_on_the_landmark_order_are_refused(tmp_path):
    folder, _ = make_run(tmp_path / "order", scene_names=["oor_02", "oor_01", "oor_03", "oor_04"])
    with pytest.raises(fs.FinalShapeError, match="names or order differ"):
        fs.load(folder)


def test_a_loaded_model_cannot_be_edited_in_place(tmp_path):
    folder, _ = make_run(tmp_path / "run")
    model = fs.load(folder)
    for array in (model.base_mm, model.weights, model.landmark_rest_scene):
        with pytest.raises(ValueError, match="read-only"):
            array[0, 0] = 1.0
    assert isinstance(model.names, tuple)


def test_a_jaw_turn_changes_nothing_and_does_not_warn():
    """Q20 was measured (docs/13 E-11): Ziva does not re-solve within a frame, so there is nothing to warn about."""
    model = synthetic()
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        turned = fs.final_shape(model, rotation(), moved(model))
        assert turned.tobytes() == fs.final_shape(model, np.eye(3), moved(model)).tobytes()
        assert turned.tobytes() == fs.final_shape(model, None, moved(model)).tobytes()


def test_importing_the_module_needs_neither_blender_nor_a_subprocess():
    import subprocess
    import sys
    code = ("import sys; import asrp_core.final_shape; "
            "bad = [m for m in ('bpy', 'subprocess', 'asrp_core.febio', 'asrp_core.run', 'asrp_core.simulate') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_base_whose_tissue_was_still_moving_is_refused_unless_asked_for(tmp_path):
    moving = {"available": True, "frame": 14, "tissue_settled": False, "tissue_step_max_mm": 0.0054,
              "tissue_settled_limit_mm": 0.001}
    folder, _ = make_run(tmp_path / "moving", settled=moving)
    with pytest.raises(fs.FinalShapeError, match="still moving.*0.0054"):
        fs.load(folder)
    assert fs.load(folder, allow_unsettled=True).base == "settled"
    still, _ = make_run(tmp_path / "still", settled={**moving, "tissue_settled": True, "tissue_step_max_mm": 4e-7})
    with pytest.warns(fs.SettledBaseWarning, match="REST shape"):  # load says it is not the lab's training base
        assert fs.load(still).base == "settled"  # a run report from before the key existed is accepted too (other tests)
