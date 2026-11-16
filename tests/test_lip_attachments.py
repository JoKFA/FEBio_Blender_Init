"""tools/lip_attachments.py: the export logic on a tiny inventory, and the position check on the real
OBJs in data/lab_export/ (docs/09 T-03). The real-data tests skip when those files are missing."""

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
from lip_attachments import build
from test_asset_report import ELEMENTWISE, inventory

from asrp_core.asset.coords import read_obj

REPO = Path(__file__).resolve().parents[1]
LAB = REPO / "data" / "lab_export"
EXPORT = LAB / "lip_attachments.json"
OBJS = {
    "lips": LAB / "mesh_middleres_OrbicularisOris.obj",
    "skull": LAB / "mesh_middleres_skull.obj",
    "jaw": LAB / "mesh_middleres_Jaw.obj",
}
HAVE_LAB = EXPORT.exists() and all(p.exists() for p in OBJS.values())


# ---- synthetic inventory: lip tissue (6 vertices) -> bone, two attachments ----

RANGE_ONE = {"wl[0].w[0:5]": [0.0, 0.25, 0.0, 0.0, 0.0, 0.0]}  # only vertex 1 stored, at 0.25
SYNTHETIC = inventory({"a1": ELEMENTWISE, "a2": RANGE_ONE})  # a1 -> {2, 3, 5} by default


def test_stored_weights_and_defaults_are_exported():
    out = build(SYNTHETIC, "abc", groups=[("a1", "up", "lip", "bone", 3), ("a2", "down", "lip", "bone", 1)])
    up, down = out["groups"]
    assert up["vertices"] == [[2, 1.0], [3, 1.0], [5, 1.0]]
    assert up["defaulted_vertices"] == [2, 3, 5]
    assert down["vertices"] == [[1, 0.25]]
    assert down["defaulted_vertices"] == []


def test_header_carries_format_and_inventory_hash():
    out = build(SYNTHETIC, "abc", groups=[("a1", "up", "lip", "bone", 3)])
    assert out["format_version"] == 1
    assert out["inventory_sha256"] == "abc"
    assert out["groups"][0]["note"] == "2026-11-12 已证实：权重表的默认值是 1.0（A-33）"


def test_wrong_vertex_count_is_refused():
    with pytest.raises(ValueError, match="expected 4"):
        build(SYNTHETIC, "abc", groups=[("a1", "up", "lip", "bone", 4)])


def test_overlapping_groups_are_refused():
    with pytest.raises(ValueError, match="share vertices"):
        build(SYNTHETIC, "abc", groups=[("a1", "up", "lip", "bone", 3), ("a1", "again", "lip", "bone", 3)])


def test_wrong_target_is_refused():
    with pytest.raises(ValueError, match="expected lip -> other"):
        build(SYNTHETIC, "abc", groups=[("a1", "up", "lip", "other", None)])


# ---- real data: the four exported sets and the position check on the OBJs ----

def measure():
    """Median nearest-vertex distances and centroid heights, from the exported sets and the OBJs."""
    export = json.loads(EXPORT.read_text(encoding="utf-8"))
    groups = {g["attachment"]: g for g in export["groups"]}
    lips, _ = read_obj(OBJS["lips"])
    skull, _ = read_obj(OBJS["skull"])
    jaw, _ = read_obj(OBJS["jaw"])

    def idx(name):
        return np.array([v for v, _ in groups[name]["vertices"]], dtype=int)

    def nearest_median(points, target):
        d = np.sqrt(((points[:, None, :] - target[None, :, :]) ** 2).sum(-1)).min(axis=1)
        return float(np.median(d)), float(d.max())

    up, low = lips[idx("zAttachment1")], lips[idx("zAttachment2")]
    return {
        "counts": {n: len(idx(n)) for n in groups},
        "upper_to_skull": nearest_median(up, skull),
        "upper_to_jaw": nearest_median(up, jaw),
        "lower_to_skull": nearest_median(low, skull),
        "lower_to_jaw": nearest_median(low, jaw),
        "upper_centroid_y": float(up[:, 1].mean()),
        "lower_centroid_y": float(low[:, 1].mean()),
    }


@pytest.mark.skipif(not HAVE_LAB, reason="data/lab_export/ (OBJs and lip_attachments.json) is not here")
def test_exported_sets_have_the_card_counts_and_do_not_overlap():
    export = json.loads(EXPORT.read_text(encoding="utf-8"))
    sets = {g["attachment"]: {v for v, _ in g["vertices"]} for g in export["groups"]}
    assert {n: len(s) for n, s in sets.items()} == {"zAttachment1": 74, "zAttachment2": 76,
                                                    "zAttachment9": 348, "zAttachment10": 309}
    names = list(sets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert not (sets[names[i]] & sets[names[j]]), (names[i], names[j])
    lip_vertices = read_obj(OBJS["lips"])[0].shape[0]
    assert all(0 <= v < lip_vertices for s in sets.values() for v in s)
    for g in export["groups"]:
        assert g["defaulted_vertices"] == sorted(g["defaulted_vertices"])
        assert all(w == 1.0 for v, w in g["vertices"] if v in set(g["defaulted_vertices"]))


@pytest.mark.skipif(not HAVE_LAB, reason="data/lab_export/ (OBJs and lip_attachments.json) is not here")
def test_upper_lip_is_on_the_skull_and_lower_lip_on_the_jaw():
    m = measure()
    up_skull, up_jaw = m["upper_to_skull"][0], m["upper_to_jaw"][0]
    low_skull, low_jaw = m["lower_to_skull"][0], m["lower_to_jaw"][0]
    assert m["counts"]["zAttachment1"] > 0 and m["counts"]["zAttachment2"] > 0
    assert up_skull > 0 and low_jaw > 0  # not a degenerate zero-distance match
    assert up_skull < 0.25 * up_jaw, (up_skull, up_jaw)
    assert low_jaw < 0.25 * low_skull, (low_jaw, low_skull)


@pytest.mark.skipif(not HAVE_LAB, reason="data/lab_export/ (OBJs and lip_attachments.json) is not here")
def test_upper_and_lower_groups_are_apart_in_height():
    m = measure()
    gap = m["upper_centroid_y"] - m["lower_centroid_y"]
    assert gap > 20, gap  # scene units, Y up


INVENTORY = Path(os.environ.get("ASRP_INVENTORY", REPO / "data" / "asset_inventory.json"))


@pytest.mark.skipif(not (INVENTORY.exists() and EXPORT.exists()),
                    reason="data/asset_inventory.json (or ASRP_INVENTORY) or the export is not here")
def test_export_matches_the_inventory_it_was_made_from():
    raw = INVENTORY.read_bytes()
    export = json.loads(EXPORT.read_text(encoding="utf-8"))
    assert export["inventory_sha256"] == hashlib.sha256(raw).hexdigest()
    rebuilt = build(json.loads(raw), export["inventory_sha256"])
    assert len(rebuilt["groups"]) == 4 and all(g["count"] > 0 for g in rebuilt["groups"])
    assert rebuilt["groups"] == export["groups"]
