"""ASRP Blender add-on: UI only. All solver work runs in asrp_core, as a subprocess."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import bpy

STATUS_ICONS = {"ok": "CHECKMARK", "warn": "INFO", "error": "ERROR"}
PLAYBACK_FORMAT = "asrp-playback/1"
MM_TO_BLENDER = 0.001  # bundles are in mm; Blender's default unit is 1 m
DOMAIN_COLORS = {"tissue": (0.8, 0.25, 0.2, 1.0), "jaw": (0.9, 0.88, 0.8, 1.0)}


def core_project() -> Path | None:
    """The asrp project whose venv runs the core: $ASRP_PROJECT, else the repo this add-on lives in."""
    override = os.environ.get("ASRP_PROJECT")
    if override:
        return Path(override)
    repo = Path(__file__).resolve().parents[2]
    return repo if (repo / "pyproject.toml").is_file() else None


def run_core(*args: str) -> subprocess.CompletedProcess:
    project = core_project()
    uv = shutil.which("uv")
    if project is None:
        raise RuntimeError("asrp project not found; set ASRP_PROJECT")
    if uv is None:
        raise RuntimeError("uv not found on PATH")
    return subprocess.run(
        [uv, "run", "--project", str(project), "asrp", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class ASRP_OT_check_backend(bpy.types.Operator):
    bl_idname = "asrp.check_backend"
    bl_label = "Check Backend"
    bl_description = "Run `asrp doctor` in the solver core and show what it finds"

    def execute(self, context):
        try:
            proc = run_core("doctor", "--json")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not proc.stdout.strip():
            self.report({"ERROR"}, f"asrp doctor printed nothing: {proc.stderr.strip()}")
            return {"CANCELLED"}
        context.window_manager.asrp_status = proc.stdout
        checks = json.loads(proc.stdout)
        problems = [c["name"] for c in checks if c["status"] != "ok"]
        self.report({"WARNING" if problems else "INFO"}, f"backend checks not ok: {problems}" if problems else "backend ready")
        return {"FINISHED"}


def build_playback_object(context, manifest: dict, folder: Path):
    mesh = bpy.data.meshes.new(f"ASRP {Path(manifest['source']['feb']).stem}")
    # from_pydata keeps vertex order, which the point cache relies on.
    mesh.from_pydata(manifest["vertices"], [], manifest["faces"])
    for name in manifest["materials"]:
        mat = bpy.data.materials.get(f"ASRP {name}") or bpy.data.materials.new(f"ASRP {name}")
        mat.diffuse_color = DOMAIN_COLORS.get(name, (0.6, 0.6, 0.6, 1.0))
        mesh.materials.append(mat)
    mesh.polygons.foreach_set("material_index", manifest["face_materials"])
    mesh.update()

    obj = bpy.data.objects.new(mesh.name, mesh)
    context.collection.objects.link(obj)
    obj.scale = (MM_TO_BLENDER,) * 3  # mesh and cache stay in mm; only display is scaled

    cache = obj.modifiers.new("ASRP result", "MESH_CACHE")
    cache.cache_format = "PC2"
    cache.filepath = str(folder / manifest["cache"])
    cache.deform_mode = "OVERWRITE"
    cache.time_mode = "FRAME"
    cache.play_mode = "SCENE"
    cache.frame_start = 0.0  # scene frame 0 = solver frame 0
    cache.frame_scale = 1.0
    cache.forward_axis = "POS_Y"  # solver and Blender are both Z-up
    cache.up_axis = "POS_Z"

    scene = context.scene
    scene.render.fps = int(manifest["fps"])
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_end = manifest["frame_count"] - 1

    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


class ASRP_OT_load_playback(bpy.types.Operator):
    bl_idname = "asrp.load_playback"
    bl_label = "Load Result"
    bl_description = "Load a solved run (playback.json + playback.pc2) and play it on the timeline"
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = Path(bpy.path.abspath(self.directory))
        manifest_path = folder / "playback.json"
        if not manifest_path.is_file():
            self.report({"ERROR"}, f"no playback.json in {folder}")
            return {"CANCELLED"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != PLAYBACK_FORMAT:
            self.report({"ERROR"}, f"unsupported bundle format {manifest.get('format')!r}")
            return {"CANCELLED"}
        obj = build_playback_object(context, manifest, folder)
        self.report({"INFO"}, f"loaded {obj.name}: {manifest['frame_count']} frames at {manifest['fps']} fps")
        return {"FINISHED"}


class ASRP_PT_main(bpy.types.Panel):
    bl_label = "ASRP"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"

    def draw(self, context):
        layout = self.layout
        layout.operator(ASRP_OT_load_playback.bl_idname, icon="IMPORT")
        layout.operator(ASRP_OT_check_backend.bl_idname, icon="FILE_REFRESH")
        status = context.window_manager.asrp_status
        if not status:
            return
        for check in json.loads(status):
            layout.label(text=f"{check['name']}: {check['detail']}", icon=STATUS_ICONS[check["status"]])


classes = (ASRP_OT_check_backend, ASRP_OT_load_playback, ASRP_PT_main)


def register():
    # WindowManager properties live only for the session; nothing is saved into the .blend.
    bpy.types.WindowManager.asrp_status = bpy.props.StringProperty()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.asrp_status
