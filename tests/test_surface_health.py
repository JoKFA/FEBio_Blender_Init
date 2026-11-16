"""`plausibility.surface_health`: the counts on a surface small enough to check by hand (reported only, no FEBio)."""

import numpy as np

from asrp_core import plausibility

# Two separate triangles, six vertices. Triangle 0 lies at z = 5, triangle 1 in the z = 0 plane.
REST = np.array([[0, 0, 5], [1, 0, 5], [0, 1, 5], [0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
FACES = [[0, 1, 2], [3, 4, 5]]


def shape(flip: bool, stretch: float) -> np.ndarray:
    """Triangle 0 turned over (two vertices swapped, same edge lengths); triangle 1's vertex 4 pushed along x so that
    the edge 3-4 is `stretch` times as long."""
    s = REST.copy()
    if flip:
        s[[1, 2]] = s[[2, 1]]
    s[4, 0] = stretch
    return s


def test_one_flipped_face_and_one_doubled_edge_give_exactly_those_counts():
    h = plausibility.surface_health(REST, np.stack([REST, shape(True, 2.5)]), FACES)
    last = h["last"]
    assert last["faces"] == 2 and last["edges"] == 6
    assert last["flipped_faces"] == 1
    assert last["edges_longer_than_double"] == 1  # edge 3-4: 2.5x; edge 4-5 only 1.90x
    assert last["edges_shorter_than_half"] == 0
    assert last["edge_ratio_min"] == 1.0 and last["edge_ratio_max"] == 2.5
    assert last["min_face_area_ratio"] == 1.0  # the flipped face keeps its area; the stretched one grows
    assert h["worst"]["frame"] == 1 and h["worst"]["flipped_faces"] == 1


def test_nothing_changed_counts_nothing_and_the_worst_frame_is_the_first():
    h = plausibility.surface_health(REST, np.stack([REST, REST, REST]), FACES)
    for part in ("last", "worst"):
        assert h[part]["flipped_faces"] == 0 and h[part]["edges_longer_than_double"] == 0
        assert h[part]["edge_ratio_min"] == h[part]["edge_ratio_max"] == 1.0
    assert h["worst"]["frame"] == 0


def test_the_worst_frame_has_the_most_flipped_faces_then_the_most_edges_out_of_range():
    both = shape(True, 1.0)
    both[[4, 5]] = both[[5, 4]]  # triangle 1 turned over as well
    frames = np.stack([shape(False, 1.0), shape(True, 1.0), shape(False, 3.0), both, shape(False, 1.0)])
    h = plausibility.surface_health(REST, frames, FACES)
    assert h["worst"]["frame"] == 3 and h["worst"]["flipped_faces"] == 2
    assert h["last"]["flipped_faces"] == 0
    # same flipped count: the frame with the long edge wins over the one without
    h = plausibility.surface_health(REST, np.stack([shape(True, 1.0), shape(True, 3.0), shape(True, 1.0)]), FACES)
    assert h["worst"]["frame"] == 1 and h["worst"]["edges_longer_than_double"] >= 1


def test_a_squashed_edge_is_counted_short_and_the_single_frame_count_uses_the_same_function():
    squashed = REST.copy()
    squashed[4, 0] = 0.25
    h = plausibility.surface_health(REST, squashed[None], FACES)["last"]
    assert h["edges_shorter_than_half"] >= 1 and h["edge_ratio_min"] == 0.25
    one = plausibility.folds(REST, squashed, np.array(FACES))
    assert one["edges < 0.5x"] == h["edges_shorter_than_half"] and one["edge ratio min / max"][0] == 0.25


def test_quads_are_fanned_into_triangles():
    quad = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    h = plausibility.surface_health(quad, quad[None], [[0, 1, 2, 3]])["last"]
    assert h["faces"] == 2 and h["edges"] == 5  # two triangles, the diagonal included
