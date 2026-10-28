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


@dataclass
class Located:
    path: Path | None
    how: str  # where the path came from, or why there is none
    misconfigured: bool = False


def locate(env_var: str, exe_names: list[str], candidates: list[str]) -> Located:
    override = os.environ.get(env_var)
    if override:
        # A set-but-wrong override is an error, not a reason to fall back:
        # falling back would run a different binary than the user asked for.
        if Path(override).is_file():
            return Located(Path(override), env_var)
        return Located(None, f"{env_var}={override} is not a file", misconfigured=True)
    for exe in exe_names:
        hit = shutil.which(exe)
        if hit:
            return Located(Path(hit), "PATH")
    for pattern in candidates:
        matches = sorted(glob.glob(pattern))
        if matches:
            return Located(Path(matches[-1]), "default install location")
    return Located(None, f"not found; install it or set {env_var}")


def find_tool(name: str, env_var: str, exe_names: list[str], candidates: list[str]) -> Check:
    found = locate(env_var, exe_names, candidates)
    if found.path:
        return Check(name, "ok", f"{found.path} (from {found.how})")
    return Check(name, "error" if found.misconfigured else "warn", found.how)


def febio_exe() -> Path:
    found = locate("ASRP_FEBIO", ["febio4"], FEBIO_CANDIDATES)
    if found.path is None:
        raise FileNotFoundError(f"FEBio {found.how}")
    return found.path


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
