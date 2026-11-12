"""Tracked text files use LF line endings.

Twice in one batch (2026-11-11) a tool wrote CRLF into docs, so the next merge showed every
line of five files as changed and conflicted. core.autocrlf is false here, so git does not
convert anything: this test is the guard. data/ and tests/fixtures/ are checked out byte
for byte and identified by their sha256 (.gitattributes), so they are left out.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEXT = {".md", ".py", ".toml", ".txt", ".html", ".js", ".css", ".yml", ".yaml", ".cfg", ".ini"}
BYTE_FOR_BYTE = ("data/", "tests/fixtures/")


def tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    names = [n for n in out.decode("utf-8").split("\0") if n]
    return [REPO / n for n in names
            if Path(n).suffix.lower() in TEXT and not n.startswith(BYTE_FOR_BYTE) and (REPO / n).is_file()]


def test_tracked_text_files_have_no_crlf():
    files = tracked_text_files()
    assert len(files) > 50, f"only {len(files)} text files found; the file listing is broken"
    bad = [str(p.relative_to(REPO)) for p in files if b"\r\n" in p.read_bytes()]
    assert not bad, "CRLF line endings (convert to LF): " + ", ".join(bad)
