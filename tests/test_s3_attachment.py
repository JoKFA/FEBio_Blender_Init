"""T-07 steps 1-2 with real FEBio: springs and gravity give the textbook answer, and springs stiffen into
a hard bond. The full table and the limits are in spikes/s3_attachment.py; this is the fast part.
"""

import pytest

import s3_attachment as s3
from asrp_core.doctor import febio_exe


def _have_febio() -> bool:
    try:
        return febio_exe().exists()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _have_febio(), reason="FEBio not found (asrp doctor)")


@pytest.mark.parametrize("k", [1.0, 2.0])
def test_cube_on_four_springs_stretches_each_by_weight_over_4K(tmp_path, k):
    r = s3.cube_on_springs(tmp_path, k, dynamic=True)
    assert r["ok"], "FEBio did not finish"
    assert r["measured"] > 0.5 * r["theory"], "the cube must hang below its start (gravity sign)"
    assert r["error_pct"] < 1.0, f"theory {r['theory']:.5f} mm, measured {r['measured']:.5f} mm"
    assert r["anchor_move"] < 1e-6, "the rigid frame, fixed in all 6 DOF, moved"


def test_the_check_can_fail(tmp_path):
    """A spring twice as stiff must be rejected by the same 1% rule (the cube hangs half as far)."""
    soft = s3.cube_on_springs(tmp_path, 1.0, dynamic=True)
    stiff = s3.cube_on_springs(tmp_path, 1.0, dynamic=True, K=2 * s3.K1)
    assert stiff["measured"] == pytest.approx(soft["measured"] / 2, rel=0.01)
    assert 100 * abs(stiff["measured"] - soft["theory"]) / soft["theory"] > 40


def test_k2_hangs_four_times_as_far_in_geometric_mm(tmp_path):
    one = s3.cube_on_springs(tmp_path, 1.0, dynamic=True)["measured"]
    two = s3.cube_on_springs(tmp_path, 2.0, dynamic=True)["measured"]
    assert two / one == pytest.approx(4.0, rel=0.01)


def test_springs_stiffen_into_the_hard_bond_monotonically(tmp_path):
    hard, rows = s3.sweep(tmp_path, [1e-2, 1e-1, 1.0, 1e1, 1e2, 1e3, 1e4])
    assert hard["ok"] and all(r["ok"] for r in rows), "a FEBio run did not finish"
    assert hard["tie_error"] < 1e-6, "hard-tied nodes do not follow the turned plate"
    assert max(
        ((hard["final"][i][0] - hard["initial"][i][0]) ** 2 + (hard["final"][i][1] - hard["initial"][i][1]) ** 2
         + (hard["final"][i][2] - hard["initial"][i][2]) ** 2) ** 0.5 for i in hard["tissue"]
    ) > 5.0, "the plate did not carry the tissue anywhere"
    assert s3.is_monotone(rows), [r["diff"] for r in rows]
    assert rows[0]["diff"] > 0.1, "the softest spring should visibly differ from hard"
    assert rows[-1]["diff"] < 1e-5 * s3.CUBE_A, rows[-1]["diff"]


def test_is_monotone_rejects_a_bump():
    assert not s3.is_monotone([{"ok": True, "diff": d} for d in (1.0, 0.1, 0.2, 0.01)])
    assert s3.is_monotone([{"ok": True, "diff": d} for d in (1.0, 0.1, 0.01)])


def test_a_zero_length_spring_does_not_solve_when_stiff(tmp_path):
    """Why the generator uses offset springs: FEBio cannot build a zero-length spring's stiffness."""
    assert not s3.soft_on_plate(tmp_path, "zero", 1.0)["ok"]


def test_offset_must_stay_well_above_the_slip(tmp_path):
    """A soft spring with a tiny offset is not the same spring: the offset rule (docs/05) has teeth."""
    hard = s3.soft_on_plate(tmp_path, "hard")
    wide = s3.soft_on_plate(tmp_path, "spring", 1e-3, offset=10.0)
    tiny = s3.soft_on_plate(tmp_path, "spring", 1e-3, offset=0.1)
    assert wide["slip_ratio"] < 0.1 and tiny["slip_ratio"] > 1.0
    d_wide, d_tiny = s3.max_node_difference(wide, hard), s3.max_node_difference(tiny, hard)
    assert abs(d_tiny - d_wide) / d_wide > 0.3, (d_wide, d_tiny)
