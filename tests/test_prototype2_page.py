"""docs/15-prototype.md section 8 (prototype two) shows the numbers of six archived files, written by a tool.

tools/prototype2_numbers.py writes every table of numbers between marker comments, and this test (so
tools/verify.py) fails when the page and data/preview/aa_*.json, landmark_layer_check.json disagree. The same
mechanism as tests/test_prototype_page.py, for the second set of blocks in the same page.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "prototype2_numbers.py"
DOC = REPO / "docs" / "15-prototype.md"


def load_tool():
    spec = importlib.util.spec_from_file_location("prototype2_numbers", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(doc: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--check", "--doc", str(doc)],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8")


def section8(tool) -> str:
    text = tool.base.read_text(DOC)
    return text[text.index("## 8. 原型机二"):]


def test_the_page_matches_the_archive():
    done = run_check(DOC)
    assert done.returncode == 0, done.stderr + done.stdout


def test_the_check_can_fail_and_names_the_block(tmp_path):
    tool = load_tool()
    text = tool.base.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems and "p2-distance" in spans
    start, end = spans["p2-distance"]
    block = text[start:end]
    digit = next(i for i, ch in enumerate(block) if ch.isdigit())  # change one digit inside the block
    changed = block[:digit] + ("7" if block[digit] != "7" else "8") + block[digit + 1:]
    assert changed != block
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text[:start] + changed + text[end:], encoding="utf-8", newline="\n")
    done = run_check(copy)
    assert done.returncode == 1
    assert done.stderr.split("Differs in block(s):")[-1].strip() == "p2-distance"  # only the changed block is named


def test_every_marker_pair_is_well_formed_and_known():
    tool = load_tool()
    text = tool.base.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems, problems
    assert set(spans) == set(tool.load()), "the page and the tool disagree on the block names"
    assert len(spans) >= 9
    for name, (start, end) in spans.items():
        assert text[start:end].count("|") > 6 or "归一化" in text[start:end], f"block {name} is empty"


def test_the_two_tools_ignore_each_others_blocks():
    tool, text = load_tool(), load_tool().base.read_text(DOC)
    names1 = set(tool.base.find_blocks(text)[0])
    names2 = set(tool.find_blocks(text)[0])
    assert names1 and names2 and not names1 & names2
    assert not tool.base.find_blocks(text)[1]


def test_the_archived_files_agree_with_each_other():
    tool = load_tool()
    d = tool.load_all()
    st = d["standin"]
    for key, run in (("a", "a_report"), ("b", "b_report")):
        layer = d[run]["landmark_layer"]
        assert layer["applied"] is True and layer["landmarks_moved"] == st["counts"]["landmarks"]
        assert abs(layer["max_translation_mm"] - st["landmark_translations"][key]["max_mm"]) < 1e-9
        assert f"variant {key.upper()}" in next(p["value"] for p in d[run]["parameters"] if p["where"] == "trajectory.source")
        assert d[run]["frames"] == st["counts"]["frames"]
        factor = next(p["value"] for p in d[run]["parameters"] if p["where"] == "scene.drivers[lip_corner_blend].blend.factor")
        assert factor == st["anchor_fraction_default"]
    default = st["anchor_sweep"][f"{st['anchor_fraction_default']:g}"]
    assert default["physics_only"] == st["distance_to_target"]["physics_only"]
    assert default["a"]["final"] == st["distance_to_target"]["a"] and default["b"]["final"] == st["distance_to_target"]["b"]
    assert d["layer"]["lab_commit"] == st["lab_repo_commit"]


def test_the_page_says_what_the_task_requires():
    tool = load_tool()
    st = tool.load_all()["standin"]
    text = section8(tool)
    assert "拿到 D2 后由 T-10 的转换取代" in text
    assert "P-07" in text and "不说哪一种对" in text
    assert "不是缺陷" in text and "不证明物理对" in text
    # the two numbers the prose states by hand are the archive's
    assert f"{st['counts']['ramp_frames']} 帧半余弦过渡" in text
    assert f"第 {st['counts']['frames'] - 1} 帧（最后一帧）" in text
    for name in ("aa_physics", "aa_a", "aa_b"):
        assert f"../data/preview/{name}.png" in text and (REPO / "data" / "preview" / f"{name}.png").stat().st_size > 10_000
    for item in ("A-33", "A-35", "Q17", "Q20", "D2", "D6", "P-07", "正则项", "36 帧半余弦过渡", "只转下颌的拟合"):
        assert f"| {item}" in text or f"[{item}]" in text.replace("](11-risks-and-questions.md)", "]"), item


# --- the page may only say what the archive holds: synthetic copies --------------------------------------


def render(tmp_path, **changes):
    """Copy the six archived files into tmp_path, let `changes[key](data)` edit a copy, render the blocks."""
    tool = load_tool()
    files = {}
    for key, path in tool.FILES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        if key in changes:
            changes[key](data)
        files[key] = tmp_path / f"{key}.json"
        files[key].write_text(json.dumps(data), encoding="utf-8", newline="\n")
    return tool.load(files)


def line_with(block: str, text: str) -> str:
    return next(line for line in block.splitlines() if text in line)


def test_the_unchanged_copy_renders_the_same_as_the_archive(tmp_path):
    assert render(tmp_path) == load_tool().load()


def test_a_failed_check_is_rendered_as_failed(tmp_path):
    def fail(report):
        report["checks"]["d"]["passed"] = False
        report["checks"]["d"]["message"] = "3 tets are inverted"
        report["passed"] = False

    blocks = render(tmp_path, b_report=fail)
    row = line_with(blocks["p2-runs"], "(d) 四面体网格保持有效")
    assert "**不通过**：3 tets are inverted" in row and row.count("通过：翻转") == 1  # A keeps its own verdict
    assert "有没通过的" in line_with(blocks["p2-runs"], "整体")


def test_the_lab_normalised_distance_is_not_claimed_unless_the_report_holds_it(tmp_path):
    assert "没有按实验室的定义算出来" in render(tmp_path)["p2-normalised"]

    def present(report):
        report["normalised_distance"] = 0.123

    text = render(tmp_path, standin=present)["p2-normalised"]
    assert "0.123" in text and "没有按实验室的定义算出来" not in text


def test_the_default_row_and_the_checks_of_the_sweep_come_from_the_report(tmp_path):
    assert "0.5（默认）" in render(tmp_path)["p2-sweep"]

    def other(report):
        report["anchor_fraction_default"] = 0.25
        report["anchor_sweep"]["0.75"]["checks"]["c"] = False

    blocks = render(tmp_path, standin=other)
    assert "0.25（默认）" in blocks["p2-sweep"] and "0.5（默认）" not in blocks["p2-sweep"]
    assert "**不通过：c**" in line_with(blocks["p2-sweep"], "| 0.75")
    assert "全部通过" in line_with(blocks["p2-sweep"], "| 0.25")


def test_a_layer_that_was_not_applied_is_rendered_as_not_applied(tmp_path):
    def off(report):
        report["landmark_layer"]["applied"] = False

    row = line_with(render(tmp_path, a_report=off)["p2-runs"], "| landmark 层")
    assert "**没有叠**" in row and row.count("已叠上") == 1


def test_a_failing_layer_check_is_rendered_as_failing(tmp_path):
    def bad(layer):
        layer["ours_vs_lab_formula_max_mm"] = 0.5
        layer["control_shifted_columns_max_mm"] = 0.0

    block = render(tmp_path, layer=bad)["p2-layer-check"]
    assert "**不通过**" in line_with(block, "实验室自己的公式") and "**抓不出错**" in block
