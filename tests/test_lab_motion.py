"""The lab's motion files: the data-only reader, the conversion to a trajectory, and the proof that the conversion
is right (T-34, docs/09).

The proof needs the data fetched from the lab's Ziva machine, which stays outside the repository
(tools/local_paths.py); without it those tests are skipped and say so. It has two halves that do not lean on each
other. The DRIVER: what we hand the solver for the jaw, frame by frame, against the jaw joint Ziva recorded while it
played the same file (signed angle, the whole relative transform, the pivot), and against the tissues that ride on
the jaw in Ziva's own result. The LANDMARKS: Ziva's own physics lips of a frame plus our converted landmark layer of
that frame must be Ziva's own final lips of that frame. Each half has controls: the same check with one thing
wrong, which must then fail.
"""

import io
import json
import math
import pickle
import subprocess
import sys
from pathlib import Path

import local_paths
import numpy as np
import pytest

from asrp_core import scene as scene_module
from asrp_core import skinning, trajectory
from asrp_core.asset import coords

REPO = Path(__file__).resolve().parents[1]
AA_JOB = "lab_motions/results/job_251205-190350/251205-190358"
TURN = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])  # scene axes -> Z up: (x, y, z) -> (x, -z, y)
RIDES_ON_THE_JAW = ("zTissue34_", "zTissue35_", "zTissue36_", "zTissue37_", "zTissue38_", "zTissue39_")


def _cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "asrp_core.cli", *map(str, args)], cwd=REPO,
                          capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def scene_path(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("lab_motion") / "scene"
    done = _cli("import-asset", REPO / "data" / "lab_export", out)
    assert done.returncode == 0, done.stdout + done.stderr
    return out / "scene.json"


def _steps(n: int = 4, pitch=(-1.0, -2.0, -3.0, -4.0)) -> np.ndarray:
    """A made-up lab motion: landmark k moves by (k, 2k, 3k) * step / 1000 scene units, the jaw pitches."""
    steps = np.zeros((n, trajectory.LAB_STEP_NUMBERS))
    for i in range(n):
        k = np.arange(300)[:, None] * np.array([1.0, 2.0, 3.0]) * (i + 1) / 1000
        steps[i, :900] = k.ravel()
        steps[i, 900] = pitch[i]
        steps[i, 903:] = 7.0  # the eyes and the forehead: must not leak into anything
    return steps


def _convert(steps, **changes) -> trajectory.Trajectory:
    args = {"driver": "jaw01", "pivot_mm": (0.0, -100.0, -50.0), "landmark_names": [f"oor_{i + 1:02d}" for i in range(300)],
            "mm_per_scene_unit": 0.962, "fps": 30, **changes}
    return trajectory.from_lab_motion(steps, **args)


# --- the reader -------------------------------------------------------------------------------------------------


def test_the_reader_reads_lists_and_arrays(tmp_path):
    steps = _steps()
    for name, data in (("arrays.pkl", [row.astype(np.float32) for row in steps]),
                       ("lists.pkl", [row.tolist() for row in steps]),
                       ("nested.pkl", [row.reshape(1, -1) for row in steps])):
        (tmp_path / name).write_bytes(pickle.dumps(data))
        read = trajectory.read_lab_motion(tmp_path / name)
        assert read.shape == (4, 3603) and read.dtype == np.float64
        assert np.abs(read - steps).max() < 1e-5


class _Touch:
    """Unpickling this with the plain loader creates a file: the proof that the plain loader runs code."""

    def __init__(self, path):
        self.path = str(path)

    def __reduce__(self):
        return (open, (self.path, "w"))


def test_the_reader_runs_nothing_from_the_file(tmp_path):
    marker = tmp_path / "ran.txt"
    hostile = tmp_path / "hostile.pkl"
    hostile.write_bytes(pickle.dumps([_Touch(marker)]))
    with pytest.raises(trajectory.TrajectoryError, match="Nothing from the file was run"):
        trajectory.read_lab_motion(hostile)
    assert not marker.exists()
    pickle.load(io.BytesIO(hostile.read_bytes())).pop().close()  # control: the plain loader does run it
    assert marker.exists()


def _array_pickle(dtype_code: bytes, dtype_state: bytes, shape: bytes, raw: bytes) -> bytes:
    """A hand-written pickle of [one numpy array] (protocol 2): the array's type, the type's state, the shape and
    the raw bytes are whatever the test says, as a hostile file could say them."""
    module = b"numpy._core.multiarray"
    dtype = b"cnumpy\ndtype\nX" + len(dtype_code).to_bytes(4, "little") + dtype_code + b"\x89\x88\x87R" + dtype_state + b"b"
    array = (b"c" + module + b"\n_reconstruct\ncnumpy\nndarray\nK\x00\x85C\x01b\x87R"
             + b"(K\x01" + shape + dtype + b"\x89C" + bytes([len(raw)]) + raw + b"tb")
    return b"\x80\x02]" + array + b"a."


PLAIN_STATE = b"(K\x03X\x01\x00\x00\x00<NNNJ\xff\xff\xff\xffJ\xff\xff\xff\xffK\x00t"  # (3, '<', None, None, None, -1, -1, 0)
ONE = b"K\x01\x85"  # the shape (1,)


def test_a_file_cannot_make_numpy_read_its_bytes_as_objects(tmp_path):
    """Found by an outside review (2026-11-13): with numpy's own dtype and _reconstruct a pickle can build an
    object array that says it holds no objects, and numpy then follows the file's bytes as pointers; reading it
    crashed the process. The reader must refuse it, in a process that stays alive."""
    hostile = tmp_path / "pointers.pkl"
    object_state = b"(K\x03X\x01\x00\x00\x00|NNNJ\xff\xff\xff\xffJ\xff\xff\xff\xffK\x00t"  # flags 0: "no objects"
    hostile.write_bytes(_array_pickle(b"O", object_state, ONE, b"\x41" * 8))
    code = ("import sys\nfrom asrp_core import trajectory\ntry:\n    trajectory.read_lab_motion(sys.argv[1])\n"
            "except trajectory.TrajectoryError as e:\n    print('REFUSED', e)\n")
    done = subprocess.run([sys.executable, "-B", "-c", code, str(hostile)], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8")
    assert done.returncode == 0, f"the reader died with exit code {done.returncode}: {done.stderr[-300:]}"
    assert "REFUSED" in done.stdout and "Nothing from the file was run" in done.stdout and "'O'" in done.stdout


@pytest.mark.parametrize("dtype_code, state, shape, raw, says", [
    (b"f8", PLAIN_STATE, ONE, b"\x00" * 7, "holds 7 bytes"),  # one float64 needs 8 bytes
    (b"f8", PLAIN_STATE, b"K\x02\x85", b"\x00" * 8, "holds 8 bytes"),  # two float64s need 16
    (b"V8", PLAIN_STATE, ONE, b"\x00" * 8, "only plain number types"),  # raw memory
    (b"U2", PLAIN_STATE, ONE, b"\x00" * 8, "only plain number types"),  # text
    (b"f8", b"(K\x03X\x01\x00\x00\x00<N(X\x01\x00\x00\x00atNJ\xff\xff\xff\xffJ\xff\xff\xff\xffK\x00t", ONE, b"\x00" * 8,
     "fields"),  # a type that claims named fields
    (b"f8", b"(K\x03X\x01\x00\x00\x00?NNNJ\xff\xff\xff\xffJ\xff\xff\xff\xffK\x00t", ONE, b"\x00" * 8, "byte order"),
    (b"f8", PLAIN_STATE, b"J\xff\xff\xff\xff\x85", b"\x00" * 8, "shape"),  # a negative length
])
def test_an_array_is_built_only_from_a_plain_number_type_and_bytes_of_the_right_length(tmp_path, dtype_code, state, shape, raw, says):
    path = tmp_path / "odd.pkl"
    path.write_bytes(_array_pickle(dtype_code, state, shape, raw))
    with pytest.raises(trajectory.TrajectoryError, match=says):
        trajectory.read_lab_data(path)
    good = tmp_path / "good.pkl"  # control: the same hand-written form with honest content is read
    good.write_bytes(_array_pickle(b"f8", PLAIN_STATE, ONE, np.float64(2.5).tobytes()))
    [array] = trajectory.read_lab_data(good)
    assert array.dtype == np.float64 and array.tolist() == [2.5]


def test_what_numpy_itself_writes_is_read_back_the_same(tmp_path):
    """Every way numpy pickles numbers: C and Fortran order, either byte order, the common number types, single
    numbers, and pickle protocols 2 to 5, inside lists, tuples and dicts."""
    grid = np.arange(24.0).reshape(2, 3, 4)
    content = {"c": grid, "f": np.asfortranarray(grid), "big": grid.astype(">f8"), "f4": grid.astype(np.float32),
               "i": np.arange(-3, 3), "u1": np.arange(5, dtype=np.uint8), "flag": np.array([True, False]),
               "one": np.float64(1.25), "count": np.int32(7), "empty": np.zeros((0, 3)), "plain": [1, 2.5, "text", None],
               "pair": (np.float32(0.5), [np.arange(3)])}
    for protocol in (2, 3, 4, 5):
        path = tmp_path / f"p{protocol}.pkl"
        path.write_bytes(pickle.dumps(content, protocol=protocol))
        read = trajectory.read_lab_data(path)
        assert read.keys() == content.keys()
        for key in ("c", "f", "big", "f4", "i", "u1", "flag", "empty"):
            assert isinstance(read[key], np.ndarray) and read[key].shape == content[key].shape, (protocol, key)
            assert read[key].dtype == content[key].dtype.newbyteorder("=") and np.array_equal(read[key], content[key])
        assert read["one"] == 1.25 and read["count"] == 7 and read["plain"] == [1, 2.5, "text", None]
        assert read["pair"][0] == 0.5 and np.array_equal(read["pair"][1][0], [0, 1, 2]) and isinstance(read["pair"], tuple)
    with pytest.raises(trajectory.TrajectoryError, match="Nothing from the file was run"):
        (tmp_path / "obj.pkl").write_bytes(pickle.dumps([np.array([{"a": 1}], dtype=object)]))
        trajectory.read_lab_data(tmp_path / "obj.pkl")
    with pytest.raises(trajectory.TrajectoryError, match="Nothing from the file was run"):
        (tmp_path / "type.pkl").write_bytes(pickle.dumps([np.dtype("f8")]))  # a bare type is not data
        trajectory.read_lab_data(tmp_path / "type.pkl")


@pytest.mark.parametrize("data, says", [
    ({"steps": 1}, "not a list of steps"),
    ([], "not a list of steps"),
    ([[1.0, 2.0, 3.0]], "each step has 3 numbers"),
    ([[1.0] * 3603, [1.0] * 3602], "of one length"),
    ([[float("nan")] * 3603], "not finite"),
    ([["a"] * 3603], "vectors of numbers"),
])
def test_the_reader_says_what_is_wrong(tmp_path, data, says):
    path = tmp_path / "bad.pkl"
    path.write_bytes(pickle.dumps(data))
    with pytest.raises(trajectory.TrajectoryError, match=says):
        trajectory.read_lab_motion(path)


def test_the_reader_refuses_a_cut_off_or_missing_file(tmp_path):
    whole = pickle.dumps([row for row in _steps()])
    (tmp_path / "cut.pkl").write_bytes(whole[: len(whole) // 2])
    with pytest.raises(trajectory.TrajectoryError, match="fetch the file again"):
        trajectory.read_lab_motion(tmp_path / "cut.pkl")
    with pytest.raises(trajectory.TrajectoryError, match="does not exist"):
        trajectory.read_lab_motion(tmp_path / "none.pkl")


# --- the conversion, on made-up numbers -------------------------------------------------------------------------


def test_frames_settle_then_one_step_per_frame_then_hold():
    motion = _convert(_steps())
    assert motion.frames == 15 + 4 + 10 and motion.settle_until_frame == 14 and motion.source_tag == "lab_setting"
    assert list(motion.drivers) == ["jaw01"] and len(motion.drivers["jaw01"]) == motion.frames
    identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    assert all(m == identity for m in motion.drivers["jaw01"][:15])  # exactly at rest through frame 14
    names, moves = trajectory.landmark_translations(motion)
    assert len(names) == 300 and moves.shape == (29, 300, 3) and not moves[:15].any()
    assert np.abs(moves[15:19] - moves[14:18]).max() > 0  # every step is its own frame
    assert all(np.array_equal(moves[f], moves[18]) for f in range(19, 29))  # the hold repeats the last step
    assert all(motion.drivers["jaw01"][f] == motion.drivers["jaw01"][18] for f in range(19, 29))
    assert _convert(_steps(), hold_frames=0).frames == 19
    assert trajectory.from_json(json.loads(json.dumps(motion.to_json()))).frames == 29  # a valid trajectory.json


def test_the_jaw_turns_about_world_x_through_the_pivot_with_the_files_sign():
    pivot = np.array([0.0, -100.0, -50.0])
    motion = _convert(_steps())
    for frame, degrees in ((15, -1.0), (18, -4.0), (28, -4.0)):
        m = np.array(motion.drivers["jaw01"][frame]).reshape(4, 4)
        assert np.abs(m[:3, :3] @ m[:3, :3].T - np.eye(3)).max() < 1e-12
        assert np.abs(m[:3, :3] @ pivot + m[:3, 3] - pivot).max() < 1e-12  # the pivot stays where it is
        assert np.abs(m[:3, 0] - [1, 0, 0]).max() < 1e-12  # the axis is X
        assert abs(math.degrees(math.atan2(m[2, 1], m[1, 1])) - degrees) < 1e-9  # signed, right-handed about +X
    # In the lab's axes (Y up, face towards -Z) a negative pitch opens the jaw: a point in front of the pivot goes
    # down. In ours (Z up, face towards +Y) that is: a point at +Y from the pivot moves towards -Z.
    m = np.array(motion.drivers["jaw01"][18]).reshape(4, 4)
    chin = pivot + [0.0, 80.0, 0.0]
    assert (m[:3, :3] @ chin + m[:3, 3])[2] < chin[2] - 1.0


def test_landmark_offsets_are_scaled_and_turned_once():
    steps = np.zeros((1, 3603))
    steps[0, 3:6] = [1.0, 2.0, 3.0]  # landmark 2: one scene unit along x, two up, three towards the back
    _, moves = trajectory.landmark_translations(_convert(steps))
    assert np.allclose(moves[15, 1], np.array([1.0, -3.0, 2.0]) * 0.962) and not moves[15, [0, 2]].any()
    assert np.allclose(coords.from_mm_zup(moves[15], 0.962)[1], [1.0, 2.0, 3.0])


def test_what_the_conversion_refuses():
    yaw = _steps()
    yaw[2, 901] = 0.5
    with pytest.raises(trajectory.TrajectoryError, match="more than its pitch"):
        _convert(yaw)
    with pytest.raises(trajectory.TrajectoryError, match="lists 299 landmarks"):
        _convert(_steps(), landmark_names=[f"oor_{i}" for i in range(299)])
    with pytest.raises(trajectory.TrajectoryError, match="read the file with read_lab_motion"):
        _convert(np.zeros((3, 900)))
    with pytest.raises(trajectory.TrajectoryError, match="hold_frames"):
        _convert(_steps(), hold_frames=-1)


def test_the_command_wants_to_be_told_that_the_segment_starts_at_rest(tmp_path, scene_path):
    lab_file = tmp_path / "job" / "run" / "combined_checkpoints.pkl"
    lab_file.parent.mkdir(parents=True)
    lab_file.write_bytes(pickle.dumps([row for row in _steps()]))
    out = tmp_path / "motion.json"
    silent = _cli("convert-motion", lab_file, scene_path, out)
    assert silent.returncode == 1 and "--starts-at-rest" in silent.stdout and "T-10" in silent.stdout and not out.exists()
    done = _cli("convert-motion", lab_file, scene_path, out, "--starts-at-rest")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "convert PASSED" in done.stdout and "29 frames" in done.stdout
    motion = trajectory.read(out)
    assert "job/run/combined_checkpoints.pkl" in motion.source and str(tmp_path) not in out.read_text(encoding="utf-8")
    s = scene_module.load(scene_path)
    assert motion.landmarks["names"] == list(s.landmarks.names)
    pivot = np.array(next(d for d in s.drivers if d.name == "jaw01").hinge.pivot_mm)
    m = np.array(motion.drivers["jaw01"][18]).reshape(4, 4)
    assert np.abs(m[:3, :3] @ pivot + m[:3, 3] - pivot).max() < 1e-9  # the scene's own pivot
    hostile = tmp_path / "hostile.pkl"
    hostile.write_bytes(pickle.dumps([_Touch(tmp_path / "ran.txt")]))
    refused = _cli("convert-motion", hostile, scene_path, tmp_path / "no.json", "--starts-at-rest")
    assert refused.returncode == 1 and "Nothing from the file was run" in refused.stdout
    assert not (tmp_path / "ran.txt").exists() and not (tmp_path / "no.json").exists()


# --- the proof on the lab's real motion and Ziva's own record of it --------------------------------------------


@pytest.fixture(scope="module")
def trip() -> Path:
    root = local_paths.ziva_trip()
    if root is None or not (root / "ziva_reference").is_dir() or not (root / AA_JOB).is_dir():
        pytest.skip("NOT VERIFIED: the Ziva trip data is not on this machine; " + local_paths.HOW_TO_SET)
    return root


@pytest.fixture(scope="module")
def ours(trip, scene_path, tmp_path_factory) -> trajectory.Trajectory:
    """The real entry point on the real file: `asrp convert-motion`, then the file it wrote. The title is the
    one the committed motion carries for the Blender panel; everything else comes from the lab's file."""
    out = tmp_path_factory.mktemp("lab_motion_aa") / "neutral_to_AA.json"
    done = _cli("convert-motion", trip / AA_JOB / "combined_checkpoints.pkl", scene_path, out, "--starts-at-rest",
                "--title", "Prototype 2: neutral to AA")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "47 frames at 30 fps" in done.stdout and "-5.16416 degrees" in done.stdout
    return trajectory.read(out)


def _folder(trip: Path, pattern: str) -> Path:
    folders = sorted((trip / "ziva_reference").glob(pattern))
    assert folders, f"no export matches {pattern}"
    return folders[-1]


def _streams(folder: Path, wanted) -> dict:
    report = json.loads((folder / "session_report.json").read_text(encoding="utf-8"))
    out = {}
    for entry in report["streams"]:
        if wanted(entry["id"]):
            points = np.fromfile(folder / entry["samples"], dtype="<f4").astype(np.float64)
            out[entry["id"]] = points.reshape(len(entry["frames"]), entry["vertices"], 3)
    return out


def _ziva_jaw(folder: Path, mm: float) -> list[np.ndarray]:
    """Per frame, the motion of everything rigidly on Ziva's jaw01 since frame 0, as a 4x4 in OUR convention (mm,
    Z up, column vectors). Maya's matrices are for row vectors, so a world point moves by inverse(M0) @ Mf; that is
    transposed, turned to Z up, and its translation scaled to mm. The base pose is divided out first: an absolute
    Maya matrix is never used as a rigid transform."""
    motion = json.loads((folder / "motion.json").read_text(encoding="utf-8"))
    key = next(k for k in motion["frames"][0] if k.split("|")[-1] == "jaw01")
    world = [np.asarray(frame[key], dtype=np.float64).reshape(4, 4) for frame in motion["frames"]]
    out = []
    for m in world:
        relative = np.linalg.inv(world[0]) @ m
        turn = relative[:3, :3].T
        assert np.abs(turn @ turn.T - np.eye(3)).max() < 1e-9 and abs(np.linalg.det(turn) - 1) < 1e-9, "not rigid"
        t = np.eye(4)
        t[:3, :3] = TURN @ turn @ TURN.T
        t[:3, 3] = mm * (TURN @ relative[3, :3])
        out.append(t)
    return out


def _signed_degrees_about_x(m: np.ndarray) -> float:
    sines = np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]]) / 2
    assert abs(sines[1]) < 1e-6 and abs(sines[2]) < 1e-6, "a turn about an axis other than X"
    return math.degrees(math.atan2(sines[0], (np.trace(m[:3, :3]) - 1) / 2))


def _driver_gap(transforms, ziva, points_mm, pivot_mm) -> dict:
    """The largest difference over ALL frames between a driver (16 numbers per frame) and Ziva's jaw: signed angle
    (degrees), any entry of the turn, the translation (mm), where the given points land (mm), and how far Ziva's
    own motion moves the pivot (mm)."""
    assert len(transforms) == len(ziva)
    gap = {"angle_deg": 0.0, "turn": 0.0, "translation_mm": 0.0, "points_mm": 0.0, "pivot_mm": 0.0}
    for mine, theirs in zip(transforms, ziva):
        m = np.array(mine, dtype=np.float64).reshape(4, 4)
        gap["angle_deg"] = max(gap["angle_deg"], abs(_signed_degrees_about_x(m) - _signed_degrees_about_x(theirs)))
        gap["turn"] = max(gap["turn"], float(np.abs(m[:3, :3] - theirs[:3, :3]).max()))
        gap["translation_mm"] = max(gap["translation_mm"], float(np.abs(m[:3, 3] - theirs[:3, 3]).max()))
        moved = np.linalg.norm(points_mm @ (m[:3, :3] - theirs[:3, :3]).T + (m[:3, 3] - theirs[:3, 3]), axis=1)
        gap["points_mm"] = max(gap["points_mm"], float(moved.max()))
        gap["pivot_mm"] = max(gap["pivot_mm"], float(np.abs(theirs[:3, :3] @ pivot_mm + theirs[:3, 3] - pivot_mm).max()))
    return gap


@pytest.mark.parametrize("pattern", ["neutral_to_AA_export_*", "AA_lips_only_export_*"])
def test_the_jaw_we_hand_the_solver_is_the_jaw_ziva_recorded(trip, scene_path, ours, pattern):
    """Frames 0 to 46, every frame: our jaw01 driver against Ziva's jaw01. Signed angle, the whole transform, where
    every vertex of the jaw and the lower teeth lands, and the pivot. Four wrong drivers must each be caught."""
    s = scene_module.load(scene_path)
    mm = s.units.mm_per_scene_unit.value
    pivot = np.array(next(d for d in s.drivers if d.name == "jaw01").hinge.pivot_mm)
    follows = [b.name for b in s.bones if b.driver == "jaw01"]
    assert follows == ["jaw", "teeth_lower"]
    points = np.concatenate([coords.read_obj(scene_path.parent / f"meshes/{name}.obj")[0] for name in follows])
    assert len(points) > 7000 and np.ptp(points, axis=0).min() > 50  # real bone meshes, not three points in a line
    ziva = _ziva_jaw(_folder(trip, pattern), mm)
    mine = ours.drivers["jaw01"]
    assert len(ziva) == 47 and ours.frames == 47 and ours.fps == 30 and ours.settle_until_frame == 14

    gap = _driver_gap(mine, ziva, points, pivot)
    assert gap["angle_deg"] < 1e-4 and gap["turn"] < 1e-9 and gap["translation_mm"] < 1e-6, gap
    assert gap["points_mm"] < 1e-6 and gap["pivot_mm"] < 1e-9, gap
    degrees = [_signed_degrees_about_x(np.array(m).reshape(4, 4)) for m in mine]
    assert all(d == 0.0 for d in degrees[:15]) and abs(degrees[15]) < 1e-5  # at rest, then a first step of ~0
    assert abs(degrees[36] + 5.16416) < 1e-5 and all(d == degrees[36] for d in degrees[37:])  # signed; held
    assert all(a > b for a, b in zip(degrees[16:36], degrees[17:37]))  # opens further on every frame

    steps = trajectory.read_lab_motion(trip / AA_JOB / "combined_checkpoints.pkl")
    angles = [0.0] * 15 + [math.radians(a) for a in steps[:, 900]] + [math.radians(steps[-1, 900])] * 10
    identity = trajectory.hinge_transforms(pivot, (1, 0, 0), [0.0])[0]
    wrong = {
        "the sign of the turn is flipped": trajectory.hinge_transforms(pivot, (1, 0, 0), [-a for a in angles]),
        "the motion is one frame late": [identity, *mine[:-1]],
        "the jaw goes back to neutral in frames 37 to 46": [*mine[:37], *([identity] * 10)],
        "the pivot is 1 mm away": trajectory.hinge_transforms(pivot + [0.0, 1.0, 0.0], (1, 0, 0), angles),
    }
    for what, transforms in wrong.items():
        bad = _driver_gap(transforms, ziva, points, pivot)
        assert bad["points_mm"] > 0.05 and (bad["angle_deg"] > 0.01 or bad["translation_mm"] > 0.05), (what, bad)
    # The angle alone lets the wrong pivot through, which is why the whole transform and the points are compared.
    assert _driver_gap(wrong["the pivot is 1 mm away"], ziva, points, pivot)["angle_deg"] < 1e-4


def test_the_tissues_on_zivas_jaw_went_where_our_driver_goes(trip, scene_path, ours):
    """Ziva's export has no bone meshes, and its bone matrices do not move in this run (the jaw mesh follows the
    joint through its skin). What shows where Ziva's jaw BONE went is the tissue stuck to it: in the full-face
    run six tissues ride on the jaw almost rigidly. Moved by OUR driver from their frame-0 points, they are within
    0.02 mm of Ziva's result on every frame, while they travel 9 to 13 mm."""
    mm = scene_module.load(scene_path).units.mm_per_scene_unit.value
    streams = _streams(_folder(trip, "neutral_to_AA_export_*"), lambda name: name.startswith(RIDES_ON_THE_JAW))
    assert len(streams) == 6
    flipped = [np.linalg.inv(np.array(m).reshape(4, 4)) for m in ours.drivers["jaw01"]]
    for name, points in streams.items():
        assert points.shape[0] == 47 and points.shape[1] > 500
        rest = coords.to_mm_zup(points[0], mm)
        worst = wrong_way = travel = 0.0
        for frame in range(47):
            there = coords.to_mm_zup(points[frame], mm)
            m = np.array(ours.drivers["jaw01"][frame]).reshape(4, 4)
            worst = max(worst, float(np.linalg.norm(rest @ m[:3, :3].T + m[:3, 3] - there, axis=1).max()))
            back = flipped[frame]
            wrong_way = max(wrong_way, float(np.linalg.norm(rest @ back[:3, :3].T + back[:3, 3] - there, axis=1).max()))
            travel = max(travel, float(np.linalg.norm(there - rest, axis=1).max()))
        assert worst < 0.02 and travel > 9.0 and wrong_way > 15.0, (name, worst, travel, wrong_way)


@pytest.mark.parametrize("pattern", ["neutral_to_AA_export_*", "AA_lips_only_export_*"])
def test_our_landmark_layer_on_zivas_physics_is_zivas_final_shape(trip, scene_path, ours, pattern):
    """Every frame f: Ziva's physics lips of frame f + the landmark layer from OUR converted motion's frame f =
    Ziva's final lips of frame f. The layer is applied the way a run applies it (skinning.deform on the scene's
    weights). It proves the landmark half of the conversion only: columns, units, axes and frames."""
    s = scene_module.load(scene_path)
    mm = s.units.mm_per_scene_unit.value
    skin = skinning.load(scene_path.parent / s.landmarks.weights.path)
    names, moves = trajectory.landmark_translations(ours)
    assert names == list(s.landmarks.names) == list(skin.names) and moves.shape == (47, 300, 3)
    lips = _streams(_folder(trip, pattern), lambda name: name in ("lips_physics", "lips_final"))
    physics, final = lips["lips_physics"], lips["lips_final"]
    assert physics.shape == final.shape == (47, 10240, 3)
    worst = shifted = late = layer = 0.0
    for frame in range(47):
        base, there = coords.to_mm_zup(physics[frame], mm), coords.to_mm_zup(final[frame], mm)
        worst = max(worst, float(np.linalg.norm(skinning.deform(base, skin.weights, moves[frame]) - there, axis=1).max()))
        shifted = max(shifted, float(np.linalg.norm(
            skinning.deform(base, skin.weights, np.roll(moves[frame], 1, axis=0)) - there, axis=1).max()))
        late = max(late, float(np.linalg.norm(
            skinning.deform(base, skin.weights, moves[max(frame - 1, 0)]) - there, axis=1).max()))
        layer = max(layer, float(np.linalg.norm(there - base, axis=1).max()))
    assert worst < 1e-4, f"physics + our landmark layer is off Ziva's final lips by {worst} mm"
    assert layer > 5.0  # the layer is not nothing: without it the same comparison is millimetres off
    assert shifted > 1.0  # control: the landmark columns shifted by one
    assert late > 0.1  # control: the landmark layer one frame late
    assert not moves[:15].any() and all(np.array_equal(moves[f], moves[36]) for f in range(37, 47))
    assert abs(float(np.linalg.norm(moves, axis=2).max()) - 12.103) < 0.01  # the lab's 12.1 mm


def test_the_motion_in_the_repository_is_the_conversion_of_the_labs_file(trip, ours):
    """data/lab_export/trajectories/neutral_to_AA.json is what the panel plays. It must be exactly what
    `asrp convert-motion` makes from the lab's file today: every proof above is about that conversion."""
    kept = trajectory.read(REPO / "data" / "lab_export" / "trajectories" / "neutral_to_AA.json")
    assert kept.to_json() == ours.to_json()


def test_the_motion_in_the_repository_is_a_run_of_47_frames_from_rest(scene_path):
    """Without the lab's data: the file is there, checks against the imported scene, and has the shape of the
    lab's neutral-to-AA motion (the numbers themselves are compared with the lab's file in the test above)."""
    path = REPO / "data" / "lab_export" / "trajectories" / "neutral_to_AA.json"
    report = scene_module.check(scene_path, path)
    assert report.ok, report.errors
    motion = trajectory.read(path)
    assert (motion.frames, motion.fps, motion.settle_until_frame, motion.source_tag) == (47, 30, 14, "lab_setting")
    assert list(motion.drivers) == ["jaw01"] and "combined_checkpoints.pkl (sha256 " in motion.source
    _, moves = trajectory.landmark_translations(motion)
    assert not moves[:15].any() and moves[15:].any() and abs(float(np.linalg.norm(moves, axis=2).max()) - 12.103) < 0.01
    last = np.array(motion.drivers["jaw01"][46]).reshape(4, 4)
    assert abs(math.degrees(math.atan2(last[2, 1], last[1, 1])) + 5.16416) < 1e-5
