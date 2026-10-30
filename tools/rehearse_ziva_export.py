"""Rehearse tools/ziva_machine_export.py on plain Maya, with no Ziva, and record what was proved.

    "C:\\Program Files\\Autodesk\\Maya2027\\bin\\mayapy.exe" tools/rehearse_ziva_export.py <non-ziva scene.mb> data/ziva_rehearsal

Migration tool, not product code. The scene is changed in memory only and never saved.

Ziva's place is taken by a keyed cluster in front of skinCluster7: the lip shape going into the
landmark layer sags, then moves, as if something were solving it. So the sampler has to read a
shape that really changes frame by frame, and what it measured is compared with the Alembic file,
under both of Maya's evaluation modes. Then each check is made to fail on purpose.

Proves the plumbing. Cannot prove anything that needs the Ziva plug-in (A-28 in docs/11).
Writes rehearsal_report.json into <out>. Exits non-zero if any expectation fails.
"""

import json
import os
import sys

import maya.standalone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MOVED_LANDMARK = "oor_100"
SAG, MOVE = 2.0, 6.0  # scene units the fake solve moves the lips: by frame 14, then by frame 30


def fake_motion(cmds):
    """Jaw still until frame 14, then 10 degrees by frame 30; one landmark moves."""
    for frame, degrees in ((0, 0), (14, 0), (30, 10)):
        cmds.setKeyframe("jaw01", attribute="rotateZ", time=frame, value=degrees)
    start = cmds.getAttr(MOVED_LANDMARK + ".translateX")
    for frame, value in ((0, start), (14, start), (30, start + 3)):
        cmds.setKeyframe(MOVED_LANDMARK, attribute="translateX", time=frame, value=value)


def fake_solve(cmds, lips, keys=((0, 0), (14, -SAG), (30, -SAG - MOVE))):
    """A keyed cluster ahead of the landmark layer stands in for Ziva's output."""
    handle = cmds.cluster(lips, frontOfChain=True)[1]
    for frame, value in keys:
        cmds.setKeyframe(handle, attribute="translateY", time=frame, value=value)


def read_back(cmds, om, path, frames):
    """Open an Alembic in an empty scene; return vertex count and world points per frame."""
    cmds.file(new=True, force=True)
    cmds.currentUnit(time="ntsc")  # Alembic stores seconds; a new scene would read them at 24 fps
    cmds.AbcImport(path, mode="import")
    meshes = [m for m in cmds.ls(type="mesh", long=True) if not cmds.getAttr(m + ".intermediateObject")]
    sel = om.MSelectionList()
    sel.add(meshes[0])
    fn = om.MFnMesh(sel.getDagPath(0))
    shapes = {}
    for frame in frames:
        cmds.currentTime(frame, update=True)
        shapes[frame] = [tuple(p)[:3] for p in fn.getPoints(om.MSpace.kWorld)]
    return shapes


def main(scene, out):
    maya.standalone.initialize(name="python")
    import maya.api.OpenMaya as om
    import maya.cmds as cmds

    import ziva_machine_export as z

    cmds.loadPlugin("AbcImport", quiet=True)
    base = {"out": out, "motion": "rehearsal", "first": 0, "last": 40, "require_simulation": False, "accepted": []}
    results, failed = {}, []

    def fresh(mode="off"):
        cmds.file(scene, open=True, force=True, ignoreVersion=True, prompt=False)
        cmds.evaluationManager(mode=mode)

    def expect(name, ok, detail=""):
        results[name] = {"ok": bool(ok), "detail": detail}
        print("%-58s %s  %s" % (name, "ok" if ok else "FAILED", detail))
        if not ok:
            failed.append(name)

    for mode in ("off", "parallel"):
        tag = "[%s] " % mode
        fresh(mode)
        fake_motion(cmds)
        fake_solve(cmds, z.LIPS)
        envelope = cmds.getAttr(z.LANDMARK_SKIN + ".envelope")
        report = z.run(base)
        stats = report["stats"]
        track = stats["physics_track"]
        expect(tag + "full run passes", not report["problems"], str(report["problems"]))
        expect(tag + "all 41 frames sampled", stats["frames_sampled"] == 41)
        expect(tag + "skinCluster7 untouched", cmds.getAttr(z.LANDMARK_SKIN + ".envelope") == envelope)
        expect(tag + "temporary mesh removed", not cmds.objExists("asrp_physics_only"))
        expect(tag + "jaw turn measured", abs(stats["jaw_degrees"] - 10) < .01, "%.3f" % stats["jaw_degrees"])
        expect(tag + "landmark layer measured", stats["final_vs_physics"] > 1, "%.3f" % stats["final_vs_physics"])
        expect(tag + "sampler saw the sag", abs(stats["gravity_sag"] - SAG) < .01, "%.3f" % stats["gravity_sag"])
        expect(tag + "sampler saw the motion", abs(stats["motion_move"] - MOVE) < .01, "%.3f" % stats["motion_move"])
        expect(tag + "simulation checks pass on it", z.check_simulation(stats) == ([], []))

        final_path = os.path.join(out, "ziva_rehearsal_final.abc").replace("\\", "/")
        physics_path = os.path.join(out, "ziva_rehearsal_physics.abc").replace("\\", "/")
        frames = (0, 7, 14, 22, 30)
        physics = read_back(cmds, om, physics_path, frames)
        final = read_back(cmds, om, final_path, frames)
        expect(tag + "both files have every vertex", len(physics[0]) == len(final[0]) == 10240)
        off_by = max(abs(z.largest_move(physics[f], physics[0]) - track[f]) for f in frames)
        expect(tag + "sampler matches the file, frame by frame", off_by < 1e-3, "worst %.6f" % off_by)
        expect(tag + "two files differ where a landmark moved", z.largest_move(final[30], physics[30]) > 1,
               "%.3f" % z.largest_move(final[30], physics[30]))
        expect(tag + "files agree before any landmark moved", z.largest_move(final[0], physics[0]) < 1e-3)

    # Each check must be able to fail.
    fresh()
    fake_solve(cmds, z.LIPS)
    report = z.run(base)
    expect("no motion loaded: refused before solving", any("jaw01 does not turn" in p for p in report["problems"]))

    fresh()
    fake_motion(cmds)
    report = z.run({**base, "require_simulation": True})
    expect("no Ziva plug-in: refused before solving", any("plug-in" in p for p in report["problems"]))

    fresh()
    fake_motion(cmds)
    report = z.run({**base, "first": 1})
    expect("timeline not from 0: refused", any("must start at 0" in p for p in report["problems"]))

    fresh()
    fake_motion(cmds)
    report = z.run(base)
    expect("no solve at all: caught", any("did not follow" in p for p in z.check_simulation(report["stats"])[0]))

    fresh()
    fake_motion(cmds)
    fake_solve(cmds, z.LIPS, ((0, 0), (14, -SAG), (20, -SAG - 2)))  # stops while the jaw goes on
    report = z.run(base)
    frozen = report["stats"]["frozen_frames"]
    expect("solve dies at frame 20: caught", any("froze" in p for p in z.check_simulation(report["stats"])[0]), str(frozen))

    fresh()
    fake_motion(cmds)
    fake_solve(cmds, z.LIPS, ((0, -5), (14, -SAG - 5), (30, -SAG - MOVE - 5)))  # starts away from rest
    report = z.run(base)
    expect("first frame not at rest: caught", any("did not reset" in p for p in z.check_simulation(report["stats"])[0]),
           "%.3f" % report["stats"]["rest_offset"])

    with open(os.path.join(out, "rehearsal_report.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("REHEARSAL " + ("FAILED: %s" % failed if failed else "PASSED"))
    sys.stdout.flush()
    maya.standalone.uninitialize()  # without it Autodesk's error reporter treats the exit as a crash
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
