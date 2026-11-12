"""`asrp run <scene.json> <trajectory.json>`: one physics run of a scene, start to finish (T-06a, docs/04 section 8).

1. `generate.build` checks the scene and trajectory, maps the attachments and writes the .feb (nothing is
   started if it refuses);
2. the run shell (`run.Prepared` -> `run.execute`, length_scale = k) makes the run folder, copies the
   inputs in, runs FEBio and writes physics/positions.json + positions.npy (the numbers, float64, frames x
   nodes x 3) already divided by k;
3. after a complete run, this module adds (all geometric mm, Z up, frames 0..N-1 of the trajectory; FEBio
   logs no frame 0, so frame 0 is the rest pose):

    physics/display.json          the display mesh at every frame, carried by the tet mesh (`embed`): a small
    physics/display.npy           header and the numbers (float64, frames x vertices x 3); `read_display`
    physics/settled_frame<n>.json the shape after the gravity-only settle, at the trajectory's
    physics/settled_frame<n>.obj  settle_until_frame n (14 for the lab's controller, ADR-30: its starting
                                  point): tet nodes and display mesh, and the display mesh as an OBJ with
                                  its faces. Written only when the trajectory names n >= 1 and every
                                  driver in use is at rest through frame n
    playback.json, playback.pc2   the display mesh and its point cache for Blender (`playback`)
    run_report.json               every temporary value and its source, the scene's simplifications,
                                  the generator's report, max|u|/δ per spring group, the plausibility
                                  checks a, b, b2, c, d (`plausibility`), return_to_settled (how far
                                  the tet nodes are from the settled shape once the drivers are back
                                  at rest; reported only), timing

A failed or cancelled run gets run_report.json (with check (a) failed) but no physics results.
"""

import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from asrp_core import embed, febio, generate, playback, plausibility, provenance, run
from asrp_core import scene as scene_module

REPORT = "run_report.json"
DISPLAY = "physics/display.json"  # the header; the numbers are in DISPLAY_ARRAY
DISPLAY_ARRAY = "physics/display.npy"
DISPLAY_FORMAT = "asrp-display/2"
SETTLE_FRAMES = 5  # check (c) averages up to this many frames ending at settle_until_frame (one frame aliases the
# ringing); never frame 0, the rest pose, whose sag is exactly 0
SLIP_LIMIT = 0.1  # docs/05 section 3: max|u| / δ above this, the spring result is off by more than ~2 %

# Settings the generator chose (all "ours"), for the run report next to the scene's own parameters.
GENERATOR_SETTINGS = [
    ("generator.rhoi", generate.RHOI, "generalized-alpha spectral radius at infinity: 0 is FEBio's strongest damping of "
     "fast modes; numerical, not physical damping. Used by T-07's runs (spikes/s3_attachment.py); docs/05 pit 2, T-12 "
     "revisits it"),
    ("generator.gravity_sign_in_febio", generate.FEBIO_GRAVITY_SIGN, "docs/05 pit 1 (ADR-10): FEBio's const body load "
     "acts opposite to the manual, so the scene's physical gravity is written negated"),
    ("generator.gravity_from", 0.0, "gravity is on at full strength from t = 0, like the lab's frames 0-14"),
    ("generator.spring_offset_delta", f"{generate.SPRING_OFFSET_EDGES:g} x median tet edge x k", "docs/05 section 3: the anchors sit delta away along x, y, z "
     "(FEBio coordinates); delta must stay >= 10 x the slip, see max|u|/delta"),
    ("generator.spring_level_tolerance", generate.SPRING_LEVEL_TOLERANCE, "stiffness levels per spring group: log-spaced, as "
     "few as keep every node's binned stiffness within this fraction of its own value, each the mean of its members "
     "(one FEBio spring material per level); the level count and the largest error are in the generator report"),
    ("generator.max_distance_edges", generate.MAX_DISTANCE_EDGES, "a display vertex farther than this x the median tet edge "
     "from its tet stops the run (docs/05 section 3 rule 5)"),
    ("generator.max_retries", generate.MAX_RETRIES, "adaptive stepping as in spikes/s2_lips_febio.py"),
    ("generator.dtmin_fraction", generate.DTMIN_FRACTION, "the step may shrink to this fraction of a frame step"),
    ("generator.motion_between_frames", "linear", "the rigid bodies' translation and rotation vector are interpolated "
     "linearly between frames (exact for a fixed hinge)"),
    ("plausibility.hard_tolerance_mm", plausibility.HARD_TOLERANCE_MM, "docs/07 section 3"),
    ("plausibility.sag_factor", plausibility.SAG_FACTOR, "check (c) passes when the measured sag is within this factor "
     "of the model's estimate, rho |g| k L^2 / (2 E), either way"),
]

class SceneRunError(Exception):
    """The scene could not be run; nothing was started. The message says what to do."""


@dataclass
class SceneRun:
    run_dir: Path
    status: str
    report: dict
    passed: bool  # complete and every plausibility check passed


def _inputs(model: generate.Model, trajectory_path: Path) -> dict[str, Path]:
    """The files the run folder needs to be run again: scene.json, the trajectory, every file it refers to."""
    base = model.scene_path.parent
    names = [t.mesh.path for t in model.scene.soft_tissues] + [t.tet_mesh.path for t in model.scene.soft_tissues]
    names += [b.mesh.path for b in model.scene.bones]
    if model.scene.landmarks is not None:
        names.append(model.scene.landmarks.weights.path)
    out = {"scene.json": model.scene_path, "trajectory.json": trajectory_path}
    for n in names:
        if Path(n).is_absolute() or ".." in Path(n).parts:
            raise SceneRunError(f"scene.json refers to {n}, outside its own folder; a run folder can only copy files "
                                "below the scene's folder")
        out[n] = base / n
    return out


def _retries(log: Path) -> int:
    text = log.read_text(errors="replace") if log.exists() else ""
    return text.count("Retrying time step")


def _write_obj(path: Path, vertices: np.ndarray, faces, header: str) -> None:
    lines = [f"# {header}"] + [f"v {x!r} {y!r} {z!r}" for x, y, z in vertices.tolist()]
    lines += ["f " + " ".join(str(i + 1) for i in f) for f in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def slips(model: generate.Model, node_frames: np.ndarray) -> dict:
    """max|u| / δ per spring group: u is a spring node's distance from where its target puts the node's rest
    position, in FEBio coordinates (geometric x k, the coordinates δ is in), over every frame."""
    out = {}
    for g in model.groups:
        if g.kind != "spring" or not g.stiffness:
            continue
        nodes = np.array(sorted(g.stiffness))
        body = model.bodies[g.target]
        motion = body.transforms or [plausibility.IDENTITY] * len(node_frames)
        u = max(float(np.linalg.norm(node_frames[f][nodes] - plausibility._moved(motion[f], model.mesh.nodes[nodes]),
                                     axis=1).max()) for f in range(len(node_frames))) * model.k
        out[g.name] = {"max_slip_febio_mm": u, "delta_febio_mm": model.delta, "ratio": u / model.delta,
                       "flag": u / model.delta > SLIP_LIMIT}
    return out


def _parameters(model: generate.Model, trajectory_path: Path) -> list[dict]:
    rows = [{"where": f"scene.{w}", **p} for w, p in scene_module.parameters(model.scene.to_json())]
    rows += [{"where": w, "value": v, "source": "ours", "note": n} for w, v, n in GENERATOR_SETTINGS]
    rows.append({"where": "trajectory.source", "value": model.trajectory.source,
                 "source": model.trajectory.source_tag or "unstated",
                 "note": f"{trajectory_path.name}: {model.trajectory.frames} frames at {model.trajectory.fps} fps"})
    return rows


def run_scene(scene_path, trajectory_path, runs_dir: Path, exe: Path, name: str | None = None,
              on_progress=None, cancel=None, timeout: float = 3600, threads: int = febio.DEFAULT_THREADS) -> SceneRun:
    scene_path, trajectory_path = Path(scene_path), Path(trajectory_path)
    t0 = time.perf_counter()
    try:
        model = generate.build(scene_path, trajectory_path)
    except (generate.GenerateError, ValueError) as e:
        raise SceneRunError(str(e)) from e
    generated_s = time.perf_counter() - t0
    with tempfile.TemporaryDirectory() as tmp:
        feb = Path(tmp) / run.FEB_NAME
        feb.write_text(model.feb_text, encoding="ascii", newline="\n")
        prepared = run.Prepared(
            feb, "generated", ["asrp", "run", scene_path.name, trajectory_path.name],
            {"generator": {w.split(".", 1)[1]: v for w, v, _ in GENERATOR_SETTINGS if w.startswith("generator.")}
             | {"spring_offset_delta_febio_mm": model.delta}},
            _inputs(model, trajectory_path), length_scale=model.k)
        result = run.execute(prepared, runs_dir, exe, name or trajectory_path.stem, on_progress, cancel, timeout, threads)
    run_dir = result.run_dir
    t1 = time.perf_counter()
    record = provenance.read(run_dir)
    retries = _retries(run_dir / run.LOG_NAME)
    report = {
        "format": "asrp-run-report/1",
        "run_id": run_dir.name,
        "status": result.status,
        "frames": model.frames,
        "parameters": _parameters(model, trajectory_path),
        "simplifications": list(model.scene.simplifications),
        "warnings": model.warnings,
        "generator": model.report,
        "checks": {},
        "timing": {},
    }
    checks = {}
    status = result.status
    failure_text = result.failure.message if result.failure else None
    positions = logged = None
    if status == "complete":
        positions = run.read_positions(run_dir / run.POSITIONS)
        logged = [round(t * model.fps) for t in positions["times_s"]]
        check_a = plausibility.motion_completed("complete", model.frames, logged, retries)
        if not check_a.passed:  # FEBio reached the end time but dropped a frame: no results, like any failed run (T-08)
            status, failure_text = "failed", check_a.message
            shutil.rmtree(run_dir / "physics", ignore_errors=True)
            record["outputs"] = {}
            record["failure"] = {"frame": None, "message": check_a.message}
            report["status"] = "failed"
    if status != "complete":
        checks["a"] = (check_a if logged is not None else
                       plausibility.motion_completed(status, model.frames, [], retries, failure_text))
        checks["b"] = plausibility.Check("hard attachments follow their bones", None, "the run did not complete")
        checks["b2"] = plausibility.Check("spring anchors follow their rigid bodies", None, "the run did not complete")
        checks["c"] = plausibility.Check("gravity sag", None, "the run did not complete")
        checks["d"] = plausibility.Check("the tet mesh stays valid", None, "the run did not complete")
    else:
        checks["a"] = check_a
        index = {nid: i for i, nid in enumerate(positions["node_ids"])}
        tissue = [index[n + 1] for n in range(len(model.mesh.nodes))]
        node_frames = np.full((model.frames, len(model.mesh.nodes), 3), np.nan)
        node_frames[0] = model.mesh.nodes
        for f, frame in zip(logged, positions["positions"]):
            if 0 < f < model.frames:
                node_frames[f] = np.asarray(frame)[tissue]
        display = np.stack([embed.apply(model.embedding, p) for p in node_frames])
        groups = [{"name": g.name, "kind": g.kind, "target": g.target, "nodes": g.nodes, "vertices": g.vertices}
                  for g in model.groups]
        transforms = {name: b.transforms for name, b in model.bodies.items()}
        checks["b"] = plausibility.follows_bones(groups, model.mesh.nodes, node_frames, model.display, display, transforms)
        rest_febio = generate.node_rest_febio(model)
        anchor_ids = [sp.anchor for sp in model.springs]
        anchor_rest = np.array([rest_febio[a] for a in anchor_ids]).reshape(-1, 3) / model.k
        anchor_frames = np.full((model.frames, len(anchor_ids), 3), np.nan)
        anchor_frames[0] = anchor_rest
        for f, frame in zip(logged, positions["positions"]):
            if 0 < f < model.frames:
                anchor_frames[f] = np.asarray(frame)[[index[a] for a in anchor_ids]]
        checks["b2"] = plausibility.anchors_follow_bodies(
            anchor_rest, [{g.name: g.target for g in model.groups}[sp.group] for sp in model.springs], anchor_frames, transforms)
        attached = np.unique(np.concatenate([g.vertices for g in model.groups])) if model.groups else np.zeros(0, int)
        free = np.setdiff1d(np.arange(len(model.display)), attached)
        settle = model.trajectory.settle_until_frame
        settled = settle is not None and settle >= 1 and _still_until(model, settle)
        report["settled_shape"] = {"available": settled, "frame": settle if settled else None}
        if settled:
            material = model.scene.soft_tissues[0].material.params
            estimate = plausibility.expected_sag(model.display, free, attached, model.gravity,
                                                 material["density_t_per_mm3"].value, material["E_mpa"].value, model.k)
            checks["c"] = plausibility.gravity_sag(model.display, display, free, model.gravity, estimate,
                                                   range(max(1, settle - SETTLE_FRAMES + 1), settle + 1))
        else:
            if settle is None:
                reason = "the trajectory does not say where the gravity-only settle ends (settle_until_frame)"
            elif settle == 0:
                reason = "settle_until_frame is 0: there is no frame after the rest pose in the gravity-only settle"
            else:
                reason = f"the motion starts on or before frame {settle}, the end of the gravity-only settle"
            checks["c"] = plausibility.Check("gravity sag", None, reason)
            report["settled_shape"]["reason"] = f"{reason}: the shape after the settle is not written"
        checks["d"] = plausibility.tet_mesh_valid(model.mesh.nodes, model.mesh.tets, node_frames)
        if settled:
            report["return_to_settled"] = plausibility.return_to_settled(
                node_frames, settle, [b.transforms for b in model.bodies.values()])
        report["spring_slip"] = slips(model, node_frames)
        _write_results(run_dir, model, node_frames, display, settle if settled else None)
        files = [run.POSITIONS, run.POSITIONS_ARRAY, DISPLAY, DISPLAY_ARRAY, "playback.json", "playback.pc2"]
        if settled:
            files[4:4] = [f"{settled_path(settle)}.json", f"{settled_path(settle)}.obj"]
        record["outputs"] = provenance.hash_files(run_dir, files)
    report["checks"] = {key: c.to_json() for key, c in checks.items()}
    # Only an explicit False is a failure; None is "not run" (the reason is in the check). (a) must always run.
    passed = status == "complete" and checks["a"].passed is True and all(c.passed is not False for c in checks.values())
    report["passed"] = passed
    report["not_run"] = {key: c.message for key, c in checks.items() if c.passed is None}
    febio_s = record.get("timing", {}).get("febio_seconds")
    steps = model.frames - 1
    report["timing"] = {
        "generate_s": round(generated_s, 3), "febio_s": febio_s, "post_s": round(time.perf_counter() - t1, 3),
        "febio_s_per_frame": round(febio_s / steps, 3) if febio_s else None,
    }
    (run_dir / REPORT).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    record["outputs"] = {**record.get("outputs", {}), **provenance.hash_files(run_dir, [REPORT])} \
        if status == "complete" else {}
    record.pop("format", None)
    record["status"] = status
    provenance.write(run_dir, record)
    return SceneRun(run_dir, status, report, passed)


def read_display(path: Path) -> dict:
    """The display header plus "positions": a float64 array (frames, vertices, 3), geometric mm."""
    data = run.load_array(path, "positions")
    shape = data["positions"].shape
    if list(shape) != [data["frames"], data["vertex_count"], 3]:
        raise run.RunError(f"{path.name} says {data['frames']} frames of {data['vertex_count']} vertices but its "
                           f"array has shape {list(shape)}. Run again.")
    return data


def settled_path(frame: int) -> str:
    return f"physics/settled_frame{frame}"


def _still_until(model: generate.Model, last: int) -> bool:
    """True when every moving body stays at its rest transform (identity) through frames 0..last, so
    those frames are the gravity-only settle the settled shape and check (c) assume."""
    eye = np.eye(4).ravel()
    for b in model.bodies.values():
        if b.transforms is None:
            continue
        for t in b.transforms[:last + 1]:
            if np.abs(np.asarray(t, dtype=float).ravel() - eye).max() > 1e-9:
                return False
    return True


def _write_results(run_dir: Path, model: generate.Model, node_frames: np.ndarray, display: np.ndarray,
                   settle: int | None = None) -> None:
    (run_dir / "physics").mkdir(exist_ok=True)
    run.save_array(run_dir / DISPLAY, {
        "format": DISPLAY_FORMAT, "units": "mm", "fps": model.fps, "frames": model.frames,
        "vertex_count": int(len(model.display)), "mesh": model.scene.soft_tissues[0].mesh.path,
        "note": "frame 0 is the rest pose (FEBio logs no frame 0); positions are geometric mm (FEBio's / k)",
    }, display, Path(DISPLAY_ARRAY).name)
    if settle is not None:
        f = settle
        (run_dir / f"{settled_path(f)}.json").write_text(json.dumps({
            "format": "asrp-settled/1", "units": "mm", "frame": f, "time_s": f / model.fps,
            "note": "the shape after the gravity-only settle, the controller's starting point (ADR-30)",
            "tet_nodes": node_frames[f].tolist(), "display": display[f].tolist(),
        }), encoding="utf-8", newline="\n")
        _write_obj(run_dir / f"{settled_path(f)}.obj", display[f], model.faces,
                   f"{model.scene.soft_tissues[0].name}, frame {f} (settled under gravity), mm, Z up, asrp run (T-06a)")
    playback.write_surface_bundle(run_dir, model.display, model.faces, display, model.fps,
                                  run_dir / run.FEB_NAME, model.scene.soft_tissues[0].name,
                                  model.scene.soft_tissues[0].mesh.path)
