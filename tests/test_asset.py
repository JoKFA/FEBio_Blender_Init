import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from asrp_core import cli, scene, tetmesh
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
    jaw01, blend = s.drivers
    assert blend.name == "lip_corner_blend" and blend.hinge is None
    assert blend.blend.of == "jaw01" and blend.blend.factor.value == 0.5 and blend.blend.factor.source == "ours"
    assert [(a.name, a.driver) for a in s.anchors] == [("lip_corner_anchor", "lip_corner_blend")]
    assert jaw01.name == "jaw01" and np.allclose(jaw01.hinge.pivot_mm, [0.0, -121.7126, -54.6536], atol=1e-3)
    assert np.allclose(jaw01.hinge.axis, [1, 0, 0], atol=1e-9)  # left-right
    raw = json.loads((out / "scene.json").read_text())
    k = raw["units"]["physics_length_scale"]
    assert k["value"] == 0.67 and k["source"] == "ours" and "ADR-31" in k["note"]
    assert raw["units"]["mm_per_scene_unit"]["value"] == 0.962
    assert len(s.landmarks.names) == 300
    # Each OBJ is named with its sha256, as T-02 asks.
    lips_obj = EXPORT / "mesh_middleres_OrbicularisOris.obj"
    assert s.soft_tissues[0].source_obj.file == lips_obj.name
    assert s.soft_tissues[0].source_obj.sha256 == hashlib.sha256(lips_obj.read_bytes()).hexdigest()


@needs_export
def test_the_scene_passes_the_check_with_no_warning(imported):
    out, result = imported
    report = scene.check(out / "scene.json")
    assert report.ok, report.errors
    assert report.warnings == []
    assert not any("no attachment" in m for m in result.report["missing"])


@needs_export
def test_the_four_lip_attachments_are_in_the_scene_as_docs_05_section_3_says(imported):
    out, result = imported
    s = scene.load(out / "scene.json")
    by_name = {a.name: a for a in s.attachments}
    assert {n: (a.target, a.kind, len(a.weights)) for n, a in by_name.items()} == {
        "upper_lip_on_skull": ("skull", "hard", 74),
        "lower_lip_on_jaw": ("jaw", "spring", 76),
        "left_corner_on_anchor": ("lip_corner_anchor", "spring", 348),
        "right_corner_on_anchor": ("lip_corner_anchor", "spring", 309),
    }
    assert by_name["upper_lip_on_skull"].stiffness.value is None
    springs = [a.stiffness for a in by_name.values() if a.kind == "spring"]
    assert len({p.value for p in springs}) == 1 and springs[0].value > 0
    assert all(p.source == "ours" and "provisional" in p.note for p in springs)
    # The weights are the file's, vertex for vertex.
    groups = {g["attachment"]: g for g in json.loads((EXPORT / "lip_attachments.json").read_text())["groups"]}
    assert by_name["lower_lip_on_jaw"].weights == groups["zAttachment2"]["vertices"]
    # The stiffness is T-07's rule: 100 x E x h, h = median tet edge x k.
    mesh, _ = tetmesh.load(TET)
    h = tetmesh.quality(mesh).median_edge_mm * 0.67
    assert springs[0].value == pytest.approx(100 * 0.02 * h, rel=5e-3)
    assert result.report["attachments_file"] == {
        "name": "lip_attachments.json",
        "sha256": hashlib.sha256((EXPORT / "lip_attachments.json").read_bytes()).hexdigest()}
    assert [a["kind"] for a in result.report["attachments"]] == ["hard", "spring", "spring", "spring"]
    assert any(m.startswith("Attachments (A-33)") and "provisional" in m for m in result.report["missing"])


@needs_export
def test_an_attachments_file_for_another_mesh_is_refused(tmp_path):
    export = tmp_path / "export"
    shutil.copytree(EXPORT, export, ignore=shutil.ignore_patterns("manual_maya_obj"))
    data = json.loads((export / "lip_attachments.json").read_text())
    data["groups"][0]["vertices"] = data["groups"][0]["vertices"][:-1]
    (export / "lip_attachments.json").write_text(json.dumps(data))
    with pytest.raises(lab.AssetError, match="zAttachment1 with 74 vertices, found 73"):
        lab.import_asset(export, tmp_path / "out", TET)


@needs_export
def test_the_report_calls_the_geometry_scale_settled_and_k_the_open_part(imported):
    out, result = imported
    text = " ".join(m for m in result.report["missing"] if not m.startswith("Attachments")) \
        + json.dumps(result.report["units"])
    assert "provisional" not in text and "Q3" not in text
    [units_line] = [m for m in result.report["missing"] if m.startswith("Physical scale")]
    assert "ADR-31" in units_line and "0.67" in units_line


@needs_export
def test_the_report_names_the_factor_the_axes_and_every_parameter_source(imported):
    _, result = imported
    r = result.report
    assert r["units"]["mm_per_scene_unit"] == 0.962 and r["units"]["axes"] == coords.AXES
    where = {p["where"]: p["source"] for p in r["parameters"]}
    assert len(where) == 18  # 13 before the attachments, plus alpha and four stiffnesses
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
@pytest.mark.parametrize("text", ["[]", "null", "not json at all"])
def test_a_tet_mesh_file_that_cannot_be_read_is_refused_before_anything_is_written(tmp_path, text):
    bad = tmp_path / "lips.json"
    bad.write_text(text)
    out = tmp_path / "lab"
    with pytest.raises(lab.AssetError):
        lab.import_asset(EXPORT, out, bad)
    assert not out.exists()


@needs_export
def test_an_edited_tet_mesh_is_refused_with_how_to_restore_it(tmp_path):
    edited = tmp_path / "lips.json"
    data = json.loads(TET.read_text())
    data["nodes"][0][0] += 0.5
    edited.write_text(json.dumps(data))
    with pytest.raises(lab.AssetError, match="has been changed since it was written.*tools/build_tetmesh.py"):
        lab.import_asset(EXPORT, tmp_path / "lab", edited)


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
    assert "import PASSED: scene check 0 errors, 0 warnings" in text
    assert "no attachment" not in text
    assert cli.main(["check", str(out / "scene.json")]) == 0


@needs_export
def test_the_scene_does_not_depend_on_where_it_was_written(imported, tmp_path):
    out, _ = imported
    lab.import_asset(EXPORT.resolve(), tmp_path / "elsewhere", TET.resolve())
    assert (tmp_path / "elsewhere" / "scene.json").read_bytes() == (out / "scene.json").read_bytes()
