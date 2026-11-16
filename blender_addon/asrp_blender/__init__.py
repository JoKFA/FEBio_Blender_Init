"""ASRP Blender add-on: UI only. All solver work runs in asrp_core, as a subprocess."""

import atexit
import json
import subprocess
import textwrap
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import asset, session
from .session import (
    ENDED,
    EXIT_WAIT_S,
    NO_PROJECT,
    RunSession,
    core_command,
    core_project,
    project_problem,
    register_exit_handler,
)

STATUS_ICONS = {"ok": "CHECKMARK", "warn": "INFO", "error": "ERROR"}
PLAYBACK_FORMAT = "asrp-playback/1"
MM_TO_BLENDER = 0.001  # bundles are in mm; Blender's default unit is 1 m
DOMAIN_COLORS = {"tissue": (0.8, 0.25, 0.2, 1.0), "jaw": (0.9, 0.88, 0.8, 1.0)}


# --- the project folder (the preference of this add-on) ----------------------------------------------------------------------
# core_project() (session.py) looks at $ASRP_PROJECT, then at the folder chosen here, then at the repo the add-on lives in.

_SESSION_PROJECT = ""  # a folder chosen while the add-on is not enabled through Blender's add-on list (no preference to write to)


def preferences():
    """This add-on's preferences, or None when the add-on is not in Blender's list of enabled add-ons."""
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


def preference_project() -> str:
    prefs = preferences()
    chosen = prefs.project_dir if prefs is not None else ""
    return bpy.path.abspath(chosen) if chosen else _SESSION_PROJECT


def set_project_preference(folder: str) -> None:
    global _SESSION_PROJECT
    prefs = preferences()
    if prefs is not None:
        prefs.project_dir = folder
    else:
        _SESSION_PROJECT = folder


def save_preferences() -> bool:
    """Write the user preferences to disk so the chosen folder survives a restart of Blender."""
    try:
        bpy.ops.wm.save_userpref()
        return True
    except RuntimeError:
        return False


class ASRP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    project_dir: bpy.props.StringProperty(name="ASRP project folder", subtype="DIR_PATH",
                                          description="The folder ASRP was downloaded into (it holds pyproject.toml and src/asrp_core)")

    def draw(self, context):
        self.layout.prop(self, "project_dir")
        project = core_project()
        if project is None:
            self.layout.label(text="No project folder yet: choose it here or in the ASRP tab (N key).", icon="ERROR")
        else:
            self.layout.label(text=f"In use: {project}", icon="CHECKMARK")


class ASRP_OT_choose_project(bpy.types.Operator):
    bl_idname = "asrp.choose_project"
    bl_label = "Choose project folder"
    bl_description = "Choose the folder ASRP was downloaded into (once). It is remembered after Blender is closed"

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = Path(bpy.path.abspath(self.directory))
        problem = project_problem(folder)
        if problem:
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        set_project_preference(str(folder))
        saved = save_preferences()
        self.report({"INFO"}, f"ASRP project folder: {folder}" + ("" if saved else ". It could not be saved: choose it again after restarting Blender"))
        return {"FINISHED"}


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
            self.report({"ERROR"}, f"The doctor command printed nothing: {proc.stderr.strip()}")
            return {"CANCELLED"}
        context.window_manager.asrp_status = proc.stdout
        checks = json.loads(proc.stdout)
        problems = [c["name"] for c in checks if c["status"] != "ok"]
        self.report({"WARNING" if problems else "INFO"}, f"Backend checks not ok: {problems}" if problems else "Backend ready")
        return {"FINISHED"}


def playback_cache(manifest: dict, version: str = "physics") -> str:
    """The point cache file of a version. A bundle with a landmark layer lists "physics" and "final" under
    "versions"; one without has only its "cache" (the physics version)."""
    versions = manifest.get("versions")
    if versions is None:
        if version != "physics":
            raise ValueError(f"This result has only the physics version, not {version!r} (no landmark layer in the run)")
        return manifest["cache"]
    if version not in versions:
        raise ValueError(f"This result has the versions {sorted(versions)}, not {version!r}")
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
        self.report({"INFO"}, f"Loaded {entry.obj.name}: {manifest['frame_count']} frames at {manifest['fps']} fps")
        return {"FINISHED"}




# --- running a scene from the panel, and the list of loaded results -----------------------------------------------------
# The run is `asrp run` as a subprocess (session.py). Nothing here computes: it starts the run, shows what it prints,
# loads the files a finished run wrote, and switches which loaded result is visible.

TICK_S = 0.25
CHECK_KEYS = ("a", "b", "b2", "c", "d")
VERSION_WORDS = {"physics": "physics only", "final": "final shape"}  # in the stored entry label
VERSION_BUTTONS = {"physics": "Physics only", "final": "Final shape"}  # on the version rows of the Results panel
# Short fixed names for the checks (the report's own names are long and get cut off in the side bar).
CHECK_LABELS = {"a": "Motion completed", "b": "Attachments follow bones", "b2": "Springs follow bodies",
                "c": "Gravity sag", "d": "Tet mesh valid"}
ROLE_WORDS = {"teeth_upper": "upper teeth", "teeth_lower": "lower teeth"}  # the objects as a person says them
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
        raise ValueError(f"No playback.json in {folder}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != PLAYBACK_FORMAT:
        raise ValueError(f"Unsupported bundle format {manifest.get('format')!r}")
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
    for key in (*CHECK_KEYS, *[k for k in checks if k not in CHECK_KEYS]):  # an unknown key is listed after the five
        c = checks.get(key)
        if c is None:
            rows.append((key, key, "NOT RUN", "The report has no entry for this check"))
            continue
        if not isinstance(c, dict) or c.get("passed") not in (True, False, None):
            if key not in CHECK_KEYS:  # an extra entry this panel does not know and cannot read: leave it out
                continue
            return None
        verdict = {True: "PASS", False: "FAIL"}.get(c.get("passed"), "NOT RUN")
        rows.append((key, str(c.get("name") or key), verdict, str(c.get("message") or "")))
    return rows


def check_label(key: str, name: str) -> str:
    """The row text of a check: "(b) Attachments follow bones". An unknown key shows the report's own name."""
    return f"({key}) {CHECK_LABELS.get(key, name)}"


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


SURFACE_KEYS = ("flipped_faces", "edges_shorter_than_half", "edges_longer_than_double")


def _surface_part(report, which=None):
    """(version, surface_health entry) of the version asked for; without one, the final version if the report has it,
    else physics. (None, None) when the report has no usable surface_health (an older run)."""
    health = report.get("surface_health") if isinstance(report, dict) else None
    if not isinstance(health, dict):
        return None, None
    for name in ((which,) if which else ("final", "physics")):
        part = health.get(name)
        last = part.get("last") if isinstance(part, dict) else None
        if isinstance(last, dict) and all(_count(last.get(k)) for k in SURFACE_KEYS):
            return name, part
    return None, None


def surface_line(report, which=None) -> str | None:
    """Reported only (not a check): the display surface at the last frame, of the version `which` (default: the final
    version if the report has one, else physics). None when the report has no usable surface_health (an older run)."""
    name, part = _surface_part(report, which)
    if part is None:
        return None
    last = part["last"]
    return (f"Surface ({name}): {last['flipped_faces']} flipped faces, {last['edges_shorter_than_half']} edges < 0.5x, "
            f"{last['edges_longer_than_double']} edges > 2x")


def worst_surface_line(report, which=None) -> str | None:
    """Reported only: the frame with the most flipped faces (which frame, how many), next to the last frame's line."""
    name, part = _surface_part(report, which)
    worst = part.get("worst") if part is not None else None
    if not (isinstance(worst, dict) and _count(worst.get("frame")) and all(_count(worst.get(k)) for k in SURFACE_KEYS)):
        return None
    return (f"Worst frame ({name}): frame {worst['frame']}, {worst['flipped_faces']} flipped faces, "
            f"{worst['edges_shorter_than_half']} edges < 0.5x, {worst['edges_longer_than_double']} edges > 2x")


ALL_PASS_NOTE = ("All five checks passed. That does not say the surface is fine: the surface lines below are only "
                 "reported, not checked.")


def all_passed(rows) -> bool:
    five = [r for r in rows if r[0] in CHECK_KEYS]
    return len(five) == len(CHECK_KEYS) and all(r[2] == "PASS" for r in five)


def settle_line(report) -> str | None:
    """Reported only: how far the tissue moved in the last frame of the settle. None for a report without it."""
    settled = report.get("settled_shape") if isinstance(report, dict) else None
    step = settled.get("tissue_step_max_mm") if isinstance(settled, dict) else None
    if not isinstance(step, (int, float)) or isinstance(step, bool):
        return None
    return f"Settle: tissue moved {_mm(step)} in the last settle frame"


def not_settled(report) -> bool:
    settled = report.get("settled_shape") if isinstance(report, dict) else None
    return isinstance(settled, dict) and settled.get("tissue_settled") is False


def result_groups(scene) -> list[list[int]]:
    """Entry indexes grouped by run folder, the groups in the order their runs were loaded."""
    groups: dict = {}
    for i, entry in enumerate(scene.asrp_results):
        groups.setdefault(entry.run_dir, []).append(i)
    return list(groups.values())


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


def current_run(scene):
    """(run name, run folder, layer on screen or None) of the result the panels talk about: the one shown from the
    results list, else the one on the asset. None when there is neither."""
    entry = shown_entry(scene)
    if entry is not None:
        return entry.run_name, entry.run_dir, None
    run = scene.asrp_asset_run
    if run and asset_open(scene):
        return Path(run).name, run, scene.asrp_asset_layer or None
    return None


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
    loaded = [v for v in versions if any(e.run_dir == key and e.version == v and is_live(e.obj) for e in scene.asrp_results)]
    versions = [v for v in versions if v not in loaded]  # what is already in the list stays; only the rest is added
    if not versions:
        raise ValueError(f"{folder.name} is already in the list")
    first = len(scene.asrp_results)
    names_before = {o.name for o in bpy.data.objects}
    timeline = (scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end)
    try:
        for version in versions:
            obj = build_playback_object(context, manifest, folder, version)
            obj.name = f"ASRP {folder.name} {version}"
            entry = scene.asrp_results.add()
            entry.label = f"{folder.name} - {VERSION_WORDS[version]}"
            entry.run_name, entry.run_dir, entry.version, entry.obj = folder.name, key, version, obj
            entry.frames, entry.fps = int(manifest["frame_count"]), int(manifest["fps"])
    except Exception:
        scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end = timeline  # the load changed them
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
                    raise ValueError("The run did not report its folder")
                # After File > Open the results go to the scene that is current now, not to the one the run began in.
                if SESSION.target == "asset":
                    asset.apply_result(bpy.context, SESSION.run_dir)  # onto the five objects of Open asset
                else:
                    add_run_folder(bpy.context, SESSION.run_dir)
    except Exception as exc:  # noqa: BLE001  a timer that raises is unregistered silently: end in a visible error instead
        SESSION.handled = True
        SESSION.load_error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, ValueError) else str(exc)
        SESSION.kill_tree()  # whatever went wrong, no process tree stays running untracked (no-op if it has ended)
        if SESSION.state == "running":
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
    asset._SAVED_SHADING.clear()  # the highlight of the file that was open is not this file's
    asset._SAVED_ACTIVE.clear()
    if SESSION.state == "running":
        show_entry(bpy.context.scene, -1)  # the opened file's saved shown result is not this run's
        ensure_timer()
    elif SESSION.state in ENDED and not SESSION.handled:
        ensure_timer()
    elif SESSION.state in ENDED:
        SESSION.reset()  # the outcome of a run in another file is not this file's banner


class ASRP_Result(bpy.types.PropertyGroup):
    label: bpy.props.StringProperty()
    run_name: bpy.props.StringProperty()
    run_dir: bpy.props.StringProperty()
    version: bpy.props.StringProperty()
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    frames: bpy.props.IntProperty()
    fps: bpy.props.IntProperty()


class ASRP_Motion(bpy.types.PropertyGroup):
    """One line of the motion list (what `asrp list-motions` printed)."""
    file: bpy.props.StringProperty()
    title: bpy.props.StringProperty()
    error: bpy.props.StringProperty()
    frames: bpy.props.IntProperty()
    fps: bpy.props.FloatProperty()
    source_tag: bpy.props.StringProperty()
    has_landmarks: bpy.props.BoolProperty()


class ASRP_AssetObject(bpy.types.PropertyGroup):
    """One of the objects Open asset made (role: skull, jaw, ...); the results are put on exactly these."""
    role: bpy.props.StringProperty()
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


def start_run(op, context, scene_file, motion, runs_dir, name: str, target: str):
    """Start `asrp run` in the background; where the finished result goes is `target` ("asset" or "files")."""
    scene = context.scene
    # A new run: no older result may stay on screen as if it were this run's (docs/04 section 9).
    show_entry(scene, -1)
    if target == "asset":
        asset.clear_result(scene)
    try:
        Path(runs_dir).mkdir(parents=True, exist_ok=True)
        SESSION.start(str(scene_file), str(motion), str(runs_dir), name)
    except (RuntimeError, OSError) as exc:
        if SESSION.state != "not_started":  # the folder could not be made: say so in the panel, not only in a popup
            SESSION.reset()
            SESSION.state, SESSION.error, SESSION.handled = "not_started", f"the run could not be started: {exc}", True
        op.report({"ERROR"}, SESSION.error)
        return {"CANCELLED"}
    SESSION.target = target
    ensure_timer()
    return {"FINISHED"}


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
                self.report({"ERROR"}, NO_PROJECT)
                return {"CANCELLED"}
            runs_dir = str(project / "runs")
        return start_run(self, context, scene_file, motion, runs_dir, scene.asrp_run_name.strip(), "files")


class ASRP_OT_open_asset(bpy.types.Operator):
    bl_idname = "asrp.open_asset"
    bl_label = "Open asset"
    bl_description = ("Import the lab export (`asrp import-asset`) and show skull, jaw, upper teeth, lower teeth and lips "
                      "as five objects. The window waits while it imports")

    def execute(self, context):
        if SESSION.running:
            self.report({"ERROR"}, "A run is in progress. Wait for it or cancel it first.")
            return {"CANCELLED"}
        try:
            made = asset.open_asset(context)
            context.scene.asrp_asset_export = str(asset.export_folder())
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        hidden = context.scene.asrp_asset_hidden
        self.report({"INFO"}, f"Opened {len(made)} objects: {', '.join(made)}" + (f"; hid {hidden}" if hidden else ""))
        return {"FINISHED"}


class ASRP_OT_pick_motion(bpy.types.Operator):
    bl_idname = "asrp.pick_motion"
    bl_label = "Motion"
    bl_description = "Use this motion for the next run"

    index: bpy.props.IntProperty()

    def execute(self, context):
        scene = context.scene
        if not (0 <= self.index < len(scene.asrp_motions)) or scene.asrp_motions[self.index].error:
            self.report({"ERROR"}, "This motion file cannot be used")
            return {"CANCELLED"}
        scene.asrp_motion_index = self.index
        return {"FINISHED"}


class ASRP_OT_run_motion(bpy.types.Operator):
    bl_idname = "asrp.run_motion"
    bl_label = "Run"
    bl_description = "Run the picked motion on the opened asset in the background, then play it on the same objects"

    def execute(self, context):
        scene = context.scene
        if SESSION.running:
            self.report({"ERROR"}, "A run is already in progress")
            return {"CANCELLED"}
        try:
            asset.asset_objects(scene)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        problem = asset.files_problem(scene)
        if scene.asrp_asset_scene and not Path(scene.asrp_asset_scene).is_file():
            self.report({"ERROR"}, problem)
            return {"CANCELLED"}
        motion = asset.picked_motion(scene)
        if motion is None or motion.error:
            self.report({"ERROR"}, "Pick a motion first")
            return {"CANCELLED"}
        try:
            runs_dir = asset.runs_folder()
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        motion_file = Path(scene.asrp_asset_export) / "trajectories" / motion.file
        return start_run(self, context, Path(scene.asrp_asset_scene), motion_file, runs_dir, Path(motion.file).stem, "asset")


class ASRP_OT_highlight(bpy.types.Operator):
    bl_idname = "asrp.highlight"
    bl_label = "Highlight"
    bl_description = ("Show this row in the 3D view: a tissue or bone is selected and made active, an attachment colours its "
                      "vertices on the lips. A result on the asset is not touched")

    kind: bpy.props.StringProperty()  # "part" (a tissue or a bone) or "attachment"
    target: bpy.props.StringProperty()  # the object's role, or the attachment's name

    def execute(self, context):
        scene = context.scene
        try:
            if self.kind == "part":
                obj = asset.asset_objects(scene).get(self.target)
                if obj is None:
                    raise ValueError(f"{self.target} is not an object of the asset. Press Open asset again.")
                asset.select_part(context, obj)
            else:
                asset.highlight_attachment(context, self.target)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASRP_OT_clear_highlight(bpy.types.Operator):
    bl_idname = "asrp.clear_highlight"
    bl_label = "Clear highlight"
    bl_description = "Put the 3D view back as it was before an attachment was highlighted"

    def execute(self, context):
        asset.clear_highlight(context)
        return {"FINISHED"}


class ASRP_OT_check_setup(bpy.types.Operator):
    bl_idname = "asrp.check_setup"
    bl_label = "Check setup"
    bl_description = "Run `asrp check` on the asset's scene file and say in plain words what it found"

    def execute(self, context):
        scene = context.scene
        if not asset_open(scene) or not Path(scene.asrp_asset_scene).is_file():
            self.report({"ERROR"}, "Open the asset first")
            return {"CANCELLED"}
        try:
            scene.asrp_setup_check = asset.run_setup_check(scene)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            scene.asrp_setup_check = f"Setup check: could not be run. {exc}"
        return {"FINISHED"}


class ASRP_OT_set_layer(bpy.types.Operator):
    bl_idname = "asrp.set_layer"
    bl_label = "Layer"
    bl_description = "Show this layer of the last run on the lips (the bones do not change)"

    layer: bpy.props.StringProperty()

    def execute(self, context):
        scene = context.scene
        if not scene.asrp_asset_run:
            self.report({"ERROR"}, "There is no result on the asset yet")
            return {"CANCELLED"}
        try:
            asset.show_layer(scene, Path(scene.asrp_asset_run), self.layer)
        except (ValueError, KeyError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASRP_OT_cancel_run(bpy.types.Operator):
    bl_idname = "asrp.cancel_run"
    bl_label = "Cancel"
    bl_description = "Ask the running solver to stop. A cancelled run keeps no results; if the run has already finished, its results are kept"

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
        self.report({"INFO"}, f"Loaded {len(added)} result{'' if len(added) == 1 else 's'}")
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


def wrapped(context, layout, text: str, icon: str = "NONE", alert: bool = False, reserve: int = 0) -> None:
    """A label that wraps to the width of the side bar (`reserve` characters narrower, when a button sits beside it)."""
    width = max(16, int(getattr(context.region, "width", 300) / 8) - reserve)
    col = layout.column(align=True)
    col.alert = alert
    for i, line in enumerate(textwrap.wrap(text, width=width) or [""]):
        col.label(text=line, icon=icon if i == 0 else "BLANK1")


def step_layout(context, layout):
    """Where a step draws: the layout itself, or, while no project folder is known, a greyed-out column under the reason."""
    if core_project() is not None:
        return layout
    wrapped(context, layout, "Choose the project folder first (top of this tab).", "INFO")
    col = layout.column()
    col.enabled = False
    return col


class ASRP_PT_main(bpy.types.Panel):
    bl_label = "ASRP"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"

    def draw(self, context):
        if core_project() is None:  # the one thing to do before anything else
            self.layout.label(text="Choose the ASRP project folder (once)", icon="ERROR")
            self.layout.operator(ASRP_OT_choose_project.bl_idname, icon="FILE_FOLDER")


def asset_open(scene) -> bool:
    try:
        asset.asset_objects(scene)
        return True
    except ValueError:
        return False


def folder_lines(context, layout, label: str, folder) -> None:
    """"Scene files: runs/_asset/<stamp>" (relative to the project folder) and a button that opens that folder."""
    wrapped(context, layout, f"{label}: {asset.relative_to_project(folder)}", "FILE_FOLDER")
    op = layout.operator("wm.path_open", text="Open folder", icon="FILEBROWSER")
    op.filepath = str(folder)


def scene_files_gone(scene) -> bool:
    return bool(scene.asrp_asset_scene) and not Path(scene.asrp_asset_scene).is_file()


class ASRP_PT_asset(bpy.types.Panel):
    bl_label = "1  Open the asset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = step_layout(context, self.layout), context.scene
        wrapped(context, layout, "One asset for both prototypes: skull, jaw, teeth, lips.")
        wrapped(context, layout, "This .blend is the scene. Save it to keep the asset and the last result.")
        row = layout.row()
        row.enabled = not SESSION.running
        row.operator(ASRP_OT_open_asset.bl_idname, icon="IMPORT")
        items = list(scene.asrp_asset_objects)
        if not items:
            layout.label(text="No asset is open")
            return
        if not asset_open(scene):
            wrapped(context, layout, "An asset object was deleted. Press Open asset again.", "ERROR", alert=True)
            return
        problem = asset.files_problem(scene)
        if problem:
            wrapped(context, layout, problem, "ERROR", alert=True)
        wrapped(context, layout, "Open: " + ", ".join(ROLE_WORDS.get(i.role, i.role) for i in items), "CHECKMARK")
        for text in (scene.asrp_asset_units, scene.asrp_asset_material, *scene.asrp_asset_report.splitlines()):
            if text:
                wrapped(context, layout, text)
        if scene.asrp_asset_scene and not scene_files_gone(scene):
            op = layout.operator("wm.path_open", text="Open import report", icon="TEXT")
            op.filepath = str(Path(scene.asrp_asset_scene).parent / "import_report.json")
            folder_lines(context, layout, "Scene files", Path(scene.asrp_asset_scene).parent)
        if is_live(scene.asrp_asset_landmarks):
            layout.prop(scene, "asrp_show_landmarks", text="Show landmarks")
            if scene.asrp_show_landmarks and scene.asrp_asset_run:
                wrapped(context, layout, "Landmarks show the rest positions; hidden while a result plays.", "INFO")
        if scene.asrp_asset_hidden:
            wrapped(context, layout, f"Hidden, because the asset was inside it: {scene.asrp_asset_hidden}. "
                                     "The eye icon in the outliner shows it again.", "HIDE_ON")


def part_row(context, layout, line: str, kind: str, target: str, icon: str = "RESTRICT_SELECT_OFF", extra: str = "") -> None:
    """A row of the Physics setup: the sentence (wrapped), and a small button that highlights it in the 3D view."""
    row = layout.row()
    col = row.column()
    wrapped(context, col, line, reserve=4)
    if extra:
        wrapped(context, col, extra, reserve=4)
    op = row.operator(ASRP_OT_highlight.bl_idname, text="", icon=icon)
    op.kind, op.target = kind, target


class ASRP_PT_setup(bpy.types.Panel):
    bl_label = "Physics setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        if not asset_open(scene):
            layout.label(text="Open the asset first")
            return
        try:
            rows = json.loads(scene.asrp_asset_setup or "{}")
        except ValueError:
            rows = {"error": "The physics setup is not readable. Press Open asset again."}
        if rows.get("error") or not rows:
            wrapped(context, layout, rows.get("error") or "The physics setup is empty. Press Open asset again.", "ERROR", alert=True)
            return
        layout.label(text="Soft tissue")
        for t in rows["tissues"]:
            part_row(context, layout, t["line"], "part", t["name"], extra=t["material"])
        layout.label(text="Bones")
        for b in rows["bones"]:
            part_row(context, layout, b["line"], "part", b["name"])
        layout.label(text="Attachments")
        for a in rows["attachments"]:
            on = scene.asrp_highlight == a["name"]
            part_row(context, layout, a["line"], "attachment", a["name"], icon="COLOR" if on else "VERTEXSEL")
        row = layout.row()
        row.enabled = bool(scene.asrp_highlight)
        row.operator(ASRP_OT_clear_highlight.bl_idname, icon="X")
        row = layout.row()
        row.enabled = not scene_files_gone(scene)
        row.operator(ASRP_OT_check_setup.bl_idname, icon="CHECKMARK")
        for i, line in enumerate(scene.asrp_setup_check.splitlines()):
            wrapped(context, layout, line, alert=line.startswith("Error"), icon="INFO" if i == 0 else "BLANK1")
        wrapped(context, layout, "Read-only in this version. Marking meshes as bone or tissue in Blender comes later.")


class ASRP_PT_motion(bpy.types.Panel):
    bl_label = "2  Choose a motion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = step_layout(context, self.layout), context.scene
        if not asset_open(scene):
            layout.label(text="Open the asset first")
            return
        col = layout.column(align=True)
        col.enabled = not SESSION.running
        for i, item in enumerate(scene.asrp_motions):
            if item.error:
                wrapped(context, col, f"{item.file}: {item.error}", "ERROR", alert=True)
                continue
            op = col.operator(ASRP_OT_pick_motion.bl_idname, text=asset.motion_label(item), depress=(i == scene.asrp_motion_index),
                              icon="CHECKBOX_HLT" if i == scene.asrp_motion_index else "CHECKBOX_DEHLT")
            op.index = i
            small = col.row()
            small.scale_y = 0.7  # the details are a smaller second line under the title
            small.label(text="      " + asset.motion_details(item))


class ASRP_PT_run(bpy.types.Panel):
    bl_label = "3  Run"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = step_layout(context, self.layout), context.scene
        wrapped(context, layout, "Computes the whole motion, then replays it. Not frame-by-frame.")
        if SESSION.running:
            self.draw_running(layout)
        else:
            row = layout.row()
            picked = asset.picked_motion(scene)
            row.enabled = asset_open(scene) and picked is not None and not picked.error and not scene_files_gone(scene)
            row.operator(ASRP_OT_run_motion.bl_idname, icon="PLAY")
            if scene_files_gone(scene):
                wrapped(context, layout, asset.files_problem(scene), "ERROR", alert=True)
            elif not row.enabled:
                layout.label(text="Open the asset and pick a motion first")
            self.draw_outcome(context, layout)
            self.draw_playback(context, layout)

    def draw_running(self, layout):
        s = SESSION
        text = "Preparing..." if s.total is None and s.frame == 0 else f"Frame {s.frame} / {s.total if s.total is not None else '?'}"
        if hasattr(layout, "progress"):
            layout.progress(factor=(s.frame / s.total) if s.total else 0.0, text=text)
        else:
            layout.label(text=text, icon="TIME")
        layout.label(text=f"{int(s.elapsed)} s elapsed" + (". Cancelling..." if s.cancel_requested else ""))
        layout.operator(ASRP_OT_cancel_run.bl_idname, icon="CANCEL")

    def draw_playback(self, context, layout):
        """After a run: Play / Pause, what is playing, and where the run's files are."""
        scene = context.scene
        if SESSION.running or SESSION.load_error or not (scene.asrp_asset_run and asset_open(scene)):
            return
        if asset.files_problem(scene):
            return  # the Asset section says the files are gone
        playing = bool(getattr(context.screen, "is_animation_playing", False))
        layout.operator("screen.animation_play", text="Pause" if playing else "Play", icon="PAUSE" if playing else "PLAY")
        first, last = scene.frame_start, scene.frame_end
        wrapped(context, layout, f"Playing frame {first} to {last}. Space bar pauses." if playing
                else f"Frame {first} to {last} is ready. Space bar plays.")
        folder_lines(context, layout, "Run files", Path(scene.asrp_asset_run))

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


class ASRP_PT_run_files(bpy.types.Panel):
    """Run any scene file with any motion file (typed paths). Not part of the three steps; its result is loaded as new
    objects into the Results list, like Load run folder. A sub-panel of Advanced."""
    bl_label = "Run other files"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_advanced"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout, scene = self.layout, context.scene
        col = layout.column(align=True)
        col.enabled = not SESSION.running
        # Each label on its own line above its field: neither competes with the path for the width of the side bar.
        for label, prop in (("Scene", "asrp_scene_path"), ("Motion (trajectory.json)", "asrp_trajectory_path"),
                            ("Runs folder", "asrp_runs_dir"), ("Run name", "asrp_run_name")):
            col.label(text=label)
            col.prop(scene, prop, text="")
        if not scene.asrp_runs_dir:
            layout.label(text="Empty runs folder = the project's runs")
        row = layout.row()
        row.enabled = not SESSION.running
        row.operator(ASRP_OT_run.bl_idname, icon="PLAY")


class ASRP_PT_results(bpy.types.Panel):
    bl_label = "Results"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"

    def draw(self, context):
        layout, scene = self.layout, context.scene
        shown = scene.asrp_shown if shown_entry(scene) is not None else -1  # a deleted object is not "shown"
        run = Path(scene.asrp_asset_run) if scene.asrp_asset_run and asset_open(scene) else None
        if run is not None and not (run / "playback.json").is_file():
            wrapped(context, layout, f"The files of the result on the asset ({run.name}) are gone. Run the motion again.", "ERROR", alert=True)
        elif run is not None:
            layout.label(text=f"On the asset: {run.name}")
            for layer in ("physics", "final"):
                if layer == "final" and not (run / "playback_final.pc2").is_file():
                    continue  # the run had no landmark layer: there is no final shape
                on = scene.asrp_asset_layer == layer
                op = layout.operator(ASRP_OT_set_layer.bl_idname, text=asset.LAYER_WORDS[layer], depress=on,
                                     icon="HIDE_OFF" if on else "HIDE_ON")
                op.layer = layer
        if shown < 0 and run is None:
            layout.label(text="No result is shown", icon="HIDE_ON")
        for indexes in result_groups(scene):
            layout.label(text=scene.asrp_results[indexes[0]].run_name)  # the run's name once, then its versions
            for i in indexes:
                entry = scene.asrp_results[i]
                word = VERSION_BUTTONS.get(entry.version, entry.version)
                row = layout.row(align=True)
                if not is_live(entry.obj):
                    row.alert = True
                    row.label(text=f"{word} (object deleted)", icon="ERROR")
                else:
                    op = row.operator(ASRP_OT_show_result.bl_idname, text=word, depress=(i == shown),
                                      icon="HIDE_OFF" if i == shown else "HIDE_ON")
                    op.index = i
                rm = row.operator(ASRP_OT_remove_result.bl_idname, text="", icon="X")
                rm.index = i


class ASRP_PT_checks(bpy.types.Panel):
    bl_label = "Checks"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout, scene = self.layout, context.scene
        current = current_run(scene)
        if current is None:
            layout.label(text="No result is shown")
            return
        run_name, run_dir, version = current
        if not Path(run_dir).is_dir():
            wrapped(context, layout, f"The run folder is gone ({run_name}). Run the motion again.", "ERROR", alert=True)
            return
        report = read_report(run_dir)
        layout.label(text=f"Run: {run_name}")
        rows = check_rows(report) if report is not None else None
        if rows is None:
            wrapped(context, layout, "The run report is unreadable (run_report.json is missing or not shaped like a report).", "ERROR", alert=True)
            return
        for key, name, verdict, message in rows:
            fail = verdict == "FAIL"
            box = layout.column(align=True)
            row = box.split(factor=0.72)  # the check on the left, its verdict on the right
            row.alert = fail
            row.label(text=check_label(key, name))
            right = row.row()
            right.alignment = "RIGHT"
            right.label(text=verdict)
            if message and (fail or verdict == "NOT RUN" or scene.asrp_show_messages):
                # With the option on, the report's own (long) check name comes with the message of a passed check.
                text = message if fail or verdict == "NOT RUN" or name == key else f"{name}. {message}"
                wrapped(context, box, text, alert=fail)
        if all_passed(rows):  # a green list must not read as "the surface is fine"
            wrapped(context, layout, ALL_PASS_NOTE, "INFO")
        wrapped(context, layout, landmark_summary(report))
        which = version if version in ("physics", "final") else None  # the layer on the asset's lips; None: final if there is one
        for line in (surface_line(report, which), worst_surface_line(report, which), settle_line(report)):
            if line:
                wrapped(context, layout, line)
        if not_settled(report):
            wrapped(context, layout, "Tissue not settled at the settle frame", "ERROR", alert=True)
        layout.prop(scene, "asrp_show_messages", text="Show every check's message")


class ASRP_PT_advanced(bpy.types.Panel):
    """Everything that is not one of the three steps: the project folder, the backend check, loading a result or a run
    folder that is already on disk, and running other files."""
    bl_label = "Advanced"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ASRP"
    bl_parent_id = "ASRP_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        project = core_project()
        wrapped(context, layout, f"Project folder: {project}" if project is not None else "No project folder chosen yet",
                "FILE_FOLDER" if project is not None else "ERROR")
        layout.operator(ASRP_OT_choose_project.bl_idname, text="Change project folder" if project is not None else "Choose project folder",
                        icon="FILE_FOLDER")
        layout.operator(ASRP_OT_check_backend.bl_idname, text="Check backend", icon="FILE_REFRESH")
        status = context.window_manager.asrp_status
        if status:
            for check in json.loads(status):
                layout.label(text=f"{check['name']}: {check['detail']}", icon=STATUS_ICONS[check["status"]])
        layout.operator(ASRP_OT_load_playback.bl_idname, text="Load result", icon="IMPORT")
        layout.operator(ASRP_OT_load_run_folder.bl_idname, icon="FILE_FOLDER")


classes = (ASRP_Preferences, ASRP_OT_choose_project, ASRP_OT_check_backend, ASRP_OT_load_playback, ASRP_Result, ASRP_Motion,
           ASRP_AssetObject, ASRP_OT_run, ASRP_OT_open_asset, ASRP_OT_pick_motion, ASRP_OT_run_motion, ASRP_OT_set_layer,
           ASRP_OT_cancel_run, ASRP_OT_load_run_folder, ASRP_OT_show_result, ASRP_OT_remove_result,
           ASRP_OT_highlight, ASRP_OT_clear_highlight, ASRP_OT_check_setup,
           ASRP_PT_main, ASRP_PT_asset, ASRP_PT_setup, ASRP_PT_motion, ASRP_PT_run, ASRP_PT_results, ASRP_PT_checks, ASRP_PT_advanced,
           ASRP_PT_run_files)


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
    S.asrp_asset_objects = bpy.props.CollectionProperty(type=ASRP_AssetObject)
    S.asrp_asset_scene = bpy.props.StringProperty(description="scene.json that Open asset imported")
    S.asrp_asset_export = bpy.props.StringProperty(description="The export folder the asset and the motions come from")
    S.asrp_asset_hidden = bpy.props.StringProperty(description="Objects Open asset hid because the asset was inside them")
    S.asrp_asset_run = bpy.props.StringProperty(description="The run folder whose result is on the asset's objects")
    S.asrp_asset_layer = bpy.props.StringProperty(description="physics or final: the layer on the asset's lips")
    S.asrp_asset_landmarks = bpy.props.PointerProperty(type=bpy.types.Object, description="The landmark dots (the sixth object of Open asset)")
    S.asrp_asset_units = bpy.props.StringProperty(description="The units line of the imported scene")
    S.asrp_asset_report = bpy.props.StringProperty(description="Lines of the import report, one per line")
    S.asrp_asset_setup = bpy.props.StringProperty(description="The Physics setup rows of the imported scene (JSON)")
    S.asrp_setup_check = bpy.props.StringProperty(description="The outcome of the last Check setup")
    S.asrp_highlight = bpy.props.StringProperty(description="The attachment whose vertices are coloured on the lips, if any")
    S.asrp_show_landmarks = bpy.props.BoolProperty(default=True, name="Show landmarks", update=lambda self, _ctx: asset.sync_landmarks(self),
                                                   description="Show the landmarks' rest positions as dots (hidden while a result is on the asset)")
    S.asrp_asset_material = bpy.props.StringProperty(description="The material line of the imported scene, for the Asset section")
    S.asrp_motions = bpy.props.CollectionProperty(type=ASRP_Motion)
    S.asrp_motion_index = bpy.props.IntProperty(default=-1, description="The motion picked for the next run, -1 for none")
    global _exit_handler
    session.preference_project = preference_project
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
    # Blender's exit calls unregister() for an installed add-on before Python shuts down, so the run is stopped here:
    # cancel file, wait at most EXIT_WAIT_S for the core to stop FEBio, then kill the tree. atexit is only the fallback.
    SESSION.close(wait=EXIT_WAIT_S)
    if _exit_handler is not None:
        atexit.unregister(_exit_handler)
        _exit_handler = None
    S = bpy.types.Scene
    session.preference_project = lambda: ""
    for name in ("asrp_show_landmarks", "asrp_highlight", "asrp_setup_check", "asrp_asset_setup", "asrp_asset_report", "asrp_asset_units",
                 "asrp_asset_landmarks", "asrp_asset_material", "asrp_motion_index", "asrp_motions", "asrp_asset_layer", "asrp_asset_run", "asrp_asset_export", "asrp_asset_hidden",
                 "asrp_asset_scene", "asrp_asset_objects", "asrp_show_messages", "asrp_shown", "asrp_results", "asrp_run_name", "asrp_runs_dir",
                 "asrp_trajectory_path", "asrp_scene_path"):
        delattr(S, name)
    del bpy.types.WindowManager.asrp_status
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
