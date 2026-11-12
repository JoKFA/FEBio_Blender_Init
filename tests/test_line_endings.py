"""Tracked text files are committed with LF line endings.

Twice in one batch (2026-11-11) a tool wrote CRLF into docs, so the next merge showed every
line of five files as changed and conflicted. This test reads what git stores (the index,
`git ls-files --eol`), not the checked-out bytes: with core.autocrlf=true a clean Windows
checkout has CRLF on disk even though the repository holds LF, and that is fine (PR #7 review).
data/ and tests/fixtures/ are kept byte for byte and identified by their sha256
(.gitattributes), so they are left out.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEXT = {".md", ".py", ".toml", ".txt", ".html", ".js", ".css", ".yml", ".yaml", ".cfg", ".ini"}
BYTE_FOR_BYTE = ("data/", "tests/fixtures/")


def committed_eol() -> dict[str, str]:
    """Path -> line-ending state of the staged blob ('lf', 'crlf', 'mixed', 'none', '-text')."""
    out = subprocess.run(["git", "ls-files", "--eol", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    found = {}
    for entry in out.decode("utf-8").split("\0"):
        if not entry:
            continue
        info, _, name = entry.partition("\t")
        index = info.split()[0]  # e.g. "i/lf"
        found[name] = index[2:]
    return found


def test_tracked_text_files_are_committed_without_crlf():
    eol = {n: e for n, e in committed_eol().items()
           if Path(n).suffix.lower() in TEXT and not n.startswith(BYTE_FOR_BYTE)}
    assert sum(e == "lf" for e in eol.values()) > 50, f"only {len(eol)} text files listed; the listing is broken"
    bad = sorted(n for n, e in eol.items() if e in ("crlf", "mixed"))
    assert not bad, "committed with CRLF (convert to LF and re-add): " + ", ".join(bad)
