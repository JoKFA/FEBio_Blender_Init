import argparse
import json
from dataclasses import asdict

from asrp_core import __version__
from asrp_core.doctor import run_checks


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
        print(f"WARN   {w}")


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
        result = lab.import_asset(Path(args.export), Path(args.out), tet, args.mm_per_scene_unit)
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
        result = run.execute(prepared, Path(args.runs_dir), febio_exe(), args.name, show, None, args.timeout)
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


def run_scene(args: argparse.Namespace, show) -> int:
    from pathlib import Path

    from asrp_core import run, simulate
    from asrp_core.doctor import febio_exe

    try:
        result = simulate.run_scene(Path(args.scene), Path(args.trajectory), Path(args.runs_dir), febio_exe(),
                                    args.name, show, None, args.timeout)
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
        extra = (f", {grp['spring_nodes']} spring nodes, {len(grp['levels_n_per_mm'])} levels, shared {grp['nodes_shared_with_other_spring_groups']}"
                 if grp["kind"] == "spring" else "")
        print(f"group      {grp['name']} ({grp['kind']} -> {grp['to']}): {grp['display_vertices']} vertices, {grp['nodes']} nodes, "
              f"{grp['clipped_coordinates']} clipped, {grp['conflicts']} conflicts, max distance {grp['max_distance_mm']:.3f} mm{extra}")
    for name, s in r.get("spring_slip", {}).items():
        print(f"slip       {name}: max|u|/delta = {s['ratio']:.2e}{'  FLAG: above 0.1, raise delta' if s['flag'] else ''}")
    for key, c in r["checks"].items():
        verdict = {True: "PASS", False: "FAIL", None: "NOT RUN"}[c["passed"]]
        print(f"check {key}    [{verdict}] {c['name']}: {c['message']}")
    t = r["timing"]
    if t.get("febio_s_per_frame") is not None:
        print(f"timing     FEBio {t['febio_s']} s, {t['febio_s_per_frame']} s per frame (budget {t['budget_s_per_frame']}, "
              f"reported only); generate {t['generate_s']} s, post {t['post_s']} s")
    print(f"report     {result.run_dir / simulate.REPORT}")
    if result.status == "complete":
        print(f"run COMPLETE: {r['frames']} frames; plausibility {'PASSED' if result.passed else 'FAILED'}")
        return 0 if result.passed else 1
    if result.status == "cancelled":
        print("run CANCELLED; FEBio stopped, no results written")
        return 2
    print(f"ERROR  {r['checks']['a']['message']}")
    print("run FAILED: no results written")
    return 1


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
    imp.set_defaults(func=cmd_import_asset)

    r = sub.add_parser("run", help="run a scene with a motion (or a ready .feb) once, everything in a run folder")
    r.add_argument("scene", nargs="?", help="path of scene.json")
    r.add_argument("trajectory", nargs="?", help="path of trajectory.json")
    r.add_argument("--feb", help="stand-in mode: run this existing .feb as is")
    r.add_argument("--runs-dir", default="runs", help="where run folders go (default: runs; English-only path)")
    r.add_argument("--name", help="name for the run folder (default: the trajectory's or the .feb's name)")
    r.add_argument("--timeout", type=float, default=3600, help="stop FEBio after this many seconds")
    r.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
