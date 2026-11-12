"""ASRP Blender add-on: UI only. All solver work runs in asrp_core, as a subprocess."""

import atexit
import json
import subprocess
import textwrap
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from .session import ENDED, RunSession, core_command, core_project, register_exit_handler

STATUS_ICONS = {"ok": "CHECKMARK", "warn": "INFO", "error": "ERROR"}
PLAYBACK_FORMAT = "asrp-playback/1"
MM_TO_BLENDER = 0.001  # bundles are in mm; Blender's default unit is 1 m
DOMAIN_COLORS = {"tissue": (0.8, 0.25, 0.2, 1.0), "jaw": (0.9, 0.88, 0.8, 1.0)}


def run_core(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(core_command(*args), capture_output=True, text=True, timeout=120)


class ASRP_OT_check_backend(bpy.types.Operator):
    bl_idname = "asrp.check_backend"
    bl_label = "Check backend"
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
    bl_label = "Load result"
    bl_description = "Load a solved run (playback.json + playback.pc2) and play it on the timeline"
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    version: bpy.props.StringProperty(default="physics")  # "physics" or, when the run has a landmark layer, "final"

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        # Through the results list, like every other loaded result: so it is shown alone and hidden when a new run starts.
        folder = Path(bpy.path.abspath(self.directory))
        try:
            manifest = read_manifest(folder)
            playback_cache(manifest, self.version)  # refuses a version the run does not have
            [index] = add_run_folder(context, folder, versions=[self.version])
        except (ValueError, KeyError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        entry = context.scene.asrp_results[index]
        self.report({"INFO"}, f"loaded {entry.obj.name}: {manifest['frame_count']} frames at {manifest['fps']} fps")
        return {"FINISHED"}




# --- running a scene from the panel, and the list of loaded results -----------------------------------------------------
# The run is `asrp run` as a subprocess (session.py). Nothing here computes: it starts the run, shows what it prints,
# loads the files a finished run wrote, and switches which loaded result is visible.

TICK_S = 0.25
CHECK_KEYS = ("a", "b", "b2", "c", "d")
VERSION_WORDS = {"physics": "physics only", "final": "final shape"}
STATE_WORDS = {
    "running": "Running",
    "complete": "Complete",
    "failed": "Failed. No results were loaded.",
    "cancelled": "Cancelled. No results were loaded.",
    "not_started": "Could not start. No results were loaded.",
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
    if not isinstance(data, dict):  # valid JSON of the wrong shape is as unreadable as broken JSON
        data = None
    _REPORTS[str(path)] = (stamp, data)
    return data


def check_rows(report) -> list[tuple[str, str, str, str]] | None:
    """(key, name, PASS | FAIL | NOT RUN, message) for the five checks, in the order a, b, b2, c, d.
    None if the report is not shaped like a run report (the panel then says the report is unreadable)."""
    if not isinstance(report, dict) or not isinstance(report.get("checks"), dict):
        return None
    checks = report["checks"]
    rows = []
    for key in CHECK_KEYS:
        c = checks.get(key)
        if c is None:
            rows.append((key, key, "NOT RUN", "the report has no entry for this check"))
            continue
        if not isinstance(c, dict) or c.get("passed") not in (True, False, None):
            return None
        verdict = {True: "PASS", False: "FAIL"}.get(c.get("passed"), "NOT RUN")
        rows.append((key, str(c.get("name") or key), verdict, str(c.get("message") or "")))
    return rows


def _mm(value) -> str:
    return f"{value:.3g} mm" if isinstance(value, (int, float)) and not isinstance(value, bool) else "?"


def landmark_summary(report) -> str:
    layer = report.get("landmark_layer") if isinstance(report, dict) else None
    if not layer:
        return "Landmark layer: not recorded in the report"
    if not isinstance(layer, dict):
        return "Landmark layer: the report entry is unreadable"
    if layer.get("applied"):
        moved = layer.get("landmarks_moved")
        return (f"Landmark layer: applied ({moved if isinstance(moved, int) else '?'} landmarks moved, "
                f"largest translation {_mm(layer.get('max_translation_mm'))})")
    return f"Landmark layer: not applied. {layer.get('reason') or ''}".strip()


def hide_object(obj, hidden: bool) -> None:
    """Hidden = disabled in viewports and in render. Shown also undoes a hide in the view layer (the eye icon), so
    that "shown" in the panel is true on screen."""
    obj.hide_viewport = hidden
    obj.hide_render = hidden
    try:
        if hidden:
            obj.select_set(False)
        else:
            obj.hide_set(False)
    except RuntimeError:
        pass  # not in this view layer


def is_live(obj) -> bool:
    """The entry's object exists and is in a collection. The viewport's X (object.delete) only unlinks an object that
    the list still points at, so it stays in bpy.data with no collection: that counts as deleted."""
    return obj is not None and len(obj.users_collection) > 0


def shown_entry(scene):
    """The entry whose object is on screen, or None (nothing shown, or its object was deleted)."""
    results = scene.asrp_results
    return results[scene.asrp_shown] if 0 <= scene.asrp_shown < len(results) and is_live(results[scene.asrp_shown].obj) else None


def show_entry(scene, index: int) -> None:
    """Exactly one loaded result is visible (viewport and render): the entry `index`, or none for -1."""
    results = scene.asrp_results
    if not (0 <= index < len(results)) or not is_live(results[index].obj):
        index = -1
    for i, entry in enumerate(results):
        if is_live(entry.obj):
            hide_object(entry.obj, i != index)
    scene.asrp_shown = index
    if index >= 0:
        scene.render.fps = results[index].fps
        scene.render.fps_base = 1.0
        scene.frame_start = 0
        scene.frame_end = results[index].frames - 1
        try:
            obj = results[index].obj
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
        except (RuntimeError, ReferenceError):
            pass


def add_run_folder(context, folder, show: bool = True, versions=None) -> list[int]:
    """Load a run folder: one entry per version (physics, and final when the run has a landmark layer; `versions`
    picks some). The final version is shown if there is one, else the physics. Raises ValueError if it cannot be loaded;
    then nothing this call added is left behind."""
    folder = Path(folder)
    manifest = read_manifest(folder)
    scene = context.scene
    key = str(folder.resolve())
    if versions is None:
        versions = ["physics"] + (["final"] if "final" in (manifest.get("versions") or {}) else [])
    for version in versions:
        if any(e.run_dir == key and e.version == version and is_live(e.obj) for e in scene.asrp_results):
            raise ValueError(f"{folder.name} ({version}) is already in the list")
    first = len(scene.asrp_results)
    names_before = {o.name for o in bpy.data.objects}
    try:
        for version in versions:
            obj = build_playback_object(context, manifest, folder, version)
            obj.name = f"ASRP {folder.name} {version}"
            entry = scene.asrp_results.add()
            entry.label = f"{folder.name} - {VERSION_WORDS[version]}"
            entry.run_name, entry.run_dir, entry.version, entry.obj = folder.name, key, version, obj
            entry.frames, entry.fps = int(manifest["frame_count"]), int(manifest["fps"])
    except Exception:
        for index in reversed(range(first, len(scene.asrp_results))):  # roll back the entries (and objects) added so far
            remove_entry(scene, index)
        for obj in [o for o in bpy.data.objects if o.name not in names_before]:  # an object built but not yet listed
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise
    added = list(range(first, len(scene.asrp_results)))
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
    try:
        state = SESSION.poll()
        if state == "running":
            redraw()
            return TICK_S
        if state in ENDED and not SESSION.handled:
            SESSION.handled = True
            if state == "complete":  # also when a plausibility check failed: the results are loaded, failed checks shown
                if SESSION.run_dir is None:
                    raise ValueError("the run did not report its folder")
                # After File > Open the results go to the scene that is current now, not to the one the run began in.
                add_run_folder(bpy.context, SESSION.run_dir)
    except Exception as exc:  # noqa: BLE001  a timer that raises is unregistered silently: end in a visible error instead
        SESSION.handled = True
        SESSION.load_error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)
        if SESSION.state == "running":
            SESSION.close()
            SESSION.state, SESSION.error = "failed", SESSION.load_error
    redraw()
    return None


def ensure_timer() -> None:
    # persistent: File > Open / revert must not drop the timer of a run that is still going
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_S, persistent=True)


@persistent
def on_load_post(*_args) -> None:
    """A file was loaded: a run may still be going (or have just ended), so poll it again. The panel's list belongs to
    the new file; the finished run's results are added to the scene that is current then."""
    if SESSION.state == "running" or (SESSION.state in ENDED and not SESSION.handled):
        ensure_timer()


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
    bl_label = "Run"
    bl_description = "Run the scene with the motion (`asrp run`) in the background, then load the result"

    def execute(self, context):
        scene = context.scene
        if SESSION.running:
            self.report({"ERROR"}, "A run is already in progress")
            return {"CANCELLED"}
        scene_file, motion = bpy.path.abspath(scene.asrp_scene_path), bpy.path.abspath(scene.asrp_trajectory_path)
        if not scene.asrp_scene_path or not scene.asrp_trajectory_path:
            self.report({"ERROR"}, "Choose a scene file and a trajectory file first")
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
            if SESSION.state != "not_started":  # the folder could not be made: say so in the panel, not only in a popup
                SESSION.reset()
                SESSION.state, SESSION.error, SESSION.handled = "not_started", f"the run could not be started: {exc}", True
            self.report({"ERROR"}, SESSION.error)
            return {"CANCELLED"}
        ensure_timer()
        return {"FINISHED"}


class ASRP_OT_cancel_run(bpy.types.Operator):
    bl_idname = "asrp.cancel_run"
    bl_label = "Cancel"
    bl_description = "Stop the run; no results are kept"

    def execute(self, context):
        SESSION.cancel()
        return {"FINISHED"}


class ASRP_OT_load_run_folder(bpy.types.Operator):
    bl_idname = "asrp.load_run_folder"
    bl_label = "Load run folder"
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
    bl_label = "Show"
    bl_description = "Show this result and hide the others"

    index: bpy.props.IntProperty()

    def execute(self, context):
        results = context.scene.asrp_results
        if not (0 <= self.index < len(results)) or not is_live(results[self.index].obj):
            self.report({"ERROR"}, "This result's object was deleted. Remove it from the list.")
            return {"CANCELLED"}
        show_entry(context.scene, self.index)
        return {"FINISHED"}


class ASRP_OT_remove_result(bpy.types.Operator):
    bl_idname = "asrp.remove_result"
    bl_label = "Remove"
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
        layout.operator(ASRP_OT_load_playback.bl_idname, text="Load result", icon="IMPORT")
        layout.operator(ASRP_OT_check_backend.bl_idname, text="Check backend", icon="FILE_REFRESH")
        status = context.window_manager.asrp_status
        if not status:
            return
        for check in json.loads(status):
            layout.label(text=f"{check['name']}: {check['detail']}", icon=STATUS_ICONS[check["status"]])


class ASRP_PT_run(bpy.types.Panel):
    bl_label = "Run"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        col = layout.column(align=True)
        col.enabled = not SESSION.running
        col.prop(scene, "asrp_scene_path", text="Scene")
        col.prop(scene, "asrp_trajectory_path", text="Trajectory")
        col.prop(scene, "asrp_runs_dir", text="Runs folder")
        col.prop(scene, "asrp_run_name", text="Name")
        if not scene.asrp_runs_dir:
            layout.label(text="Empty runs folder = the project's runs")
        wrapped(context, layout, "Computes the whole motion, then replays it. Not frame-by-frame.")
        if SESSION.running:
            self.draw_running(layout)
        else:
            layout.operator(ASRP_OT_run.bl_idname, icon="PLAY")
            self.draw_outcome(context, layout)

    def draw_running(self, layout):
        s = SESSION
        text = "Preparing..." if s.total is None and s.frame == 0 else f"Frame {s.frame} / {s.total if s.total is not None else '?'}"
        if hasattr(layout, "progress"):
            layout.progress(factor=(s.frame / s.total) if s.total else 0.0, text=text)
        else:
            layout.label(text=text, icon="TIME")
        layout.label(text=f"{int(s.elapsed)} s elapsed" + (", cancelling..." if s.cancel_requested else ""))
        layout.operator(ASRP_OT_cancel_run.bl_idname, icon="CANCEL")

    def draw_outcome(self, context, layout):
        s = SESSION
        if s.state == "idle":
            return
        ok = s.state == "complete" and not s.load_error
        layout.label(text=STATE_WORDS[s.state] if ok or s.state != "complete" else "Complete, but the results could not be loaded",
                     icon="CHECKMARK" if ok else "ERROR")
        if s.state == "complete" and s.cancel_too_late:
            wrapped(context, layout, "The cancel came too late: the run had already finished. This is a complete result and it is loaded.", "INFO")
        if s.state == "complete" and s.passed is False:
            wrapped(context, layout, "A plausibility check failed (see Checks below). The results are loaded.", "ERROR", alert=True)
        if s.state in ("failed", "not_started"):
            wrapped(context, layout, s.error, "ERROR", alert=True)
        elif s.state == "cancelled":
            wrapped(context, layout, "The run was cancelled. No results were saved.", "ERROR", alert=True)
        if s.load_error:
            wrapped(context, layout, f"The results could not be loaded: {s.load_error}", "ERROR", alert=True)


class ASRP_PT_results(bpy.types.Panel):
    bl_label = "Results"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        shown = scene.asrp_shown if shown_entry(scene) is not None else -1  # a deleted object is not "shown"
        if shown < 0:
            layout.label(text="No result is shown", icon="HIDE_ON")
        for i, entry in enumerate(scene.asrp_results):
            row = layout.row(align=True)
            if not is_live(entry.obj):
                row.alert = True
                row.label(text=f"{entry.label} (object deleted)", icon="ERROR")
            else:
                op = row.operator(ASRP_OT_show_result.bl_idname, text=entry.label, depress=(i == shown),
                                  icon="HIDE_OFF" if i == shown else "HIDE_ON")
                op.index = i
            rm = row.operator(ASRP_OT_remove_result.bl_idname, text="", icon="X")
            rm.index = i
        layout.operator(ASRP_OT_load_run_folder.bl_idname, icon="FILE_FOLDER")


class ASRP_PT_checks(bpy.types.Panel):
    bl_label = "Checks"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        entry = shown_entry(scene)
        if entry is None:
            layout.label(text="No result is shown")
            return
        report = read_report(entry.run_dir)
        layout.label(text=f"Run: {entry.run_name}")
        rows = check_rows(report) if report is not None else None
        if rows is None:
            wrapped(context, layout, "The run report is unreadable (run_report.json is missing or not shaped like a report).", "ERROR", alert=True)
            return
        for key, name, verdict, message in rows:
            fail = verdict == "FAIL"
            box = layout.column(align=True)
            row = box.row()
            row.alert = fail
            row.label(text=f"({key}) {name}: {verdict}", icon={"PASS": "CHECKMARK", "FAIL": "ERROR"}.get(verdict, "REMOVE"))
            if message and (fail or verdict == "NOT RUN" or scene.asrp_show_messages):
                wrapped(context, box, message, alert=fail)
        wrapped(context, layout, landmark_summary(report))
        layout.prop(scene, "asrp_show_messages", text="Show every check's message")


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
    global _exit_handler
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    _exit_handler = register_exit_handler(SESSION)


_exit_handler = None


def unregister():
    global _exit_handler
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    if _exit_handler is not None:
        atexit.unregister(_exit_handler)
        _exit_handler = None
    SESSION.close()
    S = bpy.types.Scene
    for name in ("asrp_show_messages", "asrp_shown", "asrp_results", "asrp_run_name", "asrp_runs_dir",
                 "asrp_trajectory_path", "asrp_scene_path"):
        delattr(S, name)
    del bpy.types.WindowManager.asrp_status
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
