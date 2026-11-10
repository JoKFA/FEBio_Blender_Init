"""Import the lab's Maya export (data/lab_export, docs/12 part 1) as a scene (T-02).

Writes into an output folder:

    scene.json           asrp-scene/1 (asrp_core.scene); passes `asrp check`
    meshes/<name>.obj    the five meshes in mm, Z up (asrp_core.asset.coords), faces as exported
    meshes/lips_tet.json a byte copy of the committed lip tet mesh (data/tetmesh/lips.json, ADR-20)
    landmarks/skin_skinCluster7.json   a byte copy of the exported landmark skin weights
    import_report.json   units, axes, meshes, every parameter and its source, what is missing, and
                         the result of the scene check

Roles follow docs/03 sections 3 and 4: the lips are the soft tissue; skull and upper teeth are
fixed; jaw and lower teeth both follow the driver jaw01, the joint that moves them in Maya. The
Ziva attribute list has not arrived (docs/12 item 2), so material, solver settings and bone masses
are placeholders marked "ours", and there are no attachments yet (T-03): `asrp check` passes with
one warning, which the report lists first under "missing".
"""

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from asrp_core import __version__, scene
from asrp_core.asset import coords

DEFAULT_MM_PER_SCENE_UNIT = 0.962  # paper appendix V; provisional (docs/11 Q3), so a setting
LIPS = "middleres_OrbicularisOris"
JAW_DRIVER = "jaw01"
# name in scene.json -> (Maya mesh name, motion, driver); docs/03 sections 3 and 4.
BONES = {
    "jaw": ("middleres_Jaw", "prescribed", JAW_DRIVER),
    "skull": ("middleres_skull", "fixed", None),
    "teeth_upper": ("middleres_TeethUp", "fixed", None),
    "teeth_lower": ("middleres_TeethDown", "prescribed", JAW_DRIVER),
}
SKIN = "skin_skinCluster7.json"
SOLVER_FPS = 30  # the lab's zSolver frame rate (docs/03 section 5)

# Data the import cannot fill yet, said once here so the report and the docs agree.
STILL_MISSING = [
    "Ziva attribute list (docs/12 item 2, Q4): material, solver substeps, damping and gravity are "
    "placeholders marked 'ours'; re-import when it arrives",
    "Motion (D2): no lab trajectory; T-06 uses a stand-in hinge motion for driver jaw01",
    "Units (Q3): mm_per_scene_unit and physics_length_scale k are provisional",
]


class AssetError(ValueError):
    """The export cannot be imported; the message says what is wrong and what to do."""


@dataclass
class ImportResult:
    scene_path: Path
    report: dict
    check: scene.Report = field(repr=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _need(path: Path) -> Path:
    if not path.is_file():
        raise AssetError(f"{path} is missing; the export folder comes from tools/maya_export.py (docs/12 part 1)")
    return path


def _write_obj(path: Path, header: list[str], vertices: np.ndarray, faces) -> None:
    lines = [f"# {h}" for h in header]
    lines += [f"v {x!r} {y!r} {z!r}" for x, y, z in vertices.tolist()]
    lines += ["f " + " ".join(str(i + 1) for i in face) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _params(node, where=""):
    """(location, Param json) for every parameter in a scene's JSON."""
    if isinstance(node, dict):
        if "value" in node and "source" in node:
            yield where, node
            return
        for k, v in node.items():
            yield from _params(v, f"{where}.{k}" if where else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = v.get("name", i) if isinstance(v, dict) else i
            yield from _params(v, f"{where}[{label}]")


def import_asset(export: Path, out: Path, tet_mesh: Path,
                 mm_per_scene_unit: float = DEFAULT_MM_PER_SCENE_UNIT) -> ImportResult:
    export, out, tet_mesh = Path(export), Path(out), Path(tet_mesh)
    report_json = json.loads(_need(export / "mesh_report.json").read_text(encoding="utf-8"))
    # ADR-18: the export already applied each mesh's world matrix. Applying it again would scale
    # everything by 2.54 a second time without any error, so refuse anything else.
    if report_json.get("obj_coordinates") != "scene":
        raise AssetError(
            f"{export / 'mesh_report.json'} says the OBJ files are in {report_json.get('obj_coordinates')!r} "
            "coordinates; this import expects 'scene' (ADR-18). Re-export with tools/maya_export.py. "
            "Do not apply world_matrix here"
        )
    if (out / "scene.json").exists():
        raise AssetError(f"{out} already holds a scene.json; import into an empty or new folder")
    _need(tet_mesh)
    (out / "meshes").mkdir(parents=True, exist_ok=True)
    (out / "landmarks").mkdir(parents=True, exist_ok=True)
    mm_note = ("paper appendix V's 0.962, provisional (docs/11 Q3)"
               if mm_per_scene_unit == DEFAULT_MM_PER_SCENE_UNIT else "set with --mm-per-scene-unit")

    meshes_report = []

    def convert(name: str, maya_name: str, role: str) -> tuple[scene.FileRef, scene.SourceObj]:
        expected = report_json["meshes"].get(maya_name)
        if expected is None:
            raise AssetError(f"mesh_report.json has no mesh {maya_name!r}; is this the lab's jaw/lips export?")
        source = _need(export / f"mesh_{maya_name}.obj")
        vertices, faces = coords.read_obj(source)
        if len(vertices) != expected["vertices"] or len(faces) != expected["faces"]:
            raise AssetError(
                f"{source.name} has {len(vertices)} vertices and {len(faces)} faces, mesh_report.json says "
                f"{expected['vertices']} and {expected['faces']}; the export is incomplete, re-export it"
            )
        mm = coords.to_mm_zup(vertices, mm_per_scene_unit)
        target = out / "meshes" / f"{name}.obj"
        source_sha = _sha256(source)
        _write_obj(target, [
            f"{name} ({maya_name}), {role}, rest shape, mm, Z up, written by asrp import-asset {__version__}",
            f"from {source.name} (sha256 {source_sha}): scene units x {mm_per_scene_unit!r} mm, then {coords.AXES}",
        ], mm, faces)
        meshes_report.append({
            "name": name, "maya_mesh": maya_name, "role": role, "source": source.name,
            "vertices": len(vertices), "faces": len(faces),
            "size_mm": (mm.max(axis=0) - mm.min(axis=0)).tolist(),
        })
        return (scene.FileRef(f"meshes/{name}.obj", _sha256(target)),
                scene.SourceObj(source.name, source_sha, expected.get("world_matrix")))

    def ours(value, note):
        return scene.Param(value, "ours", note)

    lips_mesh, lips_source = convert("lips", LIPS, "soft tissue")
    shutil.copyfile(tet_mesh, out / "meshes" / "lips_tet.json")
    tet_meta = json.loads((out / "meshes" / "lips_tet.json").read_text(encoding="utf-8"))
    no_attribute_list = "placeholder: the Ziva attribute list has not arrived (docs/12 item 2, Q4)"
    tissue = scene.SoftTissue(
        "lips", lips_mesh, lips_source,
        scene.TetRef("meshes/lips_tet.json", tet_meta.get("content_sha256", "")),
        scene.Material("neo-Hookean", {
            "E_mpa": ours(0.02, f"20 kPa, a common soft-tissue value; {no_attribute_list}"),
            "nu": ours(0.45, no_attribute_list),
            "density_t_per_mm3": ours(1.06e-9, f"1060 kg/m3; {no_attribute_list}"),
        }),
    )

    bones = []
    for name, (maya_name, motion, driver) in BONES.items():
        role = f"bone, {motion}" + (f", follows {driver}" if driver else "")
        mesh, source = convert(name, maya_name, role)
        mass = ours(None, "unknown; unused while the bone is fixed or its motion fully given")
        bones.append(scene.Bone(name, mesh, source, mass, motion, driver))

    joints = json.loads(_need(export / "joints.json").read_text(encoding="utf-8"))
    if JAW_DRIVER not in joints:
        raise AssetError(f"joints.json has no {JAW_DRIVER!r}; the jaw cannot be given a hinge")
    jaw = joints[JAW_DRIVER]
    pivot = coords.to_mm_zup([jaw["world_position"]], mm_per_scene_unit)[0]
    # jaw01 turns about its local Z axis: the third row of its world matrix (Maya stores rows as
    # the local axes in world space). A direction, so no scaling.
    axis = coords.to_mm_zup([jaw["world_matrix"][8:11]], 1.0)[0]
    axis = axis / np.linalg.norm(axis)
    drivers = [scene.Driver(JAW_DRIVER, scene.Hinge(
        pivot.tolist(), axis.tolist(), "lab_setting",
        "jaw01 in joints.json: its position, and its local Z axis (left-right)",
    ))]

    skin_file = _need(export / SKIN)
    skin = json.loads(skin_file.read_text(encoding="utf-8"))
    names = list(skin["influences"])
    missing = [n for n in names if n not in joints]
    if missing:
        raise AssetError(f"joints.json lacks {len(missing)} landmarks named in {SKIN} (e.g. {missing[0]}); re-export")
    rest = coords.to_mm_zup([joints[n]["world_position"] for n in names], mm_per_scene_unit)
    shutil.copyfile(skin_file, out / "landmarks" / SKIN)
    landmarks = scene.Landmarks(
        names, rest.tolist(), scene.FileRef(f"landmarks/{SKIN}", _sha256(out / "landmarks" / SKIN)),
        f"weights index the lips' vertices; the file is a byte copy of the export, so its matrices are "
        f"still in scene units, Maya order (T-09 reads them)",
    )

    tet_origin = tet_mesh.as_posix()
    model = scene.Scene(
        origin={
            "asset": report_json.get("scene", ""),
            "export": f"{export.as_posix()}: tools/maya_export.py, Maya {report_json.get('maya', '?')}, "
                      f"mesh_report.json sha256 {_sha256(export / 'mesh_report.json')}",
            "tool": f"asrp import-asset {__version__}",
            "notes": f"OBJ files are scene coordinates (ADR-18): scaled and turned, no world matrix applied. "
                     f"meshes/lips_tet.json is a byte copy of {tet_origin}",
        },
        units=scene.Units(
            scene.Param(mm_per_scene_unit, "ours", mm_note),
            ours(1.0, "ADR-22: k waits for the Ziva attribute list and Q3"),
            coords.AXES,
        ),
        soft_tissues=[tissue],
        bones=bones,
        drivers=drivers,
        attachments=[],
        landmarks=landmarks,
        solver=scene.Solver(
            "dynamic",
            scene.Param(SOLVER_FPS, "lab_setting", "the lab's zSolver runs at 30 frames per second (docs/03 section 5)"),
            ours(1, f"one step per frame; {no_attribute_list}"),
            ours(0.0, f"none, FEBio's default (docs/05 pit 2); {no_attribute_list}"),
            ours([0.0, 0.0, -9810.0], f"9.81 m/s2 down, physical direction; {no_attribute_list}"),
        ),
    )
    scene_path = out / "scene.json"
    scene.write(scene_path, model)
    check = scene.check(scene_path)

    report = {
        "scene": scene_path.as_posix(),
        "units": {
            "mm_per_scene_unit": mm_per_scene_unit, "mm_per_scene_unit_source": "ours", "note": mm_note,
            "axes": coords.AXES,
            "order": "the OBJ files are scene coordinates already (ADR-18): scale to mm, then turn the axes",
            "physics_length_scale": 1.0,
        },
        "meshes": meshes_report,
        "landmarks": len(names),
        "drivers": {JAW_DRIVER: {"pivot_mm": pivot.tolist(), "axis": axis.tolist(),
                                 "moves": [b.name for b in bones if b.driver == JAW_DRIVER]}},
        "parameters": [{"where": w, **p} for w, p in _params(model.to_json())],
        "missing": [*check.warnings, *STILL_MISSING],
        "check": {"errors": check.errors, "warnings": check.warnings},
    }
    (out / "import_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8", newline="\n")
    return ImportResult(scene_path, report, check)
