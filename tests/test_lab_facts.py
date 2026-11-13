"""The facts about the lab's training and Ziva's playback that the documents state (docs/13 E-15), recomputed.

Every number here is recomputed from the data fetched from the lab's Ziva machine on 2026-11-12. That data
stays outside the repository; where it is on this machine comes from tools/local_paths.py. Without it these
tests are skipped and say so. Each fact has a control: the same check with one thing deliberately wrong,
which must then fail to match.

Why this file exists: on 2026-11-13 the documents twice stated the base shape of the lab's training wrongly,
and an outside audit found it by comparing with the lab's own saved results. These checks keep that from
coming back unnoticed.
"""

import hashlib
import io
import json
import pickle
import subprocess
import sys
from pathlib import Path

import local_paths
import numpy as np
import pytest

from asrp_core.final_shape import final_shape, rest_model

REPO = Path(__file__).resolve().parents[1]
MM = 0.962  # mm per scene unit (ADR-31)
AA_JOB = "lab_motions/results/job_251205-190350/251205-190358"
ALLOWED = {("builtins", n) for n in ("list", "tuple", "dict", "float", "int", "complex", "set", "frozenset")} | {
    (m, n) for m in ("numpy.core.multiarray", "numpy._core.multiarray") for n in ("_reconstruct", "scalar")} | {
    ("numpy", "ndarray"), ("numpy", "dtype"), ("numpy.core.numeric", "_frombuffer"), ("numpy._core.numeric", "_frombuffer")}


class _Restricted(pickle.Unpickler):
    """Plain containers and numpy arrays only: the lab's files are data, never code."""

    def find_class(self, module, name):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"refused {module}.{name}")
        return super().find_class(module, name)


def _unpickle(path: Path):
    return _Restricted(io.BytesIO(path.read_bytes())).load()


@pytest.fixture(scope="module")
def trip() -> Path:
    root = local_paths.ziva_trip()
    if root is None or not (root / "ziva_reference").is_dir() or not (root / "lab_motions").is_dir():
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    return root


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    scene = tmp_path_factory.mktemp("lab_facts") / "scene"
    subprocess.run([sys.executable, "-B", "-m", "asrp_core.cli", "import-asset", str(REPO / "data" / "lab_export"),
                    str(scene)], check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    return rest_model(scene / "scene.json")


def _export(trip: Path, pattern: str) -> dict:
    folders = sorted((trip / "ziva_reference").glob(pattern))
    assert folders, f"no export matches {pattern}"
    folder = folders[-1]
    report = json.loads((folder / "session_report.json").read_text(encoding="utf-8"))
    out = {"motion": json.loads((folder / "motion.json").read_text(encoding="utf-8"))}
    for name in ("lips_physics", "lips_final"):
        entry = next(s for s in report["streams"] if s["id"] == name)
        points = np.fromfile(folder / entry["samples"], dtype="<f4").astype(np.float64)
        out[name] = points.reshape(len(entry["frames"]), entry["vertices"], 3)
        assert out[name].shape[0] > 0 and out[name].shape[1] == 10240
    return out


def _max_mm(a, b) -> float:
    return float((np.linalg.norm(np.asarray(a) - np.asarray(b), axis=-1) * MM).max())


def _jaw_degrees(motion: dict) -> np.ndarray:
    """jaw01's turn against frame 0 as a SIGNED angle about the world X axis, per frame.

    Maya's matrices are for row vectors, so the turn in world axes is inverse(M0) @ Mf. A turn that is
    not about world X fails the assertion, so a wrong axis cannot hide behind a right magnitude.
    """
    key = next(k for k in motion["frames"][0] if k.split("|")[-1] == "jaw01")
    turns = [np.asarray(frame[key], dtype=np.float64).reshape(4, 4)[:3, :3] for frame in motion["frames"]]
    origins = np.array([np.asarray(frame[key], dtype=np.float64).reshape(4, 4)[3, :3] for frame in motion["frames"]])
    assert np.abs(origins - origins[0]).max() < 1e-6, "the jaw's pivot moves: the motion is not a pure turn about it"
    out = []
    for t in turns:
        world = np.linalg.inv(turns[0]) @ t
        sines = np.array([world[1, 2] - world[2, 1], world[2, 0] - world[0, 2], world[0, 1] - world[1, 0]]) / 2
        assert abs(sines[1]) < 1e-6 and abs(sines[2]) < 1e-6, "the jaw turns about an axis other than world X"
        out.append(np.degrees(np.arctan2(sines[0], (np.trace(world) - 1) / 2)))
    return np.array(out)


def _aa_motion(trip: Path):
    steps = np.stack([np.asarray(s, dtype=np.float64).ravel()[:903] for s in _unpickle(trip / AA_JOB / "combined_checkpoints.pkl")])
    return steps[:, :900].reshape(len(steps), 300, 3), steps[:, 900:903]


def _skin(model, offsets):
    rest = model.landmark_rest_scene
    return final_shape(model, None, rest + offsets) - final_shape(model, None, rest)


def test_training_results_sit_on_the_rest_shape(trip, model):
    """The lab's saved training results are rest shape + landmark layer: no gravity settle, no FEBio run."""
    files = sorted((trip / "lab_motions").rglob("deltaB_temp.pkl"))
    assert len(files) == 145
    manifest = {f["path"]: f["sha256"] for f in json.loads((trip / "manifest.json").read_text(encoding="utf-8"))["files"]}
    worst, control, seen = 0.0, np.inf, set()
    for path in files:
        data = path.read_bytes()  # the bytes that are checked are the bytes that are read
        digest = hashlib.sha256(data).hexdigest()
        assert manifest[path.relative_to(trip).as_posix()] == digest, f"{path} is not the file that was fetched"
        seen.add(digest)
        saved = _Restricted(io.BytesIO(data)).load()
        lips = np.asarray(saved["s_next"], dtype=np.float64).reshape(-1, 3)
        landmarks = np.asarray(saved["x_joint_"], dtype=np.float64).reshape(-1, 3)
        assert lips.shape == (10240, 3) and landmarks.shape == (300, 3)
        worst = max(worst, _max_mm(final_shape(model, None, landmarks), lips))
        control = min(control, _max_mm(final_shape(model, None, np.roll(landmarks, 1, axis=0)), lips))
    assert len(seen) == 145, "two archives are the same file"
    assert worst < 1e-4, f"rest base + landmark layer is off the saved training result by {worst} mm"
    assert control > 1.0, "the control (landmarks shifted by one) must not match"


def test_a_settled_base_does_not_reproduce_the_training_result(trip, model):
    """Control for the fact above: Ziva's frame-14 shape as the base misses the AA training result."""
    saved = _unpickle(trip / AA_JOB / "deltaB_temp.pkl")
    lips = np.asarray(saved["s_next"], dtype=np.float64).reshape(-1, 3)
    offsets, _ = _aa_motion(trip)
    full = _export(trip, "neutral_to_AA_export_*")["lips_physics"]
    assert _max_mm(full[0] + _skin(model, offsets[-1]), lips) < 1e-4
    assert _max_mm(full[14] + _skin(model, offsets[-1]), lips) > 1.0
    landmarks = np.asarray(saved["x_joint_"], dtype=np.float64).reshape(-1, 3)
    assert _max_mm(landmarks, model.landmark_rest_scene + offsets[-1]) < 1e-4
    assert _max_mm(landmarks, model.landmark_rest_scene + offsets[0]) > 1.0


@pytest.mark.parametrize("pattern", ["neutral_to_AA_export_*", "AA_lips_only_export_*"])
def test_playback_is_the_same_frames_physics_plus_the_landmark_layer(trip, model, pattern):
    """Every frame: Ziva's final lips = Ziva's physics lips of THAT frame + weights @ the motion file's step."""
    export = _export(trip, pattern)
    physics, final = export["lips_physics"], export["lips_final"]
    offsets, jaw = _aa_motion(trip)
    assert len(physics) == 47 and len(offsets) == 22
    assert _max_mm(physics[0], final_shape(model, None, model.landmark_rest_scene)) < 1e-4
    worst = 0.0
    for frame in range(len(physics)):
        layer = 0.0 if frame < 15 else _skin(model, offsets[min(frame - 15, len(offsets) - 1)])
        worst = max(worst, _max_mm(physics[frame] + layer, final[frame]))
    assert worst < 1e-4
    assert _max_mm(physics[14] + _skin(model, offsets[-1]), final[36]) > 5.0  # control: the frame-14 base
    degrees = _jaw_degrees(export["motion"])
    assert np.abs(degrees[:16]).max() < 1e-4 and abs(degrees[36] + 5.16416) < 1e-4  # signed: the jaw opens as -X
    assert np.abs(degrees[37:] - degrees[36]).max() < 1e-4  # every hold frame, not only the last
    assert max(abs(degrees[15 + s] - jaw[s, 0]) for s in range(len(offsets))) < 1e-4  # signed, step by step
    assert abs(degrees[25] - degrees[24]) > 0.1  # control: one frame off is a visible difference
    sag = float((np.linalg.norm(physics[14] - physics[0], axis=1) * MM).mean())
    assert abs(sag - (0.293 if pattern.startswith("neutral") else 1.777)) < 0.01  # this IS the run it is named after
    assert np.abs(jaw[:, 1:]).max() == 0.0


def test_the_lips_only_reference_is_not_settled_at_frame_14(trip):
    """Ziva with only the lips is still falling at frame 14; the full face is nearly still."""
    lips_only = _export(trip, "AA_lips_only_export_*")["lips_physics"]
    full = _export(trip, "neutral_to_AA_export_*")["lips_physics"]
    assert _max_mm(lips_only[13], lips_only[14]) > 0.2
    assert _max_mm(full[13], full[14]) < 0.05
    sag = np.linalg.norm(lips_only[14] - lips_only[0], axis=1) * MM
    assert abs(sag.mean() - 1.777) < 0.01 and abs(sag.max() - 5.390) < 0.01
    assert 7.5 < _max_mm(lips_only[36], full[36]) < 8.5


def test_flipped_faces_come_from_the_landmark_layer_and_ziva_has_them_too(trip):
    """A few tiny triangles turn over in Ziva's own final lips and in the lab's saved training result; none in
    Ziva's physics layer. So a handful of flipped faces in our final layer is not, by itself, a fault of ours."""
    from asrp_core import plausibility
    from asrp_core.asset import coords

    _, polygons = coords.read_obj(REPO / "data" / "lab_export" / "mesh_middleres_OrbicularisOris.obj")
    triangles = coords.triangulate(polygons)
    assert len(triangles) == 20480
    for pattern in ("neutral_to_AA_export_*", "AA_lips_only_export_*"):
        export = _export(trip, pattern)
        physics = plausibility.fold_counts(export["lips_physics"][0], export["lips_physics"], triangles)
        final = plausibility.fold_counts(export["lips_final"][0], export["lips_final"], triangles)
        assert int(physics["flipped"].max()) == 0 and int(physics["short"].max()) == 0
        assert int(final["flipped"].max()) == 4 and int(final["flipped"].argmax()) == 20 and int(final["flipped"][-1]) == 3
        assert 30 <= int(final["short"][-1]) <= 45
    saved = np.asarray(_unpickle(trip / AA_JOB / "deltaB_temp.pkl")["s_next"], dtype=np.float64).reshape(1, -1, 3)
    training = plausibility.fold_counts(_export(trip, "neutral_to_AA_export_*")["lips_physics"][0], saved, triangles)
    assert int(training["flipped"][0]) == 5 and int(training["short"][0]) == 121


def test_ziva_settings(trip):
    nodes = json.loads((trip / "ziva_static" / "ziva_attributes.json").read_text(encoding="utf-8"))

    def values(kind, name):
        found = [n["attributes"][name] for n in nodes.values() if n["type"] == kind]
        assert found, f"no {kind} in the attribute file"
        return found

    assert len(values("zMaterial", "youngsModulus")) == 43
    assert set(values("zMaterial", "youngsModulus")) == {12.0} and set(values("zMaterial", "youngsModulusExp")) == {3}
    assert all(abs(v - 0.4) < 1e-6 for v in values("zMaterial", "poissonsRatio"))
    assert set(values("zMaterial", "massDensity")) == {1060.0} and set(values("zMaterial", "volumeConservation")) == {0.0}
    assert len(values("zTissue", "material__label")) == 41 and set(values("zTissue", "material__label")) == {"StVK"}
    assert set(values("zTissue", "compressionResistance")) == {20000.0} and set(values("zTissue", "collisions")) == {False}
    assert len(values("zAttachment", "isHard")) == 140 and set(values("zAttachment", "isHard")) == {False}
    assert set(values("zAttachment", "stiffness")) == {1.0} and set(values("zAttachment", "stiffnessExp")) == {8}
    assert set(values("zAttachment", "damping")) == {0.01}
    assert values("zSolver", "substeps") == [1] and values("zSolver", "maxNewtonIterations") == [5]
    assert values("zSolver", "integrator__label") == ["BackwardEuler"] and values("zSolver", "framesPerSecond") == [30.0]
    assert values("zSolver", "stiffnessDamping") == [0.001] and values("zSolver", "massDamping") == [0.0]
    assert values("zSolver", "gravityY") == [-9.8] and values("zSolver", "collisionDetection") == [False]
    assert values("zSolver", "gravityX") == [0.0] and values("zSolver", "gravityZ") == [0.0]
    assert [values("zSolverTransform", a) for a in ("scaleX", "scaleY", "scaleZ")] == [[100.0]] * 3
    assert set(values("zAttachment", "attachmentMode__label")) == {"fixed"}
    assert set(values("zAttachment", "maintainOffset")) == {True}
    assert set(values("zFiber", "strength")) == {12.0} and set(values("zFiber", "strengthExp")) == {3}
    assert len(values("zFiber", "excitation")) == 18 and set(values("zFiber", "excitation")) == {0.0}
    assert values("zCloth", "enable") == [True, True] and set(values("zTissue", "enable")) == {True}
    assert sorted(values("zCloth", "collisions")) == [False, True]  # set on one cloth; the solver's detection is off


def test_head_shake_reference(trip):
    """Only the skull and the jaw are moved (as in the lab's own test); the lips' wobble comes back once."""
    export = _export(trip, "head_shake_export_*")
    physics, bones = export["lips_physics"], export["motion"]["bones"]
    travel = {name: np.array([np.asarray(b[name], dtype=np.float64).ravel()[12:15] for b in bones]) for name in bones[0]}
    for name in bones[0]:  # every bone keeps its orientation and scale: the shake is a pure translation
        linear = np.array([np.asarray(b[name], dtype=np.float64).reshape(4, 4)[:3, :3] for b in bones])
        assert np.abs(linear - linear[0]).max() < 1e-9, f"{name} turns or scales during the head shake"
    moved = sorted(name for name, t in travel.items() if np.abs(t - t[0]).max() > 1e-6)
    assert moved == ["zBone1", "zBone2"] and len(travel) == 10
    skull = travel["zBone2"]
    assert abs(np.abs(skull - skull[0]).max() - 4.64) < 0.01
    relative = physics - (skull - skull[0])[:, None, :]
    wobble = (np.linalg.norm(relative - relative[14], axis=-1) * MM).max(axis=1)
    stop = int(np.nonzero(np.linalg.norm(np.diff(skull, axis=0), axis=1) > 1e-9)[0].max()) + 1
    assert stop == 46 and abs(wobble.max() - 2.731) < 0.01
    first = next(k for k in range(len(wobble) - stop) if wobble[stop + k] < 0.04)
    stays = next(k for k in range(len(wobble) - stop) if (wobble[stop + k:] < 0.04).all())
    assert (first, stays) == (14, 28) and wobble[stop + 16] > 0.07


def _keyed_offsets(keys: dict, names) -> np.ndarray:
    """(frames, K, 3) world offsets of the landmarks from the keys our script set: local translate minus
    frame 0, turned by the parent's world matrix (Maya: row vectors)."""
    by_short = {name.split("|")[-1].split(":")[-1]: name for name in keys["values"]}
    out = np.zeros((len(keys["frames"]), len(names), 3))
    for i, name in enumerate(names):
        full = by_short[name]
        local = np.asarray(keys["values"][full], dtype=np.float64)[:, :3]
        parent = keys["parent_of"][full]
        delta = local - local[0]
        out[:, i] = delta @ np.asarray(keys["parent_world_matrix"][parent], dtype=np.float64).reshape(4, 4)[:3, :3] if parent else delta
    return out


def test_round_trips_and_jawless_phonemes(trip, model):
    """Ten round trips: physics returns, the landmark layer drifts. Phonemes without a jaw turn: physics idle."""
    trips = _export(trip, "AA_round_trip_x10_export_*")
    physics, final, degrees = trips["lips_physics"], trips["lips_final"], np.abs(_jaw_degrees(trips["motion"]))
    assert abs(degrees.max() - 5.164) < 0.01
    ends = [i for i in range(16, len(physics) - 1) if degrees[i] < degrees[i - 1] and degrees[i] <= degrees[i + 1]]
    assert len(physics) == 605 and len(ends) == 10
    assert all(abs(_max_mm(physics[i], physics[14]) - 0.049) < 0.002 for i in ends)
    drift = [_max_mm(final[i], final[14]) for i in ends]
    assert all(abs(d - 0.5238 * (k + 1)) < 0.01 for k, d in enumerate(drift)), drift  # every cycle, not two
    key_files = sorted((trip / "probes").glob("keys_AA_round_trip_x10_*.json"))
    assert key_files, "the keys of the round trips are missing"
    offsets = _keyed_offsets(json.loads(key_files[-1].read_text(encoding="utf-8")), model.names)
    assert offsets.shape[0] == 605 and np.abs(offsets).max() > 1.0
    worst = max(_max_mm(physics[f] + _skin(model, offsets[f]), final[f]) for f in range(len(physics)))
    assert worst < 1e-4, f"round trips: physics + the keyed landmark layer is off the final lips by {worst} mm"
    for phoneme, layer_mm in (("IY", 5.27), ("UW", 11.74), ("T", 4.24)):
        export = _export(trip, f"neutral_to_{phoneme}_export_*")
        p, f = export["lips_physics"], export["lips_final"]
        assert np.abs(_jaw_degrees(export["motion"])).max() < 1e-4
        assert (np.linalg.norm(p[14:] - p[14], axis=-1) * MM).max() < 0.06
        assert abs(_max_mm(f[-1], p[-1]) - layer_mm) < 0.01
