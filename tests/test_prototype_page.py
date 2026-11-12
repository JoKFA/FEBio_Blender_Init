"""docs/15-prototype.md shows the numbers of the archived reference run, written by a tool.

The page once carried the same hand-copied number in several places and was corrected seven
times. Now tools/prototype_numbers.py writes every table of numbers between marker comments, and
this test (so tools/verify.py) fails when the page and data/preview/prototype_run_report.json
disagree, for instance after a new run was archived and the page was not rewritten.
"""

import importlib.util
import json
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


# --- the page may only say what the archived run showed: synthetic reports --------------------------------


def render(tmp_path, change=None, change_prov=None):
    """Copy the archived report and provenance into tmp_path, let `change` edit the copy, render the blocks."""
    tool = load_tool()
    report = json.loads(tool.REPORT.read_text(encoding="utf-8"))
    prov = json.loads(tool.PROVENANCE.read_text(encoding="utf-8"))
    for fn, data, path in ((change, report, tmp_path / "report.json"), (change_prov, prov, tmp_path / "prov.json")):
        if fn:
            fn(data)
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return tool.load(tmp_path / "report.json", tmp_path / "prov.json")


def line_with(block: str, text: str) -> str:
    return next(line for line in block.splitlines() if text in line)


def test_the_unchanged_copy_renders_the_same_as_the_archive(tmp_path):
    assert render(tmp_path) == load_tool().load()


def test_a_failed_check_is_rendered_as_failed_not_as_passed(tmp_path):
    def fail(report):
        report["checks"]["b"]["passed"] = False
        report["checks"]["b"]["message"] = "a hard node is 3 mm off its bone"

    blocks = render(tmp_path, fail)
    row = line_with(blocks["checks"], "(b) 粘在骨头上")
    assert "**不通过**" in row and "3 mm off" in row and "通过：" not in row
    glance = line_with(blocks["glance"], "脱")
    assert "**不通过**" in glance and "贴骨头的地方确实跟着骨头走" not in glance
    assert "通过：" in line_with(blocks["checks"], "(a) 整段算完")  # the others keep their own verdict


def test_a_check_that_did_not_run_is_rendered_as_not_run_with_its_reason(tmp_path):
    def skip(report):
        report["checks"]["c"]["passed"] = None
        report["checks"]["c"]["message"] = "settle_until_frame is 0: there is no frame after the rest pose"
        report["settled_shape"] = {"available": False, "frame": None, "reason": "settle_until_frame is 0"}

    blocks = render(tmp_path, skip)
    for name, key in (("checks", "(c) 重力下垂"), ("glance", "重力有没有")):
        row = line_with(blocks[name], key)
        assert "没运行：settle_until_frame is 0" in row and "通过：沉" not in row
    assert "没有（settle_until_frame is 0）" in line_with(blocks["run"], "回到沉降形状")


def test_retries_come_from_the_report(tmp_path):
    zero = render(tmp_path)
    assert "FEBio 没有哪一步要缩小步长重算" in zero["glance"] and "步长从没有被迫缩小" in zero["run"]

    def retried(report):
        report["checks"]["a"]["numbers"]["retries"] = 3

    blocks = render(tmp_path, retried)
    assert "FEBio 没有哪一步要缩小步长重算" not in blocks["glance"] and "步长从没有被迫缩小" not in blocks["run"]
    assert "**重试 3 次**" in blocks["glance"] and "有 3 次缩小步长重算" in blocks["glance"]
    assert "FEBio 重试 | 3 次" in blocks["run"] and "通过：重试 3 次" in blocks["checks"]


def test_the_settled_frame_comes_from_the_report(tmp_path):
    def other(report):
        report["settled_shape"]["frame"] = 9

    assert "沉降形状在第 9 帧" in line_with(render(tmp_path, other)["run"], "回到沉降形状")
    assert "沉降形状在第 14 帧" not in render(tmp_path, other)["run"]


def test_groups_are_found_by_name_not_by_position_in_the_list(tmp_path):
    def reverse(report):
        report["generator"]["groups"].reverse()

    same, flipped = render(tmp_path), render(tmp_path, reverse)
    for name in ("glance", "run", "checks", "spring-deviation", "springs", "source"):
        assert same[name] == flipped[name], name
    assert line_with(flipped["generator"], "弹簧基础刚度") == line_with(same["generator"], "弹簧基础刚度")


def test_motion_comes_from_the_report_and_scene_facts_only_when_the_report_holds_them(tmp_path):
    def moved(report):
        report["motion"] = {"max_display_distance_mm": 12.34, "frame": 21}
        for p in report["parameters"]:
            if p["where"] == "trajectory.source":
                p["value"] = "a made-up motion that opens to 20 degrees at frame 21"

    blocks = render(tmp_path, moved)
    row = line_with(blocks["glance"], "嘴唇动了多少")
    assert "**12.3 mm**（第 21 帧）" in row and "下颌张 20°" in row and "30.4" not in row

    def bare(report):
        report["motion"] = {"max_display_distance_mm": 12.34, "frame": 21}
        for p in report["parameters"]:
            if p["where"] == "trajectory.source":
                p["value"] = "no angle named here"

    assert "下颌张" not in line_with(render(tmp_path, bare)["glance"], "嘴唇动了多少")


def test_nothing_is_stated_that_the_archive_does_not_hold(tmp_path):
    text = "\n".join(render(tmp_path).values())
    for claim in ("216.6", "145 mm", "1×10⁻¹⁰", "1×10⁻⁹"):
        assert claim not in text, claim
    # the facts that stay are the archive's own: k, the offset as a multiple of the median edge, springs per node
    assert "物理尺度 k | 0.67" in text and "5 倍四面体边长中位数" in text and "每个计算点 3 根" in text


def test_a_broken_marker_is_reported(tmp_path):
    tool = load_tool()
    text = tool.read_text(DOC).replace("<!-- END generated: checks -->", "", 1)
    assert tool.find_blocks(text)[1]
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text, encoding="utf-8", newline="\n")
    assert run_check(copy).returncode == 1
