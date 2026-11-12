"""docs/15-prototype.md shows the numbers of the archived reference run, written by a tool.

The page once carried the same hand-copied number in several places and was corrected seven
times. Now tools/prototype_numbers.py writes every table of numbers between marker comments, and
this test (so tools/verify.py) fails when the page and data/preview/prototype_run_report.json
disagree, for instance after a new run was archived and the page was not rewritten.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "prototype_numbers.py"
DOC = REPO / "docs" / "15-prototype.md"


def load_tool():
    spec = importlib.util.spec_from_file_location("prototype_numbers", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(doc: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--check", "--doc", str(doc)],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8")


def test_the_page_matches_the_archived_run():
    done = run_check(DOC)
    assert done.returncode == 0, done.stderr + done.stdout


def test_the_check_can_fail_and_names_the_block(tmp_path):
    tool = load_tool()
    text = tool.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems and "checks" in spans
    start, end = spans["checks"]
    block = text[start:end]
    digit = next(i for i, ch in enumerate(block) if ch.isdigit())  # change one number inside the block
    changed = block[:digit] + ("7" if block[digit] != "7" else "8") + block[digit + 1:]
    assert changed != block
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text[:start] + changed + text[end:], encoding="utf-8", newline="\n")
    done = run_check(copy)
    assert done.returncode == 1
    assert "checks" in done.stderr
    assert "spring" not in done.stderr.split("Differs in block(s):")[-1]  # only the changed block is named


def test_every_marker_pair_is_well_formed_and_known():
    tool = load_tool()
    text = tool.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems, problems
    assert len(spans) >= 5, f"only {sorted(spans)} found; the markers are missing"
    assert set(spans) == set(tool.load()), "the page and the tool disagree on the block names"
    for name, (start, end) in spans.items():
        assert text[start:end].count("|") > 6, f"block {name} is empty"


def test_a_broken_marker_is_reported(tmp_path):
    tool = load_tool()
    text = tool.read_text(DOC).replace("<!-- END generated: checks -->", "", 1)
    assert tool.find_blocks(text)[1]
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text, encoding="utf-8", newline="\n")
    assert run_check(copy).returncode == 1
