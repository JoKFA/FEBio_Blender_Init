"""docs/15-prototype.md shows the numbers of the archives that tools/prototype_archive.py made from the product's own runs.

tools/prototype_numbers.py writes every table of numbers between marker comments and lists the numbers and claims in
the running text; this test (so tools/verify.py) fails when the page and the archives in data/preview disagree, when a
quoted number is no longer in the document it is quoted from, when something the retired AA stand-ins left is still
there, and when the page quotes a panel label the add-on does not have. Needs no lab data: it reads the committed
archives only.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "prototype_numbers.py"
DOC = REPO / "docs" / "15-prototype.md"
PREVIEW = REPO / "data" / "preview"
MESHES = ("coarse", "fine")
RETIRED = "aa_" + "standin"  # written in two pieces so that this file is not one of the hits it looks for
PICTURES = [f"prototype_aa36_{layer}_{who}.png" for layer in ("physics", "final") for who in ("coarse", "fine", "ziva")] + [
    "prototype_jaw32_coarse.png", "prototype_jaw32_fine.png"]


def load_tool():
    spec = importlib.util.spec_from_file_location("prototype_numbers", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(doc: Path, preview: Path = PREVIEW) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--check", "--doc", str(doc), "--preview", str(preview)],
                          cwd=REPO, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture()
def archive_copy(tmp_path) -> Path:
    """A copy of the archives the tool reads, for a test to damage."""
    out = tmp_path / "preview"
    out.mkdir()
    tool = load_tool()
    names = [f"prototype_compare_{m}_{r}.json" for m in MESHES for r in tool.REFERENCES]
    names += [f"prototype_ziva_comparison_{m}.json" for m in MESHES]
    names += [f"prototype_run_{m}_{k}.json" for m in MESHES for k in ("aa", "jaw")]
    names += ["prototype_archive_manifest.json", "landmark_layer_check.json", "prototype_run_report.json"]
    for name in names:
        shutil.copyfile(PREVIEW / name, out / name)
    return out


def edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8", newline="\n")


# --- the page and the archives ---------------------------------------------------------------------------


def test_the_page_matches_the_archives():
    done = run_check(DOC)
    assert done.returncode == 0, done.stderr + done.stdout


def test_the_check_can_fail_when_a_number_in_the_page_is_changed_and_names_the_block(tmp_path):
    tool = load_tool()
    text = tool.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems and "aa-distance" in spans
    start, end = spans["aa-distance"]
    block = text[start:end]
    digit = next(i for i, ch in enumerate(block) if i > block.index("\n|---") and ch.isdigit())
    changed = block[:digit] + ("7" if block[digit] != "7" else "8") + block[digit + 1:]
    assert changed != block
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text[:start] + changed + text[end:], encoding="utf-8", newline="\n")
    done = run_check(copy)
    assert done.returncode == 1
    assert "aa-distance" in done.stderr
    assert "gravity" not in done.stderr.split("Differs in block(s):")[-1]  # only the changed block is named


def test_the_check_can_fail_when_an_archive_number_is_changed(archive_copy):
    edit_json(archive_copy / "prototype_compare_coarse_full_face.json",
              lambda d: d["layers"]["physics"]["mean_mm"].__setitem__(36, 9.99))
    done = run_check(DOC, archive_copy)
    assert done.returncode == 1 and "aa-distance" in done.stderr


def test_every_marker_pair_is_well_formed_and_known():
    tool = load_tool()
    text = tool.read_text(DOC)
    spans, problems = tool.find_blocks(text)
    assert not problems, problems
    assert set(spans) == set(tool.BLOCKS), "the page and the tool disagree on the block names"
    for name, (start, end) in spans.items():
        assert len(text[start:end].strip()) > 40, f"block {name} is empty"


def test_a_broken_marker_is_reported(tmp_path):
    tool = load_tool()
    text = tool.read_text(DOC).replace("<!-- END generated: gravity -->", "", 1)
    assert tool.find_blocks(text)[1]
    copy = tmp_path / "15-prototype.md"
    copy.write_text(text, encoding="utf-8", newline="\n")
    assert run_check(copy).returncode == 1


def test_a_claim_the_archives_stop_saying_fails_the_check(archive_copy):
    """The running text names the tets of each mesh and says coarse is below fine in every number of the table."""
    tool = load_tool()
    text = tool.read_text(DOC)
    assert tool.quote_problems(text, archive_copy) == []
    edit_json(archive_copy / "prototype_ziva_comparison_coarse.json",
              lambda d: d["speed"]["ours"]["mesh"].__setitem__("tets", 127))
    assert any("127 个四面体" in p for p in tool.quote_problems(text, archive_copy))

    def coarser_than_fine(d):  # coarse worse than fine in one number of the table
        d["layers"]["physics"]["max_mm"][36] = 99.0

    edit_json(archive_copy / "prototype_compare_coarse_lips_only.json", coarser_than_fine)
    assert any("coarse is below fine" in p for p in tool.quote_problems(text, archive_copy))


def test_a_quote_cannot_outlive_its_source(monkeypatch):
    tool = load_tool()
    text = tool.read_text(DOC)
    assert tool.quote_problems(text) == []
    monkeypatch.setattr(tool, "QUOTES", [("docs/10-decisions.md", "a string no decision holds 0.0")])
    problems = tool.quote_problems(text)
    assert any("docs/10-decisions.md does not hold" in p for p in problems)
    assert any("docs/15 no longer holds" in p for p in problems)


# --- the archives are not empty and agree with each other ---------------------------------------------------


def test_the_archives_hold_what_the_page_says_they_do():
    tool = load_tool()
    a = tool.Archive()
    for mesh in MESHES:
        aa = a.zc[mesh]["neutral_to_AA"]
        assert aa["frames"] == 47 and aa["vertices"] == 10240
        assert a.zc[mesh]["speed"]["ours"]["mesh"]["tets"] > 0 and a.zc[mesh]["speed"]["ours"]["febio_s_per_frame"] > 0
        for ref in tool.REFERENCES:
            layer = a.compare[(mesh, ref)]["layers"]["physics"]
            assert layer["frames"] == 47 and layer["vertices"] == 10240
            assert all(len(layer[key]) == 47 and max(layer[key]) > 0.1 for key in ("mean_mm", "p95_mm", "max_mm"))
        for kind in ("aa", "jaw"):
            report = a.run[(mesh, kind)]
            assert report["status"] == "complete" and report["checks"]["a"]["passed"] is True
        assert a.run[(mesh, "aa")]["frames"] == 47 and a.run[(mesh, "jaw")]["frames"] == 51
    assert a.manifest["what_else_ran"] and a.manifest["febio_threads"] > 0
    assert a.landmark["landmarks"] == 300 and a.landmark["ours_vs_lab_formula_max_mm"] < a.landmark["limit_mm"]


def test_asrp_compare_and_the_comparison_tool_agree_on_the_same_run():
    """Two readers of the same run and the same Ziva frames: `asrp compare` and tools/ziva_comparison.py."""
    tool = load_tool()
    a = tool.Archive()
    for mesh in MESHES:
        for ref, key in (("full_face", "against_ziva_full_face"), ("lips_only", "against_ziva_lips_only")):
            ours = a.compare[(mesh, ref)]["layers"]["physics"]
            theirs = a.zc[mesh]["neutral_to_AA"]["physics"][key]
            for stat in ("mean_mm", "p95_mm", "max_mm"):
                for frame in tool.FRAMES:
                    assert abs(ours[stat][frame] - theirs[stat][frame]) < 1e-4, (mesh, ref, stat, frame)


def test_the_two_meshes_were_compared_with_the_same_ziva_runs_and_the_same_material():
    tool = load_tool()
    a = tool.Archive()
    assert a.zc["coarse"]["made"]["ziva_runs"] == a.zc["fine"]["made"]["ziva_runs"]
    assert a.zc["coarse"]["settings"]["material"] == a.zc["fine"]["settings"]["material"]
    assert a.zc["coarse"]["gravity_sag"]["ziva_full_face"] == a.zc["fine"]["gravity_sag"]["ziva_full_face"]
    assert a.zc["coarse"]["head_shake"]["ziva"]["wobble"] == a.zc["fine"]["head_shake"]["ziva"]["wobble"]


def test_a_failed_check_is_rendered_as_failed_and_a_check_that_did_not_run_says_why(archive_copy):
    tool = load_tool()

    def fail_and_skip(report):
        report["checks"]["c"]["passed"] = False
        report["checks"]["c"]["message"] = "free vertices moved the wrong way"
        report["checks"]["d"]["passed"] = None
        report["checks"]["d"]["message"] = "no tet mesh in this scene"

    edit_json(archive_copy / "prototype_run_fine_aa.json", fail_and_skip)
    block = tool.load(archive_copy)["checks"]
    row_c = next(line for line in block.splitlines() if "Gravity sag" in line)
    row_d = next(line for line in block.splitlines() if "Tet mesh valid" in line)
    assert "**不通过**：free vertices moved the wrong way" in row_c and "没运行：no tet mesh" in row_d
    assert row_c.count("通过") == 2 and "**不通过**" not in row_c.split("|")[2]  # the coarse column keeps its own verdict


def test_the_final_shape_sentence_does_not_say_same_when_the_layers_differ(archive_copy):
    tool = load_tool()
    assert "相同" in tool.load(archive_copy)["aa-final"]
    edit_json(archive_copy / "prototype_compare_fine_full_face.json",
              lambda d: d["layers"]["final"]["mean_mm"].__setitem__(36, d["layers"]["physics"]["mean_mm"][36] + 0.5))
    sentence = tool.load(archive_copy)["aa-final"]
    assert "不相同" in sentence and "0.5" in sentence


# --- what must not be on the page --------------------------------------------------------------------------


def test_nothing_of_the_retired_stand_ins_or_the_old_waiting_remains():
    text = DOC.read_text(encoding="utf-8")
    assert "甲" not in text and "乙" not in text
    assert not re.findall(r"\b(?:P-07|Q20|D2|D3|D6)\b", text)
    assert RETIRED not in text and "aa_a" not in text and "aa_b" not in text


def test_no_code_or_archive_of_the_retired_stand_ins_is_left():
    hits = []
    for folder in ("src", "tools", "tests", "blender_addon"):
        for path in (REPO / folder).rglob("*.py"):
            if RETIRED in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path.relative_to(REPO)))
    assert not hits, hits
    assert not sorted(p.name for p in PREVIEW.glob("aa_*"))


def test_no_path_of_this_machine_is_on_the_page():
    text = DOC.read_text(encoding="utf-8")
    assert "Users" not in text and "E:\\" not in text and "E:/" not in text and "AppData" not in text


# --- the page's structure -----------------------------------------------------------------------------------


def test_the_page_has_its_sections_and_the_walk_place_holds_exactly_one_line():
    text = DOC.read_text(encoding="utf-8")
    for heading in ("## 1. 这是什么", "## 2. 怎么用", "## 3. 算出来是什么样，离 Ziva 多远", "## 4. 已知的差距",
                    "## 5. 仍然成立的核对"):
        assert text.count("\n" + heading + "\n") == 1, heading
    marker = "<!-- WALK: screenshots and what was seen go here; the coordinator fills this in -->"
    assert text.count(marker) == 1
    after = text.split("### 用鼠标走一遍（截图）\n", 1)[1]
    body = re.split(r"\n#{1,3} ", after, maxsplit=1)[0]
    assert body.strip() == marker


def test_every_picture_the_page_shows_exists_and_every_picture_made_is_shown():
    text = DOC.read_text(encoding="utf-8")
    shown = set(re.findall(r"\]\(\.\./data/preview/([\w.-]+\.png)\)", text))
    assert set(PICTURES) <= shown, sorted(set(PICTURES) - shown)
    for name in shown:
        assert (PREVIEW / name).stat().st_size > 10_000, name


def test_the_panel_labels_the_page_quotes_are_the_add_ons():
    """The page quotes the panel's English text as it is on screen: each label is in the add-on's source, or is a
    motion title the panel reads from the motion files. The two radio buttons of step 1 are built elsewhere and
    are described as docs/06 will have them, so they are not checked here."""
    text = DOC.read_text(encoding="utf-8")
    source = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "blender_addon").rglob("*.py"))
    for label in ("1  Open the asset", "2  Choose a motion", "3  Run", "Open asset", "Run", "Cancel", "Results", "Checks",
                  "Physics only", "Final shape", "Choose project folder", "Open folder", "Pause",
                  "Choose the ASRP project folder.", "Computes the whole motion, then replays it. Not frame-by-frame.",
                  "Open: ", "Material: ", "measured in Ziva", "Frame "):
        assert label in text, f"the page no longer quotes {label!r}"
        assert label in source, f"the add-on has no {label!r}"
    for name in ("jaw_open_12deg", "neutral_to_AA", "head_shake"):
        title = json.loads((REPO / "data" / "lab_export" / "trajectories" / f"{name}.json").read_text(encoding="utf-8"))["title"]
        assert title in text, title
