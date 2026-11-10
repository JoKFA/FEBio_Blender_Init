"""How tools/asset_report.py reads zAttachment weight lists (docs/03 section 6).

Maya leaves out every list element equal to the default; an element that is not stored takes
the default (taken as 1.0, see asset_report.ATTACHMENT_WEIGHT_DEFAULT). The old reading counted
only stored elements, so a left-out element and an attachment with no weight list at all both
read as "not attached". These tests fail under that reading.
"""

from asset_report import attached_vertices, attachment_weights, read_attachments


def inventory(attachments):
    """A tiny inventory: a 6-vertex lip tissue, a bone, and the given attachments lip -> bone."""
    nodes = [
        {"name": "lipGeo", "type": "zGeo", "attrs": {"iNMh": {"vertex_count": 6}}},
        {"name": "boneGeo", "type": "zGeo", "attrs": {"iNMh": {"vertex_count": 4}}},
        {"name": "lip", "type": "zTissue", "attrs": {}},
        {"name": "bone", "type": "zBone", "attrs": {}},
    ]
    connections = [["lipGeo.oGeo", "lip.iGo"], ["boneGeo.oGeo", "bone.iGo"]]
    for name, attrs in attachments.items():
        nodes.append({"name": name, "type": "zAttachment", "attrs": attrs})
        connections += [["lipGeo.oGeo", f"{name}.iGo1"], ["boneGeo.oGeo", f"{name}.iGo2"]]
    return {"nodes": nodes, "connections": connections}


# Stored element by element: 0, 1, 4 are 0.0; 2, 3, 5 are left out (like zAttachment1, lip -> skull).
ELEMENTWISE = {"wl[0].w": {"raw_type": "CMPD"}, "wl[0].w[0]": 0.0, "wl[0].w[1]": 0.0, "wl[0].w[4]": 0.0}
# Stored as one range covering every vertex (like zAttachment2, lip -> jaw).
RANGE = {"wl[0].w[0:5]": [0.0, 1.0, 0.0, 0.5, 0.0, 0.0]}
# No weight list stored at all (like zAttachment7, node -> zTissue2).
NO_LIST = {"mOff": {"raw_type": "FLGS"}}


def test_left_out_elements_take_the_default():
    stored, defaulted = attachment_weights(ELEMENTWISE, 6)
    assert stored == {0: 0.0, 1: 0.0, 4: 0.0}
    assert defaulted == {2, 3, 5}
    nonzero, by_default = attached_vertices(ELEMENTWISE, 6)
    assert nonzero == set()
    assert by_default == {2, 3, 5}


def test_a_fully_stored_range_has_nothing_by_default():
    nonzero, by_default = attached_vertices(RANGE, 6)
    assert nonzero == {1, 3}
    assert by_default == set()


def test_no_weight_list_means_the_whole_source_body_is_attached():
    nonzero, by_default = attached_vertices(NO_LIST, 6)
    assert nonzero == set()
    assert by_default == {0, 1, 2, 3, 4, 5}


def test_read_attachments_uses_the_source_body_vertex_count():
    rows = {r[0]: r for r in read_attachments(inventory({"a1": ELEMENTWISE, "a2": RANGE, "a7": NO_LIST}))}
    name, src, dst, nonzero, by_default, n_stored, n = rows["a1"]
    assert (src, dst, n, n_stored) == ("lip", "bone", 6, 3)
    assert (len(nonzero), len(by_default)) == (0, 3)
    assert len(rows["a2"][3] | rows["a2"][4]) == 2
    assert len(rows["a7"][3] | rows["a7"][4]) == 6
