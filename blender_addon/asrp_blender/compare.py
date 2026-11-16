"""Compare with Ziva: the panel side of `asrp compare` (T-11). Still no computation (ADR-03).

`asrp compare <run folder> <Ziva export folder> --out <run folder>/compare` is a subprocess, started and followed like a run
(session.CompareSession). What it wrote is only shown here:
- compare_report.json: the numbers of the layer on display (last frame's mean / 95 % / max, the worst frame), read as they are;
- ziva_playback/: Ziva's lips as a playback package, loaded as a second object "Ziva lips" with the add-on's own playback loader;
- heatmap_physics.f32 / heatmap_final.f32 (format in heatmap.json): per frame and vertex, the distance in mm to Ziva's vertex.
  The current frame's block is picked and each value is mapped to a colour on a fixed scale (0 mm blue, 5 mm or more red).
The Ziva reference folder is the lab's data, outside the project: it is chosen once and kept in the add-on preferences only.
"""

import array
import json
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import asset
from .session import CompareSession

ZIVA_NAME = "Ziva lips"
ZIVA_ROLE = "ziva_lips"
ZIVA_COLOR = (0.45, 0.55, 0.78, 1.0)  # grey-blue: ours is red
HEAT_ATTR = "ASRP difference"
HEAT_MAX_MM = 5.0
SCALE_LINE = "Blue 0 mm, red 5 mm or more"
REPORT_NOTE = "Reported only. There is no pass line."
SESSION = CompareSession()
_REPORTS: dict = {}
_HEAT: dict = {}  # (file, modified) -> (values, vertex count, frames)


def out_folder(scene) -> Path | None:
    return Path(scene.asrp_asset_run) / "compare" if scene.asrp_asset_run else None


def read_report(scene) -> dict | None:
    out = out_folder(scene)
    path = out / "compare_report.json" if out is not None else None
    try:
        stamp = path.stat().st_mtime
    except (OSError, AttributeError):
        return None
    cached = _REPORTS.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    data = data if isinstance(data, dict) and isinstance(data.get("layers"), dict) else None
    _REPORTS[str(path)] = (stamp, data)
    return data


def layer_name(scene) -> str:
    return scene.asrp_asset_layer or "physics"


def summary_lines(scene) -> list[str]:
    """The section's numbers for the layer on display, read from compare_report.json: the last frame's mean / 95 % / max
    distance and the worst frame. [] when there is no report; one line saying so when the layer has no numbers."""
    report = read_report(scene)
    if report is None:
        return []
    layer = layer_name(scene)
    block = report["layers"].get(layer)
    word = asset.LAYER_WORDS.get(layer, layer)
    try:
        if not isinstance(block, dict) or block.get("available") is False:
            return [f"{word}: no numbers. {(block or {}).get('reason', 'The report has no such layer.')}"]
        last = int(report["frames"]["last"])
        return [f"{word}, frame {last}:", f"mean {block['mean_mm'][last]:.2f} mm, 95% {block['p95_mm'][last]:.2f} mm, "
                f"max {block['max_mm'][last]:.2f} mm",
                f"Worst frame: {block['worst']['mean_mm']['frame']} (mean {block['worst']['mean_mm']['value']:.2f} mm)"]
    except (KeyError, TypeError, ValueError, IndexError):
        return [f"{word}: the comparison report could not be read."]


def ready(scene) -> bool:
    return read_report(scene) is not None


# --- Ziva's lips ----------------------------------------------------------------------------------------------------------


def ziva_live(scene) -> bool:
    return asset.is_live(scene.asrp_ziva_object)


def remove_ziva(scene) -> None:
    obj = scene.asrp_ziva_object
    if obj is not None:
        asset.remove_objects([obj])
    scene.asrp_ziva_object = None


def sync_ziva(context) -> None:
    """Show or hide Ziva's lips; the object follows the layer on display (playback.pc2 for physics, playback_final.pc2 for final)."""
    from . import build_playback_object, playback_cache, read_manifest

    scene = context.scene
    package = out_folder(scene) / "ziva_playback" if scene.asrp_asset_run else None
    want = bool(scene.asrp_show_ziva and package is not None and ready(scene) and (package / "playback.json").is_file())
    if not want:
        if ziva_live(scene):
            scene.asrp_ziva_object.hide_viewport = scene.asrp_ziva_object.hide_render = True
        return
    manifest = read_manifest(package)
    obj = scene.asrp_ziva_object
    if not asset.is_live(obj):
        timeline = (scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end)
        selected, active = [o for o in context.view_layer.objects if o.select_get()], context.view_layer.objects.active
        obj = build_playback_object(context, manifest, package, "physics")
        obj.name = ZIVA_NAME
        obj.data.name = ZIVA_NAME
        obj[asset.ROLE_KEY] = ZIVA_ROLE
        mat = bpy.data.materials.get(ZIVA_NAME) or bpy.data.materials.new(ZIVA_NAME)
        mat.diffuse_color = ZIVA_COLOR
        for i in range(len(obj.data.materials)):
            obj.data.materials[i] = mat
        scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end = timeline  # the same timeline as ours
        for other in context.view_layer.objects:
            other.select_set(False)
        for other in selected:
            other.select_set(True)
        context.view_layer.objects.active = active
        scene.asrp_ziva_object = obj
    try:
        cache = playback_cache(manifest, layer_name(scene))
    except ValueError:
        cache = playback_cache(manifest, "physics")
    for mod in obj.modifiers:
        if mod.type == "MESH_CACHE":
            mod.filepath = str(package / cache)
    obj.hide_viewport = obj.hide_render = False


# --- the difference colours -------------------------------------------------------------------------------------------------


def heat_values(scene):
    """(values, vertices, frames) of the layer on display, from heatmap_<layer>.f32 as written (raw float32, frame-major)."""
    out = out_folder(scene)
    if out is None:
        return None
    try:
        header = json.loads((out / "heatmap.json").read_text(encoding="utf-8"))
        info = header["layers"][layer_name(scene)]
        path = out / info["file"]
        key = (str(path), path.stat().st_mtime)
        vertices, frames = int(header["vertex_count"]), int(header["frames"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if key not in _HEAT:
        values = array.array("f")
        with open(path, "rb") as f:
            values.fromfile(f, vertices * frames)
        _HEAT.clear()
        _HEAT[key] = (values, vertices, frames)
    return _HEAT[key]


def heat_colour(mm: float) -> tuple:
    t = min(max(mm / HEAT_MAX_MM, 0.0), 1.0)  # the fixed scale: 0 mm blue, 5 mm or more red
    return (t, 0.0, 1.0 - t, 1.0)


def heat_lips(scene):
    try:
        return asset.lips_object(scene, Path(scene.asrp_asset_run))  # the run's soft tissue, as the run folder's scene.json names it
    except (ValueError, OSError, KeyError):
        return None


def update_heat(scene) -> None:
    """Colour our lips by the difference of the current frame."""
    obj, data = heat_lips(scene), heat_values(scene)
    if obj is None or data is None or HEAT_ATTR not in obj.data.color_attributes:
        return
    values, vertices, frames = data
    f = min(max(scene.frame_current, 0), frames - 1)
    colours = []
    for mm in values[f * vertices:(f + 1) * vertices]:
        colours.extend(heat_colour(mm))
    obj.data.color_attributes[HEAT_ATTR].data.foreach_set("color", colours)
    obj.data.update()


@persistent
def heat_handler(scene, depsgraph=None) -> None:
    if scene.asrp_show_heat:
        update_heat(scene)


def install_handler() -> None:
    if heat_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(heat_handler)


def remove_handler() -> None:
    if heat_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(heat_handler)


def disable_heat(context) -> None:
    """Put the display back exactly as it was: the colour attribute removed, the active one and the views restored."""
    scene = context.scene
    remove_handler()
    for item in scene.asrp_asset_objects:
        if asset.is_live(item.obj):
            asset.drop_colour_attribute(item.obj.data, HEAT_ATTR)
    asset.restore_views(context)


def enable_heat(context) -> bool:
    scene = context.scene
    obj = heat_lips(scene)
    if obj is None or heat_values(scene) is None:
        return False
    if HEAT_ATTR not in obj.data.color_attributes:
        asset.new_colour_attribute(obj.data, HEAT_ATTR)
    asset.show_vertex_colours(context)
    install_handler()
    update_heat(scene)
    return True


def sync_heat(context) -> None:
    scene = context.scene
    if scene.asrp_show_heat and ready(scene):
        if not enable_heat(context):
            disable_heat(context)
    else:
        disable_heat(context)


def sync(context) -> None:
    """After a result, a layer switch or a file load: Ziva's lips and the difference colours match the checkboxes and the files."""
    sync_ziva(context)
    sync_heat(context)


def drop(scene) -> None:
    """The result the comparison belongs to is going away: no colours, no Ziva object (the checkboxes stay as they are)."""
    if scene.asrp_show_heat:
        disable_heat(bpy.context)
    remove_ziva(scene)
    _REPORTS.clear()


def unregister_handlers() -> None:
    remove_handler()
