"""Our lips against Ziva's, on the lab's real neutral-to-AA motion and on the head shake (T-34; docs/07 section 4.2).

    uv run python tools/ziva_comparison.py <out report.json> [--tissue-settings lab|ours] [--work <folder>]
                                           [--aa-run <run folder>] [--shake-run <run folder>] [--threads N]

What it does, with the product's own commands: imports data/lab_export (`asrp import-asset`), converts the lab's
motion file (`asrp convert-motion`), runs it and the head shake (`asrp run`), then compares the two layers of our
lips with the same frames of Ziva's two runs and writes one JSON report of numbers. With --aa-run / --shake-run it
compares run folders that already exist instead of running again (they must come from the same scene settings).

The Ziva results and the lab's motion file stay outside the repository; tools/local_paths.py says where they are on
this machine. The report holds numbers only: no mesh, no path of this machine.

What the report is NOT: a verdict. There is no pass line for the distance to Ziva (ADR-17). The full-face Ziva run
is the reference (the lab's real setup). The lips-only Ziva run is a sensitivity experiment we made on the machine
by switching the other 42 objects off; its boundary conditions are not ours, and it is not settled at frame 14.
Both were played by our script from the lab's motion file, not by a researcher in the lab's interface.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import head_shake_motion  # noqa: E402
import local_paths  # noqa: E402

from asrp_core import compare, plausibility, simulate, tetmesh, trajectory  # noqa: E402
from asrp_core import scene as scene_module  # noqa: E402
from asrp_core.asset import coords  # noqa: E402

FORMAT = "asrp-ziva-comparison/1"
AA_JOB = "lab_motions/results/job_251205-190350/251205-190358"
FULL, LIPS_ONLY, SHAKE = "neutral_to_AA_export_*", "AA_lips_only_export_*", "head_shake_export_*"
SETTLE = 14  # last frame of the gravity-only settle, in Ziva's runs and in ours
MOTION_STOPS = 36  # the AA motion's last step
SHAKE_STOPS = 46  # the head stops moving
WOBBLE_LIMIT_MM = 0.04
DOWN = (0.0, 0.0, -1.0)  # gravity in the core's axes (Z up); Ziva's is -Y in its own, the same direction
TURN = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])  # scene axes -> Z up
# Quoted, not recomputed here: the Maya solver log's per-step times (docs/13 E-15, from the second outside audit).
ZIVA_SOLVER_LOG = {
    "full_face_s_per_step": "about 1.47 to 1.60 on average over that evening's runs, single steps above 3",
    "lips_only_s_per_step": "0.0095 on average over the last 46 lines",
    "source": "quoted from docs/13 E-15 (the Maya solver log read by an outside audit); not recomputed by this tool. "
              "The script that read the log took the last lines of a global log, which may mix runs",
}


def rounded(values, digits: int = 6):
    """Floats to `digits` decimals, so the file is readable and stable. A number smaller than that would become 0
    (a density of 1.06e-9 did), so small numbers keep 9 significant digits instead."""
    if isinstance(values, dict):
        return {k: rounded(v, digits) for k, v in values.items()}
    if isinstance(values, (list, tuple)):
        return [rounded(v, digits) for v in values]
    if isinstance(values, (float, np.floating)):
        v = float(values)
        return round(v, digits) if v == 0 or abs(v) >= 10.0 ** (3 - digits) else float(f"{v:.9g}")
    if isinstance(values, np.integer):
        return int(values)
    return values


def asrp(*args) -> str:
    """Run the product's command line and return what it printed; stop with its output when it fails."""
    done = subprocess.run([sys.executable, "-B", "-m", "asrp_core.cli", *map(str, args)], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode not in (0, 1) or "ERROR" in done.stdout:
        raise SystemExit(f"asrp {args[0]} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def run(scene_path: Path, motion: Path, runs: Path, name: str, threads: int) -> Path:
    out = asrp("run", scene_path, motion, "--runs-dir", runs, "--name", name, "--threads", threads)
    line = next((ln for ln in out.splitlines() if ln.startswith("report ")), None)
    if line is None:
        raise SystemExit(f"asrp run printed no report line:\n{out}")
    return Path(line.split(None, 1)[1].strip()).parent


def ziva_export(trip: Path, pattern: str) -> dict:
    folders = sorted((trip / "ziva_reference").glob(pattern))
    if not folders:
        raise SystemExit(f"no Ziva export matches {pattern} in the trip data")
    folder = folders[-1]
    report = json.loads((folder / "session_report.json").read_text(encoding="utf-8"))
    out = {"name": folder.name, "report": report,
           "motion": json.loads((folder / "motion.json").read_text(encoding="utf-8"))}
    for stream in ("lips_physics", "lips_final"):
        entry = next(s for s in report["streams"] if s["id"] == stream)
        points = np.fromfile(folder / entry["samples"], dtype="<f4").astype(np.float64)
        out[stream] = points.reshape(len(entry["frames"]), entry["vertices"], 3)
    return out


def to_mm(frames: np.ndarray, mm: float) -> np.ndarray:
    return np.stack([coords.to_mm_zup(f, mm) for f in frames])


def ziva_jaw_degrees(motion: dict) -> list[float]:
    """jaw01's signed turn about world X against frame 0, per frame (Maya: row vectors, so inverse(M0) @ Mf)."""
    key = next(k for k in motion["frames"][0] if k.split("|")[-1] == "jaw01")
    world = [np.asarray(f[key], dtype=np.float64).reshape(4, 4)[:3, :3] for f in motion["frames"]]
    out = []
    for m in world:
        r = (np.linalg.inv(world[0]) @ m).T
        sines = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / 2
        if abs(sines[1]) > 1e-6 or abs(sines[2]) > 1e-6:
            raise SystemExit("Ziva's jaw01 turns about an axis other than world X; this comparison does not cover that")
        out.append(math.degrees(math.atan2(sines[0], (np.trace(r) - 1) / 2)))
    return out


def our_jaw_degrees(motion: trajectory.Trajectory) -> list[float]:
    out = []
    for t in motion.drivers["jaw01"]:
        m = np.array(t).reshape(4, 4)
        out.append(math.degrees(math.atan2((m[2, 1] - m[1, 2]) / 2, (np.trace(m[:3, :3]) - 1) / 2)))
    return out


def our_run(folder: Path) -> dict:
    report = json.loads((folder / "run_report.json").read_text(encoding="utf-8"))
    provenance = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    out = {"folder": folder, "report": report, "motion": trajectory.read(folder / "trajectory.json"),
           "threads": int(provenance["parameters"]["febio_env"]["OMP_NUM_THREADS"]),
           "scene": scene_module.load(folder / "scene.json"),
           "physics": simulate.read_display(folder / "physics" / "display.json")["positions"]}
    final = folder / "final" / "display.json"
    out["final"] = simulate.read_display(final)["positions"] if final.is_file() else None
    return out


def checks(report: dict) -> dict:
    return {key: {"name": c["name"], "passed": c["passed"], "message": c["message"]} for key, c in report["checks"].items()}


def surface(rest: np.ndarray, frames: np.ndarray, triangles: np.ndarray) -> dict:
    """Flipped faces and short edges per frame, counted by the product's own function."""
    counts = plausibility.fold_counts(rest, frames, triangles)
    flipped, short = counts["flipped"].astype(int), counts["short"].astype(int)
    worst = int(np.argmax(flipped))
    return {"flipped_per_frame": flipped.tolist(), "short_edges_per_frame": short.tolist(),
            "frames_with_flipped_faces": [int(f) for f in np.flatnonzero(flipped)],
            "worst": {"frame": worst, "flipped": int(flipped[worst]), "short_edges": int(short[worst])},
            "last": {"frame": len(flipped) - 1, "flipped": int(flipped[-1]), "short_edges": int(short[-1])}}


def where_flipped(rest: np.ndarray, ours: np.ndarray, ziva: dict, triangles: np.ndarray, frames) -> list[dict]:
    """For the given frames: which of our faces are flipped, where they are on the lips, how large they are at
    rest, and how many of the SAME faces are flipped in each Ziva run on that frame."""
    low, size = rest.min(axis=0), np.ptp(rest, axis=0)
    area = 0.5 * np.linalg.norm(np.cross(rest[triangles[:, 1]] - rest[triangles[:, 0]],
                                         rest[triangles[:, 2]] - rest[triangles[:, 0]]), axis=1)
    out = []
    for f in frames:
        mine = compare.flipped_faces(rest, ours[f], triangles)
        faces = np.flatnonzero(mine)
        entry = {"frame": int(f), "flipped": int(mine.sum()), "faces": faces.tolist(),
                 "rest_area_mm2": rounded(area[faces].tolist(), 4),
                 "share_of_lip_area": rounded(float(area[faces].sum() / area.sum()), 8),
                 # where on the lips' bounding box: 0..1 left to right (x), back to front (y), bottom to top (z)
                 "centroid_in_box": rounded(((rest[triangles[faces]].mean(axis=1) - low) / size).tolist(), 3)}
        for label, theirs in ziva.items():
            same = compare.flipped_faces(theirs[0], theirs[f], triangles)
            entry[f"ziva_{label}_flipped"] = int(same.sum())
            entry[f"same_faces_as_ziva_{label}"] = int((mine & same).sum())
        out.append(entry)
    return out


def unmatched(scene: scene_module.Scene, attributes: dict, generator: dict) -> list[dict]:
    def one(kind, name):
        return sorted({json.dumps(n["attributes"][name]) for n in attributes.values() if n["type"] == kind})

    material = scene.soft_tissues[0].material
    springs = {g["name"]: g.get("base_stiffness_n_per_mm") for g in generator["groups"] if g["kind"] == "spring"}
    return [
        {"setting": "material model", "ziva": f"{one('zTissue', 'material__label')}, compression resistance "
                                               f"{one('zTissue', 'compressionResistance')}",
         "ours": material.model,
         "note": "only Young's modulus and Poisson's ratio can be set alike; the answer under compression differs"},
        {"setting": "integrator", "ziva": str(one("zSolver", "integrator__label")), "ours": "FEBio's implicit dynamics "
         "(generalized alpha as the generator writes it)", "note": "no setting of ours selects BackwardEuler"},
        {"setting": "Newton iteration limit", "ziva": str(one("zSolver", "maxNewtonIterations")),
         "ours": "FEBio iterates to its own convergence tolerance", "note": "Ziva stops after its limit, converged or not"},
        {"setting": "stiffness damping", "ziva": f"{one('zSolver', 'stiffnessDamping')}, mass damping {one('zSolver', 'massDamping')}",
         "ours": f"mass damping {scene.solver.damping.value} only", "note": "the scene has no stiffness damping (docs/05 section 4)"},
        {"setting": "attachments", "ziva": f"all soft, stiffness {one('zAttachment', 'stiffness')} x 10^{one('zAttachment', 'stiffnessExp')} "
                                           "N/m^3 (needs an area to become a spring stiffness)",
         "ours": "upper lip hard; the others springs of 100 x E x h, N/mm: " + json.dumps(springs),
         "note": "how Ziva's value turns into a spring stiffness is decided in T-37; the lip corners hang on two "
                 "anchors we made up, in Ziva on the neighbouring tissues"},
        {"setting": "physical scale", "ziva": f"its own solver transform, scale {one('zSolverTransform', 'scaleX')} on each axis",
         "ours": f"k = {scene.units.physics_length_scale.value}",
         "note": "inferred, not checked on the machine: 100 Maya units are 1 m in Ziva's solver. A third length "
                 "scale, neither 0.962 mm per scene unit nor our k (docs/11 D18)"},
        {"setting": "gravity", "ziva": f"gravityY {one('zSolver', 'gravityY')} in the solver's own units",
         "ours": f"{scene.solver.gravity_mm_per_s2.value} mm/s^2",
         "note": "how Ziva's value becomes a displacement in the world was not measured"},
    ]


DIFFERENCES = [
    {"what": "material", "ours": "neo-Hookean, one tissue (the lips)", "ziva_full_face": "StVK, 41 tissues and 2 cloths",
     "ziva_lips_only": "StVK, the lips alone; the other 42 objects switched off in memory"},
    {"what": "physical scale", "ours": "k = 0.67 of the geometry (a real person's size)",
     "ziva_full_face": "its own solver transform (scale 100); what that is in metres is inferred, not checked",
     "ziva_lips_only": "the same as the full face"},
    {"what": "collisions", "ours": "none", "ziva_full_face": "collision detection off in the solver",
     "ziva_lips_only": "the same"},
    {"what": "constraints", "ours": "upper lip hard on the skull; lower lip on the jaw and both lip corners by springs",
     "ziva_full_face": "140 soft attachments; the lips are held by the skull, the jaw and the tissues at the lip corners",
     "ziva_lips_only": "the lips' attachments to the tissues that were switched off: what they did is not known"},
    {"what": "what the lip corners hang on", "ours": "two anchors we made up, turning half the jaw's angle",
     "ziva_full_face": "neighbouring tissues, which move by their own physics",
     "ziva_lips_only": "the neighbouring tissues are switched off and do not move"},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", help="where to write the report (JSON)")
    parser.add_argument("--tissue-settings", choices=("lab", "ours"), default="lab",
                        help="lab (default): the values measured in the lab's Ziva scene; ours: the import's defaults")
    parser.add_argument("--work", help="folder for the scene, the motions and the runs (default: a temporary folder)")
    parser.add_argument("--aa-run", help="an existing run folder of the AA motion (skips that run)")
    parser.add_argument("--shake-run", help="an existing run folder of the head shake (skips that run)")
    parser.add_argument("--threads", type=int, default=4, help="FEBio threads (default 4)")
    args = parser.parse_args()

    trip = local_paths.ziva_trip()
    if trip is None:
        raise SystemExit("NOT RUN: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    lab_motion = trip / AA_JOB / "combined_checkpoints.pkl"
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="asrp_ziva_comparison_"))
    work.mkdir(parents=True, exist_ok=True)

    if args.aa_run and args.shake_run:
        aa, shake = our_run(Path(args.aa_run)), our_run(Path(args.shake_run))
    else:
        scene_path = work / "scene" / "scene.json"
        asrp("import-asset", REPO / "data" / "lab_export", scene_path.parent, "--tissue-settings", args.tissue_settings)
        aa_motion, shake_motion = work / "neutral_to_AA.json", work / "head_shake.json"
        asrp("convert-motion", lab_motion, scene_path, aa_motion, "--starts-at-rest")
        trajectory.write(shake_motion, head_shake_motion.build(scene_path))
        aa = our_run(Path(args.aa_run) if args.aa_run else run(scene_path, aa_motion, work / "runs", "aa", args.threads))
        shake = our_run(Path(args.shake_run) if args.shake_run
                        else run(scene_path, shake_motion, work / "runs", "head_shake", args.threads))
    if aa["final"] is None:
        raise SystemExit(f"{aa['folder']} has no final layer: it is not a run of the lab's AA motion")
    scene = aa["scene"]
    mm = scene.units.mm_per_scene_unit.value

    def material_of(s: scene_module.Scene) -> dict:
        return {k: {"value": p.value, "source": p.source} for k, p in s.soft_tissues[0].material.params.items()}

    material = material_of(scene)
    if material_of(shake["scene"]) != material or shake["scene"].solver.to_json() != scene.solver.to_json():
        raise SystemExit("the AA run and the head-shake run were not made with the same material and solver settings: "
                         f"{material} against {material_of(shake['scene'])}. Compare runs of one scene")
    # what the runs were made with, read from their own scene, not from this tool's arguments
    tissue_settings = "lab" if material["E_mpa"]["source"] == "lab_setting" else "ours"

    ziva = {"full_face": ziva_export(trip, FULL), "lips_only": ziva_export(trip, LIPS_ONLY)}
    z_physics = {k: to_mm(v["lips_physics"], mm) for k, v in ziva.items()}
    z_final = {k: to_mm(v["lips_final"], mm) for k, v in ziva.items()}
    for label in ziva:
        if z_physics[label].shape != aa["physics"].shape:
            raise SystemExit(f"our AA run has {aa['physics'].shape[0]} frames of {aa['physics'].shape[1]} vertices, Ziva's "
                             f"{label} run {z_physics[label].shape[0]} of {z_physics[label].shape[1]}; they must match")
    frames = aa["physics"].shape[0]
    triangles = coords.triangulate(coords.read_obj(REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj")[1])

    # --- the driver, as a record in the report (the proof with its controls is tests/test_lab_motion.py) ---
    ours_deg = our_jaw_degrees(aa["motion"])
    driver = {"our_jaw_degrees": ours_deg}
    for label, export in ziva.items():
        theirs = ziva_jaw_degrees(export["motion"])
        driver[f"ziva_{label}_jaw_degrees"] = theirs
        driver[f"largest_difference_to_ziva_{label}_degrees"] = max(abs(a - b) for a, b in zip(ours_deg, theirs))

    # --- neutral to AA: the two layers against the same frames of both Ziva runs ---
    def last_poses(stats: dict) -> dict:
        return {f"frame_{f}": {k: stats[k][f] for k in ("mean_mm", "p95_mm", "max_mm")} for f in (MOTION_STOPS, frames - 1)}

    aa_tables = {}
    for layer, mine, theirs in (("physics", aa["physics"], z_physics), ("final", aa["final"], z_final)):
        aa_tables[layer] = {}
        for label in ziva:
            stats = compare.per_frame(mine, theirs[label])
            stats["last_pose"] = last_poses(stats)
            aa_tables[layer][f"against_ziva_{label}"] = stats
    between = compare.per_frame(z_physics["full_face"], z_physics["lips_only"])
    between["last_pose"] = last_poses(between)

    # --- gravity sag, frames 0..14, every frame against frame 0, all vertices ---
    sag = {"frames": list(range(SETTLE + 1)), "vertices": int(aa["physics"].shape[1]), "reference_frame": 0}
    for label, shape in (("ours", aa["physics"]), ("ziva_full_face", z_physics["full_face"]),
                         ("ziva_lips_only", z_physics["lips_only"])):
        d = compare.displacement(shape[: SETTLE + 1], 0, direction=DOWN)
        d["step_frame_13_to_14_max_mm"] = float(np.linalg.norm(shape[SETTLE] - shape[SETTLE - 1], axis=1).max())
        sag[label] = d

    # --- head shake: the same vertices, base frame, stop frame and window on both sides ---
    z_shake = ziva_export(trip, SHAKE)
    z_shake_physics = to_mm(z_shake["lips_physics"], mm)
    bones = z_shake["motion"]["bones"]
    skull = np.array([np.asarray(b["zBone2"], dtype=np.float64).ravel()[12:15] for b in bones])
    skull_mm = mm * ((skull - skull[0]) @ TURN.T)

    def translation(t):
        m = np.eye(4)
        m[:3, 3] = t
        return m

    z_wobble = compare.wobble(z_shake_physics, [translation(t) for t in skull_mm], SETTLE)
    head = shake["motion"].drivers["head"]
    o_wobble = compare.wobble(shake["physics"], head, SETTLE)
    window = min(len(o_wobble["per_frame_max_mm"]), len(z_wobble["per_frame_max_mm"])) - 1 - SHAKE_STOPS
    head_shake = {
        "vertices": "all 10240 display vertices on both sides", "base_frame": SETTLE, "stop_frame": SHAKE_STOPS,
        "window_frames_after_stop": int(window), "limit_mm": WOBBLE_LIMIT_MM,
        "scope": {"ours": "lips only", "ziva": "full face (there is no lips-only head shake from Ziva)"},
        "ours": {"frames": len(o_wobble["per_frame_max_mm"]), "wobble": o_wobble,
                 "head_travel_max_mm": float(max(abs(np.array(t).reshape(4, 4)[0, 3]) for t in head)),
                 "decay": compare.decay(o_wobble["per_frame_max_mm"], SHAKE_STOPS, WOBBLE_LIMIT_MM, window),
                 "free_vertices_only_max_mm": shake["report"]["relative_to_head"].get("max_mm"),
                 "checks": checks(shake["report"])},
        "ziva": {"frames": len(z_wobble["per_frame_max_mm"]), "wobble": z_wobble,
                 "head_travel_max_mm": float(np.abs(skull_mm).max()),
                 "decay": compare.decay(z_wobble["per_frame_max_mm"], SHAKE_STOPS, WOBBLE_LIMIT_MM, window),
                 "decay_over_its_whole_run": compare.decay(z_wobble["per_frame_max_mm"], SHAKE_STOPS, WOBBLE_LIMIT_MM)},
        "notes": ["a comparison across scopes: we have the lips alone, Ziva's run is the full face",
                  "in Ziva's run only the skull and the jaw were moved; 8 other bones stayed, and tissue stuck to "
                  "them is held back, so Ziva's number is not inertia alone (docs/13 E-15)",
                  "our number is not converged in the time step (docs/09 T-33); it is shown side by side only"],
    }

    # --- surface quality (ADR-43): flipped faces and short edges, ours beside Ziva's ---
    rest = aa["physics"][0]
    surfaces = {"ours_physics": surface(rest, aa["physics"], triangles), "ours_final": surface(rest, aa["final"], triangles)}
    for label in ziva:
        surfaces[f"ziva_{label}_physics"] = surface(z_physics[label][0], z_physics[label], triangles)
        surfaces[f"ziva_{label}_final"] = surface(z_final[label][0], z_final[label], triangles)
    report_health = aa["report"]["surface_health"]["final"]
    if report_health["last"]["flipped_faces"] != surfaces["ours_final"]["last"]["flipped"]:
        raise SystemExit("this tool and the run report count flipped faces differently; one of them is wrong")
    listed = sorted({*surfaces["ours_final"]["frames_with_flipped_faces"]})
    surfaces["ours_final_flipped_faces"] = where_flipped(rest, aa["final"], z_final, triangles, listed)

    # --- speed: two machines, two thread counts, two mesh sizes; orders of magnitude only ---
    tets, _ = tetmesh.load(aa["folder"] / "meshes" / "lips_tet.json")
    quality = tetmesh.quality(tets)
    attributes = json.loads((trip / "ziva_static" / "ziva_attributes.json").read_text(encoding="utf-8"))
    machine = json.loads((trip / "probes" / "machine.json").read_text(encoding="utf-8"))
    timing = aa["report"]["timing"]
    speed = {
        "ours": {"what": "FEBio's own run time, and separately the generator and the post-processing (which writes the files)",
                 "machine": "the developer's machine", "logical_processors": os.cpu_count(), "febio_threads": aa["threads"],
                 "frames": frames, "febio_s": timing["febio_s"], "febio_s_per_frame": timing["febio_s_per_frame"],
                 "generate_s": timing["generate_s"], "post_s": timing["post_s"],
                 "one_step_is": f"one frame ({scene.solver.substeps_per_frame.value} step per frame)",
                 "mesh": {"nodes": quality.nodes, "tets": quality.tets, "median_edge_mm": quality.median_edge_mm}},
        "ziva": {"machine": "the lab's Ziva machine", "logical_processors": machine["cpu_count"],
                 "maya_threads": machine["maya_threads"], "solver_threads_used": "not measured",
                 "one_step_is": "one frame (1 substep per frame)",
                 "export_s_per_frame_with_reading_and_writing": {
                     label: export["report"].get("seconds_per_frame") for label, export in ziva.items()},
                 "solver_log": ZIVA_SOLVER_LOG,
                 "mesh": {"lips_tet_size_scene_units": attributes["zTet1"]["attributes"]["tetSize"],
                          "lips_tet_size_mm": attributes["zTet1"]["attributes"]["tetSize"] * mm,
                          "tets": "not fetched"}},
        "note": "across machines and thread counts, and the lips' tets differ about tenfold in size: orders of "
                "magnitude only (docs/13 E-18). Solver time and export time are different things and are not mixed. "
                "Our number is a whole run's time divided by its frames; Ziva's solver number is a per-step time "
                "from its log: two different measures, so no ratio of the two is given",
    }

    report = {
        "format": FORMAT,
        "made": {"tool": "tools/ziva_comparison.py", "date": datetime.date.today().isoformat(),
                 "our_runs": {"aa": aa["report"]["run_id"], "head_shake": shake["report"]["run_id"]},
                 "ziva_runs": {**{k: v["name"] for k, v in ziva.items()}, "head_shake": z_shake["name"]},
                 "lab_motion": {"file": "/".join(lab_motion.parts[-3:]),
                                "sha256": hashlib.sha256(lab_motion.read_bytes()).hexdigest()}},
        "read_this_first": [
            "No pass line: the distance to Ziva is reported, not judged (ADR-17).",
            "ziva_full_face is the reference (the lab's real setup). ziva_lips_only is a sensitivity experiment we "
            "made by switching 42 objects off; its boundary conditions are not ours and it is still falling at frame 14.",
            "Ziva's runs were played by our script from the lab's motion file, not by a researcher in the lab's interface.",
            "physics = before the landmark layer (rest shape + gravity settle + what the jaw drags along); "
            "final = the same frame's physics + the same frame's landmark layer. Neither is compared with the target pose.",
            "Every 'last pose' number names its frame: 36 (the motion has just stopped) or 46 (held 10 frames more).",
            "Each side is in its own world geometry; the physical scales are not aligned (docs/11 D18), so a difference "
            "is a difference, not yet an explanation.",
        ],
        "settings": {"tissue_settings": tissue_settings, "material": material,
                     "substeps_per_frame": {"value": scene.solver.substeps_per_frame.value,
                                            "source": scene.solver.substeps_per_frame.source},
                     "fps": {"value": scene.solver.fps.value, "source": scene.solver.fps.source},
                     "ziva_measured": {"E_kPa": 12.0, "poisson": 0.4, "density_kg_m3": 1060.0, "substeps": 1, "fps": 30.0},
                     "not_matched": unmatched(scene, attributes, aa["report"]["generator"])},
        "differences_between_the_setups": DIFFERENCES,
        "driver": driver,
        "neutral_to_AA": {"frames": frames, "vertices": int(aa["physics"].shape[1]), "motion_frames": [15, MOTION_STOPS],
                          "hold_frames": [MOTION_STOPS + 1, frames - 1], "checks": checks(aa["report"]),
                          "physics": aa_tables["physics"], "final": aa_tables["final"],
                          "ziva_full_face_against_ziva_lips_only_physics": between},
        "gravity_sag": {**sag, "notes": [
            "ziva_lips_only at frame 14 is a snapshot of a lip that is still falling, not a settled shape",
            "what Ziva's sag is once settled is not known; it needs a longer gravity-only run in Ziva (docs/11 D17)",
            "Ziva's reference frame is its frame 14; it is not moved later to suit our own settle check"]},
        "head_shake": head_shake,
        "surface": {**surfaces, "note": "reported, not judged; Ziva's own numbers are the reference line (ADR-43). "
                                        "A green plausibility line does not say the surface is fine"},
        "speed": speed,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rounded(report), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def row(stats, f):
        return f"mean {stats['mean_mm'][f]:6.3f}  p95 {stats['p95_mm'][f]:6.3f}  max {stats['max_mm'][f]:6.3f}"

    print(f"material   E {material['E_mpa']['value']} MPa ({material['E_mpa']['source']}), nu {material['nu']['value']}")
    for layer in ("physics", "final"):
        for label in ziva:
            stats = aa_tables[layer][f"against_ziva_{label}"]
            print(f"AA {layer:<7} vs Ziva {label:<9} frame 36: {row(stats, MOTION_STOPS)}   frame {frames - 1}: {row(stats, frames - 1)} mm")
    print(f"Ziva full face vs Ziva lips only (physics)  frame 36: {row(between, MOTION_STOPS)} mm")
    for label in ("ours", "ziva_full_face", "ziva_lips_only"):
        s = sag[label]
        print(f"sag {label:<15} frame 14: max {s['max_mm'][SETTLE]:.3f}  mean {s['mean_mm'][SETTLE]:.3f}  along gravity "
              f"{s['along_mm'][SETTLE]:.3f} mm; still moving {s['step_frame_13_to_14_max_mm']:.4f} mm from frame 13 to 14")
    for label in ("ours", "ziva"):
        h = head_shake[label]
        print(f"shake {label:<5} wobble max {h['wobble']['max_mm']:.3f} mm (frame {h['wobble']['frame']}); after the stop first below "
              f"{WOBBLE_LIMIT_MM} mm: {h['decay']['first_below']}, stays below: {h['decay']['stays_below']} (window {window} frames)")
    for label, s in surfaces.items():
        if isinstance(s, dict):
            print(f"surface {label:<26} worst frame {s['worst']['frame']:2d}: {s['worst']['flipped']} flipped; last frame: "
                  f"{s['last']['flipped']} flipped, {s['last']['short_edges']} short edges")
    print(f"speed ours: FEBio {timing['febio_s']} s for {frames} frames = {timing['febio_s_per_frame']} s per frame, "
          f"{aa['threads']} threads of {os.cpu_count()}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
