"""The generator, the embedding, the plausibility checks and `asrp run <scene> <trajectory>` on box scenes with
textbook answers (T-06a; docs/05 sections 2-3, docs/07 sections 2-3, ADR-36). Real FEBio where it matters."""

import json
import math
from pathlib import Path

import cube_scene as cs
import numpy as np
import placeholder_jaw_motion
import pytest

from asrp_core import cli, embed, febio, generate, plausibility, simulate, tetmesh, trajectory
from asrp_core import run as run_module
from asrp_core import scene as scene_module
from asrp_core.asset import coords
from asrp_core.doctor import febio_exe

REPO = Path(__file__).resolve().parents[1]
RHO, G = 1.06e-9, 9810.0


def _have_febio() -> bool:
    try:
        return febio_exe().exists()
    except FileNotFoundError:
        return False


needs_febio = pytest.mark.skipif(not _have_febio(), reason="FEBio not found (asrp doctor)")


def at_z(z):
    return lambda v: [i for i, p in enumerate(v) if abs(p[2] - z) < 1e-9]


def display(run_dir: Path) -> np.ndarray:
    return simulate.read_display(run_dir / simulate.DISPLAY)["positions"]


def run(folder: Path, transforms, name: str, settle=None, threads=febio.DEFAULT_THREADS):
    traj = cs.motion(folder, transforms, settle=settle)
    return simulate.run_scene(folder / "scene.json", traj, folder.parent / "runs", febio_exe(), name, threads=threads)


def test_display_header_and_array_round_trip_and_a_disagreeing_header_is_refused(tmp_path):
    frames = np.random.default_rng(1).normal(size=(4, 6, 3))
    header = {"format": simulate.DISPLAY_FORMAT, "units": "mm", "fps": 30.0, "frames": 4, "vertex_count": 6}
    path = tmp_path / "physics" / "display.json"
    (tmp_path / "physics").mkdir()
    run_module.save_array(path, header, frames, "display.npy")

    read = simulate.read_display(path)
    assert read["format"] == "asrp-display/2" and read["array"] == "display.npy" and read["shape"] == [4, 6, 3]
    assert read["positions"].dtype == np.float64 and np.array_equal(read["positions"], frames)
    first = (tmp_path / "physics" / "display.npy").read_bytes()
    run_module.save_array(path, header, frames.copy(), "display.npy")  # the same numbers give the same bytes
    assert (tmp_path / "physics" / "display.npy").read_bytes() == first

    path.write_text(json.dumps({**header, "array": "display.npy", "shape": [4, 7, 3]}))
    with pytest.raises(run_module.RunError, match="do not belong together"):
        simulate.read_display(path)
    path.write_text(json.dumps({**header, "vertex_count": 7, "array": "display.npy", "shape": [4, 6, 3]}))
    with pytest.raises(run_module.RunError, match="4 frames of 7 vertices"):
        simulate.read_display(path)


# --- the embedding (zEmbedder stand-in) --------------------------------------------------------


def test_embedding_at_rest_gives_back_the_box_display_mesh_with_vertices_outside(tmp_path):
    pushed = {0: [0.0, 0.0, -0.3], 5: [-0.2, 0.1, 0.0]}
    c = cs.write(tmp_path / "box", push=pushed)
    mesh = tetmesh.TetMesh(c["nodes"], c["tets"])
    e = embed.embed(mesh, c["display"])
    assert e.outside.sum() == 2 and (e.bary[list(pushed)] < 0).any(axis=1).all()
    assert e.distance_mm[0] == pytest.approx(0.3, abs=1e-12)
    assert np.abs(embed.apply(e, mesh.nodes) - c["display"]).max() < 1e-12
    # An affine motion of the nodes moves every display vertex, inside or out, by the same map.
    r = np.array(trajectory.hinge_transforms((1, 2, 3), (0.3, 1, 0.2), [0.4])[0]).reshape(4, 4)
    moved = embed.apply(e, mesh.nodes @ r[:3, :3].T + r[:3, 3])
    assert np.abs(moved - (c["display"] @ r[:3, :3].T + r[:3, 3])).max() < 1e-12


@pytest.mark.skipif(not (REPO / "data" / "tetmesh" / "lips.json").is_file(), reason="needs data/tetmesh/lips.json")
def test_embedded_lips_at_rest_equal_the_lip_mesh():
    mesh, _ = tetmesh.load(REPO / "data" / "tetmesh" / "lips.json")
    v = coords.to_mm_zup(coords.read_obj(REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj")[0], 0.962)
    e = embed.embed(mesh, v)
    assert len(v) == 10240 and 6000 < e.outside.sum() < 7000  # docs/05: 65 % outside, so extrapolation is exercised
    assert e.distance_mm.max() == pytest.approx(0.931, abs=1e-3)
    assert np.abs(embed.apply(e, mesh.nodes) - v).max() < 1e-9


def test_spread_gives_every_node_an_eighth_and_sums_to_one():
    lam = np.array([[-0.1, 0.4, 0.3, 0.4], [1.0, 0.0, 0.0, 0.0]])
    s = embed.spread(lam)
    assert np.allclose(s.sum(axis=1), 1.0) and s.min() == pytest.approx(1 / 8)
    assert s[0, 0] == pytest.approx(1 / 8) and s[0, 1] == pytest.approx((0.4 / 1.1 + 0.25) / 2)


# --- the generator without FEBio ---------------------------------------------------------------


def test_k_one_is_the_unscaled_model_byte_for_byte(tmp_path):
    common = dict(attachments=[("top", "skull", "hard", None, at_z(10.0))])
    a = cs.write(tmp_path / "a", k=1.0, **common)
    b = cs.write(tmp_path / "b", write_k=False, **common)  # no physics_length_scale: 1.0 by default (ADR-22)
    ta, tb = cs.motion(tmp_path / "a", cs.still(3)), cs.motion(tmp_path / "b", cs.still(3))
    fa, fb = generate.build(a["scene"], ta), generate.build(b["scene"], tb)
    assert fa.feb_text == fb.feb_text
    nodes = generate.node_rest_febio(fa)
    assert all(nodes[i + 1].tolist() == p.tolist() for i, p in enumerate(a["nodes"]))
    two = cs.write(tmp_path / "c", k=2.0, **common)
    nodes2 = generate.node_rest_febio(generate.build(two["scene"], cs.motion(tmp_path / "c", cs.still(3))))
    assert all(nodes2[i + 1].tolist() == (2 * p).tolist() for i, p in enumerate(a["nodes"]))


def test_a_numpy_repr_in_the_feb_text_stops_the_generator(tmp_path, monkeypatch):
    c = cs.write(tmp_path / "box", attachments=[("top", "plate", "spring", 1.0, at_z(10.0))])
    traj = cs.motion(tmp_path / "box", cs.turn(5, 4, -0.2, (5, -10, 10), (1, 0, 0)))
    monkeypatch.setattr(generate, "_num", lambda v: repr(np.float64(v)))  # pit 16 comes back
    with pytest.raises(generate.GenerateError, match="pit 16"):
        generate.build(c["scene"], traj)


def test_numbers_reach_the_feb_as_plain_floats(tmp_path):
    c = cs.write(tmp_path / "box", attachments=[("top", "plate", "spring", 1.0, at_z(10.0))])
    m = generate.build(c["scene"], cs.motion(tmp_path / "box", cs.turn(5, 4, -0.2, (5, -10, 10), (1, 0, 0))))
    # FEBio reads "np.float64(0.1)" as 0 without a word (docs/05 pit 16).
    assert "np." not in m.feb_text and "float64" not in m.feb_text
    assert m.feb_text.count("<load_controller id=") == 2 + 6  # gravity, must points, the plate's six dofs
    ids = [int(x.split('"')[1]) for x in m.feb_text.split("<load_controller id=")[1:]]
    assert ids == list(range(1, 9))  # pit 15: 1, 2, 3 ... with no gaps


def test_a_vertex_too_far_from_its_tet_stops_the_generator(tmp_path):
    nodes, tets = cs.box((10, 10, 10), (4, 4, 4))
    h = tetmesh.quality(tetmesh.TetMesh(nodes, tets)).median_edge_mm
    c = cs.write(tmp_path / "box", push={3: [0.0, 0.0, -2.5 * h]},
                 attachments=[("top", "skull", "hard", None, at_z(10.0))])
    with pytest.raises(generate.GenerateError, match="median tet edge"):
        generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))
    ok = cs.write(tmp_path / "ok", push={3: [0.0, 0.0, -1.5 * h]}, attachments=[("top", "skull", "hard", None, at_z(10.0))])
    assert generate.build(ok["scene"], cs.motion(tmp_path / "ok", cs.still(3))).report["display_max_distance_mm"] \
        == pytest.approx(1.5 * h)


def test_a_tet_mesh_node_in_no_tet_stops_the_generator(tmp_path):
    # FEBio drops such a node with only a warning ("isolated vertices removed"), docs/05 pit 18.
    c = cs.write(tmp_path / "box", unused_node=True, attachments=[("top", "skull", "hard", None, at_z(10.0))])
    with pytest.raises(generate.GenerateError, match="belong to no tet"):
        generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))


def test_hard_beats_spring_on_a_shared_node_and_is_counted(tmp_path):
    c = cs.write(tmp_path / "box", attachments=[
        ("top", "skull", "hard", None, at_z(10.0)),
        ("ring", "plate", "spring", 1.0, lambda v: [i for i, p in enumerate(v) if abs(p[2] - 7.5) < 1e-9]),
    ])
    m = generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))
    top, ring = m.groups
    shared = set(top.nodes.tolist()) & set(ring.nodes.tolist())
    assert shared and ring.conflicts == len(shared)
    assert not shared & set(ring.stiffness) and all(m.hard[n] == "skull" for n in shared)
    assert m.report["groups"][1]["conflicts"] == len(shared)


def test_one_node_on_two_rigid_bodies_is_an_error(tmp_path):
    c = cs.write(tmp_path / "box", attachments=[
        ("top", "skull", "hard", None, at_z(10.0)),
        ("ring", "plate", "hard", None, lambda v: [i for i, p in enumerate(v) if abs(p[2] - 7.5) < 1e-9]),
    ])
    with pytest.raises(generate.GenerateError, match="cannot join two rigid bodies"):
        generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))


def test_spring_stiffness_is_base_times_weight_shares_and_keeps_the_total(tmp_path):
    c = cs.write(tmp_path / "box", push={0: [0.0, 0.0, -0.3]},
                 attachments=[("bottom", "plate", "spring", 2.0, lambda v: [i for i, p in enumerate(v) if p[2] < 1e-9])])
    m = generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))
    [g] = m.groups
    assert g.clipped > 0  # the pushed vertex has a negative coordinate
    assert sum(g.stiffness.values()) == pytest.approx(2.0 * len(g.vertices))  # λ̂ sums to 1 per vertex
    assert min(g.stiffness.values()) >= 2.0 / 8 - 1e-12
    by_level = sum(g.levels[g.level_of[n]] for n in g.stiffness)
    assert by_level == pytest.approx(sum(g.stiffness.values()), rel=1e-12)  # levels keep the group's total
    assert g.max_level_error <= generate.SPRING_LEVEL_TOLERANCE  # every node within 2 % of its own value
    assert all(abs(g.levels[g.level_of[n]] - v) <= 0.02 * v for n, v in g.stiffness.items())
    assert len(g.levels) > 1 and m.report["groups"][0]["level_count"] == len(g.levels)
    assert len(m.springs) == 3 * len(g.stiffness) and m.feb_text.count("<delem>") == len(m.springs)


# --- textbook boxes in FEBio (docs/07 section 2) -----------------------------------------------


def hanging(folder: Path, k: float, frames=30, E=0.03, settle=None):  # stiff enough to stay in small strain
    L = 20.0
    c = cs.write(folder, size=(2.0, 2.0, L), cells=(2, 2, 20), E=E, nu=0.0, k=k,
                 attachments=[("top", "skull", "hard", None, at_z(L))])
    r = run(folder, cs.still(frames), folder.name, settle)
    model = generate.build(c["scene"], folder / "motion.json")
    held_z = c["nodes"][sorted(model.hard)][:, 2]
    free_length = held_z.min()  # the hard attachment holds the top face's tets: one layer more (ADR-36)
    assert set(np.nonzero(c["nodes"][:, 2] >= free_length - 1e-9)[0]) == set(model.hard)
    bottom = at_z(0.0)(c["display"])
    d = display(r.run_dir)
    tip = float(np.mean(d[frames - 10:, bottom, 2] - c["display"][bottom, 2]))
    theory = RHO * G * (k * free_length) ** 2 / (2 * E) / k  # bar under its own weight, back in geometric mm
    return r, tip, theory


@needs_febio
def test_a_hanging_bar_sags_by_the_textbook_amount_and_k_doubles_it(tmp_path):
    r1, tip1, theory1 = hanging(tmp_path / "k1", 1.0)
    r2, tip2, theory2 = hanging(tmp_path / "k2", 2.0)
    for r in (r1, r2):  # (c) is not asked: a 2 mm bar sags less than the lips' 0.1 mm x k floor
        assert r.report["checks"]["a"]["passed"] and r.report["checks"]["b"]["passed"], r.report["checks"]
    assert -tip1 == pytest.approx(theory1, rel=0.01)
    assert -tip2 == pytest.approx(theory2, rel=0.01)
    assert tip2 / tip1 == pytest.approx(2.0, rel=0.01)  # docs/07 section 3: geometric sag grows like k


def lateral_stretch(stretch: float, E: float, nu: float) -> float:
    """FEBio's neo-Hookean under uniaxial stress: the sideways stretch t with mu (t^2 - 1) + lambda ln(stretch t^2) = 0."""
    mu, lam = E / (2 * (1 + nu)), E * nu / ((1 + nu) * (1 - 2 * nu))
    lo, hi = 0.5, 1.0
    for _ in range(100):
        t = (lo + hi) / 2
        lo, hi = (lo, t) if mu * (t * t - 1) + lam * math.log(stretch * t * t) > 0 else (t, hi)
    return t


@needs_febio
def test_a_stretched_bar_narrows_by_the_textbook_amount(tmp_path):
    L, pull, frames = 20.0, 2.0, 30
    folder = tmp_path / "stretch"
    c = cs.write(folder, size=(2.0, 2.0, L), cells=(2, 2, 20), nu=0.45, gravity=(0, 0, 0), hinge=None,
                 attachments=[("bottom", "skull", "hard", None, at_z(0.0)), ("top", "plate", "hard", None, at_z(L))])
    r = run(folder, cs.shift(frames, 20, (0, 0, pull)), "stretch")
    assert r.status == "complete" and r.report["checks"]["b"]["passed"] and r.report["checks"]["c"]["passed"] is None
    model = generate.build(c["scene"], folder / "motion.json")
    z = c["nodes"][sorted(model.hard)][:, 2]
    free = z[z > L / 2].min() - z[z < L / 2].max()  # each hard face holds one layer of tets more
    mid = at_z(L / 2)(c["display"])
    d = display(r.run_dir)
    width = np.mean([np.ptp(d[f, mid, 0]) for f in range(frames - 5, frames)]) / 2.0
    theory = lateral_stretch((free + pull) / free, 0.015, 0.45)
    assert 1 - width > 0.04  # it really narrowed
    assert width == pytest.approx(theory, abs=2e-3)


# --- the attachment rule on a box under a turning plate (docs/05 section 3, ADR-36) -------------

PIVOT, AXIS = (5.0, -10.0, 10.0), (1.0, 0.0, 0.0)


def plate_box(folder: Path, kind: str, stiffness=None):
    probe = cs.write(folder / "probe")
    top = at_z(10.0)(probe["display"])
    push = {top[0]: [0.0, 0.0, 0.3], top[7]: [0.2, 0.0, 0.25]}  # outside: a negative barycentric coordinate
    return cs.write(folder / f"{kind}_{stiffness}", hinge=(PIVOT, AXIS), push=push,
                    attachments=[("top", "plate", kind, stiffness, lambda v: top)]), top


TURN = cs.turn(30, 20, -0.5, PIVOT, AXIS)


@pytest.fixture(scope="module")
def hard_plate(tmp_path_factory):
    folder = tmp_path_factory.mktemp("plate")
    c, top = plate_box(folder, "hard")
    r = run(c["scene"].parent, TURN, "hard")
    return folder, c, top, r


@needs_febio
def test_hard_nodes_and_display_vertices_move_with_the_plate_every_frame(hard_plate):
    _, c, top, r = hard_plate
    assert r.passed, r.report["checks"]
    b = r.report["checks"]["b"]["numbers"]
    assert b["hard_nodes_max_deviation_mm"] < 1e-6 and b["hard_display_vertices_max_deviation_mm"] < 1e-6
    d = display(r.run_dir)
    for f in (5, 20, 29):
        want = np.array([trajectory.apply(TURN[f], c["display"][v]) for v in top])
        assert np.abs(d[f, top] - want).max() < 1e-6
    assert np.linalg.norm(d[29, top] - c["display"][top], axis=1).max() > 5.0  # the plate really carried them
    assert r.report["generator"]["groups"][0]["clipped_coordinates"] > 0  # the pushed vertices are outside


@needs_febio
def test_a_plate_turning_about_a_tilted_axis_and_moving_is_followed(tmp_path):
    # Ru, Rv, Rw together are a rotation vector in FEBio, and x, y, z move the reference point: a general
    # rigid motion (here a tilted hinge plus a slide) is followed, not only a turn about x.
    folder = tmp_path / "tilted"
    pivot, axis = (2.0, -8.0, 12.0), (1.0, 1.0, 0.5)
    cs.write(folder, hinge=(pivot, axis), attachments=[("top", "plate", "hard", None, at_z(10.0))])
    motion = [(np.array(slide).reshape(4, 4) @ np.array(turn).reshape(4, 4)).ravel().tolist()
              for turn, slide in zip(cs.turn(20, 15, 0.4, pivot, axis), cs.shift(20, 15, (1.0, -2.0, 0.5)))]
    r = run(folder, motion, "tilted")
    b = r.report["checks"]["b"]
    assert r.status == "complete" and b["passed"], b
    assert b["numbers"]["hard_nodes_max_deviation_mm"] < 1e-6


@needs_febio
def test_stiffer_springs_converge_to_the_hard_result(hard_plate, tmp_path):
    _, _, _, hard = hard_plate
    reference = display(hard.run_dir)
    diffs = []
    for K in (0.01, 1.0, 100.0):
        c, _ = plate_box(tmp_path, "spring", K)
        r = run(c["scene"].parent, TURN, f"spring{K:g}")
        assert r.status == "complete" and r.report["generator"]["groups"][0]["clipped_coordinates"] > 0
        assert not r.report["spring_slip"]["top"]["flag"]
        b2 = r.report["checks"]["b2"]  # the spring anchors ride the turning plate (review: not only the lips on the skull)
        assert b2["passed"] and b2["numbers"]["anchor_nodes"] > 0 and b2["numbers"]["max_deviation_mm"] < 1e-6, b2
        diffs.append(float(np.linalg.norm(display(r.run_dir) - reference, axis=2).max()))
    assert diffs[0] > diffs[1] > diffs[2], diffs
    assert diffs[0] > 0.1 and diffs[2] < 1e-3, diffs


@needs_febio
def test_same_input_twice_agrees_within_1e_9_mm_at_the_default_threads(hard_plate):
    folder, c, _, first = hard_plate
    again = run(c["scene"].parent, TURN, "hard")
    a, b = display(first.run_dir), display(again.run_dir)
    assert a.shape == b.shape and np.abs(a - b).max() <= 1e-9
    assert np.abs(a - a[0]).max() > 1.0  # the plate really turns, so "equal" is not "nothing moved"
    tets = [run_module.read_positions(r.run_dir / run_module.POSITIONS)["positions"] for r in (first, again)]
    assert tets[0].shape == tets[1].shape and np.abs(tets[0] - tets[1]).max() <= 1e-9


@needs_febio
def test_same_input_twice_gives_the_same_playback_files_with_one_thread(hard_plate):
    folder, c, _, _ = hard_plate
    first = run(c["scene"].parent, TURN, "hard_1a", threads=1)
    again = run(c["scene"].parent, TURN, "hard_1b", threads=1)
    for name in ("playback.json", "playback.pc2", "physics/display.json", "physics/display.npy", "physics/positions.json",
                 "physics/positions.npy"):
        assert (first.run_dir / name).read_bytes() == (again.run_dir / name).read_bytes(), name
    assert json.loads((first.run_dir / "provenance.json").read_text())["parameters"]["febio_env"] == {
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


@needs_febio
def test_the_run_folder_holds_its_inputs_results_and_report(hard_plate):
    _, c, _, r = hard_plate
    d = r.run_dir
    for name in ("scene.json", "trajectory.json", "tissue.obj", "tissue_tet.json", "skull.obj", "plate.obj", "model.feb",
                 "physics/positions.json", "physics/positions.npy", "physics/display.json", "physics/display.npy", "playback.json",
                 "playback.pc2", "run_report.json", "provenance.json"):
        assert (d / name).is_file(), name
    record = json.loads((d / "provenance.json").read_text())
    assert record["mode"] == "generated" and record["parameters"]["length_scale"] == 1.0
    assert {"run_report.json", "playback.pc2", "physics/positions.json", "physics/positions.npy", "physics/display.json",
            "physics/display.npy"} <= set(record["outputs"])
    assert not (d / "positions.txt").exists() and not (d / "model.xplt").exists()  # derived and large: not kept
    report = cs.report(d)
    where = {p["where"]: p["source"] for p in report["parameters"]}
    assert where["scene.soft_tissues[tissue].material.E_mpa"] == "ours" and where["generator.rhoi"] == "ours"
    scene_params = list(scene_module.parameters(json.loads((d / "scene.json").read_text())))
    assert len(scene_params) > 5 and all(f"scene.{w}" in where for w, _ in scene_params)
    assert report["simplifications"] == []  # the cube scene lists none; the lips' three are checked in test_prototype
    assert "attachments_not_built" not in report
    assert not {"budget_s_per_frame", "budget_note"} & set(report["timing"])
    assert where["trajectory.source"] == "unstated"  # cube_scene.motion writes no source_tag: never guessed
    manifest = json.loads((d / "playback.json").read_text())
    assert manifest["frame_count"] == 30 and len(manifest["vertices"]) == len(c["display"])


@needs_febio
def test_the_report_gives_the_largest_distance_any_display_vertex_moves_and_the_frame(hard_plate):
    _, c, top, r = hard_plate
    shown = display(r.run_dir)
    far = np.linalg.norm(shown - shown[0][None], axis=2)  # worked out again here, from the written display file
    motion = r.report["motion"]
    assert set(motion) == {"max_display_distance_mm", "frame"}
    assert motion["max_display_distance_mm"] == pytest.approx(far.max(), rel=1e-12) and motion["max_display_distance_mm"] > 5.0
    assert far[motion["frame"]].max() == far.max()
    assert cs.report(r.run_dir)["motion"] == motion  # and it is in the file, not only in memory


# --- k with springs: a stiff box hanging on springs (ADR-36, docs/05 section 2) -----------------


@needs_febio
@pytest.mark.parametrize("k", [1.0, 2.0])
def test_a_box_on_springs_drops_by_weight_over_stiffness_at_real_size(tmp_path, k):
    # N/mm per unit weight. Stiff enough that the bounce is much faster than a frame, so rhoi = 0 damps it
    # out (a softer box keeps ringing and the tail mean misses); the box drops 0.012 mm at k = 1. E = 100 MPa
    # keeps the box rigid next to the springs (E = 1000 MPa at k = 2 does not converge: a conditioning limit
    # of this toy, not of the generator).
    base = 0.1
    folder = tmp_path / f"springs_k{k:g}"
    c = cs.write(folder, cells=(2, 2, 2), E=100.0, nu=0.3, k=k,
                 attachments=[("top", "skull", "spring", base, at_z(10.0))])
    r = run(folder, cs.still(40), "springs")
    assert r.status == "complete", r.report["checks"]["a"]
    model = generate.build(c["scene"], folder / "motion.json")
    [g] = model.groups
    positions = run_module.read_positions(r.run_dir / run_module.POSITIONS)
    index = {n: i for i, n in enumerate(positions["node_ids"])}
    nodes = sorted(g.stiffness)
    stiffness = np.array([g.levels[g.level_of[n]] for n in nodes])
    z = np.array([[frame[index[n + 1]][2] for n in nodes] for frame in positions["positions"][-10:]])
    # Force balance: the springs' stiffness-weighted drop carries the weight. Their stiffnesses add up to
    # base x the weights (λ̂ sums to 1 per vertex); in geometric mm the drop is rho V k^2 g / (base sum w).
    drop = -float(np.mean((z - c["nodes"][nodes, 2]) @ stiffness) / stiffness.sum())
    theory = RHO * 1000.0 * k ** 2 * G / (base * len(g.vertices))
    assert stiffness.sum() == pytest.approx(base * len(g.vertices))
    assert drop == pytest.approx(theory, rel=0.01)


# --- the plausibility checks fail when they should (docs/07 section 3) --------------------------


def test_check_a_fails_on_a_missing_frame_or_a_failed_run():
    assert plausibility.motion_completed("complete", 5, [1, 2, 3, 4], 2).passed
    assert not plausibility.motion_completed("complete", 5, [1, 2, 4], 0).passed
    assert not plausibility.motion_completed("failed", 5, [], 0, "did not converge").passed


def test_check_b_fails_when_a_hard_node_or_vertex_leaves_its_bone():
    rng = np.random.default_rng(1)
    rest, verts = rng.normal(size=(20, 3)), rng.normal(size=(8, 3))
    motion = cs.turn(6, 5, 0.3, (0, 0, 0), (0, 1, 1))
    nodes = np.stack([np.array([trajectory.apply(m, p) for p in rest]) for m in motion])
    disp = np.stack([np.array([trajectory.apply(m, p) for p in verts]) for m in motion])
    groups = [{"name": "g", "kind": "hard", "target": "plate", "nodes": np.arange(10), "vertices": np.arange(4)}]
    assert plausibility.follows_bones(groups, rest, nodes, verts, disp, {"plate": motion}).passed
    bad = nodes.copy()
    bad[3, 2] += [0.0, 0.002, 0.0]
    assert not plausibility.follows_bones(groups, rest, bad, verts, disp, {"plate": motion}).passed
    bad = disp.copy()
    bad[5, 1] += [0.002, 0.0, 0.0]
    assert not plausibility.follows_bones(groups, rest, nodes, verts, bad, {"plate": motion}).passed
    off = nodes.copy()
    off[:, 15] += 1.0  # not in the group: does not matter
    assert plausibility.follows_bones(groups, rest, off, verts, disp, {"plate": motion}).passed


@needs_febio
def test_check_c_fails_when_the_gravity_flip_is_lost(tmp_path, monkeypatch):
    r, _, _ = hanging(tmp_path / "right", 1.0, E=0.005, settle=14)  # softer, so it sags more than the 0.1 mm floor
    assert r.report["checks"]["c"]["passed"], r.report["checks"]["c"]
    monkeypatch.setattr(generate, "FEBIO_GRAVITY_SIGN", 1.0)  # write the scene's gravity as it is (pit 1 forgotten)
    folder = tmp_path / "flipped"
    cs.write(folder, size=(2.0, 2.0, 20.0), cells=(2, 2, 20), E=0.005, nu=0.0,
             attachments=[("top", "skull", "hard", None, at_z(20.0))])
    bad = run(folder, cs.still(30), "flipped", settle=14)
    c = bad.report["checks"]["c"]
    assert bad.status == "complete" and c["passed"] is False and c["numbers"]["mean_sag_along_gravity_mm"] < 0
    assert not bad.passed


def test_check_b2_fails_when_an_anchor_leaves_its_rigid_body_or_the_angle_is_wrong():
    rng = np.random.default_rng(2)
    rest = rng.normal(size=(12, 3))
    motion = cs.turn(6, 5, 0.3, (0, 0, 0), (0, 1, 1))
    pos = np.stack([np.array([trajectory.apply(m, p) for p in rest]) for m in motion])
    pos[:, 8:] = rest[8:]  # the last four are on the fixed skull
    targets = ["plate"] * 8 + ["skull"] * 4
    check = plausibility.anchors_follow_bodies(rest, targets, pos, {"plate": motion})
    assert check.passed and check.numbers["anchor_nodes"] == 12 and check.numbers["per_body"]["skull"]["anchor_nodes"] == 4
    wrong = cs.turn(6, 5, 0.3 * 1.01, (0, 0, 0), (0, 1, 1))  # a prescribed angle 1 % off in the comparison
    assert not plausibility.anchors_follow_bodies(rest, targets, pos, {"plate": wrong}).passed
    bad = pos.copy()
    bad[4, 10] += [0.002, 0.0, 0.0]  # a node on the fixed body drifts
    assert not plausibility.anchors_follow_bodies(rest, targets, bad, {"plate": motion}).passed
    assert plausibility.anchors_follow_bodies(rest[:0], [], pos[:, :0], {}).numbers["anchor_nodes"] == 0


def test_the_free_length_is_the_largest_distance_to_the_nearest_held_vertex_in_chunks():
    rng = np.random.default_rng(5)
    pts = rng.uniform(-10, 10, size=(300, 3))
    held = np.arange(0, 300, 37)
    free = np.setdiff1d(np.arange(300), held)
    brute = max(min(np.linalg.norm(pts[i] - pts[j]) for j in held) for i in free)
    for chunk in (1, 7, 256, 10_000):
        assert plausibility.free_length(pts, free, held, chunk) == pytest.approx(brute, abs=1e-12)
    bar = np.array([[0.0, 0, z] for z in range(0, 21)])  # a bar held at z = 0: L is its length
    assert plausibility.free_length(bar, np.arange(1, 21), np.array([0]), 4) == pytest.approx(20.0)


def test_the_expected_sag_is_the_hanging_bar_formula_and_none_without_something_to_measure_from():
    bar = np.array([[0.0, 0, z] for z in range(0, 21)])
    free, held = np.arange(1, 21), np.array([0])
    est = plausibility.expected_sag(bar, free, held, [0, 0, -9810.0], 1.06e-9, 0.015, 0.67)
    assert est.free_length_mm == pytest.approx(20.0) and est.sag_mm == pytest.approx(1.06e-9 * 9810.0 * 0.67 * 400.0 / 0.03)
    assert plausibility.expected_sag(bar, free, np.array([], dtype=int), [0, 0, -9810.0], 1.06e-9, 0.015, 1.0) is None
    assert plausibility.expected_sag(bar, np.array([], dtype=int), held, [0, 0, -9810.0], 1.06e-9, 0.015, 1.0) is None
    assert plausibility.expected_sag(bar, free, held, [0, 0, 0.0], 1.06e-9, 0.015, 1.0) is None
    stiffer = plausibility.expected_sag(bar, free, held, [0, 0, -9810.0], 1.06e-9, 0.15, 0.67)
    assert stiffer.sag_mm == pytest.approx(est.sag_mm / 10)  # proportional to 1 / E


def test_check_c_passes_within_a_factor_of_ten_of_the_estimate_and_fails_outside_it():
    rest = np.zeros((4, 3))
    est = plausibility.SagEstimate(0.1, 25.0, 1.06e-9, 0.015, 0.67)
    g, free, last5 = [0, 0, -9810], np.arange(4), range(10, 15)

    def with_sag(sag, frames=15):
        shifted = np.zeros((frames, 4, 3))
        shifted[10:, :, 2] = -sag
        return plausibility.gravity_sag(rest, shifted, free, g, est, last5)

    passed = with_sag(0.095)
    assert passed.passed and passed.numbers["expected_sag_mm"] == 0.1 and passed.numbers["free_length_mm"] == 25.0
    assert passed.numbers["range_mm"] == pytest.approx([0.01, 1.0]) and passed.numbers["frames"] == [10, 14]
    assert with_sag(0.0101).passed and with_sag(0.99).passed
    assert with_sag(0.0099).passed is False  # more than 10 times below
    assert with_sag(1.01).passed is False  # more than 10 times above
    assert with_sag(-0.1).passed is False  # up, the gravity flip
    assert with_sag(0.1, frames=12).passed is None  # the motion ends before the frames to average
    assert plausibility.gravity_sag(rest, np.zeros((15, 4, 3)), free, g, None, last5).passed is None  # no estimate
    assert plausibility.gravity_sag(rest, np.zeros((15, 4, 3)), free[:0], g, est, last5).passed is None  # no free vertex
    early = plausibility.gravity_sag(rest, np.where(np.arange(15)[:, None, None] >= 10, [0, 0, -0.08], 0.0) * np.ones((15, 4, 3)),
                                     free, g, est, range(6, 11))  # mostly before the sag: 0.08 / 5 mm on average
    assert early.numbers["frames"] == [6, 10] and early.numbers["mean_sag_along_gravity_mm"] == pytest.approx(0.016)


@needs_febio
def test_check_c_range_follows_the_material_a_stiffer_bar_is_expected_to_sag_less(tmp_path):
    soft, _, _ = hanging(tmp_path / "soft", 1.0, E=0.005, settle=14)
    stiff, _, _ = hanging(tmp_path / "stiff", 1.0, E=0.05, settle=14)
    a, b = soft.report["checks"]["c"], stiff.report["checks"]["c"]
    assert a["passed"] and b["passed"], (a, b)
    assert a["numbers"]["expected_sag_mm"] == pytest.approx(10 * b["numbers"]["expected_sag_mm"])
    assert a["numbers"]["mean_sag_along_gravity_mm"] == pytest.approx(10 * b["numbers"]["mean_sag_along_gravity_mm"], rel=0.05)
    assert 0.1 < a["numbers"]["mean_sag_along_gravity_mm"] / a["numbers"]["expected_sag_mm"] < 10


def test_check_d_fails_on_an_inverted_tet_and_reports_the_volume_ratios():
    rest = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]])
    tets = np.array([[0, 1, 2, 3], [1, 2, 3, 4]])
    frames = np.stack([rest, rest * 0.5, rest * 2.0, rest])
    ok = plausibility.tet_mesh_valid(rest, tets, frames)
    assert ok.passed and ok.numbers["inverted_tets"] == 0 and ok.numbers["frames_with_inverted_tets"] == 0
    assert ok.numbers["min_volume_ratio"] == pytest.approx(0.125) and ok.numbers["min_volume_ratio_frame"] == 1
    assert ok.numbers["max_volume_ratio"] == pytest.approx(8.0)

    bad = frames.copy()
    bad[2, 3, 2] = -1.0  # frame 2: node 3 goes through the opposite face of tet 0; tet 1 shares that node too
    check = plausibility.tet_mesh_valid(rest, tets, bad)
    assert check.passed is False and check.numbers["inverted_tets"] >= 1 and check.numbers["frames_with_inverted_tets"] == 1
    assert check.numbers["min_volume_ratio"] < 0 and check.numbers["min_volume_ratio_frame"] == 2
    assert "turned inside out" in check.message
    flat = frames.copy()
    flat[1, 3] = flat[1, 0]  # a tet squashed to zero volume is not valid either
    assert plausibility.tet_mesh_valid(rest, tets, flat).passed is False
    missing = frames.copy()
    missing[3, 2] = np.nan  # a frame FEBio did not log
    gone = plausibility.tet_mesh_valid(rest, tets, missing)
    assert gone.passed is False
    assert gone.numbers["min_volume_ratio"] is None  # -inf for a missing position: JSON has no such number
    json.dumps(gone.numbers, allow_nan=False)
    zero_rest = rest.copy()
    zero_rest[3] = zero_rest[0]  # a rest tet of zero volume: its ratio is inf or NaN
    degenerate = plausibility.tet_mesh_valid(zero_rest, tets, frames)
    assert degenerate.numbers["max_volume_ratio"] is None  # inf
    json.dumps(degenerate.numbers, allow_nan=False)


def test_a_display_header_that_is_not_json_or_lacks_a_key_is_refused_in_a_sentence(tmp_path):
    header = {"format": simulate.DISPLAY_FORMAT, "units": "mm", "fps": 30.0, "frames": 4, "vertex_count": 6}
    path = tmp_path / "display.json"
    run_module.save_array(path, header, np.zeros((4, 6, 3)), "display.npy")
    good = json.loads(path.read_text())
    for text, words in (("{nope", "as JSON"), ("3", "not a JSON object"),
                        (json.dumps({k: v for k, v in good.items() if k != "vertex_count"}), "vertex_count"),
                        (json.dumps({k: v for k, v in good.items() if k != "shape"}), "shape")):
        path.write_text(text)
        with pytest.raises(run_module.RunError, match=words):
            simulate.read_display(path)


def test_return_to_settled_measures_only_frames_where_every_driver_is_back_at_rest():
    eye = np.eye(4).ravel().tolist()
    moved = cs.turn(12, 3, 0.3, (0, 0, 0), (1, 0, 0))  # frames 0-2 still, then turning
    one = [moved[f] if 3 <= f <= 7 else eye for f in range(12)]
    two = [eye] * 12
    nodes = np.zeros((12, 3, 3))
    nodes[:, :, 0] = np.arange(12)[:, None] * 0.001  # drifts 1 micrometre per frame along x
    got = plausibility.return_to_settled(nodes, 2, [one, two, None])
    assert got["frames"] == [8, 9, 10, 11]
    assert got["max_mm"] == pytest.approx(0.009) and got["mean_mm"] == pytest.approx(np.mean([0.006, 0.007, 0.008, 0.009]))
    assert plausibility.return_to_settled(nodes, 2, [one[:8] + moved[8:], two])["frames"] == []  # never back at rest
    assert plausibility.return_to_settled(nodes, 11, [one, two]) == {"frames": []}  # nothing after the settle
    assert plausibility.return_to_settled(nodes, 8, [one, two])["frames"] == [9, 10, 11]


@needs_febio
def test_a_run_reports_check_d_and_how_far_it_is_from_the_settled_shape_when_the_plate_is_back(tmp_path):
    c, _ = plate_box(tmp_path / "back", "hard")
    ramp = [0.0] * 5 + [-0.1 * (i + 1) for i in range(4)] + [-0.1 * (4 - i) for i in range(4)] + [0.0] * 17
    motion = trajectory.hinge_transforms(PIVOT, AXIS, ramp)  # still to frame 4, turn and return by frame 12, still
    r = run(c["scene"].parent, motion, "back", settle=4)
    d = r.report["checks"]["d"]
    assert r.status == "complete" and d["passed"] is True and "tet mesh" in d["name"], d
    assert d["numbers"]["min_volume_ratio"] > 0.5 and d["numbers"]["inverted_tets"] == 0
    back = r.report["return_to_settled"]
    assert back["frames"][0] == 13 and back["frames"][-1] == 29 and len(back["frames"]) == 17
    assert 0 <= back["max_mm"] < 0.5 and back["mean_mm"] <= back["max_mm"]
    none = run(c["scene"].parent, motion, "no_settle")  # no settle_until_frame: no settled shape, no measurement
    assert "return_to_settled" not in none.report and none.report["checks"]["d"]["passed"] is True


# --- the placeholder motion and the command line ------------------------------------------------


def test_placeholder_motion_is_still_then_opens_to_12_degrees_and_closes():
    a = placeholder_jaw_motion.angles_deg()
    assert len(a) == 51 and max(a[:15]) == 0.0 and a[15] > 0
    assert a[placeholder_jaw_motion.OPEN_AT] == pytest.approx(12.0) and max(a) == pytest.approx(12.0)
    assert a[-1] == pytest.approx(0.0, abs=1e-12)


@needs_febio
def test_asrp_run_with_a_scene_prints_the_checks(hard_plate, capsys):
    folder, c, _, _ = hard_plate
    code = cli.main(["run", str(c["scene"]), str(c["scene"].parent / "motion.json"), "--runs-dir", str(folder / "cli")])
    out = capsys.readouterr().out
    assert code == 0 and "plausibility PASSED" in out and "check b    [PASS]" in out and "s per frame" in out
    assert "budget" not in out and "reported only" not in out


# --- PR #8 review: a dropped frame leaves no results; names stay safe for XML --------------------


@needs_febio
def test_a_run_whose_febio_log_misses_a_frame_fails_and_leaves_no_results(tmp_path, monkeypatch):
    real = run_module.read_positions

    def drop_one(path):
        data = real(path)
        data["times_s"] = data["times_s"][:2] + data["times_s"][3:]
        data["positions"] = np.concatenate([data["positions"][:2], data["positions"][3:]])
        return data

    monkeypatch.setattr(run_module, "read_positions", drop_one)
    cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    r = run(tmp_path / "box", cs.still(6), "dropped")
    assert r.status == "failed" and not r.passed
    a = r.report["checks"]["a"]
    assert a["passed"] is False and "missing frame(s) 3" in a["message"]
    assert r.report["status"] == "failed"
    assert not (r.run_dir / "physics").exists() and not (r.run_dir / "playback.json").exists()
    assert json.loads((r.run_dir / "provenance.json").read_text())["status"] == "failed"
    assert (r.run_dir / "run_report.json").exists()


def test_the_generator_escapes_names_even_if_validation_let_one_through(tmp_path):
    import xml.etree.ElementTree as ET
    c = cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0)),
                                                ("side", "plate", "spring", 1.0, at_z(0.0))])
    model = generate.build(c["scene"], cs.motion(tmp_path / "box", cs.still(3)))
    bad = 'sk&<ull"'
    for body in model.bodies.values():
        if body.name == "skull":
            body.name = bad
    model.bodies = {b.name: b for b in model.bodies.values()}
    for g in model.groups:
        if g.target == "skull":
            g.target = bad
    model.hard = {n: (bad if t == "skull" else t) for n, t in model.hard.items()}
    root = ET.fromstring(generate._feb(model))  # raises ParseError if a name went in raw
    assert any(e.get("name") == f"rb_{bad}" for e in root.iter())


# --- PR #8 review: not-run checks are not failures; the settled shape needs a still settling phase ---


@needs_febio
def test_a_spring_only_scene_and_a_short_trajectory_pass_with_the_unrun_checks_listed(tmp_path):
    cs.write(tmp_path / "spring", attachments=[("top", "plate", "spring", 1.0, at_z(10.0))])
    r = run(tmp_path / "spring", cs.still(8), "spring_only")
    checks = r.report["checks"]
    assert checks["b"]["passed"] is None and "b" in r.report["not_run"]
    assert checks["a"]["passed"] is True and r.passed, {k: (c["passed"], c["message"]) for k, c in checks.items()}

    cs.write(tmp_path / "short", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    s = run(tmp_path / "short", cs.still(8), "short")
    assert s.report["checks"]["c"]["passed"] is None and "c" in s.report["not_run"] and s.passed


@needs_febio
def test_the_settled_shape_is_written_at_the_frame_the_trajectory_names_and_not_without_one(tmp_path):
    cs.write(tmp_path / "still", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    ok = run(tmp_path / "still", cs.still(20), "still", settle=14)
    assert ok.report["settled_shape"] == {"available": True, "frame": 14}
    settled = json.loads((ok.run_dir / "physics" / "settled_frame14.json").read_text())
    assert settled["frame"] == 14 and np.allclose(settled["display"], display(ok.run_dir)[14])
    assert (ok.run_dir / "physics" / "settled_frame14.obj").exists()
    assert ok.report["checks"]["c"]["numbers"]["frames"] == [10, 14]

    other = run(tmp_path / "still", cs.still(20), "still_at_7", settle=7)  # any frame the file names, not a constant
    assert other.report["settled_shape"] == {"available": True, "frame": 7}
    assert json.loads((other.run_dir / "physics" / "settled_frame7.json").read_text())["frame"] == 7
    assert (other.run_dir / "physics" / "settled_frame7.obj").exists()
    assert not (other.run_dir / "physics" / "settled_frame14.json").exists()
    assert other.report["checks"]["c"]["numbers"]["frames"] == [3, 7]
    assert "physics/settled_frame7.obj" in json.loads((other.run_dir / "provenance.json").read_text())["outputs"]

    early = run(tmp_path / "still", cs.still(20), "still_at_2", settle=2)  # fewer than five frames: starts at frame 1
    assert early.report["checks"]["c"]["numbers"]["frames"] == [1, 2]

    none = run(tmp_path / "still", cs.still(20), "no_settle")  # the trajectory does not say
    assert none.report["settled_shape"]["available"] is False and none.report["settled_shape"]["frame"] is None
    assert not list((none.run_dir / "physics").glob("settled_frame*"))
    c_check = none.report["checks"]["c"]
    assert c_check["passed"] is None and "does not say where the gravity-only settle ends (settle_until_frame)" in c_check["message"]
    assert none.passed and "physics/settled_frame14.json" not in json.loads((none.run_dir / "provenance.json").read_text())["outputs"]


@needs_febio
def test_check_c_never_averages_the_rest_pose_frame(tmp_path):
    cs.write(tmp_path / "cube", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    zero = run(tmp_path / "cube", cs.still(20), "settle_0", settle=0)  # no frame after the rest pose: not run
    c_check = zero.report["checks"]["c"]
    assert c_check["passed"] is None and c_check["message"] == (
        "settle_until_frame is 0: there is no frame after the rest pose in the gravity-only settle")
    assert zero.status == "complete" and zero.passed and "c" in zero.report["not_run"]
    shape = zero.report["settled_shape"]
    assert shape["available"] is False and shape["frame"] is None and "settle_until_frame is 0" in shape["reason"]
    assert not list((zero.run_dir / "physics").glob("settled_frame*"))
    for n, want in ((1, [1, 1]), (2, [1, 2]), (14, [10, 14])):
        r = run(tmp_path / "cube", cs.still(20), f"settle_{n}", settle=n)
        assert r.report["checks"]["c"]["numbers"]["frames"] == want, n
        assert r.report["settled_shape"] == {"available": True, "frame": n}


@needs_febio
def test_a_driver_that_moves_before_the_settle_ends_gives_no_settled_shape_and_no_check_c(tmp_path):
    c, _ = plate_box(tmp_path / "moving", "hard")
    r = run(c["scene"].parent, TURN, "moving", settle=14)  # turns from frame 1, but the file says it is still to 14
    assert r.status == "complete" and r.report["checks"]["a"]["passed"]
    assert not list((r.run_dir / "physics").glob("settled_frame*"))
    c_check = r.report["checks"]["c"]
    assert c_check["passed"] is None and "starts on or before frame 14" in c_check["message"]
    assert r.report["settled_shape"]["available"] is False and r.report["settled_shape"]["frame"] is None and r.passed


# --- review: post-processing that breaks after FEBio finished must not look complete -------------


def _assert_failed_after_febio(r, tmp_path, *, text):
    assert r.status == "failed" and r.passed is False
    assert not (r.run_dir / "physics").exists()
    assert not (r.run_dir / "playback.json").exists() and not (r.run_dir / "playback.pc2").exists()
    prov = json.loads((r.run_dir / "provenance.json").read_text())
    assert prov["status"] == "failed" and prov["outputs"] == {} and text in prov["failure"]["message"]
    rep = cs.report(r.run_dir)
    assert rep["status"] == "failed" and rep["passed"] is False and "settled_shape" not in rep
    a = rep["checks"]["a"]
    assert a["passed"] is False and text in a["message"]
    assert str(tmp_path) not in json.dumps(rep) and str(tmp_path) not in json.dumps(prov)  # paths are scrubbed


@needs_febio
def test_a_failure_while_embedding_after_febio_finished_makes_the_run_failed(tmp_path, monkeypatch):
    cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0))])

    def boom(*a, **k):
        raise RuntimeError(f"cannot embed in {tmp_path / 'secret' / 'x.bin'}")

    monkeypatch.setattr(embed, "apply", boom)
    r = run(tmp_path / "box", cs.still(6), "embed_boom", settle=2)
    _assert_failed_after_febio(r, tmp_path, text="cannot embed in x.bin")


@needs_febio
def test_a_failure_while_writing_the_playback_files_removes_what_was_written(tmp_path, monkeypatch):
    cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    real = simulate.playback.write_surface_bundle

    def half_then_boom(run_dir, *a, **k):
        real(run_dir, *a, **k)
        raise OSError("disk full")

    monkeypatch.setattr(simulate.playback, "write_surface_bundle", half_then_boom)
    r = run(tmp_path / "box", cs.still(6), "playback_boom")
    _assert_failed_after_febio(r, tmp_path, text="disk full")


@needs_febio
def test_a_number_that_is_not_valid_json_in_the_report_fails_the_run(tmp_path, monkeypatch):
    cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0))])
    monkeypatch.setattr(simulate, "slips", lambda model, frames: {"g": {"ratio": float("nan")}})
    r = run(tmp_path / "box", cs.still(6), "nan")
    assert r.status == "failed"
    text = (r.run_dir / "run_report.json").read_text()
    assert "NaN" not in text and json.loads(text)["status"] == "failed"


@needs_febio
def test_ctrl_c_during_post_processing_is_not_swallowed(tmp_path, monkeypatch):
    cs.write(tmp_path / "box", attachments=[("top", "skull", "hard", None, at_z(10.0))])

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(embed, "apply", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path / "box", cs.still(6), "ctrl_c")
