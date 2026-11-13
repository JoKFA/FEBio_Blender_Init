"""The Ziva-machine helpers that can be checked without Maya: head-shake keys, value summary, the motion reader."""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lab_motion_lower_lip as motion  # noqa: E402
import ziva_trip_probe as probe  # noqa: E402

EXPORT = ROOT / "data" / "lab_export"


def test_head_shake_keys_are_the_labs_quarter_loop_keys():
    keys = probe.shake_keys(2.0)
    assert keys[:6] == [(0, 2.0), (16, 2.0), (18.5, 7.0), (21.0, 2.0), (23.5, -3.0), (26.0, 2.0)]
    assert len(keys) == 2 + 3 * 4 and keys[-1] == (46.0, 2.0)


def test_summary_counts_equal_values_once():
    assert probe.summarize([0.5, 0.5, 2, 0.5]) == [{"value": 0.5, "nodes": 3}, {"value": 2, "nodes": 1}]


def lower_lip_landmark():
    skin = json.loads((EXPORT / "skin_skinCluster7.json").read_text(encoding="utf-8"))
    groups = json.loads((EXPORT / "lip_attachments.json").read_text(encoding="utf-8"))["groups"]
    lower = [v for v, _ in next(g for g in groups if g["attachment"] == "zAttachment2")["vertices"]]
    assert len(lower) == 76
    return skin, max(skin["weights"][lower[0]], key=lambda pair: pair[1])[0]


def test_pkl_motion_gives_the_weighted_displacement_and_only_where_landmarks_move():
    _, landmark = lower_lip_landmark()
    steps = []
    for fraction in (0.5, 1.0):
        vector = np.zeros(3603)
        vector[3 * landmark + 1] = -13.0 / 0.962 * fraction  # 13 mm down at 0.962 mm per scene unit
        vector[900] = 20.0 * fraction
        steps.append(vector)
    offsets, jaw = motion.offsets_from_pkl(pickle.dumps(steps))
    result = motion.report(offsets, jaw, EXPORT, 0.962)
    lower = next(g for g in result["groups"] if g["group"].startswith("zAttachment2"))
    assert result["frames"] == 2 and result["landmarks_moving_over_0.01_mm"] == 1
    assert result["landmark_travel_last_frame_max_mm"] == pytest.approx(13.0)
    assert 0 < lower["last_frame_max_mm"] <= 13.0 + 1e-9 and lower["any_frame_max_mm"] == lower["last_frame_max_mm"]
    assert result["jaw_euler_offset_last_frame_deg"] == [20.0, 0.0, 0.0]
    still, _ = motion.offsets_from_pkl(pickle.dumps([np.zeros(3603)]))
    assert all(g["any_frame_max_mm"] == 0 for g in motion.report(still, None, EXPORT, 0.962)["groups"])


def test_keys_file_gives_the_same_numbers_as_the_pkl():
    skin, landmark = lower_lip_landmark()
    values = {name: [[0.0] * 6, [0.0] * 6] for name in skin["influences"]}
    values[skin["influences"][landmark]][1][1] = -1.3
    values["jaw01"] = [[0, 0, 0, 5.0, 0, 0], [0, 0, 0, 25.0, 0, 0]]
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    keys = {"frames": [14, 15], "values": values, "parent_of": {n: "|head" if n == "jaw01" else "|joint_oor" for n in values},
            "parent_world_matrix": {"|joint_oor": identity, "|head": identity}}
    offsets, jaw = motion.offsets_from_keys(keys, skin["influences"])
    vector = np.zeros(3603)
    vector[3 * landmark + 1] = -1.3
    from_pkl, _ = motion.offsets_from_pkl(pickle.dumps([np.zeros(3603), vector]))
    assert np.array_equal(offsets, from_pkl) and list(jaw[-1]) == [20.0, 0.0, 0.0]
    keys["parent_world_matrix"]["|joint_oor"] = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    turned, _ = motion.offsets_from_keys(keys, skin["influences"])
    assert np.allclose(turned[1, landmark], [1.3, 0, 0])


class Hostile:
    def __reduce__(self):
        import os
        return (os.system, ("echo should-never-run",))


def test_the_reader_refuses_anything_but_plain_data():
    with pytest.raises(pickle.UnpicklingError, match="refused"):
        motion.offsets_from_pkl(pickle.dumps([Hostile()]))
    with pytest.raises(ValueError, match="expected a list of vectors"):
        motion.offsets_from_pkl(pickle.dumps([np.zeros(10)]))
