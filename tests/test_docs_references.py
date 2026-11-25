"""The documents must not point at things that are not there (docs/13 E-09, second audit).

Three documents define ids that the others cite: task cards (`### T-xx` in docs/09), decisions (`### ADR-xx` in
docs/10) and explanations (`## E-xx` in docs/13). A citation of an id nobody defines, or a relative link to a
file that does not exist, is how the documents drift apart without anyone noticing; both fail here. A task card or
explanation may live in the live document or in its `docs/archive/` file, but never in both.

Two more ways a page breaks for the next reader and not for its author:
- a link or picture whose file is on this disk but ignored by git, or spelled in another case (Windows opens it,
  GitHub and Linux do not): every link target must be a path git holds, spelled as git spells it;
- an English translation (`NN-name.en.md`) that no longer carries the numbers or the links of its Chinese source.

And one way a page breaks when another page is reorganised: an address by number. "[07](07-validation.md) 第 6 节"
still opens the file after section 6 has moved to the archive, and a link to `#a-heading` still opens the page after
the heading was reworded. Twice a rewrite renumbered sections and left more than twenty such addresses behind. So in
the live documents a section number, a "第 N 部分" or an anchor written at a link must exist in the page the link opens.
The archive is frozen history and is not checked as a source; "原 [04](...) 第 13.2 节" says where something used to
be and is not checked either.
"""

import posixpath
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
FILES = sorted(DOCS.rglob("*.md")) + [REPO / "README.md"]
INLINE_LINK = re.compile(r"\]\(([^)]*)\)")  # everything between the parentheses; taken apart in `link_targets`
REFERENCE_LINK = re.compile(r"^\[[^\]]+\]:\s*(\S+)", re.M)
# kind -> (how it is cited anywhere, the documents that may define it (the first is the live one), how a
# definition's heading starts)
IDS = {
    "task card": (r"\bT-\d+[A-Za-z]?\b", ("tasks/T-*.md", "archive/tasks/T-*.md"),
                  r"^# (T-\d+[A-Za-z]?)\b"),
    "decision": (r"\bADR-\d+[A-Za-z]?\b", ("decisions/ADR-*.md", "archive/decisions/ADR-*.md"),
                 r"^# (ADR-\d+[A-Za-z]?)\b"),
    "explanation": (r"\bE-\d+[A-Za-z]?\b", ("13-explanations.md", "explanations/E-*.md", "archive/explanations/E-*.md"),
                    r"^#{1,2} (E-\d+[A-Za-z]?)\b"),
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


SECTION_HEADING = re.compile(r"^#{2,6}[ \t]+(\d+(?:\.\d+)*)\.?[ \t]", re.M)  # "## 4. 标题", "### 4.2 标题", "## 13.1 标题"
PART_HEADING = re.compile(r"^#{2,6}[ \t]+(第[一二三四五六七八九十]+部分)", re.M)
ANY_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.M)
# a link to a page, then right after it "第 4.2 节" / "（第 5、10 节）" / "§4" / "第二部分"; "原" before the link marks
# an address that is no longer valid on purpose
ADDRESS = re.compile(r"(原\s*)?\[[^\]\n]*\]\(([^)\s#]+\.md)(?:#[^)\s]*)?\)\s*[（(]?\s*"
                     r"(?:第\s*(\d[\d.、，,和到至–—~\-\s]*?)\s*节|§\s*(\d+(?:\.\d+)*)|(第[一二三四五六七八九十]+部分))")
# the same with the number inside the link text: "[07 第 8.2 节](07-validation.md)"
ADDRESS_IN_TEXT = re.compile(r"(原\s*)?\[[^\]\n]*?第\s*(\d[\d.、，,和到至–—~\-\s]*?)\s*节[^\]\n]*\]\(([^)\s#]+\.md)(?:#[^)\s]*)?\)")
ANCHORED_LINK = re.compile(r"\]\(([^)\s#]*)#([^)\s]+)\)")
EXPLICIT_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")


def live(files, docs: Path) -> list[Path]:
    """The documents that say what is true now: everything except the archive."""
    return [f for f in files if (docs / "archive") not in f.parents]


def addresses_by_number(files) -> list[tuple[Path, Path, str]]:
    """Every (page, page it points at, section number or part name) written at a link, in the given pages."""
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        found = [(former, target, numbers or paragraph, part)
                 for former, target, numbers, paragraph, part in ADDRESS.findall(text)]
        found += [(former, target, numbers, "") for former, numbers, target in ADDRESS_IN_TEXT.findall(text)]
        for former, target, numbers, part in found:
            if former:
                continue
            names = [part] if part else [n.strip(".") for n in re.findall(r"\d[\d.]*", numbers)]
            out += [(f, f.parent / target, name) for name in names]
    return out


def missing_sections(files) -> list[str]:
    """Addresses by number whose page has no heading with that number or part name."""
    out = []
    for f, target, name in addresses_by_number(files):
        if not target.is_file():
            continue  # a missing file is `broken_links`' finding
        text = target.read_text(encoding="utf-8")
        if name not in SECTION_HEADING.findall(text) + PART_HEADING.findall(text):
            out.append(f"{f.name}: {target.name} has no {name}")
    return out


def anchors(text: str) -> set[str]:
    """The anchors a page offers, as GitHub makes them from its headings (lower case; punctuation dropped, letters,
    digits, hyphens and underscores kept; spaces to hyphens; a repeated heading gets -1, -2, ...), plus `<a id="">`."""
    out, seen = set(EXPLICIT_ANCHOR.findall(text)), Counter()
    for heading in ANY_HEADING.findall(text):
        heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        out.add(slug if not seen[slug] else f"{slug}-{seen[slug]}")
        seen[slug] += 1
    return out


def broken_anchors(files) -> list[str]:
    """Links to `page.md#anchor` (or `#anchor` on the same page) where the page has no such heading."""
    out = []
    for f in files:
        for target, anchor in ANCHORED_LINK.findall(f.read_text(encoding="utf-8")):
            page = f if not target else f.parent / target
            if target.startswith(("http://", "https://")) or page.suffix != ".md" or not page.is_file():
                continue
            if unquote(anchor) not in anchors(page.read_text(encoding="utf-8")):
                out.append(f"{f.name}: {target}#{anchor}")
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


def _home_files(docs: Path, pattern: str) -> list[Path]:
    """Resolve one IDS home entry: either a literal relative file or a glob pattern under docs/."""
    if any(ch in pattern for ch in "*?["):
        return sorted(p for p in docs.glob(pattern) if p.is_file())
    p = docs / pattern
    return [p] if p.is_file() else []


def definitions(kind: str, docs: Path) -> list[str]:
    """Every id of a kind defined in its homes, once per definition. The first home must yield at least one file;
    archive homes that are not there define nothing."""
    _, homes, heading = IDS[kind]
    out = []
    for i, home in enumerate(homes):
        matched = _home_files(docs, home)
        if i == 0 and not matched:
            raise FileNotFoundError(docs / home)
        for path in matched:
            out += re.findall(heading, path.read_text(encoding="utf-8"), re.M)
    return out


def defined_twice(kind: str, docs: Path) -> list[str]:
    return sorted(i for i, n in Counter(definitions(kind, docs)).items() if n > 1)


def undefined(kind: str, files, docs: Path) -> list[str]:
    cited = IDS[kind][0]
    defined = set(definitions(kind, docs))
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


def test_a_section_number_written_at_a_link_exists_in_that_page():
    pages = live(FILES, DOCS)
    assert len(pages) > 80 and len(pages) < len(FILES)  # the live pages are found, and the archive is left out
    assert len(addresses_by_number(pages)) > 100  # the addresses are found at all
    assert missing_sections(pages) == []


def test_an_anchor_written_in_a_link_exists_in_that_page():
    assert broken_anchors(live(FILES, DOCS)) == []


@pytest.mark.parametrize("name", sorted(TRANSLATIONS))
def test_a_translation_carries_the_numbers_and_links_of_its_source(name):
    source = (DOCS / TRANSLATIONS[name]).read_text(encoding="utf-8")
    assert len(NUMBER.findall(source)) > 50 and len(link_targets(source)) > 10  # there is something to compare
    assert translation_drift((DOCS / name).read_text(encoding="utf-8"), source, TRANSLATIONS[name], TRANSLATIONS) == []


@pytest.mark.parametrize("kind", sorted(IDS))
def test_every_cited_id_is_defined(kind):
    homes = IDS[kind][1]
    assert all(_home_files(DOCS, h) for h in homes)
    assert len(definitions(kind, DOCS)) > 5  # the definitions are found at all
    assert undefined(kind, FILES, DOCS) == []


@pytest.mark.parametrize("kind", sorted(IDS))
def test_no_id_is_defined_in_two_places(kind):
    assert len(definitions(kind, DOCS)) > 5  # the definitions are found at all
    assert defined_twice(kind, DOCS) == []


def test_the_check_can_fail(tmp_path):
    docs = tmp_path / "docs"
    (docs / "tasks").mkdir(parents=True)
    (docs / "there.md").write_text("x", encoding="utf-8")
    (docs / "tasks" / "T-01.md").write_text(
        "# T-01 a card\n"
        "fine: [a](../there.md#part) [b](<../there.md>) [c](../there.md \"title\") [d](#here) [e](https://example.org/x.md) T-06b\n"
        "broken: [f](../missing.md) [g](<../gone too.md>) [h](../lost.md \"title\") and T-99 and T-06c\n"
        "[ref]: ../nowhere.md\n", encoding="utf-8")
    (docs / "tasks" / "T-06b.md").write_text("# T-06b another\n", encoding="utf-8")
    files = [docs / "tasks" / "T-01.md", docs / "tasks" / "T-06b.md"]
    assert broken_links(files) == [f"T-01.md: ../{name}" for name in
                                   ("missing.md", "gone too.md", "lost.md", "nowhere.md")]
    assert undefined("task card", files, docs) == ["T-06c", "T-99"]
    # the archive is a second home: an id defined only there is accepted, one defined in both homes is reported,
    # one defined nowhere is still reported
    (docs / "archive" / "tasks").mkdir(parents=True)
    (docs / "archive" / "tasks" / "T-06c.md").write_text("# T-06c finished\n", encoding="utf-8")
    (docs / "archive" / "tasks" / "T-01.md").write_text("# T-01 twice\n", encoding="utf-8")
    assert undefined("task card", files, docs) == ["T-99"]
    assert defined_twice("task card", docs) == ["T-01"]
    (docs / "archive" / "tasks" / "T-01.md").unlink()
    assert defined_twice("task card", docs) == []


def test_the_section_and_anchor_checks_can_fail(tmp_path):
    docs = tmp_path / "docs"
    (docs / "tasks").mkdir(parents=True)
    (docs / "archive").mkdir()
    (docs / "07-page.md").write_text(
        "# 07 一页\n## 1. 第一节\n### 1.2 小节\n## 4. 对比（`asrp compare`）\n## 第二部分：给实验室的一页\n"
        "## 说明\n## 说明\n<a id=\"fixed\"></a>\n", encoding="utf-8")
    card = docs / "tasks" / "T-01.md"
    card.write_text(
        "# T-01 a card\n"
        "fine: [07](../07-page.md) 第 1 节、[07](../07-page.md)（第 1.2、4 节）、[07](../07-page.md) §4、"
        "[07](../07-page.md) 第二部分、（原 [07](../07-page.md) 第 13.2 节）、[07](../07-page.md) 第 3 条、"
        "[gone](../gone.md) 第 9 节、[07 第 1.2 节](../07-page.md)\n"
        "fine: [a](../07-page.md#4-对比asrp-compare) [b](../07-page.md#说明-1) [c](../07-page.md#fixed) [d](#t-01-a-card)\n"
        "stale: [07](../07-page.md) 第 6 节、[07](../07-page.md)（第 1、5 节）、[07](../07-page.md) §4.2、"
        "[07](../07-page.md) 第三部分、[07 第 8.2 节](../07-page.md)\n"
        "stale: [e](../07-page.md#4-对比) [f](../07-page.md#说明-2) [g](#nowhere)\n", encoding="utf-8")
    old = docs / "archive" / "T-00.md"
    old.write_text("# T-00 finished\n[07](../07-page.md) 第 6 节 [h](../07-page.md#gone)\n", encoding="utf-8")
    files = [docs / "07-page.md", card, old]
    assert live(files, docs) == [docs / "07-page.md", card]  # the archive is frozen history
    assert len(addresses_by_number([card])) == 13  # "原 ..." and "第 3 条" are not addresses by section
    assert missing_sections(live(files, docs)) == [f"T-01.md: 07-page.md has no {n}"
                                                   for n in ("6", "5", "4.2", "第三部分", "8.2")]
    assert broken_anchors(live(files, docs)) == ["T-01.md: ../07-page.md#4-对比", "T-01.md: ../07-page.md#说明-2",
                                                 "T-01.md: #nowhere"]
    assert missing_sections([old]) == ["T-00.md: 07-page.md has no 6"]  # it would be found, were the archive checked


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
