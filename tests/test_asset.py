import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from asrp_core import cli, scene
from asrp_core.asset import coords, lab

REPO = Path(__file__).resolve().parents[1]
EXPORT = REPO / "data" / "lab_export"
TET = REPO / "data" / "tetmesh" / "lips.json"
HAVE_EXPORT = (EXPORT / "mesh_report.json").is_file() and TET.is_file()
needs_export = pytest.mark.skipif(not HAVE_EXPORT, reason="needs data/lab_export and data/tetmesh/lips.json")
# docs/03 section 3
VERTICES = {"lips": 10240, "jaw": 7426, "skull": 28414, "teeth_upper": 24608, "teeth_lower": 24608}
SOURCE = {"lips": "middleres_OrbicularisOris", "jaw": "middleres_Jaw", "skull": "middleres_skull",
          "teeth_upper": "middleres_TeethUp", "teeth_lower": "middleres_TeethDown"}


# --- the one conversion --------------------------------------------------------------------------


def test_scene_axes_become_z_up_and_scaled():
    out = coords.to_mm_zup([[1, 2, 3], [-4, 0.5, 0]], 2.0)
    # Each axis on its own: x stays, scene z (forward-back) becomes -y, scene y (up) becomes z.
    assert out.tolist() == [[2.0, -6.0, 4.0], [-8.0, -0.0, 1.0]]


def test_the_conversion_is_a_rotation_not_a_mirror():
    ex, ey, ez = coords.to_mm_zup(np.eye(3), 1.0)
    assert np.allclose(np.cross(ex, ey), ez)  # right-handed stays right-handed: left and right do not swap


def test_the_conversion_wants_points_and_a_positive_scale():
    with pytest.raises(ValueError, match=r"\(n, 3\)"):
        coords.to_mm_zup([1, 2, 3], 1.0)
    with pytest.raises(ValueError, match="positive"):
        coords.to_mm_zup([[1, 2, 3]], 0.0)


def test_obj_reading_keeps_order_drops_texture_indices_and_fans_quads(tmp_path):
    path = tmp_path / "a.obj"
    path.write_text("# c\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1/1 2/2 3/3 4/4\nf 3 2 1\n")
    vertices, faces = coords.read_obj(path)
    assert vertices.shape == (4, 3) and faces == [[0, 1, 2, 3], [2, 1, 0]]
    assert coords.triangulate(faces).tolist() == [[0, 1, 2], [0, 2, 3], [2, 1, 0]]


# --- the lab import, on the real export ----------------------------------------------------------------


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    if not HAVE_EXPORT:
        pytest.skip("needs data/lab_export and data/tetmesh/lips.json")
    before = hashlib.sha256(TET.read_bytes()).hexdigest()
    out = tmp_path_factory.mktemp("import") / "lab"
    result = lab.import_asset(EXPORT, out, TET)
    assert hashlib.sha256(TET.read_bytes()).hexdigest() == before, "the import changed data/tetmesh/lips.json"
    return out, result


def raw_vertices(path: Path) -> np.ndarray:
    # Read independently of coords.read_obj, so a bug there cannot hide here.
    return np.array([[float(c) for c in line.split()[1:4]] for line in path.read_text().splitlines()
                     if line.startswith("v ")])


@needs_export
def test_five_meshes_with_the_vertex_counts_of_docs_03(imported):
    out, result = imported
    assert {m["name"]: m["vertices"] for m in result.report["meshes"]} == VERTICES
    for name, count in VERTICES.items():
        assert len(raw_vertices(out / "meshes" / f"{name}.obj")) == count


@needs_export
def test_every_vertex_is_scene_times_the_factor_with_the_axes_turned(imported):
    out, _ = imported
    for name, maya in SOURCE.items():
        scene_xyz = raw_vertices(EXPORT / f"mesh_{maya}.obj")
        mm = raw_vertices(out / "meshes" / f"{name}.obj")
        assert len(mm) == len(scene_xyz) > 0
        worst = max(np.abs(mm[:, 0] - 0.962 * scene_xyz[:, 0]).max(),
                    np.abs(mm[:, 1] + 0.962 * scene_xyz[:, 2]).max(),
                    np.abs(mm[:, 2] - 0.962 * scene_xyz[:, 1]).max())
        assert worst < 1e-3, f"{name}: {worst} mm"


@needs_export
def test_sizes_agree_with_maya_own_report_and_the_jaw_is_150_mm(imported):
    _, result = imported
    report = json.loads((EXPORT / "mesh_report.json").read_text())
    for m in result.report["meshes"]:
        sx, sy, sz = report["meshes"][m["maya_mesh"]]["size"]
        assert np.allclose(m["size_mm"], [0.962 * sx, 0.962 * sz, 0.962 * sy], atol=1e-6)
    jaw = next(m for m in result.report["meshes"] if m["name"] == "jaw")
    assert abs(jaw["size_mm"][1] - 150.0) < 0.01  # 155.92 x 0.962, the paper's jaw (ADR-16)


@needs_export
def test_the_scene_has_the_roles_of_docs_03(imported):
    out, _ = imported
    s = scene.load(out / "scene.json")
    assert [t.name for t in s.soft_tissues] == ["lips"]
    assert {b.name: (b.motion, b.driver) for b in s.bones} == {
        "jaw": ("prescribed", "jaw01"), "teeth_lower": ("prescribed", "jaw01"),
        "skull": ("fixed", None), "teeth_upper": ("fixed", None),
    }
    [jaw01] = s.drivers
    assert jaw01.name == "jaw01" and np.allclose(jaw01.hinge.pivot_mm, [0.0, -121.7126, -54.6536], atol=1e-3)
    assert np.allclose(jaw01.hinge.axis, [1, 0, 0], atol=1e-9)  # left-right
    raw = json.loads((out / "scene.json").read_text())
    assert raw["units"]["physics_length_scale"] == {"value": 1.0, "source": "ours",
                                                    "note": "ADR-22: k waits for the Ziva attribute list and Q3"}
    assert raw["units"]["mm_per_scene_unit"]["value"] == 0.962
    assert len(s.landmarks.names) == 300
    # Each OBJ is named with its sha256, as T-02 asks.
    lips_obj = EXPORT / "mesh_middleres_OrbicularisOris.obj"
    assert s.soft_tissues[0].source_obj.file == lips_obj.name
    assert s.soft_tissues[0].source_obj.sha256 == hashlib.sha256(lips_obj.read_bytes()).hexdigest()


@needs_export
def test_the_scene_passes_the_check_with_only_the_missing_attachments_warning(imported):
    out, result = imported
    report = scene.check(out / "scene.json")
    assert report.ok, report.errors
    assert len(report.warnings) == 1 and "soft tissue 'lips' has no attachment" in report.warnings[0]
    assert result.report["missing"][0] == report.warnings[0]


@needs_export
def test_the_report_names_the_factor_the_axes_and_every_parameter_source(imported):
    _, result = imported
    r = result.report
    assert r["units"]["mm_per_scene_unit"] == 0.962 and r["units"]["axes"] == coords.AXES
    where = {p["where"]: p["source"] for p in r["parameters"]}
    assert len(where) == 13
    assert where["solver.fps"] == "lab_setting"
    assert where["soft_tissues[lips].material.E_mpa"] == "ours"
    assert all(s in scene.SOURCES for s in where.values())


@needs_export
def test_the_factor_is_a_setting_and_a_tet_mesh_for_another_factor_is_refused(tmp_path):
    result = lab.import_asset(EXPORT, tmp_path / "lab", TET, mm_per_scene_unit=1.0)
    jaw = next(m for m in result.report["meshes"] if m["name"] == "jaw")
    assert abs(jaw["size_mm"][1] - 155.917) < 0.01  # unscaled
    assert not result.check.ok
    assert any("made with mm_per_scene_unit 0.962, the scene uses 1.0" in e and "regenerate" in e
               for e in result.check.errors)


@needs_export
def test_obj_files_not_in_scene_coordinates_are_refused(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    report = json.loads((EXPORT / "mesh_report.json").read_text())
    report["obj_coordinates"] = "object"
    (export / "mesh_report.json").write_text(json.dumps(report))
    with pytest.raises(lab.AssetError, match="expects 'scene' \\(ADR-18\\).*Do not apply world_matrix"):
        lab.import_asset(export, tmp_path / "out", TET)


@needs_export
def test_an_incomplete_export_is_refused(tmp_path):
    export = tmp_path / "export"
    shutil.copytree(EXPORT, export, ignore=shutil.ignore_patterns("manual_maya_obj", "mesh_middleres_skull.obj"))
    with pytest.raises(lab.AssetError, match="mesh_middleres_skull.obj is missing"):
        lab.import_asset(export, tmp_path / "out", TET)


@needs_export
def test_an_existing_scene_is_not_overwritten(imported):
    out, _ = imported
    with pytest.raises(lab.AssetError, match="already holds a scene.json"):
        lab.import_asset(EXPORT, out, TET)


@needs_export
def test_asrp_import_asset_runs_end_to_end(tmp_path, capsys):
    out = tmp_path / "lab"
    assert cli.main(["import-asset", str(EXPORT), str(out)]) == 0
    text = capsys.readouterr().out
    assert "import PASSED: scene check 0 errors, 1 warnings" in text
    assert "missing    soft tissue 'lips' has no attachment" in text
    assert cli.main(["check", str(out / "scene.json")]) == 0


@needs_export
def test_the_scene_does_not_depend_on_where_it_was_written(imported, tmp_path):
    out, _ = imported
    lab.import_asset(EXPORT.resolve(), tmp_path / "elsewhere", TET.resolve())
    assert (tmp_path / "elsewhere" / "scene.json").read_bytes() == (out / "scene.json").read_bytes()
