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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
