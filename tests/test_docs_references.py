"""The documents must not point at things that are not there (docs/13 E-09, second audit).

Three documents define ids that the others cite: task cards (`### T-xx` in docs/09), decisions (`### ADR-xx` in
docs/10) and explanations (`## E-xx` in docs/13). A citation of an id nobody defines, or a relative link to a
file that does not exist, is how the documents drift apart without anyone noticing; both fail here.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
FILES = sorted(DOCS.glob("*.md")) + [REPO / "README.md", REPO / "AGENTS.md"]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
# kind -> (how it is cited anywhere, the document that defines it, how a definition's heading starts)
IDS = {
    "task card": (r"\bT-\d+[ab]?\b", "09-roadmap-and-tasks.md", r"^### (T-\d+[ab]?)\b"),
    "decision": (r"\bADR-\d+\b", "10-decisions.md", r"^### (ADR-\d+)\b"),
    "explanation": (r"\bE-\d+\b", "13-explanations.md", r"^## (E-\d+)\b"),
}


def broken_links(files) -> list[str]:
    out = []
    for f in files:
        for target in LINK.findall(f.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (f.parent / target).exists():
                out.append(f"{f.name}: {target}")
    return out


def undefined(kind: str, files, docs: Path) -> list[str]:
    cited, home, heading = IDS[kind]
    defined = set(re.findall(heading, (docs / home).read_text(encoding="utf-8"), re.M))
    used = set()
    for f in files:
        used |= set(re.findall(cited, f.read_text(encoding="utf-8")))
    return sorted(used - defined)


def test_every_relative_link_in_the_documents_points_at_a_file():
    assert FILES and all(f.is_file() for f in FILES)
    assert broken_links(FILES) == []


@pytest.mark.parametrize("kind", sorted(IDS))
def test_every_cited_id_is_defined(kind):
    home = DOCS / IDS[kind][1]
    assert len(re.findall(IDS[kind][2], home.read_text(encoding="utf-8"), re.M)) > 5  # the definitions are found at all
    assert undefined(kind, FILES, DOCS) == []


def test_the_check_can_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "09-roadmap-and-tasks.md").write_text("### T-01 a card\nsee [the plan](missing.md) and T-99\n", encoding="utf-8")
    files = [docs / "09-roadmap-and-tasks.md"]
    assert broken_links(files) == ["09-roadmap-and-tasks.md: missing.md"]
    assert undefined("task card", files, docs) == ["T-99"]
