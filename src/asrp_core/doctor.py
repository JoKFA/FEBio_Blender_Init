"""Environment checks: can this machine run the Blender -> FEBio pipeline?

Status meanings: "ok"; "warn" = something is missing but nothing is broken
(e.g. FEBio not installed yet); "error" = a setting is wrong and would make
runs fail or silently use the wrong tool. Only errors make the CLI exit 1.
"""

import glob
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Default install locations are guesses until FEBio Studio is installed here;
# ASRP_FEBIO / ASRP_BLENDER always win.
FEBIO_CANDIDATES = [
    r"C:\Program Files\FEBio*\bin\febio4.exe",
    r"C:\Program Files\FEBio*\febio4.exe",
]
BLENDER_CANDIDATES = [r"C:\Program Files\Blender Foundation\Blender *\blender.exe"]


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "error"
    detail: str


def find_tool(name: str, env_var: str, exe_names: list[str], candidates: list[str]) -> Check:
    override = os.environ.get(env_var)
    if override:
        # A set-but-wrong override is an error, not a reason to fall back:
        # falling back would run a different binary than the user asked for.
        if Path(override).is_file():
            return Check(name, "ok", f"{override} (from {env_var})")
        return Check(name, "error", f"{env_var}={override} is not a file")
    for exe in exe_names:
        hit = shutil.which(exe)
        if hit:
            return Check(name, "ok", f"{hit} (from PATH)")
    for pattern in candidates:
        matches = sorted(glob.glob(pattern))
        if matches:
            return Check(name, "ok", f"{matches[-1]} (default install location)")
    return Check(name, "warn", f"not found; install it or set {env_var}")


def check_ascii_path(path: Path) -> Check:
    # FEBio and other C++ tools on Windows often fail to open non-ASCII paths.
    if str(path).isascii():
        return Check("ascii path", "ok", str(path))
    return Check("ascii path", "warn", f"{path} contains non-ASCII characters; solver runs may fail")


def check_python() -> Check:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info >= (3, 13):
        return Check("python", "ok", f"{version} ({sys.executable})")
    return Check("python", "error", f"{version}; need >= 3.13 to match Blender 5.2")


def run_checks() -> list[Check]:
    project_root = Path(__file__).resolve().parents[2]
    return [
        check_python(),
        find_tool("febio", "ASRP_FEBIO", ["febio4"], FEBIO_CANDIDATES),
        find_tool("blender", "ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES),
        check_ascii_path(project_root),
    ]
