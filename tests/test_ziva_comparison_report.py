"""The comparison report in the repository (data/preview/ziva_comparison.json, written by tools/ziva_comparison.py)
has every table the T-34 card asks for, complete: a table with a hole in it, or a "last pose" without its frame,
must not pass as a report. This reads the committed numbers only; it does not need the lab's data.

Where a number is a known fact about Ziva's own results (docs/13 E-15), the report must carry that number: it
shows the tool read the right run, the right frames and the right vertices.
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import local_paths
import pytest

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "data" / "preview" / "ziva_comparison.json"
RUNS = ("full_face", "lips_only")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _numbers(values, count: int) -> bool:
    return (isinstance(values, list) and len(values) == count
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values))


def test_it_holds_numbers_only_and_nothing_of_one_machine():
    text = REPORT.read_text(encoding="utf-8")
    assert len(text) < 200_000  # per-frame numbers, not a mesh
    assert ":\\\\" not in text and ":/" not in text and "Users" not in text
    assert json.loads(text)["format"] == "asrp-ziva-comparison/1"


def test_both_layers_have_three_numbers_on_every_frame_against_both_ziva_runs(report):
    aa = report["neutral_to_AA"]
    assert aa["frames"] == 47 and aa["vertices"] == 10240 and aa["motion_frames"] == [15, 36] and aa["hold_frames"] == [37, 46]
    for layer in ("physics", "final"):
        assert set(aa[layer]) == {f"against_ziva_{run}" for run in RUNS}
        for run in RUNS:
            table = aa[layer][f"against_ziva_{run}"]
            assert table["frames"] == 47 and table["vertices"] == 10240
            for key in ("mean_mm", "p95_mm", "max_mm"):
                assert _numbers(table[key], 47), (layer, run, key)
            assert all(a <= b <= c for a, b, c in zip(table["mean_mm"], table["p95_mm"], table["max_mm"]))
            assert table["max_mm"][0] < 1e-4  # frame 0 is the rest shape on both sides
            assert table["max_mm"][36] > 0.1  # and the two are not the same result
            assert set(table["last_pose"]) == {"frame_36", "frame_46"}  # every "last pose" names its frame
            for pose in table["last_pose"].values():
                assert set(pose) == {"mean_mm", "p95_mm", "max_mm"} and all(v > 0 for v in pose.values())
    assert all(c["passed"] in (True, False, None) and c["message"] for c in aa["checks"].values())
    assert set(aa["checks"]) == {"a", "b", "b2", "c", "d"}


def test_the_ziva_side_carries_the_known_numbers_of_its_own_two_runs(report):
    between = report["neutral_to_AA"]["ziva_full_face_against_ziva_lips_only_physics"]
    assert abs(between["mean_mm"][36] - 1.98) < 0.01 and abs(between["max_mm"][36] - 7.98) < 0.01
    assert abs(between["mean_mm"][14] - 1.51) < 0.01 and abs(between["max_mm"][14] - 5.09) < 0.01
    sag = report["gravity_sag"]
    assert abs(sag["ziva_full_face"]["mean_mm"][14] - 0.293) < 0.001 and abs(sag["ziva_full_face"]["max_mm"][14] - 1.224) < 0.01
    assert abs(sag["ziva_lips_only"]["mean_mm"][14] - 1.777) < 0.001 and abs(sag["ziva_lips_only"]["max_mm"][14] - 5.390) < 0.01
    assert abs(sag["ziva_lips_only"]["along_mm"][14] - 1.72) < 0.01
    assert abs(sag["ziva_lips_only"]["step_frame_13_to_14_max_mm"] - 0.365) < 0.001  # still falling
    assert abs(sag["ziva_full_face"]["step_frame_13_to_14_max_mm"] - 0.026) < 0.001
    surface = report["surface"]
    for run, short in (("full_face", 37), ("lips_only", 39)):
        assert max(surface[f"ziva_{run}_physics"]["flipped_per_frame"]) == 0
        final = surface[f"ziva_{run}_final"]
        assert final["worst"] == {"frame": 20, "flipped": 4, "short_edges": final["short_edges_per_frame"][20]}
        assert final["last"] == {"frame": 46, "flipped": 3, "short_edges": short}
    shake = report["head_shake"]["ziva"]
    assert abs(shake["wobble"]["max_mm"] - 2.731) < 0.001 and shake["wobble"]["frame"] == 45
    assert (shake["decay_over_its_whole_run"]["first_below"], shake["decay_over_its_whole_run"]["stays_below"]) == (14, 28)


def test_the_sag_table_has_every_frame_of_the_settle_for_all_three(report):
    sag = report["gravity_sag"]
    assert sag["frames"] == list(range(15)) and sag["vertices"] == 10240 and sag["reference_frame"] == 0
    for who in ("ours", "ziva_full_face", "ziva_lips_only"):
        for key in ("max_mm", "mean_mm", "along_mm"):
            assert _numbers(sag[who][key], 15), (who, key)
        assert sag[who]["max_mm"][0] == 0.0 and sag[who]["mean_mm"][14] > 0.01 and sag[who]["along_mm"][14] > 0
        assert isinstance(sag[who]["step_frame_13_to_14_max_mm"], float)
    assert any("still falling" in n for n in sag["notes"]) and any("not known" in n for n in sag["notes"])


def test_the_head_shake_names_its_measure_and_gives_both_decay_numbers(report):
    shake = report["head_shake"]
    assert (shake["base_frame"], shake["stop_frame"], shake["limit_mm"]) == (14, 46, 0.04)
    assert "all 10240" in shake["vertices"] and shake["scope"] == {
        "ours": "lips only", "ziva": "full face (there is no lips-only head shake from Ziva)"}
    window = shake["window_frames_after_stop"]
    assert window >= 28  # long enough to hold Ziva's "stays below" (28 frames after the stop)
    for who in ("ours", "ziva"):
        side = shake[who]
        assert _numbers(side["wobble"]["per_frame_max_mm"], side["frames"]) and side["wobble"]["max_mm"] > 0
        assert side["wobble"]["reference_frame"] == 14 and side["wobble"]["vertices"] == 10240
        assert side["decay"]["window"] == window and side["decay"]["stop_frame"] == 46
        assert {"first_below", "stays_below"} <= set(side["decay"])  # a number, or None: "not reached in the window"
        assert abs(side["head_travel_max_mm"] - 4.464) < 0.001  # the same shake on both sides
    assert any("not converged" in n for n in shake["notes"]) and any("across scopes" in n for n in shake["notes"])


def test_the_speed_table_names_machine_threads_and_mesh_on_both_sides(report):
    speed = report["speed"]
    ours, ziva = speed["ours"], speed["ziva"]
    assert ours["machine"] and ours["logical_processors"] >= 1 and ours["febio_threads"] >= 1
    assert ours["febio_s"] > 0 and ours["febio_s_per_frame"] > 0 and ours["generate_s"] > 0 and ours["post_s"] > 0
    assert ours["mesh"]["nodes"] == 6747 and ours["mesh"]["tets"] == 26721
    assert ziva["machine"] and ziva["logical_processors"] == 16 and ziva["maya_threads"] == 16
    assert ziva["solver_threads_used"] == "not measured"
    exports = ziva["export_s_per_frame_with_reading_and_writing"]
    assert abs(exports["full_face"] - 2.55) < 0.01 and abs(exports["lips_only"] - 1.03) < 0.01
    assert "not recomputed" in ziva["solver_log"]["source"]
    assert abs(ziva["mesh"]["lips_tet_size_scene_units"] - 26.37) < 0.01 and "one frame" in ziva["one_step_is"]


def test_what_could_be_set_is_zivas_and_what_could_not_is_listed(report):
    settings = report["settings"]
    assert settings["tissue_settings"] == "lab"
    assert settings["material"]["E_mpa"] == {"value": 0.012, "source": "lab_setting"}
    assert settings["material"]["nu"] == {"value": 0.4, "source": "lab_setting"}
    assert settings["material"]["density_t_per_mm3"] == {"value": 1.06e-09, "source": "lab_setting"}
    assert settings["substeps_per_frame"] == {"value": 1, "source": "lab_setting"}
    assert settings["fps"] == {"value": 30, "source": "lab_setting"}
    measured = settings["ziva_measured"]
    assert (measured["E_kPa"], measured["poisson"], measured["density_kg_m3"], measured["substeps"], measured["fps"]) == (
        12.0, 0.4, 1060.0, 1, 30.0)
    listed = {row["setting"]: row for row in settings["not_matched"]}
    assert set(listed) == {"material model", "integrator", "Newton iteration limit", "stiffness damping", "attachments",
                           "physical scale", "gravity"}
    assert all(row["ziva"] and row["ours"] and row["note"] for row in listed.values())
    assert "StVK" in listed["material model"]["ziva"] and "20000" in listed["material model"]["ziva"]
    assert "BackwardEuler" in listed["integrator"]["ziva"] and "N/m^3" in listed["attachments"]["ziva"]
    assert "100" in listed["physical scale"]["ziva"] and "0.67" in listed["physical scale"]["ours"]
    assert {row["what"] for row in report["differences_between_the_setups"]} == {
        "material", "physical scale", "collisions", "constraints", "what the lip corners hang on"}
    assert all(row["ours"] and row["ziva_full_face"] and row["ziva_lips_only"] for row in report["differences_between_the_setups"])


def test_flipped_faces_and_short_edges_are_listed_frame_by_frame_beside_zivas(report):
    surface = report["surface"]
    for layer in ("ours_physics", "ours_final"):
        assert _numbers(surface[layer]["flipped_per_frame"], 47) and _numbers(surface[layer]["short_edges_per_frame"], 47)
    listed = surface["ours_final_flipped_faces"]
    assert [e["frame"] for e in listed] == surface["ours_final"]["frames_with_flipped_faces"]
    for entry in listed:
        assert entry["flipped"] == len(entry["faces"]) == len(entry["centroid_in_box"]) == len(entry["rest_area_mm2"]) > 0
        assert entry["flipped"] == surface["ours_final"]["flipped_per_frame"][entry["frame"]]
        for run in RUNS:
            assert entry[f"ziva_{run}_flipped"] == surface[f"ziva_{run}_final"]["flipped_per_frame"][entry["frame"]]
            assert 0 <= entry[f"same_faces_as_ziva_{run}"] <= min(entry["flipped"], entry[f"ziva_{run}_flipped"])
    assert "not judged" in surface["note"]


def test_the_driver_record_and_the_reading_notes_are_there(report):
    driver = report["driver"]
    assert _numbers(driver["our_jaw_degrees"], 47) and abs(driver["our_jaw_degrees"][36] + 5.16416) < 1e-5
    for run in RUNS:
        assert _numbers(driver[f"ziva_{run}_jaw_degrees"], 47)
        assert driver[f"largest_difference_to_ziva_{run}_degrees"] < 0.01
    notes = " ".join(report["read_this_first"])
    for phrase in ("No pass line", "reference", "sensitivity experiment", "our script", "target pose", "36", "46"):
        assert phrase in notes
    made = report["made"]
    assert len(made["lab_motion"]["sha256"]) == 64 and made["lab_motion"]["file"].endswith("combined_checkpoints.pkl")
    assert set(made["ziva_runs"]) == {"full_face", "lips_only", "head_shake"}


def test_our_side_carries_the_numbers_of_the_runs_the_report_was_made_from(report):
    """Our own numbers, pinned like Ziva's: a report made from other runs (the default material, an older scene, a
    wrong percentile) must not pass as this one. They change when the lab tissue settings or the generator change;
    then the report is written again and these numbers and docs/13 E-19 are updated together."""
    aa = report["neutral_to_AA"]
    full, lips = aa["physics"]["against_ziva_full_face"], aa["physics"]["against_ziva_lips_only"]
    assert [round(full[k][36], 3) for k in ("mean_mm", "p95_mm", "max_mm")] == [2.212, 4.913, 7.638]
    assert [round(full[k][46], 3) for k in ("mean_mm", "p95_mm", "max_mm")] == [2.212, 4.910, 7.634]
    assert [round(full[k][14], 3) for k in ("mean_mm", "p95_mm", "max_mm")] == [0.218, 0.586, 1.117]
    assert [round(lips[k][36], 3) for k in ("mean_mm", "p95_mm", "max_mm")] == [2.321, 4.321, 7.098]
    assert full["worst"]["mean_mm"] == {"value": pytest.approx(2.2186, abs=1e-4), "frame": 37}
    # the final layer differs from Ziva's exactly as the physics layer does: the landmark layer is the same on both
    for run in RUNS:
        physics, final = aa["physics"][f"against_ziva_{run}"], aa["final"][f"against_ziva_{run}"]
        assert max(abs(a - b) for key in ("mean_mm", "p95_mm", "max_mm") for a, b in zip(physics[key], final[key])) < 1e-4
    ours = report["gravity_sag"]["ours"]
    assert round(ours["mean_mm"][14], 3) == 0.122 and round(ours["max_mm"][14], 3) == 0.497
    assert ours["step_frame_13_to_14_max_mm"] < 1e-4  # ours is still at frame 14
    wobble = report["head_shake"]["ours"]["wobble"]
    assert round(wobble["max_mm"], 3) == 0.121 and wobble["frame"] == 19
    assert report["head_shake"]["ours"]["decay"]["first_below"] == 2
    surface = report["surface"]
    assert max(surface["ours_physics"]["flipped_per_frame"]) == 0 and max(surface["ours_physics"]["short_edges_per_frame"]) == 0
    flipped = surface["ours_final"]["flipped_per_frame"]
    assert max(flipped) == 8 and [f for f, n in enumerate(flipped) if n == 8] == [20, 21]
    assert surface["ours_final"]["last"] == {"frame": 46, "flipped": 3, "short_edges": 109}
    # every face Ziva flips is flipped in ours too, on every frame where ours has any
    for entry in surface["ours_final_flipped_faces"]:
        for run in RUNS:
            assert entry[f"same_faces_as_ziva_{run}"] == entry[f"ziva_{run}_flipped"], entry["frame"]
    assert report["speed"]["ours"]["febio_threads"] == 4


def test_the_explanation_in_docs_13_quotes_this_reports_numbers(report):
    """docs/13 E-19 is written from this file. If the report is made again and the document is not, the rows the
    document quotes are no longer in it."""
    text = (REPO / "docs" / "13-explanations.md").read_text(encoding="utf-8")
    entry = text[text.index("## E-19"):]
    entry = entry[: entry.index("## 怎么加新的一条")]
    aa, sag = report["neutral_to_AA"], report["gravity_sag"]

    def three(table, frame):
        return f"{table['mean_mm'][frame]:.2f} / {table['p95_mm'][frame]:.2f} / {table['max_mm'][frame]:.2f}"

    for frame in (14, 20, 36, 46):
        cells = [three(aa["physics"][f"against_ziva_{run}"], frame) for run in RUNS]
        cells.append(three(aa["ziva_full_face_against_ziva_lips_only_physics"], frame))
        assert " | ".join(cells) in entry, f"frame {frame}: the row {cells} is not in E-19"
    for frame in (1, 6, 14):
        cells = [f"{sag[who]['mean_mm'][frame]:.3f} / {sag[who]['max_mm'][frame]:.3f} / {sag[who]['along_mm'][frame]:.3f}"
                 for who in ("ours", "ziva_full_face", "ziva_lips_only")]
        assert f"| {frame} | " + " | ".join(cells) + " |" in entry, f"sag frame {frame}"
    shake, surface = report["head_shake"], report["surface"]
    for number in (f"{shake['ours']['wobble']['max_mm']:.3f} mm", f"{shake['ziva']['wobble']['max_mm']:.3f} mm",
                   f"{surface['ours_final']['last']['short_edges']} 条", f"{surface['ziva_full_face_final']['last']['short_edges']} 条",
                   f"{report['speed']['ours']['febio_s_per_frame']:.2f} 秒"):
        assert number in entry, number


def _same(a, b, where: str, ignore) -> list[str]:
    """Where two reports differ, apart from the keys in `ignore` and from differences below 1e-6 in a number."""
    if any(where.endswith(key) for key in ignore):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return [f"{where}: keys {sorted(a.keys() ^ b.keys())}"]
        return [d for k in a for d in _same(a[k], b[k], f"{where}.{k}", ignore)]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{where}: {len(a)} against {len(b)} entries"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _same(x, y, f"{where}[{i}]", ignore)]
    if isinstance(a, float) or isinstance(b, float):
        ok = isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 1e-6 + 1e-6 * abs(b)
        return [] if ok else [f"{where}: {a!r} against {b!r}"]
    return [] if a == b else [f"{where}: {a!r} against {b!r}"]


@pytest.mark.skipif(os.environ.get("ASRP_SLOW") != "1", reason="two real lip runs, about a minute: set ASRP_SLOW=1")
def test_the_report_in_the_repository_is_what_the_tool_writes_today(report, tmp_path):
    """The real entry point on the real data: tools/ziva_comparison.py from the import to the report (two FEBio
    runs), against the committed file. Only the date, the run names, the timings and the checks' wording (which
    carries 1e-10-sized numbers) may differ. So a changed default, generator or converter cannot leave a stale
    report behind unnoticed at the full verification level."""
    if local_paths.ziva_trip() is None:
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    out = tmp_path / "report.json"
    done = subprocess.run([sys.executable, "-B", str(REPO / "tools" / "ziva_comparison.py"), str(out), "--work",
                           str(tmp_path / "work")], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    fresh = json.loads(out.read_text(encoding="utf-8"))
    ignore = (".made.date", ".made.our_runs", ".message", ".febio_s", ".febio_s_per_frame", ".generate_s", ".post_s",
              ".logical_processors")
    differences = _same(fresh, report, "report", ignore)
    assert not differences, differences[:10]
    assert fresh["speed"]["ours"]["febio_s"] > 0 and fresh["made"]["our_runs"]["aa"]
