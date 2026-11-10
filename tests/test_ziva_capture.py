"""T-19: completeness checks must reject plausible-looking partial exports."""

import array
import json

import pytest

import ziva_machine_export as z


def test_translation_does_not_require_jaw_rotation_or_landmark_motion():
    stats = {"frames_sampled": 31, "frames_expected": 31, "bone_translation": 5,
             "jaw_degrees": 0, "landmark_travel": 0, "final_vs_physics": 0}
    assert z.check_motion(stats, "head_translation") == []
    assert z.check_motion(stats, "expression")
    assert z.check_motion({**stats, "bone_translation": 0}, "head_translation")


def test_empty_nonfinite_and_mismatched_meshes_are_not_valid_motion():
    for a, b in (([], []), ([(0, 0, 0)], []), ([(float("nan"), 0, 0)], [(0, 0, 0)])):
        with pytest.raises(ValueError):
            z.largest_move(a, b)


def test_sanitized_namespace_collisions_get_distinct_stable_ids():
    assert z.file_name("a:b") == z.file_name("a_b")
    assert z.stable_name("a:b") != z.stable_name("a_b")
    assert z.stable_name("a:b") == z.stable_name("a:b")


def test_settings_never_waive_structural_errors_or_allow_path_in_motion(tmp_path):
    base = {**z.SETTINGS, "out": str(tmp_path)}
    assert z.validate_settings(base) == str(tmp_path)
    for update in ({"motion": "../escape"}, {"accepted": [""]}, {"stage": "export"},
                   {"kind": "unknown"}, {"out": str(tmp_path / "中文")}):
        with pytest.raises(ValueError):
            z.validate_settings({**base, **update})


def test_frame_checks_detect_missing_duplicate_out_of_order_and_short_samples(tmp_path):
    p = tmp_path / "mesh.points.f32"
    p.write_bytes(array.array("f", [0] * 18).tobytes())
    entry = {"id": "mesh", "samples": p.name, "vertices": 2, "frames": [0, 1, 2]}
    z.check_samples(entry, 0, 2, str(tmp_path))
    for frames in ([0, 2], [0, 1, 1], [1, 0, 2]):
        with pytest.raises(ValueError):
            z.check_samples({**entry, "frames": frames}, 0, 2, str(tmp_path))
    p.write_bytes(p.read_bytes()[:-4])
    with pytest.raises(ValueError, match="byte length"):
        z.check_samples(entry, 0, 2, str(tmp_path))


def test_nan_backup_rejected(tmp_path):
    (tmp_path / "a").write_bytes(array.array("f", [0, float("nan"), 0]).tobytes())
    with pytest.raises(ValueError, match="non-finite"):
        z.check_samples({"id": "a", "samples": "a", "vertices": 1, "frames": [0]}, 0, 0, str(tmp_path))


def test_topology_digest_detects_reordered_vertices_with_unchanged_count():
    assert z.topology_digest([3], [0, 1, 2]) != z.topology_digest([3], [0, 2, 1])


class Schema:
    def __init__(self, times, constant=False):
        self.times, self.constant = times, constant

    def getNumSamples(self):
        return len(self.times)

    def isConstant(self):
        return self.constant

    def getTimeSampling(self):
        return self

    def getSampleTime(self, i):
        return self.times[i]


def test_actual_alembic_samples_not_interpolated_queries():
    times = [0, 1 / 30, 2 / 30]
    z.check_sample_times(Schema(times), times, "mesh")
    z.check_sample_times(Schema([0], constant=True), times, "static_mesh")
    for bad in (Schema([0, 2 / 30]), Schema([0, 1 / 30, 1 / 30]), Schema([0, .1, .2])):
        with pytest.raises(ValueError):
            z.check_sample_times(bad, times, "mesh")


def test_receipt_rejects_altered_manifest_and_empty_collection(tmp_path):
    z.write_json(str(tmp_path / "session_report.json"), {"problems": [], "streams": []})
    z.seal_capture(str(tmp_path))
    (tmp_path / "session_report.json").write_text('{"problems":[]}')
    result = z.check_capture(str(tmp_path), read_alembic=False)
    assert not result["ok"] and "changed file" in result["problems"][0]
    receipt = z.check_collection(str(tmp_path))
    assert not receipt["complete"] and receipt["problems"]


def test_collection_does_not_count_a_diagnostic_whose_files_are_missing_or_changed(tmp_path):
    probe = tmp_path / "probe_1"
    probe.mkdir()
    good = {"stage": "probe", "require_simulation": True, "problems": [],
            "probe": {"source_restored": True, "channel_restored": True, "time_after": 14, "baseline_repeat_error": 0.0}}
    z.write_json(str(probe / "session_report.json"), good)
    missing = "same-frame diagnostic with verified channel restoration missing"

    assert missing in z.check_collection(str(tmp_path))["problems"]  # no seal at all
    z.seal_capture(str(probe))
    assert missing not in z.check_collection(str(tmp_path))["problems"]  # sealed and intact
    z.write_json(str(probe / "session_report.json"), {**good, "notes": ["edited after capture"]})
    assert missing in z.check_collection(str(tmp_path))["problems"]  # changed since it was sealed


def test_manifest_file_cannot_escape_capture(tmp_path):
    with pytest.raises(ValueError):
        z.safe_child(str(tmp_path), "../outside")


def test_capture_callback_retains_failure_if_maya_swallows_it():
    sampler = object.__new__(z.CaptureSampler)
    sampler.errors = []
    sampler.sampler = lambda _: (_ for _ in ()).throw(ValueError("missing frame"))
    sampler(2)
    sampler(3)
    assert len(sampler.errors) == 1 and "missing frame" in sampler.errors[0]
