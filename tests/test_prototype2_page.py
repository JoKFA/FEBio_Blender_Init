"""docs/15-prototype.md section 8 (prototype two) shows the numbers of the archived files, written by a tool.

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


# --- section 8.8, ten round trips (T-29) -------------------------------------------------------------

CYCLE_BLOCKS = ("p2-cycles-conditions", "p2-cycles-checks", "p2-cycles-physics", "p2-cycles-physics-report",
                "p2-cycles-final", "p2-cycles-trend", "p2-cycles-health")


def test_the_cycle_blocks_are_in_the_page_with_ten_rows():
    tool = load_tool()
    text = tool.base.read_text(DOC)
    spans, _ = tool.find_blocks(text)
    blocks = tool.load()
    for name in CYCLE_BLOCKS:
        assert name in spans and name in blocks, name
    n = tool.load_all()["cycles"]["cycles"]
    assert n == 10
    assert len(blocks["p2-cycles-physics"].splitlines()) == 2 + n and len(blocks["p2-cycles-final"].splitlines()) == 2 + n


def test_the_cycle_page_says_what_the_card_requires():
    text = section8(load_tool())
    sub = text[text.index("### 8.8 来回 10 次"):]
    assert "几乎是按构造通过" in sub and "绝对量" in sub and "不是一段段累加" in sub
    assert "不回答实验室的观察" in sub and "P-06" in sub and "A-39" in sub
    assert "不说哪一种对" in sub and "P-07" in sub


def test_the_archived_cycle_files_agree_with_each_other():
    d = load_tool().load_all()
    cy = d["cycles"]
    for key, run_key in (("a", "cycles_a_report"), ("b", "cycles_b_report")):
        r = d[run_key]
        assert r["frames"] == cy[key]["frames"] == 15 + 2 * 36 * cy["cycles"]
        assert r["passed"] == cy[key]["all_passed"]
        assert r["checks"]["d"]["numbers"]["inverted_tets"] == cy[key]["check_d"]["inverted_tets"]
        assert len(cy[key]["return_frames"]) == len(cy[key]["open_frames"]) == cy["cycles"]
        assert r["return_to_settled"]["frames"] == cy[key]["return_frames"]  # the report finds the same returns
        # the report's aggregate is the largest of the ten per-return values (the same measurement, two ways)
        assert abs(r["return_to_settled"]["max_mm"] - cy[key]["physics_return_max_mm"]["largest"]) <= 1e-9 * max(1.0, r["return_to_settled"]["max_mm"])
        for name in ("physics_return_max_mm", "final_return_max_mm", "final_open_max_mm"):
            assert len(cy[key][name]["values"]) == cy["cycles"]


def test_a_failed_cycle_check_a_flipped_face_and_a_growing_series_are_rendered_as_such(tmp_path):
    def fail(report):
        report["checks"]["d"]["passed"] = False
        report["checks"]["d"]["message"] = "7 tets are inverted"
        report["passed"] = False

    blocks = render(tmp_path, cycles_b_report=fail)
    row = line_with(blocks["p2-cycles-checks"], "(d) 四面体网格保持有效")
    assert "**不通过**：7 tets are inverted" in row and row.count("通过：翻转") == 1

    def grow(cy):
        cy["a"]["physics_return_max_mm"].update(slope_sign="up", slope_per_cycle=1.5e-3, last=0.0123, first=0.001)
        cy["b"]["mesh_health_open"]["cycle_10"]["flipped (dot < 0)"] = 123

    blocks = render(tmp_path, cycles=grow)
    assert "上升" in line_with(blocks["p2-cycles-trend"], "物理：回到起点，最大")
    assert "翻面 123 /" in blocks["p2-cycles-health"]


def test_the_reading_paragraph_of_8_8_is_true_of_the_archive():
    """8.8 says: no return value grows, the open pose repeats to rounding, the surface health counts do not increase.
    If the archive ever says otherwise, this fails and the paragraph has to be rewritten."""
    cy = load_tool().load_all()["cycles"]
    for key in ("a", "b"):
        for name in ("physics_return_max_mm", "physics_return_mean_mm", "final_return_max_mm", "final_return_mean_mm"):
            s = cy[key][name]
            assert s["first"] > 0, name  # the check can fail: a zero would mean nothing was measured
            assert s["largest"] <= s["first"] * (1 + 1e-6), (key, name)
        assert cy[key]["final_open_max_mm"]["largest"] < 1e-6
        h1, hn = (cy[key]["mesh_health_open"][f"cycle_{c}"] for c in (1, cy["cycles"]))
        assert h1["flipped (dot < 0)"] > 0 and h1["edges < 0.5x"] > 0  # present from the first opening
        assert hn["flipped (dot < 0)"] <= h1["flipped (dot < 0)"] and hn["edges < 0.5x"] <= h1["edges < 0.5x"]
        assert cy[key]["check_d"]["inverted_tets"] == 0 and cy[key]["all_passed"] is True
    assert cy["b"]["mesh_health_open"]["cycle_1"]["flipped (dot < 0)"] > cy["a"]["mesh_health_open"]["cycle_1"]["flipped (dot < 0)"]
