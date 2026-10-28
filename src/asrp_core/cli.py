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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="asrp")
    parser.add_argument("--version", action="version", version=f"asrp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check that FEBio, Blender and Python are usable")
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
