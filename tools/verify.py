"""The project's check, in three levels. Before every merge request run the full one (the definition of done):

    uv run python tools/verify.py                 # full
    uv run python tools/verify.py --level auto    # picks a level from the files that changed (the Stop hook uses this)

Levels, each containing the one before:
- docs: the lint check (`ruff check .`; it does not enforce line length and nothing is reformatted), the check that
  no lab or vendor file is tracked by git (`tools/check_no_lab_files.py`), and the tests about the documents and
  about this gate. About ten seconds.
- core: the whole test suite without the slow real-lip run. About three minutes.
- full: the test suite with ASRP_SLOW=1 (the real-lip run in tests/test_prototype.py), `asrp doctor`, Blender's own
  validation of the add-on manifest, the Blender add-on round trip, the FEBio -> Blender playback check, and the
  panel check (real `asrp run` processes: complete, cannot start, cancelled). The three Blender scripts load the
  add-on from source, which skips packaging, so only the manifest step would notice an add-on that cannot be built.

`auto` looks at the uncommitted files and the files of the last commit: only documents -> docs; anything under
blender_addon/ -> full; otherwise core. It never replaces the full run before a merge request.
Blender is found the same way `asrp doctor` finds it ($ASRP_BLENDER, PATH, default install location), so nothing
is tied to one machine. Writes nothing into the repo. Exits non-zero on the first failure.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from asrp_core.doctor import BLENDER_CANDIDATES, locate  # noqa: E402


def step(name: str, cmd: list[str], extra_env: dict | None = None) -> None:
    print(f"\n=== {name}", flush=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}
    if subprocess.run(cmd, cwd=REPO, env=env).returncode != 0:
        sys.exit(f"verify FAILED at: {name}")


DOC_TESTS = ["tests/test_docs_references.py", "tests/test_verify_gate.py", "tests/test_no_lab_files.py",
             "tests/test_prototype_page.py"]  # the results page is a document too
LEVELS = ("docs", "core", "full")


def changed_files() -> list[str]:
    """Uncommitted files plus the files of the last commit, as repo-relative paths."""
    def lines(*args):
        done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        return [x for x in done.stdout.splitlines() if x.strip()] if done.returncode == 0 else []
    status = [line[3:].split(" -> ")[-1].strip('"') for line in lines("status", "--porcelain")]
    return sorted(set(status + lines("diff", "--name-only", "HEAD~1", "HEAD")))


def pick_level(files: list[str]) -> str:
    """docs when only documents changed, full when the Blender add-on changed, core otherwise.
    With nothing changed there is nothing to pick from, so the answer is the full run."""
    if not files:
        return "full"
    if any(f.startswith("blender_addon/") for f in files):
        return "full"
    if all(f.startswith("docs/") or f.endswith(".md") for f in files):
        return "docs"
    return "core"


def main(argv: list[str] | None = None) -> None:
    args = list(argv or [])
    level = "full"
    if args[:1] == ["--level"] and len(args) == 2 and args[1] in (*LEVELS, "auto"):
        level = args[1]
    elif args:
        sys.exit("usage: verify.py [--level docs|core|full|auto]")
    if level == "auto":
        level = pick_level(changed_files())
    print(f"verify level: {level}", flush=True)
    pytest = [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider"]  # -rs: say why a test was skipped
    step("lint", [sys.executable, "-m", "ruff", "check", "."])
    step("no lab or vendor files in git", [sys.executable, str(REPO / "tools" / "check_no_lab_files.py")])
    if level == "docs":
        step("tests", pytest + DOC_TESTS)
        print("\nverify PASSED (docs level; run the full level before a merge request)")
        return
    if level == "core":
        step("tests", pytest)
        print("\nverify PASSED (core level; run the full level before a merge request)")
        return
    step("tests", pytest, {"ASRP_SLOW": "1"})
    step("asrp doctor", [sys.executable, "-m", "asrp_core.cli", "doctor"])
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        sys.exit(f"verify FAILED: Blender {blender.how}")
    step("add-on manifest", [str(blender.path), "--factory-startup", "--command", "extension", "validate",
                             str(REPO / "blender_addon" / "asrp_blender")])
    for check in ("check_blender_addon.py", "check_playback.py", "check_panel.py"):
        step(check, [str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1",
                     "--python", str(REPO / "tools" / check)])
    print("\nverify PASSED")


if __name__ == "__main__":
    main(sys.argv[1:])
