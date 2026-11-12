"""ASRP Blender add-on: UI only. All solver work runs in asrp_core, as a subprocess."""

import json
import subprocess
import textwrap
from pathlib import Path

import bpy

from .session import ENDED, RunSession, core_command, core_project

STATUS_ICONS = {"ok": "CHECKMARK", "warn": "INFO", "error": "ERROR"}
PLAYBACK_FORMAT = "asrp-playback/1"
MM_TO_BLENDER = 0.001  # bundles are in mm; Blender's default unit is 1 m
DOMAIN_COLORS = {"tissue": (0.8, 0.25, 0.2, 1.0), "jaw": (0.9, 0.88, 0.8, 1.0)}


def run_core(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(core_command(*args), capture_output=True, text=True, timeout=120)


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


def playback_cache(manifest: dict, version: str = "physics") -> str:
    """The point cache file of a version. A bundle with a landmark layer lists "physics" and "final" under
    "versions"; one without has only its "cache" (the physics version)."""
    versions = manifest.get("versions")
    if versions is None:
        if version != "physics":
            raise ValueError(f"this result has only the physics version, not {version!r} (no landmark layer in the run)")
        return manifest["cache"]
    if version not in versions:
        raise ValueError(f"this result has the versions {sorted(versions)}, not {version!r}")
    return versions[version]


def build_playback_object(context, manifest: dict, folder: Path, version: str = "physics"):
    cache_file = playback_cache(manifest, version)
    label = f" ({version})" if manifest.get("versions") else ""
    mesh = bpy.data.meshes.new(f"ASRP {Path(manifest['source']['feb']).stem}{label}")
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
    cache.filepath = str(folder / cache_file)
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
    version: bpy.props.StringProperty(default="physics")  # "physics" or, when the run has a landmark layer, "final"

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
        try:
            obj = build_playback_object(context, manifest, folder, self.version)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"loaded {obj.name}: {manifest['frame_count']} frames at {manifest['fps']} fps")
        return {"FINISHED"}




# --- running a scene from the panel, and the list of loaded results -----------------------------------------------------
# The run is `asrp run` as a subprocess (session.py). Nothing here computes: it starts the run, shows what it prints,
# loads the files a finished run wrote, and switches which loaded result is visible.

TICK_S = 0.25
CHECK_KEYS = ("a", "b", "b2", "c", "d")
VERSION_WORDS = {"physics": "只有物理", "final": "最终形状"}
STATE_WORDS = {
    "running": "正在计算",
    "complete": "完成",
    "failed": "失败，没有加载任何结果",
    "cancelled": "已取消，没有加载任何结果",
    "not_started": "没有开始，没有加载任何结果",
}
SESSION = RunSession()
_REPORTS: dict = {}


def read_manifest(folder: Path) -> dict:
    path = Path(folder) / "playback.json"
    if not path.is_file():
        raise ValueError(f"no playback.json in {folder}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != PLAYBACK_FORMAT:
        raise ValueError(f"unsupported bundle format {manifest.get('format')!r}")
    return manifest


def read_report(run_dir) -> dict | None:
    """run_report.json of a run folder (re-read only when the file changed), or None."""
    path = Path(run_dir) / "run_report.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    cached = _REPORTS.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    _REPORTS[str(path)] = (stamp, data)
    return data


def check_rows(report: dict) -> list[tuple[str, str, str, str]]:
    """(key, name, PASS | FAIL | NOT RUN, message) for the five checks, in the order a, b, b2, c, d."""
    checks = report.get("checks") or {}
    rows = []
    for key in CHECK_KEYS:
        c = checks.get(key)
        if c is None:
            rows.append((key, key, "NOT RUN", "the report has no entry for this check"))
            continue
        verdict = {True: "PASS", False: "FAIL"}.get(c.get("passed"), "NOT RUN")
        rows.append((key, c.get("name", key), verdict, c.get("message", "")))
    return rows


def landmark_summary(report: dict) -> str:
    layer = report.get("landmark_layer")
    if not layer:
        return "landmark 层：报告里没有记录"
    if layer.get("applied"):
        return (f"landmark 层：已叠加（移动了 {layer.get('landmarks_moved')} 个 landmark，"
                f"最大平移 {layer.get('max_translation_mm', 0):.3g} mm）")
    return f"landmark 层：没有叠加。{layer.get('reason', '')}"


def hide_object(obj, hidden: bool) -> None:
    obj.hide_viewport = hidden
    obj.hide_render = hidden
    if hidden:
        try:
            obj.select_set(False)
        except RuntimeError:
            pass  # not selectable anyway


def show_entry(scene, index: int) -> None:
    """Exactly one loaded result is visible (viewport and render): the entry `index`, or none for -1."""
    results = scene.asrp_results
    if not (0 <= index < len(results)) or results[index].obj is None:
        index = -1
    for i, entry in enumerate(results):
        if entry.obj is not None:
            hide_object(entry.obj, i != index)
    scene.asrp_shown = index
    if index >= 0:
        scene.render.fps = results[index].fps
        scene.render.fps_base = 1.0
        scene.frame_start = 0
        scene.frame_end = results[index].frames - 1


def add_run_folder(context, folder, show: bool = True) -> list[int]:
    """Load a run folder: one entry per version (physics, and final when the run has a landmark layer).
    The final version is shown if there is one, else the physics. Raises ValueError if it cannot be loaded."""
    folder = Path(folder)
    manifest = read_manifest(folder)
    scene = context.scene
    key = str(folder.resolve())
    if any(e.run_dir == key and e.obj is not None for e in scene.asrp_results):
        raise ValueError(f"{folder.name} is already in the list")
    versions = ["physics"] + (["final"] if "final" in (manifest.get("versions") or {}) else [])
    added = []
    for version in versions:
        obj = build_playback_object(context, manifest, folder, version)
        obj.name = f"ASRP {folder.name} {version}"
        entry = scene.asrp_results.add()
        entry.label = f"{folder.name} · {VERSION_WORDS[version]}"
        entry.run_name, entry.run_dir, entry.version, entry.obj = folder.name, key, version, obj
        entry.frames, entry.fps = int(manifest["frame_count"]), int(manifest["fps"])
        added.append(len(scene.asrp_results) - 1)
    show_entry(scene, added[-1] if show else scene.asrp_shown)
    return added


def remove_entry(scene, index: int) -> None:
    entry = scene.asrp_results[index]
    obj = entry.obj
    if obj is not None:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    shown = scene.asrp_shown
    scene.asrp_results.remove(index)
    scene.asrp_shown = -1 if shown == index else shown - 1 if shown > index else shown


def redraw() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except AttributeError:
        pass  # no window (background mode)


def tick():
    """The timer callback: take in what the run printed; when it has ended, load its results once.
    Returns the seconds until the next call, or None to stop the timer."""
    state = SESSION.poll()
    if state == "running":
        redraw()
        return TICK_S
    if state in ENDED and not SESSION.handled:
        SESSION.handled = True
        if state == "complete":  # also when a plausibility check failed: the results are loaded and the failed checks shown
            try:
                if SESSION.run_dir is None:
                    raise ValueError("the run did not report its folder")
                add_run_folder(bpy.context, SESSION.run_dir)
            except (ValueError, KeyError, OSError) as exc:
                SESSION.load_error = str(exc)
        redraw()
    return None


def ensure_timer() -> None:
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_S)


class ASRP_Result(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    run_name: bpy.props.StringProperty()
    run_dir: bpy.props.StringProperty()
    version: bpy.props.StringProperty()
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    frames: bpy.props.IntProperty()
    fps: bpy.props.IntProperty()


class ASRP_OT_run(bpy.types.Operator):
    bl_idname = "asrp.run"
    bl_label = "运行"
    bl_description = "Run the scene with the motion (`asrp run`) in the background, then load the result"

    def execute(self, context):
        scene = context.scene
        if SESSION.running:
            self.report({"ERROR"}, "已经有一次运行在进行")
            return {"CANCELLED"}
        scene_file, motion = bpy.path.abspath(scene.asrp_scene_path), bpy.path.abspath(scene.asrp_trajectory_path)
        if not scene.asrp_scene_path or not scene.asrp_trajectory_path:
            self.report({"ERROR"}, "请先选好场景文件和运动文件")
            return {"CANCELLED"}
        runs_dir = bpy.path.abspath(scene.asrp_runs_dir) if scene.asrp_runs_dir else ""
        if not runs_dir:
            project = core_project()
            if project is None:
                self.report({"ERROR"}, "asrp project not found; set ASRP_PROJECT or choose a runs folder")
                return {"CANCELLED"}
            runs_dir = str(project / "runs")
        # A new run: no older result may stay on screen as if it were this run's (docs/04 section 9).
        show_entry(scene, -1)
        try:
            Path(runs_dir).mkdir(parents=True, exist_ok=True)
            SESSION.start(scene_file, motion, runs_dir, scene.asrp_run_name.strip())
        except (RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ensure_timer()
        return {"FINISHED"}


class ASRP_OT_cancel_run(bpy.types.Operator):
    bl_idname = "asrp.cancel_run"
    bl_label = "取消"
    bl_description = "Stop the run; no results are kept"

    def execute(self, context):
        SESSION.cancel()
        return {"FINISHED"}


class ASRP_OT_load_run_folder(bpy.types.Operator):
    bl_idname = "asrp.load_run_folder"
    bl_label = "加载运行文件夹"
    bl_description = "Add an earlier run folder (playback.json, run_report.json) to the list of results"

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            added = add_run_folder(context, Path(bpy.path.abspath(self.directory)))
        except (ValueError, KeyError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"loaded {len(added)} result(s)")
        return {"FINISHED"}


class ASRP_OT_show_result(bpy.types.Operator):
    bl_idname = "asrp.show_result"
    bl_label = "显示"
    bl_description = "Show this result and hide the others"

    index: bpy.props.IntProperty()

    def execute(self, context):
        results = context.scene.asrp_results
        if not (0 <= self.index < len(results)) or results[self.index].obj is None:
            self.report({"ERROR"}, "这个结果的物体已经被删除，请从列表里移除")
            return {"CANCELLED"}
        show_entry(context.scene, self.index)
        return {"FINISHED"}


class ASRP_OT_remove_result(bpy.types.Operator):
    bl_idname = "asrp.remove_result"
    bl_label = "移除"
    bl_description = "Remove this result from the list and delete its object"

    index: bpy.props.IntProperty()

    def execute(self, context):
        if not (0 <= self.index < len(context.scene.asrp_results)):
            return {"CANCELLED"}
        remove_entry(context.scene, self.index)
        return {"FINISHED"}


def wrapped(context, layout, text: str, icon: str = "NONE", alert: bool = False) -> None:
    """A label that wraps to the width of the side bar."""
    width = max(16, int(getattr(context.region, "width", 300) / 8))
    col = layout.column(align=True)
    col.alert = alert
    for i, line in enumerate(textwrap.wrap(text, width=width) or [""]):
        col.label(text=line, icon=icon if i == 0 else "BLANK1")


class ASRP_PT_main(bpy.types.Panel):
    bl_label = "ASRP"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"

    def draw(self, context):
        layout = self.layout
        layout.operator(ASRP_OT_load_playback.bl_idname, text="加载结果", icon="IMPORT")
        layout.operator(ASRP_OT_check_backend.bl_idname, text="检查后端", icon="FILE_REFRESH")
        status = context.window_manager.asrp_status
        if not status:
            return
        for check in json.loads(status):
            layout.label(text=f"{check['name']}: {check['detail']}", icon=STATUS_ICONS[check["status"]])


class ASRP_PT_run(bpy.types.Panel):
    bl_label = "运行"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        col = layout.column(align=True)
        col.enabled = not SESSION.running
        col.prop(scene, "asrp_scene_path", text="场景")
        col.prop(scene, "asrp_trajectory_path", text="运动")
        col.prop(scene, "asrp_runs_dir", text="运行文件夹")
        col.prop(scene, "asrp_run_name", text="名称")
        if not scene.asrp_runs_dir:
            layout.label(text="运行文件夹留空 = 项目里的 runs")
        wrapped(context, layout, "这里会先算完整个动作，再回放；不是逐帧互动的。")
        if SESSION.running:
            self.draw_running(layout)
        else:
            layout.operator(ASRP_OT_run.bl_idname, icon="PLAY")
            self.draw_outcome(context, layout)

    def draw_running(self, layout):
        s = SESSION
        text = "正在准备…" if s.total is None and s.frame == 0 else f"第 {s.frame} / {s.total if s.total is not None else '?'} 帧"
        if hasattr(layout, "progress"):
            layout.progress(factor=(s.frame / s.total) if s.total else 0.0, text=text)
        else:
            layout.label(text=text, icon="TIME")
        layout.label(text=f"已用 {int(s.elapsed)} 秒" + ("；正在取消…" if s.cancel_requested else ""))
        layout.operator(ASRP_OT_cancel_run.bl_idname, icon="CANCEL")

    def draw_outcome(self, context, layout):
        s = SESSION
        if s.state == "idle":
            return
        layout.label(text=STATE_WORDS[s.state], icon="CHECKMARK" if s.state == "complete" else "ERROR")
        if s.state == "complete" and s.passed is False:
            wrapped(context, layout, "有合理性检查没有通过（见下面的“检查”）；结果已加载。", "ERROR", alert=True)
        if s.state in ("failed", "not_started"):
            wrapped(context, layout, s.error, "ERROR", alert=True)
        elif s.state == "cancelled":
            wrapped(context, layout, "运行被取消了；没有保存任何结果。", "ERROR", alert=True)
        if s.load_error:
            wrapped(context, layout, f"结果无法加载：{s.load_error}", "ERROR", alert=True)


class ASRP_PT_results(bpy.types.Panel):
    bl_label = "结果"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        shown = scene.asrp_shown
        if not (0 <= shown < len(scene.asrp_results)):
            layout.label(text="当前没有显示结果", icon="HIDE_ON")
        for i, entry in enumerate(scene.asrp_results):
            row = layout.row(align=True)
            if entry.obj is None:
                row.alert = True
                row.label(text=f"{entry.label}（物体已被删除）", icon="ERROR")
            else:
                op = row.operator(ASRP_OT_show_result.bl_idname, text=entry.label, depress=(i == shown),
                                  icon="HIDE_OFF" if i == shown else "HIDE_ON")
                op.index = i
            rm = row.operator(ASRP_OT_remove_result.bl_idname, text="", icon="X")
            rm.index = i
        layout.operator(ASRP_OT_load_run_folder.bl_idname, icon="FILE_FOLDER")


class ASRP_PT_checks(bpy.types.Panel):
    bl_label = "检查"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        shown = scene.asrp_shown
        if not (0 <= shown < len(scene.asrp_results)):
            layout.label(text="没有显示的结果")
            return
        entry = scene.asrp_results[shown]
        report = read_report(entry.run_dir)
        layout.label(text=f"运行：{entry.run_name}")
        if report is None:
            wrapped(context, layout, "这个运行文件夹里没有可读的 run_report.json。", "ERROR", alert=True)
            return
        for key, name, verdict, message in check_rows(report):
            fail = verdict == "FAIL"
            box = layout.column(align=True)
            row = box.row()
            row.alert = fail
            row.label(text=f"({key}) {name}: {verdict}", icon={"PASS": "CHECKMARK", "FAIL": "ERROR"}.get(verdict, "REMOVE"))
            if message and (fail or verdict == "NOT RUN" or scene.asrp_show_messages):
                wrapped(context, box, message, alert=fail)
        wrapped(context, layout, landmark_summary(report))
        layout.prop(scene, "asrp_show_messages", text="显示每项检查的说明")


classes = (ASRP_OT_check_backend, ASRP_OT_load_playback, ASRP_Result, ASRP_OT_run, ASRP_OT_cancel_run,
           ASRP_OT_load_run_folder, ASRP_OT_show_result, ASRP_OT_remove_result,
           ASRP_PT_main, ASRP_PT_run, ASRP_PT_results, ASRP_PT_checks)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # WindowManager properties live only for the session; the scene's own (paths, loaded results) are saved with it.
    bpy.types.WindowManager.asrp_status = bpy.props.StringProperty()
    S = bpy.types.Scene
    S.asrp_scene_path = bpy.props.StringProperty(subtype="FILE_PATH", description="scene.json")
    S.asrp_trajectory_path = bpy.props.StringProperty(subtype="FILE_PATH", description="trajectory.json")
    S.asrp_runs_dir = bpy.props.StringProperty(subtype="DIR_PATH", description="Where run folders go; empty means <project>/runs")
    S.asrp_run_name = bpy.props.StringProperty(description="Optional name for the run folder")
    S.asrp_results = bpy.props.CollectionProperty(type=ASRP_Result)
    S.asrp_shown = bpy.props.IntProperty(default=-1, description="Index of the result on screen, -1 for none")
    S.asrp_show_messages = bpy.props.BoolProperty(description="Show the message of every check, not only of failed ones")


def unregister():
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    SESSION.close()
    S = bpy.types.Scene
    for name in ("asrp_show_messages", "asrp_shown", "asrp_results", "asrp_run_name", "asrp_runs_dir",
                 "asrp_trajectory_path", "asrp_scene_path"):
        delattr(S, name)
    del bpy.types.WindowManager.asrp_status
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
