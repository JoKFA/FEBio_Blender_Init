"""Write manifest.json for a folder of files brought back from the lab's machine, and point the repo at it.

    uv run python tools/lab_trip_manifest.py <folder outside the repo>

The manifest lists every file with its size and SHA-256. tools/check_no_lab_files.py reads it, so none of
these files can be committed by accident, whatever it is renamed to. The pointer is written to .local/, which is this machine's and is never committed.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POINTER = REPO / ".local" / "ziva_trip_pointer.json"  # this machine only; .local/ is git-ignored


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(folder: Path) -> dict:
    files = [{"path": p.relative_to(folder).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)}
             for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    return {"format": "asrp-lab-trip-manifest/1", "files": files}


def main(argv=None) -> int:
    folder = Path((argv or sys.argv[1:])[0]).resolve()
    if REPO in folder.parents or folder == REPO:
        sys.exit("the folder must be outside the repo")
    manifest = build(folder)
    if not manifest["files"]:
        sys.exit(f"no files under {folder}")
    target = folder / "manifest.json"
    target.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(f["size"] for f in manifest["files"])
    POINTER.parent.mkdir(exist_ok=True)
    POINTER.write_text(json.dumps({"manifest": str(target), "manifest_sha256": sha256(target),
                                   "files": len(manifest["files"]), "bytes": total,
                                   "note": "Data from the lab's Ziva machine. It stays outside the repo; "
                                           "tools/check_no_lab_files.py refuses any tracked file with one of these hashes."},
                                  indent=1), encoding="utf-8")
    print(f"{len(manifest['files'])} files, {total / 1e9:.2f} GB -> {target}\npointer -> {POINTER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
