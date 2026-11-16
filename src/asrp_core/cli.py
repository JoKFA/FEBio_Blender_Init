import argparse
import json
from dataclasses import asdict

from asrp_core import __version__, febio
from asrp_core.doctor import run_checks


def thread_count(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a thread count; give a whole number, 1 or more")
    return n


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_checks()
    if args.json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        for c in checks:
            print(f"[{c.status:5}] {c.name:12} {c.detail}")
    return 1 if any(c.status == "error" for c in checks) else 0


def print_check(report) -> None:
    for e in report.errors:
        print(f"ERROR  {e}")
    for w in report.warnings:
        print(f"WARNING  {w}")


def cmd_check(args: argparse.Namespace) -> int:
    from asrp_core import scene

    report = scene.check(args.scene, args.trajectory)
    s = report.scene
    if s is not None:
        k = s.units.physics_length_scale
        print(f"scene      {args.scene} ({scene.FORMAT_VERSION})")
        print(f"units      mm_per_scene_unit {s.units.mm_per_scene_unit.value} ({s.units.mm_per_scene_unit.source}), "
              f"physics_length_scale {k.value} ({k.source}{', default' if s.units.physics_length_scale_defaulted else ''}), "
              f"axes {s.units.axes_from_source}")
        print(f"objects    {len(s.soft_tissues)} soft tissue, {len(s.bones)} bones "
              f"({sum(b.motion == 'fixed' for b in s.bones)} fixed, {sum(b.motion == 'prescribed' for b in s.bones)} "
              f"prescribed), {len(s.drivers)} drivers, {len(s.attachments)} attachments, "
              f"{0 if s.landmarks is None else len(s.landmarks.names)} landmarks")
    if report.trajectory is not None:
        t = report.trajectory
        print(f"trajectory {args.trajectory}: {t.frames} frames at {t.fps} fps, drivers {', '.join(t.drivers)}")
    print_check(report)
    verdict = "PASSED" if report.ok else "FAILED"
    print(f"check {verdict}: {len(report.errors)} errors, {len(report.warnings)} warnings")
    return 0 if report.ok else 1


def cmd_import_asset(args: argparse.Namespace) -> int:
    from pathlib import Path

    from asrp_core.asset import lab

    tet = Path(args.tetmesh) if args.tetmesh else Path(args.export) / ".." / "tetmesh" / "lips.json"
    try:
        result = lab.import_asset(Path(args.export), Path(args.out), tet, args.mm_per_scene_unit,
                                  tissue_settings=args.tissue_settings, attachment_rule=args.attachments)
    except lab.AssetError as e:
        print(f"ERROR  {e}")
        print("import FAILED")
        return 1
    r = result.report
    u = r["units"]
    print(f"scene      {r['scene']}")
    print(f"units      {u['mm_per_scene_unit']} mm per scene unit ({u['mm_per_scene_unit_source']}: {u['note']}), "
          f"axes {u['axes']}, physics_length_scale {u['physics_length_scale']}")
    for m in r["meshes"]:
        size = " x ".join(f"{v:.1f}" for v in m["size_mm"])
        print(f"mesh       {m['name']:12} {m['vertices']:6d} vertices  {size} mm  ({m['role']})")
    for name, d in r["drivers"].items():
        if "pivot_mm" not in d:  # no hinge (the head, T-28)
            rest = ", at rest when a motion leaves it out" if d.get("absent_means_rest") else ""
            print(f"driver     {name}: no hinge{rest}, moves {', '.join(d['moves'])}")
            continue
        pivot = ", ".join(f"{v:.2f}" for v in d["pivot_mm"])
        axis = ", ".join(f"{v:.3f}" for v in d["axis"])
        print(f"driver     {name}: pivot ({pivot}) mm, axis ({axis}), moves {', '.join(d['moves'])}")
    print(f"landmarks  {r['landmarks']}")
    by_source = {}
    for p in r["parameters"]:
        by_source.setdefault(p["source"], []).append(p["where"])
    for source, where in sorted(by_source.items()):
        print(f"params     {source}: {', '.join(where)}")
    for m in r["missing"]:
        print(f"missing    {m}")
    print_check(result.check)
    print(f"report     {Path(args.out) / 'import_report.json'}")
    verdict = "PASSED" if result.check.ok else "FAILED"
    print(f"import {verdict}: scene check {len(result.check.errors)} errors, {len(result.check.warnings)} warnings")
    return 0 if result.check.ok else 1


def cmd_convert_motion(args: argparse.Namespace) -> int:
    """A lab motion file (combined_checkpoints.pkl) of a segment that starts at rest -> trajectory.json."""
    import hashlib
    from pathlib import Path

    from asrp_core import scene, trajectory

    def fail(message: str) -> int:
        print(f"ERROR  {message}")
        print("convert FAILED")
        return 1

    if not args.starts_at_rest:
        return fail(
            "a lab motion file holds offsets from the start of its segment and does not say where that start is. "
            "If this segment starts at the rest pose (a transition FROM neutral), say so with --starts-at-rest. "
            "A segment that starts from another pose (AA back to neutral, say) cannot be converted on its own: "
            "it has to follow the segment that leads to its start, in one trajectory that begins at rest "
            "(docs/09 T-10)")
    try:
        s = scene.load(args.scene)
    except ValueError as e:
        return fail(f"{args.scene} cannot be read as a scene: {e}")
    jaw = next((d for d in s.drivers if d.name == args.driver), None)
    if jaw is None or jaw.hinge is None:
        return fail(f"{args.scene} has no driver {args.driver!r} with a hinge; the jaw's pivot comes from it. "
                    "Import the lab asset again (asrp import-asset)")
    if max(abs(a - b) for a, b in zip(jaw.hinge.axis, trajectory.LAB_WORLD_AXIS)) > 1e-6:
        return fail(f"driver {args.driver!r} has hinge axis {list(jaw.hinge.axis)}, but the lab's interface turns the "
                    "jaw about world X; this scene is not the lab asset the motion was made for")
    if s.landmarks is None:
        return fail(f"{args.scene} has no landmarks; import the lab asset (asrp import-asset), which carries them")
    motion_path = Path(args.motion)
    try:
        steps = trajectory.read_lab_motion(motion_path)
        digest = hashlib.sha256(motion_path.read_bytes()).hexdigest()
        # the file's own name and its two folders (job and run), never the path on this machine
        origin = "/".join(motion_path.resolve().parts[-3:])
        motion = trajectory.from_lab_motion(
            steps, driver=args.driver, pivot_mm=jaw.hinge.pivot_mm, landmark_names=s.landmarks.names,
            mm_per_scene_unit=s.units.mm_per_scene_unit.value, fps=s.solver.fps.value,
            hold_frames=args.hold_frames, source=f"{origin} (sha256 {digest})")
    except trajectory.TrajectoryError as e:
        return fail(str(e))
    if args.title is not None:
        motion.title = args.title
        try:
            trajectory.from_json(motion.to_json())
        except trajectory.TrajectoryError as e:
            return fail(str(e))
    trajectory.write(args.out, motion)
    report = scene.check(args.scene, args.out)
    moved = max(max(sum(c * c for c in t) ** 0.5 for t in row) for row in motion.landmarks["translations_mm"])
    print(f"motion     {origin}: {len(steps)} steps, sha256 {digest}")
    print(f"trajectory {args.out}: {motion.frames} frames at {motion.fps} fps, settle until frame "
          f"{motion.settle_until_frame}, {args.driver} turns to {steps[-1, 900]:.5f} degrees about world X, "
          f"{len(motion.landmarks['names'])} landmarks move at most {moved:.3f} mm")
    print_check(report)
    verdict = "PASSED" if report.ok else "FAILED"
    print(f"convert {verdict}: scene and trajectory check {len(report.errors)} errors, {len(report.warnings)} warnings")
    return 0 if report.ok else 1


def cmd_set_motion_title(args: argparse.Namespace) -> int:
    from asrp_core import motions, trajectory

    try:
        motions.set_title(args.file, args.title)
    except trajectory.TrajectoryError as e:
        print(f"ERROR  {e}")
        return 1
    print(f"title      {args.file}: {args.title}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """One run of ours against a Ziva export folder (T-11): report, heat-map data, Ziva's lips as a playback package."""
    from asrp_core import compare, ziva_compare

    try:
        report = ziva_compare.compare_run(args.run, args.ziva, args.out, args.target)
    except (ziva_compare.CompareRunError, compare.CompareError) as e:
        print(f"ERROR  {e}")
        print("compare FAILED: nothing compared")
        return 1
    for line in ziva_compare.summary_lines(report):
        print(line)
    print(f"report     {args.out}/{ziva_compare.REPORT}")
    print("compare DONE: the differences are reported, not judged (no pass line, ADR-17)")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from pathlib import Path

    from asrp_core import run
    from asrp_core.doctor import febio_exe

    def show(p: run.Progress) -> None:
        print(f"progress   frame {p.done} / {p.total if p.total is not None else '?'}", flush=True)

    if args.scene or args.trajectory:
        if args.feb or not (args.scene and args.trajectory):
            print("ERROR  Give either <scene.json> <trajectory.json>, or --feb <existing .feb>.")
            return 2
        return run_scene(args, show)
    if not args.feb:
        print("ERROR  Give <scene.json> <trajectory.json>, or --feb <existing .feb>.")
        return 2

    try:
        prepared = run.standin(Path(args.feb))
        result = run.execute(prepared, Path(args.runs_dir), febio_exe(), args.name, show, None, args.timeout, args.threads)
    except (run.RunError, FileNotFoundError) as e:
        print(f"ERROR  {e}")
        return 1
    print(f"run folder {result.run_dir}")
    if result.status == "complete":
        print(f"run COMPLETE: {result.frames} frames")
        return 0
    if result.status == "cancelled":
        print(f"run CANCELLED after {result.frames} frames; FEBio stopped, no results written")
        return 2
    f = result.failure
    print(f"ERROR  {f'frame {f.frame}' if f.frame is not None else 'before the first frame'}: {f.message}")
    print("run FAILED: no results written")
    return 1


def surface_text(h: dict) -> str:
    return (f"{h['flipped_faces']} flipped faces of {h['faces']}, {h['edges_shorter_than_half']} edges < 0.5x, "
            f"{h['edges_longer_than_double']} edges > 2x, edge ratio {h['edge_ratio_min']:.3f}..{h['edge_ratio_max']:.3f}")


def run_scene(args: argparse.Namespace, show) -> int:
    from pathlib import Path

    from asrp_core import run, simulate
    from asrp_core.doctor import febio_exe

    try:
        result = simulate.run_scene(Path(args.scene), Path(args.trajectory), Path(args.runs_dir), febio_exe(),
                                    args.name, show, None, args.timeout, args.threads,
                                    on_start=lambda d: print(f"run folder {d}", flush=True))
    except (simulate.SceneRunError, run.RunError, FileNotFoundError) as e:
        print(f"ERROR  {e}")
        print("run NOT STARTED")
        return 1
    r = result.report
    g = r["generator"]
    print(f"run folder {result.run_dir}")
    print(f"generator  k {g['physics_length_scale_k']}, {g['febio_nodes']['tissue']} tet nodes, {g['tets']} tets, "
          f"{g['hard_nodes']} hard nodes, {g['springs']} springs, display max distance {g['display_max_distance_mm']:.3f} mm "
          f"(limit {g['max_distance_limit_mm']:.3f})")
    for grp in g["groups"]:
        extra = (f", {grp['spring_nodes']} spring nodes, {grp['level_count']} levels (max error {grp['max_level_error']:.2%}), shared {grp['nodes_shared_with_other_spring_groups']}"
                 if grp["kind"] == "spring" else "")
        print(f"group      {grp['name']} ({grp['kind']} -> {grp['to']}): {grp['display_vertices']} vertices, {grp['nodes']} nodes, "
              f"{grp['clipped_coordinates']} clipped, {grp['conflicts']} conflicts, max distance {grp['max_distance_mm']:.3f} mm{extra}")
    for w in r.get("warnings", []):
        print(f"WARNING  {w}")
    for name, s in r.get("spring_slip", {}).items():
        print(f"slip       {name}: max|u|/delta = {s['ratio']:.2e}{'  FLAG: above 0.1, raise delta' if s['flag'] else ''}")
    for key, c in r["checks"].items():
        verdict = {True: "PASS", False: "FAIL", None: "NOT RUN"}[c["passed"]]
        print(f"check {key}    [{verdict}] {c['name']}: {c['message']}")
    layer = r.get("landmark_layer")
    if layer and layer["applied"]:
        print(f"landmarks  applied: {layer['landmarks_moved']} moved, largest translation {layer['max_translation_mm']:.3g} mm, "
              f"final differs from physics by at most {layer['max_final_minus_physics_mm']:.3g} mm (frame {layer['frame']})")
    elif layer:
        print(f"landmarks  not applied: {layer['reason']}")
    back = r.get("return_to_settled")
    if back and back["frames"]:
        print(f"returns    drivers back at rest on frame(s) {', '.join(map(str, back['frames']))}: nodes are at most "
              f"{back['max_mm']:.2e} mm (mean {back['mean_mm']:.2e} mm) from the settled shape (reported only)")
    health = r.get("surface_health")
    for version in ("physics", "final"):
        h = (health or {}).get(version)
        if h:
            worst = h["worst"]
            more = f"; worst frame {worst['frame']}: {surface_text(worst)}" if worst["frame"] != r["frames"] - 1 else ""
            print(f"surface    {version}, last frame: {surface_text(h['last'])}{more} (reported only)")
    settled = r.get("settled_shape") or {}
    if "tissue_step_max_mm" in settled:
        before, now = settled["tissue_step_frames"]
        still = settled.get("tissue_settled")
        verdict = "" if still is None else (f"; settled (limit {settled['tissue_settled_limit_mm']:g} mm)" if still else
                                            f"; NOT SETTLED: above the {settled['tissue_settled_limit_mm']:g} mm limit, the "
                                            "settled shape is still moving (give the motion a longer settle)")
        print(f"settle     frame {now}: the tissue moved at most {settled['tissue_step_max_mm']:.2e} mm since frame {before}"
              f"{verdict} (reported only)")
    t = r["timing"]
    if t.get("febio_s_per_frame") is not None:
        print(f"timing     FEBio {t['febio_s']} s, {t['febio_s_per_frame']} s per frame; "
              f"generate {t['generate_s']} s, post {t['post_s']} s")
    print(f"report     {result.run_dir / simulate.REPORT}")
    if result.status == "complete":
        skipped = r.get("not_run", {})
        note = f" ({len(skipped)} not run: {'; '.join(f'{k}: {m}' for k, m in skipped.items())})" if skipped else ""
        print(f"run COMPLETE: {r['frames']} frames; plausibility {'PASSED' if result.passed else 'FAILED'}{note}")
        return 0 if result.passed else 1
    if result.status == "cancelled":
        print("run CANCELLED; FEBio stopped, no results written")
        return 2
    print(f"ERROR  {r['checks']['a']['message']}")
    print("run FAILED: no results written")
    return 1


def cmd_list_motions(args: argparse.Namespace) -> int:
    from asrp_core import motions

    try:
        found = motions.list_motions(args.folder)
    except motions.MotionsError as e:
        print(f"ERROR  {e}")
        return 1
    for line in motions.lines(found):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="asrp")
    parser.add_argument("--version", action="version", version=f"asrp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check that FEBio, Blender and Python are usable")
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(func=cmd_doctor)

    check = sub.add_parser("check", help="check a scene.json, and optionally a trajectory.json against it")
    check.add_argument("scene", help="path of scene.json")
    check.add_argument("trajectory", nargs="?", help="path of trajectory.json (optional)")
    check.set_defaults(func=cmd_check)

    imp = sub.add_parser("import-asset", help="turn a Maya export (data/lab_export) into a scene.json")
    imp.add_argument("export", help="the export folder from tools/maya_export.py")
    imp.add_argument("out", help="an empty or new folder for scene.json, meshes/ and the report")
    imp.add_argument("--mm-per-scene-unit", type=float, default=0.962,
                     help="geometry scale, mm per scene unit (default 0.962, the lab controller's conversion, ADR-31)")
    imp.add_argument("--tetmesh", help="the lip tet mesh (default: <export>/../tetmesh/lips.json)")
    imp.add_argument("--tissue-settings", choices=("ours", "lab"), default="lab",
                     help="lab (default): the Young's modulus (12 kPa), Poisson's ratio (0.4), density and substeps "
                          "measured in the lab's Ziva scene (docs/03 section 5). ours: our earlier material (15 kPa, "
                          "0.45). In both, the material model, damping, gravity and physical scale stay ours")
    imp.add_argument("--attachments", choices=("ours", "ziva-soft"), default="ours",
                     help="ours (default): upper lip hard, the others springs of 100 x E x h. ziva-soft: all four "
                          "groups springs of Ziva's 0.1 N/mm3 x the group's mean lip-surface area per vertex x k^2 "
                          "(docs/05 section 3); for tet meshes so coarse that the lips share tet nodes")
    imp.set_defaults(func=cmd_import_asset)

    conv = sub.add_parser("convert-motion",
                          help="turn a lab motion file (combined_checkpoints.pkl) that starts at rest into a trajectory.json")
    conv.add_argument("motion", help="the lab's motion file, as fetched (read as data; nothing in it is run)")
    conv.add_argument("scene", help="path of scene.json (the jaw's pivot, the landmark names and the units come from it)")
    conv.add_argument("out", help="where to write trajectory.json")
    conv.add_argument("--starts-at-rest", action="store_true",
                      help="required: confirms that this segment starts at the rest pose (the file does not say)")
    conv.add_argument("--driver", default="jaw01", help="the scene's jaw driver (default jaw01)")
    conv.add_argument("--hold-frames", type=int, default=10,
                      help="frames the last pose is held (default 10, as in the Ziva reference runs)")
    conv.add_argument("--title", help="the name the Blender panel shows for this motion (one line, at most 34 characters)")
    conv.set_defaults(func=cmd_convert_motion)

    st = sub.add_parser("set-motion-title", help="put a title (the name the Blender panel shows) into a trajectory.json")
    st.add_argument("file", help="the trajectory file")
    st.add_argument("title", help="one line, at most 34 characters")
    st.set_defaults(func=cmd_set_motion_title)

    lm = sub.add_parser("list-motions", help="list the trajectory files of an export folder, one JSON line each")
    lm.add_argument("folder", help="the export folder (it has a trajectories/ folder), or a folder of trajectory files")
    lm.set_defaults(func=cmd_list_motions)

    r = sub.add_parser("run", help="run a scene with a motion (or a ready .feb) once, everything in a run folder")
    r.add_argument("scene", nargs="?", help="path of scene.json")
    r.add_argument("trajectory", nargs="?", help="path of trajectory.json")
    r.add_argument("--feb", help="stand-in mode: run this existing .feb as is")
    r.add_argument("--runs-dir", default="runs", help="where run folders go (default: runs; English-only path)")
    r.add_argument("--name", help="name for the run folder (default: the trajectory's or the .feb's name)")
    r.add_argument("--timeout", type=float, default=3600, help="stop FEBio after this many seconds")
    r.add_argument("--threads", type=thread_count, default=febio.DEFAULT_THREADS,
                   help=f"FEBio threads (default {febio.DEFAULT_THREADS}, never more than this machine's CPUs); "
                        "1 gives bit-identical results, more gives results within 1e-9 mm")
    r.set_defaults(func=cmd_run)

    cmp = sub.add_parser("compare", help="compare a run of ours with a Ziva export folder: report, heat maps, "
                                         "Ziva's lips as a playback package")
    cmp.add_argument("run", help="our run folder (made by asrp run)")
    cmp.add_argument("ziva", help="a Ziva export folder (the lab's data, outside the repository)")
    cmp.add_argument("--out", required=True,
                     help="where to write the report, the heat-map data and Ziva's playback package. It holds Ziva's "
                          "shapes, so it must be outside the repository, or under its git-ignored runs/")
    cmp.add_argument("--target", help="the lab's target-pose file (dataV22_phoneme_AA_for_d2.py), for the distance "
                                      "to the artist's target pose; without it that number is reported as not available")
    cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
