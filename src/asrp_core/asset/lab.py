"""Import the lab's Maya export (data/lab_export, docs/12 part 1) as a scene (T-02).

Writes into an output folder:

    scene.json           asrp-scene/1 (asrp_core.scene); passes `asrp check`
    meshes/<name>.obj    the five meshes in mm, Z up (asrp_core.asset.coords), faces as exported
    meshes/lips_tet.json a byte copy of the committed lip tet mesh (data/tetmesh/lips.json, ADR-20)
    landmarks/skin_mm.json   the landmark skin converted to mm, Z up, column vectors (asrp-skin/1,
                         asrp_core.asset.skin); the raw export is not copied, its sha256 is inside
    import_report.json   units, axes, meshes, every parameter and its source, what is missing, and
                         the result of the scene check

Roles follow docs/03 sections 3 and 4: the lips are the soft tissue; skull and upper teeth follow
the driver head (T-28), which is at rest whenever a trajectory leaves it out, so they are then
fixed; jaw and lower teeth both follow the driver jaw01, the joint that moves them in Maya. The
Ziva attribute list was fetched on 2026-11-12 (docs/03 section 5), but this import does not use it yet:
material, solver settings and bone masses are still our own values, marked "ours" (they change in T-37,
after the T-34 baseline). The four lip attachments come from T-03's lip_attachments.json
(docs/05 section 3): upper lip hard on the skull, lower lip a spring to the jaw, the two lip
corners springs to an anchor that moves half as far as the jaw relative to the head (T-06a, T-28).
Their stiffness and the
blend factor are provisional values marked "ours". `asrp check` passes with no warning.
"""

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from asrp_core import __version__, scene, tetmesh
from asrp_core.asset import coords
from asrp_core.asset import skin as skin_module

DEFAULT_MM_PER_SCENE_UNIT = 0.962  # paper appendix V, same as the lab controller (ADR-31); still a setting
LIPS = "middleres_OrbicularisOris"
JAW_DRIVER = "jaw01"
# ADR-32: what phase 1 leaves out of the lab's model; written into scene.json, copied into the run report.
SIMPLIFICATIONS = [
    "the 6 muscles around the mouth attached to the lips (zAttachment to zTissue around the orbicularis): not built in "
    "phase 1, ADR-32",
    "the 9 skin attachments to the lips (zCloth): not built in phase 1, ADR-32 (skin is phase 2, T-18)",
    "the chain mouth-corner node -> zTissue2/3 -> skull and jaw: replaced by the lip-corner anchor that moves alpha x the "
    "jaw's motion relative to the head (A-35, docs/05 section 3)",
]
# T-28: the skull and the upper teeth follow a head driver. A trajectory that leaves it out keeps the head at rest
# (absent_means_rest), and the generator then writes the skull as a fixed body, exactly as before T-28.
HEAD_DRIVER = "head"
# name in scene.json -> (Maya mesh name, motion, driver); docs/03 sections 3 and 4.
BONES = {
    "jaw": ("middleres_Jaw", "prescribed", JAW_DRIVER),
    "skull": ("middleres_skull", "prescribed", HEAD_DRIVER),
    "teeth_upper": ("middleres_TeethUp", "prescribed", HEAD_DRIVER),
    "teeth_lower": ("middleres_TeethDown", "prescribed", JAW_DRIVER),
}
SKIN = "skin_skinCluster7.json"  # the lab export's name
SKIN_MM = "skin_mm.json"  # the converted file in the scene folder
ATTACHMENTS = "lip_attachments.json"
PHYSICS_LENGTH_SCALE = 0.67  # skull width 216.6 mm -> about 145 mm, a real person (ADR-31); ours
# T-06a: the lip corner anchor turns this fraction of the jaw's angle (docs/05 section 3); ours.
CORNER_BLEND = 0.5
CORNER_DRIVER = "lip_corner_blend"
CORNER_ANCHOR = "lip_corner_anchor"
# T-07's provisional spring rule (docs/05 section 3): base stiffness = 100 x E x h, h = node spacing
# in the solver's coordinates (median tet edge, geometry mm, times k).
STIFFNESS_OVER_EH = 100.0
# Maya attachment -> (name in scene.json, target in scene.json, kind, expected vertex count).
LIP_ATTACHMENTS = {
    "zAttachment1": ("upper_lip_on_skull", "skull", "hard", 74),
    "zAttachment2": ("lower_lip_on_jaw", "jaw", "spring", 76),
    "zAttachment9": ("left_corner_on_anchor", CORNER_ANCHOR, "spring", 348),
    "zAttachment10": ("right_corner_on_anchor", CORNER_ANCHOR, "spring", 309),
}
SOLVER_FPS = 30  # the lab's zSolver frame rate (docs/03 section 5)
# T-06a's temporary material (docs/09 T-06a card), ours: guessed to be near Ziva's defaults, not checked.
TISSUE_E_MPA = 0.015
TISSUE_NU = 0.45
TISSUE_DENSITY = 1.06e-9  # t/mm^3
TISSUE_NOTE = ("our own value, NOT Ziva's. Measured in the lab's scene on 2026-11-12: E 12 kPa, Poisson 0.4, "
               "density 1060, material model StVK (docs/03 section 5). This default changes in T-37")

# Data the import cannot fill yet, said once here so the report and the docs agree.
STILL_MISSING = [
    "Ziva's settings were measured on 2026-11-12 (docs/03 section 5) but are not used by this import yet: "
    "material, solver substeps, damping and gravity are our own values marked 'ours' (T-37)",
    "Motion: the lab's motion files were fetched (docs/13 E-11) but this import carries none; the converter "
    "is T-34 / T-10, until then a stand-in hinge motion drives jaw01",
    "Attachments: the vertex sets are confirmed (A-33: the map default is 1.0). Their type and stiffness are "
    "ours, not Ziva's: upper lip hard, the others springs of 100 x E x h, lip corner blend factor 0.5; Ziva "
    "has 140 soft attachments of 1e8 N/m^3 (docs/03 section 5, T-37)",
    "Physical scale (ADR-31): geometry is settled (0.962 mm per scene unit); physics_length_scale k "
    "is 0.67, real-person size, a value we chose from the meeting conclusion, not Ziva's scale",
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
    # Through the shared loader, and before anything is written: a damaged or foreign file is
    # then reported the same way as everywhere else, and no half-made output folder is left.
    try:
        _, tet_meta = tetmesh.load(tet_mesh)
    except ValueError as e:
        # load() names the file in its own messages; a JSON syntax error does not.
        raise AssetError(str(e) if str(tet_mesh) in str(e) else
                         f"{tet_mesh} is not a readable tet mesh file ({e}); restore it from git or "
                         "regenerate it with tools/build_tetmesh.py") from e
    (out / "meshes").mkdir(parents=True, exist_ok=True)
    (out / "landmarks").mkdir(parents=True, exist_ok=True)
    mm_note = ("paper appendix V's 0.962, also the lab controller's conversion (ADR-31)"
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

    attachments_file = _need(export / ATTACHMENTS)
    attachments_json = json.loads(attachments_file.read_text(encoding="utf-8"))
    attachments_sha = _sha256(attachments_file)

    lips_mesh, lips_source = convert("lips", LIPS, "soft tissue")
    shutil.copyfile(tet_mesh, out / "meshes" / "lips_tet.json")
    no_attribute_list = "our own value: Ziva's measured settings (docs/03 section 5) are not used yet (T-37)"
    tissue_vertex_count = len(coords.read_obj(export / f"mesh_{LIPS}.obj")[0])
    tissue = scene.SoftTissue(
        "lips", lips_mesh, lips_source,
        scene.TetRef("meshes/lips_tet.json", tet_meta.get("content_sha256", "")),
        scene.Material("neo-Hookean", {
            "E_mpa": ours(TISSUE_E_MPA, f"15 kPa; {TISSUE_NOTE}"),
            "nu": ours(TISSUE_NU, TISSUE_NOTE),
            "density_t_per_mm3": ours(TISSUE_DENSITY, f"1060 kg/m3; {TISSUE_NOTE}"),
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
    drivers = [
        scene.Driver(JAW_DRIVER, scene.Hinge(
            pivot.tolist(), axis.tolist(), "lab_setting",
            "jaw01 in joints.json: its position, and its local Z axis (left-right)",
        )),
        scene.Driver(CORNER_DRIVER, None, scene.Blend(JAW_DRIVER, ours(
            CORNER_BLEND,
            "alpha: the lip corner anchor moves this fraction of the jaw's motion relative to the head (for the jaw "
            "turning about jaw01's hinge, alpha x its angle; docs/05 section 3, A-35); 0 follows the skull, 1 the "
            "jaw. Provisional"), HEAD_DRIVER)),
        scene.Driver(HEAD_DRIVER, None, None, True),
    ]
    anchors = [scene.Anchor(CORNER_ANCHOR, CORNER_DRIVER,
                            "stands for the mouth corner node of the Ziva model (zTissue4/5): no mesh, "
                            "invisible, no collision; both corners attach to it")]

    # Attachments (docs/05 section 3). The spring base stiffness is T-07's temporary rule, 100 x E x h.
    tet_mesh_data, _ = tetmesh.load(tet_mesh)
    k = PHYSICS_LENGTH_SCALE
    h = tetmesh.quality(tet_mesh_data).median_edge_mm * k
    e_mpa = tissue.material.params["E_mpa"].value
    stiffness = float(f"{STIFFNESS_OVER_EH * e_mpa * h:.3g}")
    stiffness_note = (
        f"provisional (T-07 rule): 100 x E x h = 100 x {e_mpa} MPa x {h:.3f} mm, h = median tet edge "
        f"{h / k:.3f} mm x k {k}; ours, not Ziva's (Ziva: soft attachments of 1e8 N/m^3, which need an "
        "area to become a spring stiffness; docs/05 section 3, T-37)"
    )
    groups = {g.get("attachment"): g for g in attachments_json.get("groups", [])}
    attachments = []
    attachments_report = []
    for maya_name, (name, target, kind, count) in LIP_ATTACHMENTS.items():
        g = groups.get(maya_name)
        if g is None or len(g.get("vertices", [])) != count:
            raise AssetError(
                f"{ATTACHMENTS} should hold {maya_name} with {count} vertices, found "
                f"{'no such group' if g is None else len(g.get('vertices', []))}; re-export it with "
                "tools/lip_attachments.py (T-03)"
            )
        if g.get("source_vertex_count") != tissue_vertex_count:
            raise AssetError(
                f"{maya_name} in {ATTACHMENTS} is for a mesh of {g.get('source_vertex_count')} vertices, the "
                f"lips have {tissue_vertex_count}; the files do not belong together"
            )
        base = ours(None if kind == "hard" else stiffness,
                    "hard: the vertices join the target, no stiffness" if kind == "hard" else stiffness_note)
        weights = [[int(v), float(w)] for v, w in g["vertices"]]
        attachments.append(scene.Attachment(name, tissue.name, target, kind, base, weights))
        attachments_report.append({
            "name": name, "maya_attachment": maya_name, "label": g.get("label", ""), "to": target,
            "kind": kind, "vertices": len(weights),
            "defaulted_weights": len(g.get("defaulted_vertices", [])),
            "stiffness_n_per_mm": base.value, "source": "ours" if kind == "spring" else "lip_attachments.json",
        })

    skin_file = _need(export / SKIN)
    skin = json.loads(skin_file.read_text(encoding="utf-8"))
    names = list(skin["influences"])
    missing = [n for n in names if n not in joints]
    if missing:
        raise AssetError(f"joints.json lacks {len(missing)} landmarks named in {SKIN} (e.g. {missing[0]}); re-export")
    rest = coords.to_mm_zup([joints[n]["world_position"] for n in names], mm_per_scene_unit)
    try:
        converted = skin_module.convert(skin, joints, mm_per_scene_unit)
    except skin_module.SkinConvertError as e:
        raise AssetError(str(e)) from e
    converted["source"] = {"file": SKIN, "sha256": _sha256(skin_file)}
    skin_target = out / "landmarks" / SKIN_MM
    skin_target.write_text(json.dumps(converted, separators=(",", ":"), ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
    landmarks = scene.Landmarks(
        names, rest.tolist(), scene.FileRef(f"landmarks/{SKIN_MM}", _sha256(skin_target)),
        "weights index the lips' vertices; the file is the export converted to mm, Z up, column vectors "
        "(asrp-skin/1: names, rest_world, bind_pre, geom, weights; the raw export's sha256 is in 'source'); "
        "read it with asrp_core.skinning.load",
    )

    # Folder and file names plus hashes, not the paths as typed: the same export imported on
    # another machine must give the same scene.json.
    tet_origin = f"{tet_mesh.name} (content sha256 {tet_meta.get('content_sha256', '')})"
    model = scene.Scene(
        origin={
            "asset": report_json.get("scene", ""),
            "export": f"{export.resolve().name}: tools/maya_export.py, Maya {report_json.get('maya', '?')}, "
                      f"mesh_report.json sha256 {_sha256(export / 'mesh_report.json')}",
            "tool": f"asrp import-asset {__version__}",
            "notes": f"OBJ files are scene coordinates (ADR-18): scaled and turned, no world matrix applied. "
                     f"meshes/lips_tet.json is a byte copy of {tet_origin}. "
                     f"Attachments are from {ATTACHMENTS} (sha256 {attachments_sha}; the vertex sets are "
                     "confirmed, A-33)",
        },
        units=scene.Units(
            scene.Param(mm_per_scene_unit, "ours", mm_note),
            ours(PHYSICS_LENGTH_SCALE,
                 "meeting conclusion (ADR-31): skull width 216.6 mm becomes about 145 mm, a real person; "
                 "not Ziva's scale"),
            coords.AXES,
        ),
        soft_tissues=[tissue],
        bones=bones,
        drivers=drivers,
        attachments=attachments,
        anchors=anchors,
        simplifications=list(SIMPLIFICATIONS),
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
            "physics_length_scale": PHYSICS_LENGTH_SCALE,
        },
        "attachments_file": {"name": ATTACHMENTS, "sha256": attachments_sha},
        "attachments": attachments_report,
        "anchors": [{"name": CORNER_ANCHOR, "driver": CORNER_DRIVER, "of": JAW_DRIVER, "factor": CORNER_BLEND}],
        "meshes": meshes_report,
        "landmarks": len(names),
        "drivers": {JAW_DRIVER: {"pivot_mm": pivot.tolist(), "axis": axis.tolist(),
                                 "moves": [b.name for b in bones if b.driver == JAW_DRIVER]},
                    HEAD_DRIVER: {"absent_means_rest": True,
                                  "moves": [b.name for b in bones if b.driver == HEAD_DRIVER]}},
        "parameters": [{"where": w, **p} for w, p in scene.parameters(model.to_json())],
        "missing": [*check.warnings, *STILL_MISSING],
        "check": {"errors": check.errors, "warnings": check.warnings},
    }
    (out / "import_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8", newline="\n")
    return ImportResult(scene_path, report, check)
