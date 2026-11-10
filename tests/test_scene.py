import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from asrp_core import cli, scene, tetmesh

HERE = Path(__file__).resolve().parent
S1 = HERE / "fixtures" / "s1"
REPO = HERE.parent
LIPS_TET = REPO / "data" / "tetmesh" / "lips.json"
LIPS_OBJ = REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj"


def copy_s1(tmp_path) -> Path:
    out = tmp_path / "s1"
    shutil.copytree(S1, out, ignore=shutil.ignore_patterns("build.py", "__pycache__"))
    return out


def edit_scene(folder: Path, change) -> Path:
    path = folder / "scene.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, indent=2))
    return path


def errors_of(path, traj=None):
    report = scene.check(path, traj)
    return report, "\n".join(report.errors)


# --- the S1 example ------------------------------------------------------------------------------


def test_the_s1_example_files_are_what_the_builder_writes(tmp_path):
    spec = importlib.util.spec_from_file_location("s1_build", S1 / "build.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.build(tmp_path)
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["jaw.obj", "scene.json", "skull.obj", "tissue.obj", "tissue_tet.json", "trajectory.json"]
    for name in written:
        assert (tmp_path / name).read_bytes() == (S1 / name).read_bytes(), name


def test_the_s1_scene_reads_back_unchanged(tmp_path):
    original = json.loads((S1 / "scene.json").read_text())
    loaded = scene.load(S1 / "scene.json")
    assert loaded.to_json() == original
    scene.write(tmp_path / "scene.json", loaded)
    assert (tmp_path / "scene.json").read_bytes() == (S1 / "scene.json").read_bytes()
    assert scene.load(tmp_path / "scene.json") == loaded


def test_the_s1_scene_has_everything_s1_has():
    s = scene.load(S1 / "scene.json")
    assert [t.name for t in s.soft_tissues] == ["tissue"]
    assert {b.name: (b.motion, b.driver) for b in s.bones} == {"skull": ("fixed", None), "jaw": ("prescribed", "jaw_hinge")}
    assert s.drivers[0].hinge.pivot_mm == [5.0, -30.0, 0.0]
    # Both attachments hold the 9 surface vertices of one face of the 3 x 3 grid.
    assert [len(a.weights) for a in s.attachments] == [9, 9]
    assert s.solver.gravity_mm_per_s2.value == [0.0, 0.0, -9810.0]


def test_the_s1_scene_and_trajectory_pass_the_check():
    report = scene.check(S1 / "scene.json", S1 / "trajectory.json")
    assert report.ok, report.errors
    assert report.warnings == []
    assert report.trajectory.frames == 46


def test_every_parameter_says_where_it_came_from():
    def params(node):
        if isinstance(node, dict):
            if "value" in node:
                yield node
            for v in node.values():
                yield from params(v)
        elif isinstance(node, list):
            for v in node:
                yield from params(v)

    found = list(params(json.loads((S1 / "scene.json").read_text())))
    assert len(found) >= 12
    assert all(p["source"] in scene.SOURCES for p in found)


def test_a_parameter_without_a_source_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit_scene(folder, lambda d: d["soft_tissues"][0]["material"].update(E_mpa=0.02))
    report, text = errors_of(path)
    assert not report.ok
    assert "E_mpa: every parameter needs a value and where it came from" in text


# --- the kinds of error T-05 names -----------------------------------------------------------------


def test_a_missing_file_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    (folder / "jaw.obj").unlink()
    report, text = errors_of(folder / "scene.json")
    assert not report.ok
    assert "bone 'jaw': file jaw.obj is missing" in text


def test_a_changed_file_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    with (folder / "skull.obj").open("a") as f:
        f.write("# touched\n")
    report, text = errors_of(folder / "scene.json")
    assert "skull.obj has changed since the scene was written" in text


def test_missing_units_are_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d.pop("units")))
    assert not report.ok and "'units' is missing" in text


def test_a_missing_mm_per_scene_unit_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["units"].pop("mm_per_scene_unit")))
    assert not report.ok and "units.mm_per_scene_unit is missing" in text


def test_a_wrong_unit_system_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["units"].update(system="m-N-Pa-s")))
    assert not report.ok and "it must be 'mm-N-MPa-s'" in text


def test_physics_length_scale_left_out_is_1_and_ours(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit_scene(folder, lambda d: d["units"].pop("physics_length_scale"))
    report = scene.check(path)
    assert report.ok, report.errors
    k = report.scene.units.physics_length_scale
    assert (k.value, k.source) == (1.0, "ours")
    # Written back, it is still left out: the file says what the author wrote.
    assert "physics_length_scale" not in report.scene.to_json()["units"]


def test_an_attachment_with_no_weight_above_zero_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)

    def zero(d):
        d["attachments"][0]["weights"] = [[i, 0.0] for i, _ in d["attachments"][0]["weights"]]

    report, text = errors_of(edit_scene(folder, zero))
    assert not report.ok
    assert "attachment 'tissue_on_jaw' has no valid vertex" in text


def test_an_attachment_whose_vertices_are_not_on_the_mesh_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["attachments"][0].update(weights=[[500, 1.0], [501, 1.0]])))
    assert "2 vertex numbers are outside 'tissue''s 58 vertices" in text
    assert "has no valid vertex" in text


def test_an_attachment_weight_above_one_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["attachments"][0]["weights"][0].__setitem__(1, 1.5)))
    assert "weights must be between 0 and 1 (found 1.5)" in text


def test_no_attachment_at_all_is_only_a_warning(tmp_path):
    folder = copy_s1(tmp_path)
    report = scene.check(edit_scene(folder, lambda d: d.update(attachments=[])))
    assert report.ok, report.errors
    assert len(report.warnings) == 1
    assert "soft tissue 'tissue' has no attachment" in report.warnings[0]


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d["attachments"][0].update(to="cranium"), "goes to 'cranium', which is not an object"),
        (lambda d: d["attachments"][0].update({"from": "jaw"}), "starts from 'jaw', which is not a soft tissue"),
        (lambda d: d["bones"][1].update(driver="jaw02"), "follows driver 'jaw02', which the scene does not list"),
    ],
)
def test_a_reference_to_something_that_does_not_exist_is_an_error(tmp_path, change, message):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, change))
    assert not report.ok and message in text


def test_an_unknown_format_version_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d.update(format_version="asrp-scene/2")))
    assert not report.ok and "this asrp reads 'asrp-scene/1' only" in text


def test_a_fixed_bone_cannot_follow_a_driver(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["bones"][0].update(driver="jaw_hinge")))
    assert "a fixed bone does not move" in text


def test_a_hard_attachment_with_a_stiffness_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    report, text = errors_of(edit_scene(folder, lambda d: d["attachments"][0]["stiffness"].update(value=5.0)))
    assert "a hard attachment has no stiffness" in text


# --- scene alone, and scene with a trajectory ------------------------------------------------------


def test_a_prescribed_bone_needs_no_motion_when_only_the_scene_is_checked():
    report = scene.check(S1 / "scene.json")
    assert report.ok and report.trajectory is None


def test_a_prescribed_bone_whose_driver_has_no_motion_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    traj = json.loads((folder / "trajectory.json").read_text())
    traj["drivers"] = {"head": traj["drivers"]["jaw_hinge"]}
    (folder / "trajectory.json").write_text(json.dumps(traj))
    report, text = errors_of(folder / "scene.json", folder / "trajectory.json")
    assert not report.ok
    assert "bone 'jaw' follows driver 'jaw_hinge', but the trajectory has no motion for it" in text
    assert any("driver 'head' moves no bone" in w for w in report.warnings)


def test_a_trajectory_whose_frame_count_does_not_add_up_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    traj = json.loads((folder / "trajectory.json").read_text())
    traj["frames"] = 50
    (folder / "trajectory.json").write_text(json.dumps(traj))
    report, text = errors_of(folder / "scene.json", folder / "trajectory.json")
    assert not report.ok and "46 transforms but the file says frames = 50" in text


def test_a_trajectory_at_another_frame_rate_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    traj = json.loads((folder / "trajectory.json").read_text())
    traj["fps"] = 24
    (folder / "trajectory.json").write_text(json.dumps(traj))
    report, text = errors_of(folder / "scene.json", folder / "trajectory.json")
    assert not report.ok and "24 frames per second, the scene's solver runs at 30" in text


# --- the three tet mesh checks -------------------------------------------------------------------------


def test_an_edited_tet_mesh_is_an_error_that_says_regenerate(tmp_path):
    folder = copy_s1(tmp_path)
    text = (folder / "tissue_tet.json").read_text()
    marker = '"nodes": [\n    [0.0, 0.0, 0.0]'
    assert marker in text
    (folder / "tissue_tet.json").write_text(text.replace(marker, '"nodes": [\n    [0.0, 0.0, 0.5]'))
    report, msg = errors_of(folder / "scene.json")
    assert not report.ok
    assert "has been changed since it was written" in msg and "regenerate it with tools/build_tetmesh.py" in msg


@pytest.mark.parametrize("text", ["[]", "null"])
def test_a_tet_mesh_file_that_is_not_a_json_object_is_reported_not_raised(tmp_path, text):
    folder = copy_s1(tmp_path)
    (folder / "tissue_tet.json").write_text(text)
    report, msg = errors_of(folder / "scene.json")
    assert not report.ok
    assert "is not an asrp-tetmesh v1 file" in msg and "regenerate it with tools/build_tetmesh.py" in msg


def test_a_tet_mesh_made_from_another_surface_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit_scene(folder, lambda d: d["soft_tissues"][0]["source_obj"].update(sha256="0" * 64))
    report, msg = errors_of(path)
    assert not report.ok
    assert "was made from another surface" in msg and "regenerate the tet mesh" in msg


def test_a_tet_mesh_made_for_another_unit_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit_scene(folder, lambda d: d["units"]["mm_per_scene_unit"].update(value=0.962))
    report, msg = errors_of(path)
    assert not report.ok
    assert "was made with mm_per_scene_unit 1.0, the scene uses 0.962" in msg and "regenerate the tet mesh" in msg


def test_a_tet_mesh_other_than_the_one_named_is_an_error(tmp_path):
    folder = copy_s1(tmp_path)
    path = edit_scene(folder, lambda d: d["soft_tissues"][0]["tet_mesh"].update(content_sha256="f" * 64))
    report, msg = errors_of(path)
    assert "is not the one the scene names" in msg


@pytest.mark.skipif(not (LIPS_TET.is_file() and LIPS_OBJ.is_file()), reason="needs data/tetmesh/lips.json and the lip OBJ")
def test_the_real_lip_tet_mesh_passes_against_the_real_obj(tmp_path):
    # Copies, so nothing in data/ is touched; the scene points at them.
    shutil.copy(LIPS_TET, tmp_path / "lips.json")
    shutil.copy(LIPS_OBJ, tmp_path / "lips.obj")
    _, meta = tetmesh.load(LIPS_TET)
    s = scene.load(S1 / "scene.json")
    s.units.mm_per_scene_unit = scene.Param(0.962, "ours")
    t = s.soft_tissues[0]
    t.mesh = scene.FileRef("lips.obj", tetmesh.file_sha256(LIPS_OBJ))
    t.source_obj = scene.SourceObj(LIPS_OBJ.name, tetmesh.file_sha256(LIPS_OBJ))
    t.tet_mesh = scene.TetRef("lips.json", meta["content_sha256"])
    s.bones, s.drivers, s.attachments = [], [], []
    scene.write(tmp_path / "scene.json", s)
    report = scene.check(tmp_path / "scene.json")
    assert report.ok, report.errors


# --- the command -------------------------------------------------------------------------------------


def test_asrp_check_passes_the_example(capsys):
    assert cli.main(["check", str(S1 / "scene.json"), str(S1 / "trajectory.json")]) == 0
    out = capsys.readouterr().out
    assert "check PASSED: 0 errors, 0 warnings" in out
    assert "46 frames at 30 fps" in out


def test_asrp_check_fails_on_an_error_and_passes_on_a_warning(tmp_path, capsys):
    folder = copy_s1(tmp_path)
    edit_scene(folder, lambda d: d.update(attachments=[]))
    assert cli.main(["check", str(folder / "scene.json")]) == 0
    assert "WARN   soft tissue 'tissue' has no attachment" in capsys.readouterr().out
    (folder / "jaw.obj").unlink()
    assert cli.main(["check", str(folder / "scene.json")]) == 1
    out = capsys.readouterr().out
    assert "ERROR  bone 'jaw': file jaw.obj is missing" in out and "check FAILED: 1 errors" in out
