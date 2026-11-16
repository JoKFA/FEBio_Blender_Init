"""The three-step flow of the panel: Open asset, pick a motion, Run, and the result plays on the same five objects.

Still no computation (ADR-03): the asset is made by `asrp import-asset`, the list of motions by `asrp list-motions`,
the result by `asrp run`. This module reads the files those commands wrote and puts them on Blender objects:
- Open asset: builds one mesh object per mesh of the imported scene (the soft tissue and the bones), from the OBJ
  files in the scene folder (mm, Z up: the same numbers the solver reads);
- a finished run: the lips object gets a Mesh Cache modifier on the run's point cache (the layer asked for), each bone
  object gets one keyframe per frame from the run folder's trajectory.json (the transform of the driver it follows,
  as written in the file, nothing derived); the timeline gets the motion's frame count and fps.
Objects keep their identity: a second run replaces the modifier and the keyframes, never the objects.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from .session import NO_PROJECT, core_command, core_project

MM_TO_BLENDER = 0.001  # the meshes stay in mm; only the objects' scale shows them in metres
ASSET_PREFIX = "ASRP "
LANDMARKS_NAME = "ASRP landmarks"  # the sixth object of Open asset: not one of the five (asrp_asset_objects does not list it)
LANDMARK_RADIUS_MM = 0.8  # each landmark is a small octahedron of this radius (1.6 mm across) around its rest position
HIGHLIGHT_ATTR = "ASRP highlight"  # the colour attribute an attachment row puts on the lips
HIGHLIGHT_ON = (1.0, 0.85, 0.0, 1.0)
HIGHLIGHT_OFF = (0.55, 0.55, 0.55, 1.0)
SOURCE_PHRASE = {"lab_setting": "measured in Ziva", "ours": "our value", "ziva_default": "Ziva default"}
ROLE_KEY = "asrp_role"  # custom property on each of the five objects
LAYER_WORDS = {"physics": "Physics only", "final": "Final shape"}
TISSUE_SETTINGS = "lab"  # Open asset imports with Ziva's measured material values (the T-34 report used them)
IMPORT_TIMEOUT_S = 900  # the first import after installing may have to build the Python environment
# After Open asset every 3D view looks at the asset from the front and a little to the right and above (the asset's
# face looks along +Y), from this many times the asset's radius: the head then fills most of the view.
VIEW_FROM = (0.55, 1.0, 0.25)
VIEW_DISTANCE_OVER_RADIUS = 2.6


def export_folder() -> Path:
    """The lab export the asset is imported from: $ASRP_EXPORT, else data/lab_export of the project."""
    override = os.environ.get("ASRP_EXPORT")
    if override:
        return Path(override)
    project = core_project()
    if project is None:
        raise ValueError(NO_PROJECT)
    return project / "data" / "lab_export"


def runs_folder() -> Path:
    """Where run folders go: $ASRP_RUNS_DIR, else the runs folder of the project."""
    override = os.environ.get("ASRP_RUNS_DIR")
    if override:
        return Path(override)
    project = core_project()
    if project is None:
        raise ValueError(NO_PROJECT)
    return project / "runs"


def scenes_folder() -> Path:
    return runs_folder() / "_asset"


def run_core_quiet(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(core_command(*args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, stdin=subprocess.DEVNULL, **kw)


def last_error(proc: subprocess.CompletedProcess) -> str:
    """The text a failed command printed for the researcher: its ERROR lines, else the last line it printed."""
    lines = [x.strip() for x in (proc.stdout + "\n" + proc.stderr).splitlines() if x.strip()]
    errors = [x[len("ERROR"):].strip() for x in lines if x.startswith("ERROR")]
    return " ".join(errors) if errors else (lines[-1] if lines else f"the command ended with exit code {proc.returncode} and printed nothing")


# --- the motion list ----------------------------------------------------------------------------------------------------


def read_motions(export: Path) -> list[dict]:
    """The motions of an export folder, from `asrp list-motions` (one JSON object per line). Raises ValueError."""
    proc = run_core_quiet("list-motions", str(export))
    if proc.returncode != 0:
        raise ValueError(f"The list of motions could not be read: {last_error(proc)}")
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            out.append(json.loads(line))
    if not out:
        raise ValueError(f"No motion files were found in {export / 'trajectories'}")
    return out


def fill_motions(scene, motions: list[dict]) -> None:
    scene.asrp_motions.clear()
    for m in motions:
        item = scene.asrp_motions.add()
        item.file = m["file"]
        item.title = str(m.get("title") or m["file"])
        item.error = str(m.get("error") or "")
        item.frames = int(m.get("frames") or 0)
        item.fps = float(m.get("fps") or 0.0)
        item.source_tag = str(m.get("source_tag") or "")
        item.has_landmarks = bool(m.get("landmarks"))
    first = next((i for i, m in enumerate(scene.asrp_motions) if not m.error), -1)
    scene.asrp_motion_index = first


SOURCE_WORDS = {"lab_setting": "lab motion", "ours": "test motion", "ziva_default": "Ziva default", "unstated": "source not stated"}


def motion_label(item) -> str:
    """The first line of a motion in the list: its title (the file name when the file has none)."""
    return f"{item.file} (cannot be used)" if item.error else item.title or item.file


def motion_details(item) -> str:
    """The second, smaller line: "47 frames, 30 fps, lab motion"."""
    return f"{item.frames} frames, {item.fps:g} fps, {SOURCE_WORDS.get(item.source_tag, item.source_tag)}"


def picked_motion(scene):
    index = scene.asrp_motion_index
    return scene.asrp_motions[index] if 0 <= index < len(scene.asrp_motions) else None


# --- the five objects ----------------------------------------------------------------------------------------------------


def read_obj(path: Path) -> tuple[list, list]:
    """Vertices and faces of an OBJ as the solver reads it (asrp_core.asset.coords.read_obj): 0-based vertex lists,
    no texture or normal indices, file order."""
    vertices, faces = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                vertices.append([float(c) for c in line.split()[1:4]])
            elif line.startswith("f "):
                faces.append([int(c.split("/")[0]) - 1 for c in line.split()[1:]])
    return vertices, faces


def read_scene_json(scene_json: Path) -> dict:
    try:
        data = json.loads(Path(scene_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {scene_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{scene_json} is not a scene description")
    return data


def asset_meshes(data: dict) -> list[tuple[str, str, str]]:
    """(role, mesh file relative to the scene folder, kind) for every mesh of the scene: its soft tissues, then its bones."""
    out = [(t["name"], t["mesh"]["path"], "tissue") for t in data.get("soft_tissues", [])]
    out += [(b["name"], b["mesh"]["path"], "bone") for b in data.get("bones", [])]
    return out


def material_line(data: dict) -> str:
    """"Material: 12 kPa, 0.4 (measured in Ziva)", read from the imported scene.json, not written here."""
    tissues = data.get("soft_tissues") or [{}]
    params = (tissues[0].get("material") or {}) if isinstance(tissues[0], dict) else {}
    try:
        e, nu = params["E_mpa"], params["nu"]
        kpa = float(e["value"]) * 1000.0
        where = {"lab_setting": "measured in Ziva", "ours": "our own values", "ziva_default": "Ziva's defaults"}.get(e.get("source"), "source not stated")
        return f"Material: {kpa:g} kPa, {float(nu['value']):g} ({where})"
    except (KeyError, TypeError, ValueError):
        return "Material: not readable from the scene file"


def relative_to_project(folder) -> str:
    """A folder as a path relative to the project folder, with forward slashes ("runs/_asset/<stamp>"); the whole path when
    the folder is not inside the project."""
    folder = Path(folder)
    project = core_project()
    try:
        return folder.resolve().relative_to(project.resolve()).as_posix() if project is not None else folder.as_posix()
    except ValueError:
        return folder.as_posix()


def units_line(data: dict) -> str:
    """"Units: mm (1 scene unit = 0.962 mm)", read from scene.json."""
    try:
        return f"Units: mm (1 scene unit = {float(data['units']['mm_per_scene_unit']['value']):g} mm)"
    except (KeyError, TypeError, ValueError):
        return "Units: not readable from the scene file"


def report_lines(report_path: Path) -> list[str]:
    """What the import wrote about itself (import_report.json), as short lines for the panel."""
    try:
        r = json.loads(Path(report_path).read_text(encoding="utf-8"))
        meshes = r["meshes"]
        lips = next((m for m in meshes if m.get("role") == "soft tissue"), None)
        problems = r["check"]
        out = [f"Imported: {len(meshes)} meshes, {int(r['landmarks'])} landmarks"]
        if lips is not None:
            out.append(f"{str(lips['name']).capitalize()}: {int(lips['vertices'])} vertices")
        out.append(f"Problems found: {len(problems['errors'])} errors, {len(problems['warnings'])} warnings")
        return out
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return ["The import report could not be read"]


def source_phrase(source) -> str:
    return SOURCE_PHRASE.get(source, "source not stated")


def read_tet_summary(path: Path) -> tuple:
    """(number of tets, kind) of a tet mesh file; the kind is its "kind" field, "fine" when it has none."""
    try:
        tet = json.loads(Path(path).read_text(encoding="utf-8"))
        kind = tet.get("kind")
        return len(tet["tets"]), kind if isinstance(kind, str) and kind else "fine"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, "unreadable"


def setup_rows(scene_json: Path, data: dict) -> dict:
    """The Physics setup section, read from scene.json (and the tet mesh file it names): one entry per soft tissue, bone and
    attachment, as the sentences the panel shows. The wording comes from the scene's own fields, not from names."""
    base = Path(scene_json).parent
    attachments = data.get("attachments") or []
    used = {a.get("from") for a in attachments} | {a.get("to") for a in attachments}
    tissues, bones, atts = [], [], []
    for t in data.get("soft_tissues", []):
        tets, kind = read_tet_summary(base / t["tet_mesh"]["path"])
        m = t["material"]
        e, nu, rho = m["E_mpa"], m["nu"], m["density_t_per_mm3"]
        numbers = [f"{float(e['value']) * 1000:g} kPa", f"nu {float(nu['value']):g}", f"{float(rho['value']) * 1e12:g} kg/m3"]
        sources = [p.get("source") for p in (e, nu, rho)]
        if len(set(sources)) == 1:
            material = f"{', '.join(numbers)} ({source_phrase(sources[0])})"
        else:
            material = ", ".join(f"{n} ({source_phrase(x)})" for n, x in zip(numbers, sources))
        tissues.append({"name": t["name"], "line": f"{t['name']}: {'?' if tets is None else tets} tets, {kind} mesh",
                        "material": f"{m.get('model', 'material')}: {material}"})
    for b in data.get("bones", []):
        does = "fixed" if b.get("motion") == "fixed" else f"follows {b.get('driver')}"
        if b["name"] not in used:
            does = f"display only ({does})"  # no attachment of the scene touches it
        bones.append({"name": b["name"], "line": f"{b['name']}: {does}"})
    for a in attachments:
        n = len(a.get("weights") or [])
        if a.get("kind") == "hard":
            how = "hard"
        else:
            k = a.get("stiffness") or {}
            how = f"{a.get('kind')} {float(k['value']):g} N/mm ({source_phrase(k.get('source'))})" if k.get("value") is not None else str(a.get("kind"))
        atts.append({"name": a["name"], "line": f"{a['from']} to {a['to']}: {n} vertices, {how}"})
    return {"tissues": tissues, "bones": bones, "attachments": atts}


def make_setup(data_path: Path, data: dict) -> str:
    try:
        return json.dumps(setup_rows(data_path, data))
    except (KeyError, TypeError, ValueError) as exc:
        return json.dumps({"error": f"The physics setup could not be read from scene.json ({type(exc).__name__}: {exc})"})


def create_landmarks(context, data: dict):
    """One small octahedron per lip landmark, centred on its rest position (mm, from scene.json: nothing is computed here), in
    one object with the same scale as the five. None when the scene has no landmarks."""
    pts = (data.get("landmarks") or {}).get("rest_positions_mm") or []
    if not pts:
        return None
    r = LANDMARK_RADIUS_MM
    corners = ((r, 0, 0), (-r, 0, 0), (0, r, 0), (0, -r, 0), (0, 0, r), (0, 0, -r))
    faces = ((0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5))
    vertices, polygons = [], []
    for x, y, z in pts:
        base = len(vertices)
        vertices += [(x + cx, y + cy, z + cz) for cx, cy, cz in corners]
        polygons += [tuple(base + i for i in f) for f in faces]
    mesh = bpy.data.meshes.new(LANDMARKS_NAME)
    mesh.from_pydata(vertices, [], polygons)
    mat = bpy.data.materials.get(LANDMARKS_NAME) or bpy.data.materials.new(LANDMARKS_NAME)
    mat.diffuse_color = (1.0, 0.9, 0.1, 1.0)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(LANDMARKS_NAME, mesh)
    obj[ROLE_KEY] = "landmarks"
    context.collection.objects.link(obj)
    obj.scale = (MM_TO_BLENDER,) * 3
    obj.hide_select = True  # a click in the viewport picks the lips, not a dot
    return obj


def sync_landmarks(scene) -> None:
    """The dots show the rest positions: visible when "Show landmarks" is on and no result is on the asset."""
    obj = scene.asrp_asset_landmarks
    if not is_live(obj):
        return
    hidden = (not scene.asrp_show_landmarks) or bool(scene.asrp_asset_run)
    obj.hide_viewport = obj.hide_render = hidden


def remove_landmarks(scene) -> None:
    obj = scene.asrp_asset_landmarks
    if obj is not None:
        remove_objects([obj])
    scene.asrp_asset_landmarks = None


def files_problem(scene) -> str | None:
    """A plain sentence when the scene folder or the run folder this .blend points to is gone, else None."""
    sc, run = scene.asrp_asset_scene, scene.asrp_asset_run
    if sc and not Path(sc).is_file():
        return f"The scene files of this asset are gone ({Path(sc).parent}). Press Open asset again."
    if run and not (Path(run) / "playback.json").is_file():
        return f"The files of the last result are gone ({run}). Run the motion again, or press Open asset again."
    return None


# --- the highlight of the Physics setup section -----------------------------------------------------------------------------

_SAVED_SHADING: dict = {}  # (window index, area index) -> (shading type, colour type) before the highlight
_SAVED_ACTIVE: dict = {}  # mesh name -> the colour attribute that was active before the highlight (or None)


def view3d_spaces(context):
    for wi, window in enumerate(windows(context)):
        for ai, area in enumerate(window.screen.areas):
            if area.type == "VIEW_3D":
                yield (wi, ai), area.spaces[0]


def select_part(context, obj) -> None:
    """Select this object and make it active (and nothing else)."""
    for other in context.view_layer.objects:
        if other.select_get():
            other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def attachment_entry(scene, name: str) -> dict:
    data = read_scene_json(Path(scene.asrp_asset_scene))
    entry = next((a for a in data.get("attachments", []) if a.get("name") == name), None)
    if entry is None:
        raise ValueError(f"The scene has no attachment {name!r}")
    return entry


def clear_highlight(context) -> None:
    """Put the display back as it was: the colour attribute removed, the previous active colour attribute and the viewport's
    colour type restored. Nothing else of the scene is touched."""
    scene = context.scene
    for item in scene.asrp_asset_objects:
        mesh = item.obj.data if is_live(item.obj) else None
        if mesh is not None and HIGHLIGHT_ATTR in mesh.color_attributes:
            mesh.color_attributes.remove(mesh.color_attributes[HIGHLIGHT_ATTR])
            prev = _SAVED_ACTIVE.pop(mesh.name, None)
            if prev and prev in mesh.color_attributes:
                mesh.color_attributes.active_color = mesh.color_attributes[prev]
    for key, space in view3d_spaces(context):
        saved = _SAVED_SHADING.get(key)
        space.shading.type, space.shading.color_type = saved if saved else (space.shading.type, "MATERIAL")
    _SAVED_SHADING.clear()
    scene.asrp_highlight = ""


def highlight_attachment(context, name: str) -> int:
    """Colour the vertices of an attachment on the object it comes from (the lips) and show vertex colours in the 3D views.
    Returns the number of vertices coloured. The result on the asset (cache, keys, frame) is not touched."""
    scene = context.scene
    entry = attachment_entry(scene, name)
    obj = asset_objects(scene).get(entry["from"])
    if obj is None:
        raise ValueError(f"The attachment starts on {entry['from']!r}, which is not an object of the asset")
    clear_highlight(context)
    mesh = obj.data
    vertices = {int(w[0]) for w in entry.get("weights", [])}
    if not vertices or max(vertices) >= len(mesh.vertices):
        raise ValueError(f"The attachment {name!r} has no vertices on the {entry['from']} object. Press Open asset again.")
    active = mesh.color_attributes.active_color
    _SAVED_ACTIVE[mesh.name] = active.name if active is not None else None
    attr = mesh.color_attributes.new(HIGHLIGHT_ATTR, "FLOAT_COLOR", "POINT")
    colors = []
    for i in range(len(mesh.vertices)):
        colors += HIGHLIGHT_ON if i in vertices else HIGHLIGHT_OFF
    attr.data.foreach_set("color", colors)
    mesh.color_attributes.active_color = attr
    for key, space in view3d_spaces(context):
        _SAVED_SHADING[key] = (space.shading.type, space.shading.color_type)
        space.shading.type, space.shading.color_type = "SOLID", "VERTEX"
    scene.asrp_highlight = name
    return len(vertices)


def run_setup_check(scene) -> str:
    """`asrp check scene.json` in plain English: the number of problems, then each message on its own line."""
    proc = run_core_quiet("check", scene.asrp_asset_scene)
    errors = [x[len("ERROR"):].strip() for x in proc.stdout.splitlines() if x.startswith("ERROR")]
    warnings = [x[len("WARNING"):].strip() for x in proc.stdout.splitlines() if x.startswith("WARNING")]
    if proc.returncode not in (0, 1) or not any(x.startswith("check ") for x in proc.stdout.splitlines()):
        raise ValueError(f"The check could not be run: {last_error(proc)}")
    head = "No problems found." if not errors and not warnings else f"{len(errors)} errors, {len(warnings)} warnings."
    return "\n".join([f"Setup check: {head}", *[f"Error: {m}" for m in errors], *[f"Warning: {m}" for m in warnings]])


def material(kind: str):
    name = "ASRP " + ("lips" if kind == "tissue" else "bone")
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (0.8, 0.25, 0.2, 1.0) if kind == "tissue" else (0.9, 0.88, 0.8, 1.0)
    return mat


def create_objects(context, scene_json: Path) -> dict:
    """One mesh object per mesh of the scene, in the collection of the context; returns {role: object}."""
    scene_json = Path(scene_json)
    data = read_scene_json(scene_json)
    made: dict = {}
    try:
        for role, rel, kind in asset_meshes(data):
            vertices, faces = read_obj(scene_json.parent / rel)
            mesh = bpy.data.meshes.new(f"{ASSET_PREFIX}{role}")
            mesh.from_pydata(vertices, [], faces)  # keeps the vertex order the point cache relies on
            mesh.materials.append(material(kind))
            mesh.update()
            obj = bpy.data.objects.new(f"{ASSET_PREFIX}{role}", mesh)
            obj[ROLE_KEY] = role
            context.collection.objects.link(obj)
            obj.scale = (MM_TO_BLENDER,) * 3
            made[role] = obj
    except Exception:
        remove_objects(list(made.values()))
        raise
    return made


def remove_objects(objects) -> None:
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def register_objects(scene, made: dict, scene_json: Path) -> None:
    scene.asrp_asset_objects.clear()
    for role, obj in made.items():
        item = scene.asrp_asset_objects.add()
        item.role, item.obj = role, obj
    scene.asrp_asset_scene = str(scene_json)
    scene.asrp_asset_run = ""
    scene.asrp_asset_layer = ""


def is_live(obj) -> bool:
    return obj is not None and len(obj.users_collection) > 0


def asset_objects(scene) -> dict:
    """{role: object} of the five objects Open asset made; ValueError when there are none or one was deleted."""
    items = list(scene.asrp_asset_objects)
    if not items:
        raise ValueError("No asset is open. Press Open asset first.")
    gone = [i.role for i in items if not is_live(i.obj)]
    if gone:
        raise ValueError(f"The asset object(s) {', '.join(gone)} were deleted. Press Open asset again.")
    return {i.role: i.obj for i in items}


def open_asset(context) -> dict:
    """Step 1: import the lab export into a new scene folder (`asrp import-asset`), read the motion list
    (`asrp list-motions`), build the objects. Replaces the objects of an asset opened before. Raises ValueError."""
    scene = context.scene
    export = export_folder()
    if not export.is_dir():
        raise ValueError(f"The export folder {export} does not exist")
    out = scenes_folder() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = run_core_quiet("import-asset", str(export), str(out), "--tissue-settings", TISSUE_SETTINGS, timeout=IMPORT_TIMEOUT_S)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"The asset could not be imported: {exc}") from exc
    if proc.returncode != 0:
        raise ValueError(f"The asset could not be imported: {last_error(proc)}")
    scene_json = out / "scene.json"
    motions = read_motions(export)
    data = read_scene_json(scene_json)
    made = create_objects(context, scene_json)
    try:
        landmarks = create_landmarks(context, data)
    except Exception:
        remove_objects(list(made.values()))
        raise
    if scene.asrp_highlight:
        clear_highlight(context)
    for item in list(scene.asrp_asset_objects):  # the objects of an asset opened before
        if is_live(item.obj):
            remove_objects([item.obj])
    remove_landmarks(scene)
    register_objects(scene, made, scene_json)
    scene.asrp_asset_landmarks = landmarks
    scene.asrp_asset_material = material_line(data)
    scene.asrp_asset_units = units_line(data)
    scene.asrp_asset_report = "\n".join(report_lines(out / "import_report.json"))
    scene.asrp_asset_setup = make_setup(scene_json, data)
    scene.asrp_setup_check = ""
    sync_landmarks(scene)
    fill_motions(scene, motions)
    for other in context.selected_objects:
        other.select_set(False)
    scene.asrp_asset_hidden = ", ".join(hide_what_encloses(context, made))
    frame_views(context, made)
    return made


# --- making the opened asset visible ----------------------------------------------------------------------------------------
#
# The asset is shown at its real size (a head, about a quarter of a metre). Blender's own start-up scene has a 2 m cube
# at the origin, so a freshly opened asset sits INSIDE that cube and the researcher sees a cube and nothing else
# (seen in the windowed walk-through, 2026-11-15). Open asset therefore hides whatever encloses the asset (hidden, not
# deleted: the eye icon in the outliner shows it again) and points the 3D views at the asset.


def world_box(obj) -> tuple[Vector, Vector]:
    """The lowest and highest corner of an object's bounding box in world coordinates."""
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (Vector(min(c[i] for c in corners) for i in range(3)), Vector(max(c[i] for c in corners) for i in range(3)))


def asset_box(objects) -> tuple[Vector, Vector]:
    boxes = [world_box(o) for o in objects]
    return (Vector(min(b[0][i] for b in boxes) for i in range(3)), Vector(max(b[1][i] for b in boxes) for i in range(3)))


def hide_what_encloses(context, made: dict) -> list[str]:
    """Hide every visible mesh object that is not the asset's and whose bounding box holds the whole asset: the asset
    would be inside it and could not be seen. Returns the names of the objects hidden."""
    context.view_layer.update()  # the new objects' world matrices
    low, high = asset_box(made.values())
    ours = {o.session_uid for o in made.values()}
    hidden = []
    for obj in context.view_layer.objects:
        if obj.type != "MESH" or obj.session_uid in ours or obj.hide_get():
            continue
        a, b = world_box(obj)
        if all(a[i] <= low[i] and high[i] <= b[i] for i in range(3)):
            obj.hide_set(True)
            hidden.append(obj.name)
    return hidden


def frame_views(context, made: dict) -> int:
    """Point every 3D view of every window at the asset. Returns how many views were set (none in a Blender without a
    window, where there is nothing to look at)."""
    context.view_layer.update()
    low, high = asset_box(made.values())
    centre, radius = (low + high) / 2, (high - low).length / 2
    count = 0
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            view = area.spaces[0].region_3d
            if view.view_perspective == "CAMERA":  # looking through the scene camera: that camera is not on the asset
                view.view_perspective = "PERSP"
            view.view_location = centre
            view.view_distance = VIEW_DISTANCE_OVER_RADIUS * radius
            view.view_rotation = Vector(VIEW_FROM).normalized().to_track_quat("Z", "Y")
            area.tag_redraw()
            count += 1
    return count


# --- putting a finished run on the objects --------------------------------------------------------------------------------


def clear_motion(obj) -> None:
    if obj.animation_data is not None:
        obj.animation_data_clear()
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.scale = (MM_TO_BLENDER,) * 3


def clear_result(scene) -> None:
    """The asset back at rest: no point cache on the lips, no keyframes on the bones. Done when a new run starts, so
    the previous result does not stay on screen as if it were this run's."""
    for item in scene.asrp_asset_objects:
        obj = item.obj
        if not is_live(obj):
            continue
        for mod in [m for m in obj.modifiers if m.name == "ASRP result"]:
            obj.modifiers.remove(mod)
        clear_motion(obj)
    scene.asrp_asset_run = ""
    scene.asrp_asset_layer = ""
    sync_landmarks(scene)


def set_cache(obj, cache_file: Path) -> None:
    for mod in [m for m in obj.modifiers if m.name == "ASRP result"]:
        obj.modifiers.remove(mod)
    cache = obj.modifiers.new("ASRP result", "MESH_CACHE")
    cache.cache_format = "PC2"
    cache.filepath = str(cache_file)
    cache.deform_mode = "OVERWRITE"
    cache.time_mode = "FRAME"
    cache.play_mode = "SCENE"
    cache.frame_start = 0.0  # scene frame 0 = solver frame 0
    cache.frame_scale = 1.0
    cache.forward_axis = "POS_Y"  # solver and Blender are both Z-up
    cache.up_axis = "POS_Z"


def default_layer(manifest: dict) -> str:
    """Final shape when the run produced one (the motion had a landmark layer), else Physics only."""
    return "final" if "final" in (manifest.get("versions") or {}) else "physics"


def lips_object(scene, run_dir: Path):
    """The object of the soft tissue the run's point cache belongs to (the run folder's scene.json names it)."""
    tissues = read_scene_json(Path(run_dir) / "scene.json").get("soft_tissues", [])
    objs = asset_objects(scene)
    if len(tissues) != 1 or tissues[0]["name"] not in objs:
        raise ValueError("The run's soft tissue is not one of the asset's objects. Press Open asset again.")
    return objs[tissues[0]["name"]]


def show_layer(scene, run_dir: Path, layer: str) -> None:
    """Point the lips at the cache of `layer` ("physics" or "final") of the run folder."""
    from . import playback_cache, read_manifest

    manifest = read_manifest(run_dir)
    cache_file = Path(run_dir) / playback_cache(manifest, layer)
    obj = lips_object(scene, run_dir)
    if len(obj.data.vertices) != len(manifest["vertices"]):
        raise ValueError(f"The lips object has {len(obj.data.vertices)} vertices but the run's point cache has "
                         f"{len(manifest['vertices'])}: the run was made from another asset. Press Open asset again.")
    set_cache(obj, cache_file)
    scene.asrp_asset_layer = layer


def key_bone(obj, rows: list) -> None:
    """One keyframe per frame (location, rotation) from the 16-number transforms of the motion file, linear in between."""
    clear_motion(obj)
    edit = bpy.context.preferences.edit
    before = edit.keyframe_new_interpolation_type
    edit.keyframe_new_interpolation_type = "LINEAR"
    try:
        previous = None
        for frame, m in enumerate(rows):
            mat = Matrix(((m[0], m[1], m[2], m[3]), (m[4], m[5], m[6], m[7]), (m[8], m[9], m[10], m[11]), (0.0, 0.0, 0.0, 1.0)))
            quat = mat.to_3x3().to_quaternion()
            if previous is not None:
                quat.make_compatible(previous)  # q and -q are the same turn; keep the keys on one side
            previous = quat
            obj.location = mat.translation * MM_TO_BLENDER
            obj.rotation_quaternion = quat
            obj.keyframe_insert("location", frame=frame)
            obj.keyframe_insert("rotation_quaternion", frame=frame)
    finally:
        edit.keyframe_new_interpolation_type = before


# --- showing the finished result: first frame, the motion's range, the timeline zoomed, playing -------------------------------

PLAY_REQUESTS: list = []  # one entry per play request (what a check without a window can look at): (first frame, last frame, started)
RANGE_AREAS = ("DOPESHEET_EDITOR", "TIMELINE")  # the Timeline is a Dope Sheet mode; both are zoomed to the scene's range


def windows(context) -> list:
    try:
        return list(context.window_manager.windows)
    except AttributeError:
        return []


def zoom_timelines(context) -> int:
    """Zoom every timeline / dope sheet area to the scene's frame range (View All). Returns how many were zoomed."""
    count = 0
    for window in windows(context):
        for area in window.screen.areas:
            if area.type not in RANGE_AREAS:
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            try:
                with context.temp_override(window=window, area=area, region=region):
                    bpy.ops.action.view_all()
                count += 1
            except RuntimeError:
                pass  # this area cannot be zoomed right now; the others still are
    return count


def start_playback(context) -> bool:
    """Start the animation playing (once: a second call does not pause it). False when there is no window to play in."""
    for window in windows(context):
        screen = window.screen
        if screen.is_animation_playing:
            return True
        try:
            with context.temp_override(window=window, screen=screen):
                bpy.ops.screen.animation_play()
            return True
        except RuntimeError:
            continue
    return False


def show_playback(context, frames: int) -> None:
    """After a run: the timeline is on the motion's first frame with the motion's range, the timelines are zoomed to it, and
    playback starts by itself. In a Blender without a window the play request is only recorded."""
    scene = context.scene
    scene.frame_start, scene.frame_end = 0, frames - 1
    scene.frame_current = 0
    zoom_timelines(context)
    started = start_playback(context)
    PLAY_REQUESTS.append((scene.frame_start, scene.frame_end, started))


def apply_result(context, run_dir) -> str:
    """A finished run onto the asset's objects: the lips' point cache (the default layer), the bones' keyframes, the
    timeline. Returns the layer shown. Raises ValueError (nothing is half-applied: the asset is put back at rest)."""
    from . import hide_object, read_manifest, show_entry

    scene, run_dir = context.scene, Path(run_dir)
    objs = asset_objects(scene)
    try:
        manifest = read_manifest(run_dir)
        run_scene = read_scene_json(run_dir / "scene.json")
        traj = json.loads((run_dir / "trajectory.json").read_text(encoding="utf-8"))
        frames = int(manifest["frame_count"])
        if int(traj["frames"]) != frames:
            raise ValueError(f"The run's motion has {traj['frames']} frames but its point cache has {frames}")
        drivers = {d["name"]: d for d in run_scene.get("drivers", [])}
        clear_result(scene)
        for bone in run_scene.get("bones", []):
            obj = objs.get(bone["name"])
            if obj is None:
                raise ValueError(f"The run has a bone {bone['name']!r} that the asset does not have. Press Open asset again.")
            if bone.get("motion") != "prescribed":
                continue  # fixed: stays where it is
            driver = bone["driver"]
            if drivers.get(driver, {}).get("blend") is not None:
                raise ValueError(f"The bone {bone['name']!r} follows the derived driver {driver!r}; the panel plays only the "
                                 "motion file's own drivers")
            rows = traj["drivers"].get(driver)
            if rows is None:
                if drivers.get(driver, {}).get("absent_means_rest"):
                    continue  # the motion leaves this driver out: the bone does not move
                raise ValueError(f"The motion has no transforms for {driver!r}, which the bone {bone['name']!r} follows")
            key_bone(obj, rows)
        layer = default_layer(manifest)
        show_layer(scene, run_dir, layer)
    except Exception:
        clear_result(scene)
        raise
    scene.asrp_asset_run = str(run_dir)
    sync_landmarks(scene)
    render = scene.render
    render.fps, render.fps_base = int(manifest["fps"]), 1.0
    scene.frame_start, scene.frame_end = 0, frames - 1
    scene.frame_set(0)
    show_playback(context, frames)
    show_entry(scene, -1)  # an older result of the results list is not shown with this one
    for obj in objs.values():
        hide_object(obj, False)
    return layer
