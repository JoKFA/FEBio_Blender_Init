"""The project's definition-of-done check. Run it before every merge request:

    uv run python tools/verify.py

Runs, in order: the test suite (with ASRP_SLOW=1, so the real-lip run in tests/test_prototype.py is
included; it takes several minutes), `asrp doctor`, Blender's own validation of the add-on
manifest, the Blender add-on round trip, and the FEBio -> Blender playback check. The two
Blender scripts load the add-on from source, which skips packaging, so only the manifest
step would notice an add-on that cannot be built. Blender is found the same way
`asrp doctor` finds it ($ASRP_BLENDER, PATH, default install location), so nothing is tied
to one machine.
Writes nothing into the repo. Exits non-zero on the first failure.
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


def main() -> None:
    step("tests", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], {"ASRP_SLOW": "1"})
    step("asrp doctor", [sys.executable, "-m", "asrp_core.cli", "doctor"])
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        sys.exit(f"verify FAILED: Blender {blender.how}")
    step("add-on manifest", [str(blender.path), "--factory-startup", "--command", "extension", "validate",
                             str(REPO / "blender_addon" / "asrp_blender")])
    for check in ("check_blender_addon.py", "check_playback.py"):
        step(check, [str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1",
                     "--python", str(REPO / "tools" / check)])
    print("\nverify PASSED")


if __name__ == "__main__":
    main()
