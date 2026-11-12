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
FILES = sorted(DOCS.rglob("*.md")) + [REPO / "README.md", REPO / "AGENTS.md"]
INLINE_LINK = re.compile(r"\]\(([^)]*)\)")  # everything between the parentheses; taken apart in `link_targets`
REFERENCE_LINK = re.compile(r"^\[[^\]]+\]:\s*(\S+)", re.M)
# kind -> (how it is cited anywhere, the document that defines it, how a definition's heading starts)
IDS = {
    "task card": (r"\bT-\d+[A-Za-z]?\b", "09-roadmap-and-tasks.md", r"^### (T-\d+[A-Za-z]?)\b"),
    "decision": (r"\bADR-\d+[A-Za-z]?\b", "10-decisions.md", r"^### (ADR-\d+[A-Za-z]?)\b"),
    "explanation": (r"\bE-\d+[A-Za-z]?\b", "13-explanations.md", r"^## (E-\d+[A-Za-z]?)\b"),
}


def link_targets(text: str) -> list[str]:
    """The file part of every Markdown link in a text: `[a](path#anchor)`, `[a](<path with spaces>)`,
    `[a](path "title")` and reference-style `[a]: path`."""
    out = []
    for inner in INLINE_LINK.findall(text):
        inner = inner.strip()
        if inner.startswith("<"):
            target = inner[1:inner.index(">")] if ">" in inner else inner[1:]
        else:
            target = inner.split()[0] if inner.split() else ""
        out.append(target)
    out += REFERENCE_LINK.findall(text)
    return [t.split("#", 1)[0] for t in out]


def broken_links(files) -> list[str]:
    out = []
    for f in files:
        for target in link_targets(f.read_text(encoding="utf-8")):
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue  # empty: a link to an anchor on the same page
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
    assert len(FILES) > 15 and all(f.is_file() for f in FILES)
    assert sum(len(link_targets(f.read_text(encoding="utf-8"))) for f in FILES) > 100  # the links are found at all
    assert broken_links(FILES) == []


@pytest.mark.parametrize("kind", sorted(IDS))
def test_every_cited_id_is_defined(kind):
    home = DOCS / IDS[kind][1]
    assert len(re.findall(IDS[kind][2], home.read_text(encoding="utf-8"), re.M)) > 5  # the definitions are found at all
    assert undefined(kind, FILES, DOCS) == []


def test_the_check_can_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "there.md").write_text("x", encoding="utf-8")
    (docs / "09-roadmap-and-tasks.md").write_text(
        "### T-01 a card\n### T-06b another\n"
        "fine: [a](there.md#part) [b](<there.md>) [c](there.md \"title\") [d](#here) [e](https://example.org/x.md) T-06b\n"
        "broken: [f](missing.md) [g](<gone too.md>) [h](lost.md \"title\") and T-99 and T-06c\n"
        "[ref]: nowhere.md\n", encoding="utf-8")
    files = [docs / "09-roadmap-and-tasks.md"]
    assert broken_links(files) == [f"09-roadmap-and-tasks.md: {name}" for name in
                                   ("missing.md", "gone too.md", "lost.md", "nowhere.md")]
    assert undefined("task card", files, docs) == ["T-06c", "T-99"]
