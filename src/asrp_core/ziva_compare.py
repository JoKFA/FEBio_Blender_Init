"""`asrp compare`: one run of ours against a Ziva export (T-11; docs/07 section 4.2, docs/04 section 7).

    compare_run(run_folder, ziva_export_folder, out_folder, target=None) -> the report (also written)

writes into `out_folder`:

    compare_report.json   numbers only: per frame the mean / p95 / max distance (mm) of the physics layer and of
                          the final shape, apart; the two indicators that do not need Ziva (distance to the
                          artist's target pose, the lower lip's follow ratio) or "not available" with the reason;
                          per Ziva stream its identity (run id, stream id, real frames, file length, motion
                          coverage, read-back); the settings the two sides were read with. No mesh, no path.
    heatmap.json          the header of the heat-map data: units, frames, vertex count, which reference
    heatmap_physics.f32   per frame, per vertex: the distance in mm to Ziva's same vertex. Raw little-endian
    heatmap_final.f32     float32, frame-major (value of frame f, vertex v at index f * vertex_count + v). Raw
                          floats because the add-on can read them without numpy (array.array, or one numpy call),
                          the way it reads the point caches, and because the file is what the panel shows as it is:
                          nothing is computed in Blender
    ziva_playback/        Ziva's lips as a playback package of the same format as ours (playback.json,
                          playback.pc2, playback_final.pc2, 30 frames per second, mm, Z up), loadable by the
                          add-on's run loader next to our run

The folder holds lab data (Ziva's shapes), so it must be outside the repository, or under its git-ignored runs/
(`check_out_folder`). Nothing here says whether a difference is acceptable: there is no pass line (ADR-17).

Both sides must be the same 10,240 vertices in the same order, the same frames (0 to n-1), 30 frames per second.
Anything else is an error that says what differs; frames are never cut to the shorter side.
"""

import datetime
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from asrp_core import compare, final_shape, playback, simulate, trajectory, ziva_export
from asrp_core import scene as scene_module
from asrp_core.asset import coords

FORMAT = "asrp-compare/1"
HEATMAP_FORMAT = "asrp-heatmap/1"
REPORT, HEATMAP = "compare_report.json", "heatmap.json"
PACKAGE = "ziva_playback"
SUPPORTED_FPS = 30.0
PHYSICS, FINAL = "lips_physics", "lips_final"
TARGET_START, TARGET_END = "x_middleres_OrbicularisOris0", "x_middleres_OrbicularisOris1"
LOWER_LIP = "lower_lip_on_jaw"
PACKAGE_TOLERANCE_MM = 1e-4
REPO = Path(__file__).resolve().parents[2]

TOPOLOGY_NOTE = (
    "Ziva re-triangulates the lips every frame (polyTriangulate); the vertex numbering and count do not change. "
    "This package has fixed topology, so it carries ONE connectivity: the triangles of frame 0 (the export's rest "
    "OBJ). The points are compared and played in the export's own vertex order; the connectivity of any later "
    "frame is not carried and not claimed to match")


class CompareRunError(ValueError):
    """The comparison cannot be made as asked; the message says why and what to do."""


@dataclass
class Side:
    """One result, in the core's units (mm, Z up), as `build_report` takes it. `jaw` is the jaw's motion as 4x4
    column-vector transforms in mm, one per frame, frame 0 = rest; None when it is not known."""

    label: str
    physics: np.ndarray
    final: np.ndarray | None = None
    final_missing: str = ""
    jaw: np.ndarray | None = None
    jaw_missing: str = ""


# --- where the output may go -------------------------------------------------------------------------------


def check_out_folder(out) -> Path:
    """The output folder, resolved, or an error: the folder holds Ziva's shapes (lab data), so it must not be
    inside this repository's tree unless git ignores it (that is `runs/`). Outside the repository it is free."""
    out = Path(out).resolve()
    inside = REPO == out or REPO in out.parents
    if not inside or not (REPO / ".git").exists():
        return out
    try:
        ignored = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", str(out)],
                                 capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = (out.relative_to(REPO).parts or ("",))[0] == "runs"
    if not ignored:
        raise CompareRunError(
            f"{out} is inside the repository and git does not ignore it. The comparison holds Ziva's shapes, which "
            "are the lab's data and must never be committed: give a folder outside the repository, or one under "
            "runs/ (which git ignores)")
    return out


# --- reading our run ---------------------------------------------------------------------------------------


@dataclass
class OurRun:
    side: Side
    run_id: str
    fps: float
    mm_per_scene_unit: float
    groups: dict
    settle_frame: int | None
    training: np.ndarray | None
    training_missing: str
    scene_path: Path


def read_run(folder) -> OurRun:
    folder = Path(folder)
    report_path = folder / simulate.REPORT
    if not report_path.is_file():
        raise CompareRunError(f"{folder} has no {simulate.REPORT}; give the folder of a run made by asrp run")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "complete":
        raise CompareRunError(f"the run in {folder.name} has status {report.get('status')!r}, not 'complete'; "
                              "there is no result to compare")
    try:
        physics = simulate.read_display(folder / simulate.DISPLAY)
        final_path = folder / simulate.FINAL_DISPLAY
        final = simulate.read_display(final_path)["positions"] if final_path.is_file() else None
        scene = scene_module.load(folder / "scene.json")
        motion = trajectory.read(folder / "trajectory.json")
    except (ValueError, OSError) as e:
        raise CompareRunError(f"{folder.name} cannot be read as a finished run: {e}") from None
    count = physics["positions"].shape[1]
    groups = {a.name: np.array(sorted({int(v) for v, w in a.weights if w > 0}), dtype=np.int64)
              for a in scene.attachments}
    held = np.unique(np.concatenate(list(groups.values()))) if groups else np.array([], dtype=np.int64)
    groups["no_attachment_holds"] = np.setdiff1d(np.arange(count), held)
    jaw_driver = next((d.name for d in scene.drivers if d.hinge is not None), None)
    jaw, jaw_missing = None, "the scene has no jaw driver with a hinge"
    if jaw_driver is not None and jaw_driver in motion.drivers:
        jaw, jaw_missing = np.asarray(motion.drivers[jaw_driver], dtype=np.float64).reshape(-1, 4, 4), ""
    elif jaw_driver is not None:
        jaw_missing = f"the trajectory has no driver {jaw_driver!r}"
    training, training_missing = None, "the run's trajectory has no landmark layer, so there is no training shape"
    landmarks = trajectory.landmark_translations(motion)
    if landmarks is not None:
        names, translations = landmarks
        model = final_shape.rest_model(folder / "scene.json")
        if list(model.names) != names:
            raise CompareRunError("the trajectory's landmark names are not the scene's; the run folder is inconsistent")
        mm = scene.units.mm_per_scene_unit.value
        training = np.stack([coords.to_mm_zup(final_shape.final_shape(
            model, None, model.landmark_rest_scene + coords.from_mm_zup(t, mm)), mm) for t in translations])
        training_missing = ""
    side = Side("ours", physics["positions"], final, "" if final is not None else
                "our run has no landmark layer (no final/ folder), so it has no final shape",
                jaw, jaw_missing)
    return OurRun(side, str(report.get("run_id", folder.name)), float(physics.get("fps", scene.solver.fps.value)),
                  float(scene.units.mm_per_scene_unit.value), groups, motion.settle_until_frame,
                  training, training_missing, folder / "scene.json")


# --- reading Ziva's side -----------------------------------------------------------------------------------


@dataclass
class ZivaRead:
    side: Side
    identities: dict
    rest_vertices_mm: np.ndarray
    triangles: np.ndarray
    fps: float
    linear_unit: str


def read_ziva(folder, mm_per_scene_unit: float, frames: int) -> ZivaRead:
    """Ziva's two lip streams in the core's units, aligned to frames 0 to frames-1; an error when they are not
    that, or when the physics stream is only a prefix of its run."""
    folder = Path(folder)
    try:
        report = ziva_export.session(folder)
        ids = {s: ziva_export.identity(folder, s) for s in (PHYSICS, FINAL)}
    except ziva_export.ZivaExportError as e:
        raise CompareRunError(str(e)) from None
    if float(report.get("fps", 0)) != SUPPORTED_FPS:
        raise CompareRunError(f"{folder.name} is at {report.get('fps')} frames per second; this comparison supports "
                              f"{SUPPORTED_FPS:g} only (the lab's scene is 30; Blender's frame rate is whole numbers)")
    phys = ids[PHYSICS]
    if not phys["complete"]:
        raise CompareRunError(f"{folder.name}: {PHYSICS} cannot be used as a complete run: "
                              f"{'; '.join(phys['why_not_complete'])}. A prefix is not compared as if it were the run")
    try:
        points, real = ziva_export.read_points(folder, PHYSICS)
        if real != list(range(frames)):
            raise CompareRunError(
                f"{folder.name}: {PHYSICS} holds frames {real[0]} to {real[-1]} ({len(real)} frames) but our run has "
                f"frames 0 to {frames - 1}; compare the same frames of the same motion")
        rest_vertices, triangles = ziva_export.rest_faces(folder, PHYSICS)
        final_points, final_missing = None, ""
        if not ids[FINAL]["complete"]:
            final_missing = f"Ziva's {FINAL} cannot be used: {'; '.join(ids[FINAL]['why_not_complete'])}"
        else:
            final_points, final_real = ziva_export.read_points(folder, FINAL)
            if final_real != real:
                final_points, final_missing = None, f"Ziva's {FINAL} holds other frames than {PHYSICS}"
        jaw, jaw_missing = None, ""
        try:
            jaw = ziva_export.body_transforms(folder, "jaw01", mm_per_scene_unit, real)
        except ziva_export.ZivaExportError as e:
            jaw_missing = str(e)
    except ziva_export.ZivaExportError as e:
        raise CompareRunError(str(e)) from None
    fps = float(report.get("fps", 0))

    def to_mm(a):
        return np.stack([coords.to_mm_zup(f, mm_per_scene_unit) for f in a])

    side = Side("ziva", to_mm(points), None if final_points is None else to_mm(final_points), final_missing,
                jaw, jaw_missing)
    return ZivaRead(side, ids, coords.to_mm_zup(rest_vertices, mm_per_scene_unit), triangles, fps,
                    str(report.get("linear_unit")))


def read_target(path, mm_per_scene_unit: float) -> dict:
    """The artist's target pose from the lab's file (`dataV22_phoneme_AA_for_d2.py`): the start shape (`...0`) and
    the target shape (`...1`, the set the card names) of the lips, in mm, Z up. The file is parsed, never run."""
    import ast

    path = Path(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as e:
        raise CompareRunError(f"the target file {path.name} cannot be read: {e}") from None
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in (TARGET_START, TARGET_END):
            found[node.targets[0].id] = np.asarray(ast.literal_eval(node.value), dtype=np.float64)
    if TARGET_END not in found:
        raise CompareRunError(f"the target file {path.name} has no {TARGET_END}; it is not the lab's target file")
    for name, a in found.items():
        if a.ndim != 2 or a.shape[1] != 3:
            raise CompareRunError(f"{name} in {path.name} is not a list of (x, y, z) points")
    return {"file": path.name, "end": coords.to_mm_zup(found[TARGET_END], mm_per_scene_unit),
            "start": coords.to_mm_zup(found[TARGET_START], mm_per_scene_unit) if TARGET_START in found else None}


# --- the report ---------------------------------------------------------------------------------------------


def _round(values, digits: int = 6):
    if isinstance(values, dict):
        return {k: _round(v, digits) for k, v in values.items()}
    if isinstance(values, (list, tuple)):
        return [_round(v, digits) for v in values]
    if isinstance(values, (float, np.floating)):
        return round(float(values), digits)
    if isinstance(values, np.integer):
        return int(values)
    return values


def _not_available(reason: str) -> dict:
    return {"available": False, "reason": reason}


def _target_distance(shape: np.ndarray, target: dict, end_frame: int) -> dict:
    stats = compare.distance_to_target(shape, target["end"])
    out = {"per_frame": {k: stats[k] for k in ("mean_mm", "p95_mm", "max_mm")},
           "at_frame": {"frame": end_frame, **{k: stats[k][end_frame] for k in ("mean_mm", "p95_mm", "max_mm")}}}
    if target["start"] is not None:
        initial = compare.distance_to_target(target["start"][None], target["end"])
        out["initial_distance_mm"] = {k: initial[k][0] for k in ("mean_mm", "p95_mm", "max_mm")}
        out["final_over_initial"] = {k: (out["at_frame"][k] / initial[k][0] if initial[k][0] > 0 else None)
                                     for k in ("mean_mm", "p95_mm", "max_mm")}
    return out


def _follow(side: Side, groups: dict, settle: int | None, end_frame: int | None) -> dict | str:
    """{group: {reference frame: follow_ratio dict}} for one side, or the reason it cannot be made."""
    if side.jaw is None:
        return side.jaw_missing or "the jaw's motion is not known"
    refs = [0] + ([settle] if settle else [])
    return {name: {str(r): compare.follow_ratio(side.physics, side.jaw, r, idx) for r in refs}
            for name, idx in groups.items() if len(idx)}


def build_report(ours: Side, theirs: Side, groups: dict, *, settle_frame: int | None = None,
                 training: np.ndarray | None = None, training_missing: str = "", target: dict | None = None,
                 target_missing: str = "no target pose file was given (--target)") -> tuple[dict, dict]:
    """The numbers. Returns (report parts, heat maps): {"layers", "indicators", "rest_agreement", "frames"} and
    {"physics": (F, V) mm, "final": (F, V) mm or absent}. Everything else in the report is the caller's record."""
    if ours.physics.shape != theirs.physics.shape:
        raise CompareRunError(
            f"the two results differ in size: ours {ours.physics.shape[0]} frames of {ours.physics.shape[1]} "
            f"vertices, Ziva's {theirs.physics.shape[0]} frames of {theirs.physics.shape[1]}; compare the same "
            "frames of the same mesh")
    frames, vertices = ours.physics.shape[:2]
    layers, heat = {}, {}
    layers["physics"] = {"what": "the lips before the landmark layer (Ziva: before skinCluster7)",
                         **compare.per_frame(ours.physics, theirs.physics)}
    heat["physics"] = compare.distances(ours.physics, theirs.physics)
    if ours.final is not None and theirs.final is not None:
        layers["final"] = {"what": "the lips after the landmark layer (Ziva: after skinCluster7)",
                           **compare.per_frame(ours.final, theirs.final)}
        heat["final"] = compare.distances(ours.final, theirs.final)
    else:
        layers["final"] = _not_available("; ".join(r for r in (ours.final_missing, theirs.final_missing) if r)
                                         or "one side has no final shape")
    end_frame = None
    if ours.jaw is not None:
        moving = np.flatnonzero(np.abs(np.diff(ours.jaw, axis=0)).reshape(frames - 1, -1).max(axis=1) > 1e-9)
        end_frame = int(moving[-1]) + 1 if len(moving) else None
    indicators = {}

    # the distance to the artist's target pose (ADR-25): the final shapes, and the training shape
    if target is None:
        indicators["distance_to_target"] = _not_available(target_missing)
    elif target["end"].shape != (vertices, 3):
        raise CompareRunError(f"the target pose has {target['end'].shape[0]} vertices, the lips {vertices}")
    else:
        at = end_frame if end_frame is not None else frames - 1
        d = {"available": True, "target_file": target["file"], "set": "the `1` set (the target shape; the card's "
             "'frame 50' group, docs/03 section 13.7)", "frame_looked_at": at,
             "frame_looked_at_is": "the last frame the jaw moves" if end_frame is not None else "the last frame",
             "notes": ["not a pass line, not a material error (ADR-17, ADR-25)",
                       "the playback's final shape is not the training shape: in playback the physics carries the "
                       "lower lip along with the jaw, so it can be far from the target (docs/13 E-13)"]}
        d["training_shape"] = (_target_distance(training, target, at) if training is not None
                               else _not_available(training_missing))
        d["ours_final"] = (_target_distance(ours.final, target, at) if ours.final is not None
                           else _not_available(ours.final_missing))
        d["ziva_final"] = (_target_distance(theirs.final, target, at) if theirs.final is not None
                           else _not_available(theirs.final_missing))
        indicators["distance_to_target"] = d

    # the lower lip's follow ratio, physics layer only
    f_ours, f_ziva = _follow(ours, groups, settle_frame, end_frame), _follow(theirs, groups, settle_frame, end_frame)
    definition = ("sum(u . r) / sum(r . r) over the group; u = the group's displacement from the reference frame, "
                  "r = where the group would go if glued to the jaw (the jaw's rigid motion between the same two "
                  "frames); 1 follows the jaw, 0 does not, negative goes the other way (docs/07 section 4.2)")
    if isinstance(f_ours, str) or isinstance(f_ziva, str) or end_frame is None or LOWER_LIP not in groups:
        reason = (f"ours: {f_ours}" if isinstance(f_ours, str) else f"Ziva: {f_ziva}" if isinstance(f_ziva, str)
                  else "the jaw does not move in this motion" if end_frame is None
                  else f"the scene has no group {LOWER_LIP!r}")
        indicators["lower_lip_follow"] = _not_available(reason)
    else:
        by_ref = {}
        for ref in f_ours[LOWER_LIP]:
            row = {}
            for label, table in (("ours", f_ours), ("ziva", f_ziva)):
                f = table[LOWER_LIP][ref]
                row[label] = {"ratio": f["per_frame"][end_frame], "moved_mean_mm": f["moved_mean_mm"][end_frame],
                              "rigid_mean_mm": f["rigid_mean_mm"][end_frame],
                              "applicable": f["per_frame"][end_frame] is not None}
            by_ref[ref] = row
        indicators["lower_lip_follow"] = {
            "available": True, "definition": definition, "layer": "physics (before the landmark layer), both sides",
            "group": f"{LOWER_LIP}: {len(groups[LOWER_LIP])} vertices", "measured_at_frame": end_frame,
            "measured_at_is": "the last frame the jaw moves", "by_reference_frame": by_ref,
            "per_frame": {label: {g: {ref: v["per_frame"] for ref, v in refs.items()}
                                  for g, refs in table.items()}
                          for label, table in (("ours", f_ours), ("ziva", f_ziva))},
            "note": "None is 'not applicable': the jaw has not moved between the reference frame and that frame"}
    rest = float(np.linalg.norm(ours.physics[0] - theirs.physics[0], axis=1).max())
    return ({"frames": frames, "vertices": vertices, "layers": layers, "indicators": indicators,
             "rest_agreement_max_mm": rest}, heat)


# --- the package, the heat maps, the command ----------------------------------------------------------------


def write_heatmaps(out: Path, heat: dict, header: dict) -> dict:
    layers = {}
    for name in ("physics", "final"):
        if name not in heat:
            layers[name] = header["_unavailable"][name]
            continue
        a = np.ascontiguousarray(heat[name], dtype="<f4")
        a.tofile(out / f"heatmap_{name}.f32")
        layers[name] = {"file": f"heatmap_{name}.f32", "max_mm": float(a.max()), "mean_mm": float(a.mean()),
                        "p99_mm": float(np.percentile(a, 99)), "size_bytes": int(a.nbytes)}
    body = {k: v for k, v in header.items() if k != "_unavailable"}
    body["layers"] = layers
    (out / HEATMAP).write_text(json.dumps(_round(body), indent=1) + "\n", encoding="utf-8", newline="\n")
    return layers


def write_ziva_package(out: Path, z: ZivaRead, export_name: str, fps: float) -> dict:
    """Ziva's lips as a playback package, then read back and held against the points it was made from."""
    folder = out / PACKAGE
    folder.mkdir(parents=True, exist_ok=True)
    side = z.side
    source = {"feb": f"ziva_{export_name}", "kind": "ziva export", "export": export_name,
              "streams": {PHYSICS: z.identities[PHYSICS]["file"]["name"],
                          **({FINAL: z.identities[FINAL]["file"]["name"]} if side.final is not None else {})}}
    playback.write_reference_bundle(folder, side.physics[0], z.triangles, side.physics, fps, source, TOPOLOGY_NOTE,
                                    material="ziva", final_frames=side.final)
    worst = {}
    for version, points in (("physics", side.physics), ("final", side.final)):
        if points is None:
            continue
        name = "playback.pc2" if version == "physics" else "playback_final.pc2"
        back = playback.read_pc2(folder / name).astype(np.float64)
        if back.shape != points.shape:
            raise CompareRunError(f"{PACKAGE}/{name} reads back as {back.shape}, not {points.shape}")
        worst[version] = float(np.linalg.norm(back - points, axis=2).max())
        if worst[version] > PACKAGE_TOLERANCE_MM:
            raise CompareRunError(f"{PACKAGE}/{name} differs from the export's points by {worst[version]} mm "
                                  f"(limit {PACKAGE_TOLERANCE_MM} mm)")
    return {"folder": PACKAGE, "files": sorted(p.name for p in folder.iterdir()), "fps": fps,
            "frames": int(side.physics.shape[0]), "units": "mm, Z up (the core's axes; scene units x our scene's "
            "mm_per_scene_unit, then (x, y, z) -> (x, -z, y))",
            "read_back_max_mm": worst, "read_back_limit_mm": PACKAGE_TOLERANCE_MM,
            "topology": {"faces_from": "frame 0 (the export's rest OBJ, lips_physics.obj)", "fixed": True,
                         "faces": int(len(z.triangles)), "note": TOPOLOGY_NOTE}}


def compare_run(run_folder, ziva_folder, out_folder, target=None) -> dict:
    """The command. Returns the report (written as compare_report.json with the other files; see the module)."""
    out = check_out_folder(out_folder)
    run_folder, ziva_folder = Path(run_folder), Path(ziva_folder)
    ours = read_run(run_folder)
    frames, vertices = ours.side.physics.shape[:2]
    if ours.fps != SUPPORTED_FPS:
        raise CompareRunError(f"our run is at {ours.fps:g} frames per second; this comparison supports "
                              f"{SUPPORTED_FPS:g} only (Blender's frame rate is whole numbers; the lab's scene is 30)")
    z = read_ziva(ziva_folder, ours.mm_per_scene_unit, frames)
    if z.side.physics.shape[1] != vertices:
        raise CompareRunError(f"our lips have {vertices} vertices, Ziva's {z.side.physics.shape[1]}; they must be the "
                              "same mesh in the same order")
    pose = read_target(target, ours.mm_per_scene_unit) if target else None
    parts, heat = build_report(ours.side, z.side, ours.groups, settle_frame=ours.settle_frame,
                               training=ours.training, training_missing=ours.training_missing, target=pose)
    out.mkdir(parents=True, exist_ok=True)
    unavailable = {n: parts["layers"][n] for n in ("physics", "final") if n not in heat}
    package = write_ziva_package(out, z, ziva_folder.name, SUPPORTED_FPS)
    heat_layers = write_heatmaps(out, heat, {
        "format": HEATMAP_FORMAT, "units": "mm", "fps": SUPPORTED_FPS, "frames": frames, "vertex_count": vertices,
        "dtype": "float32 little-endian", "layout": "frame-major: the value of frame f, vertex v is at index "
        "f * vertex_count + v",
        "meaning": "the distance between our vertex and Ziva's vertex of the same number; 0 is the same place. "
                   "Not a verdict (ADR-17)",
        "reference": {"kind": "ziva export", "export": ziva_folder.name, "run_id": ziva_folder.name,
                      "streams": {"physics": PHYSICS, "final": FINAL}},
        "ours": {"run_id": ours.run_id}, "_unavailable": unavailable})
    report = {
        "format": FORMAT,
        "made": {"date": datetime.date.today().isoformat(), "command": "asrp compare"},
        "read_this_first": [
            "No pass line: the difference is reported, not judged (ADR-17).",
            "physics = before the landmark layer, final = after it; they are reported apart and neither is "
            "compared with the target pose except where the target section says so.",
            "Ziva's points are scene units x our scene's mm_per_scene_unit, axes (x, y, z) -> (x, -z, y); the two "
            "sides' physical scales are not aligned (docs/11 D18), so a difference is a difference, not an explanation.",
            "Which Ziva run it is matters: the full-face run is the reference, the lips-only run a sensitivity "
            "experiment (docs/07 section 4.2). The export's folder name says which.",
        ],
        "ours": {"run_id": ours.run_id, "run_folder": run_folder.name, "frames": frames, "vertices": vertices,
                 "fps": ours.fps, "mm_per_scene_unit": ours.mm_per_scene_unit, "has_final_shape": ours.side.final is not None},
        "ziva": {"export": ziva_folder.name, "fps": z.fps, "linear_unit_as_written": z.linear_unit,
                 "streams": list(z.identities.values())},
        "frames": {"first": 0, "last": frames - 1, "count": frames},
        "rest_agreement_max_mm": parts["rest_agreement_max_mm"],
        "layers": parts["layers"], "indicators": parts["indicators"],
        "points_and_connectivity": {
            "points": "compared in the export's own vertex order; same numbering on both sides",
            "connectivity": "not compared. " + TOPOLOGY_NOTE},
        "heatmap": {"header": HEATMAP, "layers": heat_layers},
        "ziva_playback": package,
    }
    (out / REPORT).write_text(json.dumps(_round(report), indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                              newline="\n")
    return report


def summary_lines(report: dict) -> list[str]:
    """What the command prints."""
    o, zv = report["ours"], report["ziva"]
    lines = [f"ours       {o['run_id']}: {o['frames']} frames of {o['vertices']} vertices",
             f"ziva       {zv['export']}"]
    for s in zv["streams"]:
        f, m = s["real_frames"], s["motion_coverage"]
        covers = "no motion record" if m is None else f"motion covers {m['first']}-{m['last']}"
        back = "alembic read-back verified" if (s["readback"] or {}).get("alembic_verified") else "read-back not confirmed"
        state = "complete" if s["complete"] else "NOT complete: " + "; ".join(s["why_not_complete"])
        lines.append(f"stream     {s['stream_id']}: frames {f['first']}-{f['last']} ({f['count']}), "
                     f"{s['file']['bytes']} bytes, {covers}, {back}, {state}")
    n = report["frames"]["count"]
    for name, layer in report["layers"].items():
        if layer.get("available") is False:
            lines.append(f"{name:<10} not available: {layer['reason']}")
            continue
        w = layer["worst"]
        last = n - 1
        lines.append(f"{name:<10} frame {last}: mean {layer['mean_mm'][last]:.3f}  p95 {layer['p95_mm'][last]:.3f}  "
                     f"max {layer['max_mm'][last]:.3f} mm; over all frames mean up to {w['mean_mm']['value']:.3f} "
                     f"(frame {w['mean_mm']['frame']}), max up to {w['max_mm']['value']:.3f} (frame {w['max_mm']['frame']})")
    d = report["indicators"]["distance_to_target"]
    if not d["available"]:
        lines.append(f"target     not available: {d['reason']}")
    else:
        for key in ("training_shape", "ours_final", "ziva_final"):
            t = d[key]
            if t.get("available") is False:
                lines.append(f"target     {key}: not available: {t['reason']}")
            else:
                a = t["at_frame"]
                ratio = t.get("final_over_initial", {}).get("mean_mm")
                lines.append(f"target     {key} at frame {a['frame']}: mean {a['mean_mm']:.3f}  p95 {a['p95_mm']:.3f}  "
                             f"max {a['max_mm']:.3f} mm" + ("" if ratio is None else f"  (mean / initial {ratio:.3f})"))
    fl = report["indicators"]["lower_lip_follow"]
    if not fl["available"]:
        lines.append(f"follow     not available: {fl['reason']}")
    else:
        for ref, row in fl["by_reference_frame"].items():
            def show(r):
                return "n/a" if r["ratio"] is None else f"{r['ratio']:.3f}"
            lines.append(f"follow     lower lip, frame {fl['measured_at_frame']} against frame {ref}: ours "
                         f"{show(row['ours'])}, Ziva {show(row['ziva'])}")
    p = report["ziva_playback"]
    lines.append(f"package    {p['folder']}/: {p['frames']} frames at {p['fps']:g} fps, read back within "
                 f"{max(p['read_back_max_mm'].values()):.2e} mm of the export's points")
    return lines
