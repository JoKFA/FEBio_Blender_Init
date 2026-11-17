"""The documents must not point at things that are not there (docs/13 E-09, second audit).

Three documents define ids that the others cite: task cards (`### T-xx` in docs/09), decisions (`### ADR-xx` in
docs/10) and explanations (`## E-xx` in docs/13). A citation of an id nobody defines, or a relative link to a
file that does not exist, is how the documents drift apart without anyone noticing; both fail here.

Two more ways a page breaks for the next reader and not for its author:
- a link or picture whose file is on this disk but ignored by git, or spelled in another case (Windows opens it,
  GitHub and Linux do not): every link target must be a path git holds, spelled as git spells it;
- an English translation (`NN-name.en.md`) that no longer carries the numbers or the links of its Chinese source.
"""

import posixpath
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
FILES = sorted(DOCS.rglob("*.md")) + [REPO / "README.md"]
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


def git_paths(repo: Path = REPO) -> set[str]:
    """Every path git holds or takes on the next `git add` (tracked, or untracked and not ignored), as git spells it."""
    listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repo,
                            capture_output=True, check=True).stdout.decode("utf-8")
    return {p for p in listed.split("\0") if p}


def links_outside_git(files, paths: set[str], repo: Path = REPO) -> list[str]:
    """Links to something a clone does not get: an ignored file, or a name whose case differs from git's."""
    folders = {"."} | {p.rsplit("/", i)[0] for p in paths for i in range(1, p.count("/") + 1)}
    out = []
    for f in files:
        for target in link_targets(f.read_text(encoding="utf-8")):
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            path = posixpath.normpath(posixpath.join(f.parent.relative_to(repo).as_posix(), target))
            if path not in paths and path not in folders:
                out.append(f"{f.name}: {target}")
    return out


# translation -> its Chinese source, both in docs/. The Chinese page is the one that is edited; the translation follows.
TRANSLATIONS = {"15-prototype.en.md": "15-prototype.md", "16-pipeline.en.md": "16-pipeline.md"}
TRANSLATION_NOTE = "> **English translation.**"  # the line under the title that names the source; not counted below
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?(?:e-?\d+)?")


def translation_drift(translation: str, source: str, source_name: str, translations: dict[str, str]) -> list[str]:
    """What a translation no longer shares with its source: a number written in digits that appears a different
    number of times, or a link target (links between translated pages point at the translations)."""
    lines = translation.splitlines()
    notes = [line for line in lines if line.startswith(TRANSLATION_NOTE)]
    if len(notes) != 1 or f"]({source_name})" not in notes[0]:
        return [f"no single line starting {TRANSLATION_NOTE!r} that links to {source_name}"]
    body = "\n".join(line for line in lines if not line.startswith(TRANSLATION_NOTE))
    out = []
    ours, theirs = Counter(NUMBER.findall(body)), Counter(NUMBER.findall(source))
    for number in sorted(set(ours) | set(theirs)):
        if ours[number] != theirs[number]:
            out.append(f"number {number}: {theirs[number]} in the source, {ours[number]} in the translation")
    english = {src: en for en, src in translations.items()}
    wanted = Counter(english.get(t, t) for t in link_targets(source) if t)
    found = Counter(t for t in link_targets(body) if t)
    for target in sorted(set(wanted) | set(found)):
        if wanted[target] != found[target]:
            out.append(f"link {target}: {wanted[target]} expected from the source, {found[target]} in the translation")
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


def test_every_link_target_is_a_path_git_holds():
    paths = git_paths()
    assert len(paths) > 100 and "docs/README.md" in paths  # git answered, with paths spelled from the repository root
    pictures = [t for f in FILES for t in link_targets(f.read_text(encoding="utf-8")) if t.endswith((".png", ".gif"))]
    assert len(pictures) > 20  # the pictures are among the links checked
    assert links_outside_git(FILES, paths) == []


@pytest.mark.parametrize("name", sorted(TRANSLATIONS))
def test_a_translation_carries_the_numbers_and_links_of_its_source(name):
    source = (DOCS / TRANSLATIONS[name]).read_text(encoding="utf-8")
    assert len(NUMBER.findall(source)) > 50 and len(link_targets(source)) > 10  # there is something to compare
    assert translation_drift((DOCS / name).read_text(encoding="utf-8"), source, TRANSLATIONS[name], TRANSLATIONS) == []


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


def test_the_git_check_can_fail(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "page.md"
    page.write_text("![a](../data/preview/a.png) ![b](../data/preview/B.png) ![c](../runs/c.gif) [d](other.md) "
                    "[e](../data/preview) [f](..) [g](https://example.org/g.png)\n", encoding="utf-8")
    paths = {"docs/page.md", "docs/other.md", "data/preview/a.png", "data/preview/b.png"}  # b.png, not B.png; runs/ ignored
    assert links_outside_git([page], paths, tmp_path) == ["page.md: ../data/preview/B.png", "page.md: ../runs/c.gif"]


def test_the_translation_check_can_fail():
    names = {"a.en.md": "a.md", "b.en.md": "b.md"}
    source = "# 标题\n第 36 帧 1.88 mm，共 10,240 个，4.4e-08。[b](b.md) [c](c.md) ![图](../data/x.gif)\n"
    note = "> **English translation.** The Chinese page [a.md](a.md) is the source.\n"
    good = "# Title\n" + note + "Frame 36: 1.88 mm over 10,240, 4.4e-08. [b](b.en.md) [c](c.md) ![picture](../data/x.gif)\n"
    assert translation_drift(good, source, "a.md", names) == []
    assert translation_drift(good.replace("1.88", "1.89"), source, "a.md", names) == [
        "number 1.88: 1 in the source, 0 in the translation", "number 1.89: 0 in the source, 1 in the translation"]
    assert translation_drift(good.replace("10,240", "10240"), source, "a.md", names) != []
    assert translation_drift(good.replace("x.gif", "y.gif"), source, "a.md", names) == [
        "link ../data/x.gif: 1 expected from the source, 0 in the translation",
        "link ../data/y.gif: 0 expected from the source, 1 in the translation"]
    assert translation_drift(good.replace("b.en.md", "b.md"), source, "a.md", names) != []  # must link the translation
    assert translation_drift(good.replace(note, ""), source, "a.md", names) != []  # the note that names the source
