"""Make the archives and pictures that docs/15 stands on, with the product's own commands.

    uv run python tools/prototype_archive.py [--work <folder>] [--threads 4] [--note "<what else ran>"]
                                             [--no-render] [--out data/preview]

For each of the two lip meshes (the coarse lattice with Ziva's soft attachments, which is the panel's default; the
fine mesh with the upper lip hard) it does what a researcher does by mouse, through the command line:

    asrp import-asset  ->  asrp run (neutral to AA, head shake, jaw opens 12 degrees)
    asrp compare       against Ziva's full-face run and against Ziva's lips-only run (the AA motion)
    tools/ziva_comparison.py   gravity sag, surface counts, head shake and speed (needs both runs of the mesh)

then copies the numbers into <out> (default data/preview) under names that say what they are, and calls
tools/render_comparison.py for the pictures. docs/15 takes every number from these files and
tests/test_prototype_page.py keeps the page and the files from drifting apart (tools/prototype_numbers.py).

Written to <out>:

    prototype_compare_<mesh>_<full_face|lips_only>.json   the `asrp compare` report (numbers only, no mesh, no path)
    prototype_ziva_comparison_<mesh>.json                 tools/ziva_comparison.py's report
    prototype_run_<mesh>_<aa|jaw>.json                    the run report of the AA run and of the 12 degree run
    prototype_archive_manifest.json                       when, from which commit, with which commands, what machine
    prototype_aa36_*.png, prototype_jaw32_*.png           the pictures (tools/render_comparison.py)

<mesh> is `coarse` or `fine`. The Ziva results stay outside the repository (tools/local_paths.py says where on this
machine); Blender runs with --background only. The work folder holds Ziva's shapes through `asrp compare`, so it is
a temporary folder outside the repository unless you name another.

--note is written to the manifest as it is: say what else ran on the machine while FEBio was timed, since the
seconds per frame depend on it. The tool cannot know.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import local_paths  # noqa: E402

MESHES = {
    "coarse": ["--tetmesh", "data/tetmesh/lips_lattice.json", "--attachments", "ziva-soft"],
    "fine": [],
}
FULL, LIPS_ONLY = "neutral_to_AA_export_*", "AA_lips_only_export_*"
AA_MOTION = REPO / "data" / "lab_export" / "trajectories" / "neutral_to_AA.json"
JAW_MOTION = REPO / "data" / "lab_export" / "trajectories" / "jaw_open_12deg.json"


def asrp(*args) -> str:
    done = subprocess.run([sys.executable, "-B", "-m", "asrp_core.cli", *map(str, args)], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    if done.returncode not in (0, 1) or "ERROR" in done.stdout:
        raise SystemExit(f"asrp {args[0]} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def run_folder(scene: Path, motion: Path, runs: Path, name: str, threads: int) -> Path:
    out = asrp("run", scene, motion, "--runs-dir", runs, "--name", name, "--threads", threads)
    line = next((ln for ln in out.splitlines() if ln.startswith("report ")), None)
    if line is None:
        raise SystemExit(f"asrp run printed no report line:\n{out}")
    folder = Path(line.split(None, 1)[1].strip()).parent
    report = json.loads((folder / "run_report.json").read_text(encoding="utf-8"))
    if report.get("status") != "complete":
        raise SystemExit(f"{folder.name} did not complete: {report.get('status')}")
    return folder


def export(trip: Path, pattern: str) -> Path:
    folders = sorted((trip / "ziva_reference").glob(pattern))
    if not folders:
        raise SystemExit(f"no Ziva export matches {pattern} in the trip data")
    return folders[-1]


def git(*args) -> str:
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", help="folder for the scenes, runs and comparison folders (default: a temporary one)")
    parser.add_argument("--out", default=str(REPO / "data" / "preview"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--note", default="", help="what else ran on this machine while FEBio was timed")
    parser.add_argument("--no-render", action="store_true", help="skip the pictures")
    args = parser.parse_args()

    trip = local_paths.ziva_trip()
    if trip is None:
        raise SystemExit("NOT RUN: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    work = Path(args.work).resolve() if args.work else Path(tempfile.mkdtemp(prefix="asrp_prototype_archive_"))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    full, lips_only = export(trip, FULL), export(trip, LIPS_ONLY)
    commands, runs = [], {}

    for mesh, options in MESHES.items():
        base = work / mesh
        shutil.rmtree(base, ignore_errors=True)
        scene_dir = base / "scene"
        asrp("import-asset", REPO / "data" / "lab_export", scene_dir, "--tissue-settings", "lab", *options)
        commands.append("asrp import-asset data/lab_export <scene folder> --tissue-settings lab " + " ".join(options))
        scene = scene_dir / "scene.json"
        shake = base / "head_shake.json"
        subprocess.run([sys.executable, "-B", str(REPO / "tools" / "head_shake_motion.py"), str(scene), str(shake)], cwd=REPO,
                       check=True, capture_output=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        runs[mesh] = {name: run_folder(scene, motion, base / "runs", name, args.threads)
                      for name, motion in (("aa", AA_MOTION), ("shake", shake), ("jaw", JAW_MOTION))}
        for kind, folder in (("full_face", full), ("lips_only", lips_only)):
            target = base / f"compare_{kind}"
            asrp("compare", runs[mesh]["aa"], folder, "--out", target)
            shutil.copyfile(target / "compare_report.json", out / f"prototype_compare_{mesh}_{kind}.json")
        subprocess.run([sys.executable, "-B", str(REPO / "tools" / "ziva_comparison.py"),
                        str(out / f"prototype_ziva_comparison_{mesh}.json"), "--aa-run", str(runs[mesh]["aa"]),
                        "--shake-run", str(runs[mesh]["shake"])], cwd=REPO, check=True,
                       env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        for name in ("aa", "jaw"):
            shutil.copyfile(runs[mesh][name] / "run_report.json", out / f"prototype_run_{mesh}_{name}.json")

    commands += [f"asrp run <scene> data/lab_export/trajectories/neutral_to_AA.json --threads {args.threads}",
                 f"asrp run <scene> <head shake from tools/head_shake_motion.py> --threads {args.threads}",
                 f"asrp run <scene> data/lab_export/trajectories/jaw_open_12deg.json --threads {args.threads}",
                 "asrp compare <AA run> <Ziva full-face export> --out <folder>  (and the lips-only export)",
                 "uv run python tools/ziva_comparison.py <report> --aa-run <AA run> --shake-run <shake run>"]
    if not args.no_render:
        subprocess.run([sys.executable, "-B", str(REPO / "tools" / "render_comparison.py"),
                        "--coarse-aa", str(runs["coarse"]["aa"]), "--fine-aa", str(runs["fine"]["aa"]),
                        "--coarse-jaw", str(runs["coarse"]["jaw"]), "--fine-jaw", str(runs["fine"]["jaw"]),
                        "--ziva", str(full), "--out", str(out)], cwd=REPO, check=True)
        commands.append("uv run python tools/render_comparison.py ...")
    manifest = {
        "format": "asrp-prototype-archive/1",
        "tool": "tools/prototype_archive.py",
        "date": datetime.date.today().isoformat(),
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "machine": f"the development machine (a Windows 11 PC, {os.cpu_count()} logical processors)",
        "febio_threads": args.threads,
        "what_else_ran": args.note or "not stated",
        "commands": commands,
        "meshes": {"coarse": "data/tetmesh/lips_lattice.json, --attachments ziva-soft",
                   "fine": "data/tetmesh/lips.json, default attachments (upper lip hard)"},
        "ziva_runs": {"full_face": full.name, "lips_only": lips_only.name},
    }
    (out / "prototype_archive_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"archives written to {out}")


if __name__ == "__main__":
    main()
