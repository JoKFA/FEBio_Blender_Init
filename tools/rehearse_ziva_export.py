"""Rehearse tools/ziva_machine_export.py on plain Maya, with no Ziva, and record what was proved.

    "C:\\Program Files\\Autodesk\\Maya2027\\bin\\mayapy.exe" tools/rehearse_ziva_export.py <non-ziva scene.mb> data/ziva_rehearsal

Migration tool, not product code. The scene is changed in memory only and never saved.

Ziva's place is taken by a keyed cluster in front of skinCluster7: the lip shape going into the
landmark layer sags, then moves, as if something were solving it. So the sampler has to read a
shape that really changes frame by frame, and what it measured is compared with the Alembic file,
under both of Maya's evaluation modes. Then each check is made to fail on purpose.

Items 2 and 7 (weight maps, the meshes Ziva keeps) are rehearsed on stand-ins with the same
plugs: a cluster's weightList, and network nodes carrying a zGeo's mesh and matrix plugs, filled
the ways Ziva fills them (connected worldMesh; stored copy whose source was deleted).

Proves the plumbing. Cannot prove anything that needs the Ziva plug-in (A-28 in docs/11).
Writes rehearsal_report.json into <out>. Exits non-zero if any expectation fails.
"""

import json
import os
import sys
import time

import maya.standalone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from check_lab_export import parse_obj, worst_distance  # noqa: E402

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
    """A keyed cluster ahead of the landmark layer stands in for Ziva's output. Returns the cluster."""
    cluster, handle = cmds.cluster(lips, frontOfChain=True)
    for frame, value in keys:
        cmds.setKeyframe(handle, attribute="translateY", time=frame, value=value)
    return cluster


def fake_geo(cmds, z, name, mesh_plug=None, matrix_plug=None, keep_mesh_connected=True):
    """A stand-in for a zGeo: the same mesh and matrix plugs, filled the two ways Ziva fills them.

    keep_mesh_connected=False leaves a stored copy, like a tissue's zGeo after its mesh was deleted.
    """
    node = cmds.createNode("network", name=name)
    cmds.addAttr(node, longName="inputMesh", shortName=z.GEO_MESH, dataType="mesh")
    cmds.addAttr(node, longName="inputMatrix", shortName=z.GEO_MATRIX, dataType="matrix")
    if mesh_plug:
        cmds.connectAttr(mesh_plug, node + "." + z.GEO_MESH)
        cmds.dgeval(node + "." + z.GEO_MESH)
        if not keep_mesh_connected:
            cmds.disconnectAttr(mesh_plug, node + "." + z.GEO_MESH)
    if matrix_plug:
        cmds.connectAttr(matrix_plug, node + "." + z.GEO_MATRIX)
    cmds.lockNode(node, lock=True)  # survives deleting its source mesh
    return node


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
    out = os.path.abspath(out)  # Alembic plug-ins resolve relative paths against Maya's project folder
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

    # Item 2's weight maps: a cluster's weightList has the layout zAttachment stores (wl[0].w[...]).
    fresh()
    cluster = fake_solve(cmds, z.LIPS)
    cmds.percent(cluster, z.LIPS + ".vtx[0:10239]", value=0.75)  # a full map, like a lip attachment
    cmds.percent(cluster, z.LIPS + ".vtx[0:9]", value=0.5)
    cmds.percent(cluster, z.LIPS + ".vtx[20]", value=0.0)
    attrs_path, maps_path = os.path.join(out, "rehearsal_attributes.json"), os.path.join(out, "rehearsal_maps.json")
    z.dump_ziva_attributes(attrs_path, types=["cluster"])
    with open(attrs_path) as f:
        scalar = json.load(f)[cluster]["attributes"].get("weightList.weights", "")
    expect("scalar attribute dump cannot read a weight map", "unreadable" in str(scalar), str(scalar)[:40])
    started = time.time()
    count = z.dump_ziva_maps(maps_path, types=["cluster"])
    seconds = time.time() - started
    with open(maps_path) as f:
        entry = json.load(f)[cluster]
    stored = entry["weight_maps"]["0"]
    lookup = dict(zip(stored["indices"], stored["values"]))
    probe = (0, 9, 10, 20, 10239)
    truth = [cmds.getAttr("%s.weightList[0].weights[%d]" % (cluster, i)) for i in probe]
    got = [lookup.get(i, stored["default"]) for i in probe]
    expect("weight map read back exactly", count == 1 and truth == got and truth[:4] == [0.5, 0.5, 0.75, 0.0],
           "%s, %d stored, %.2f s" % (got, len(stored["indices"]), seconds))
    wired = entry["connections"]["in"]
    expect("wiring recorded as source -> destination",
           wired and all(dst.startswith(cluster + ".") for _, dst in wired), str(wired[:1]))

    # Item 7: stand-ins for zGeo, filled each way Ziva fills them.
    fresh()
    jaw_shape = cmds.listRelatives("middleres_Jaw", shapes=True, noIntermediate=True)[0]
    muscle = cmds.duplicate(z.LIPS, name="asrp_fake_muscle")[0]
    geos = [
        fake_geo(cmds, z, "fake_tissue", z.LIPS + "ShapeOrig.outMesh", z.LIPS + ".worldMatrix[0]", False),
        fake_geo(cmds, z, "fake_bone", jaw_shape + ".worldMesh[0]", "middleres_Jaw.worldMatrix[0]"),
        fake_geo(cmds, z, "fake_deleted", muscle + ".outMesh", None, False),
        fake_geo(cmds, z, "fake_wrong_space", z.LIPS + "ShapeOrig.outMesh", None),
    ]
    cmds.delete(muscle)
    meshes_dir, meshes_path = os.path.join(out, "rehearsal_meshes"), os.path.join(out, "rehearsal_meshes.json")
    written, notes = z.export_ziva_meshes(meshes_dir, meshes_path, geos=geos, first=0)
    with open(meshes_path) as f:
        got = json.load(f)["geos"]
    tissue, bone, deleted = got.get("fake_tissue", {}), got.get("fake_bone", {}), got.get("fake_deleted", {})
    expect("every stand-in exported", written == 4, str(written))
    expect("stored copy placed by iNMx, on the lips",
           tissue.get("placed_by") == z.GEO_MATRIX and tissue.get("mesh_copy_stored")
           and (tissue.get("off_from_scene_mesh") is not None and tissue["off_from_scene_mesh"] < 1e-6)
           and (tissue.get("vertices"), tissue.get("faces")) == (10240, 20480), str(tissue.get("off_from_scene_mesh")))
    lab_obj = os.path.join(REPO, "data", "lab_export", "mesh_%s.obj" % z.LIPS)
    ours, theirs = parse_obj(os.path.join(meshes_dir, tissue.get("file", "missing"))), parse_obj(lab_obj)
    expect("stored copy matches data/lab_export vertex by vertex, same faces",
           worst_distance(ours[0], theirs[0]) < 1e-6 and ours[1] == theirs[1],
           "%.2g" % worst_distance(ours[0], theirs[0]))
    expect("worldMesh copy placed by its own matrix, on the jaw",
           bone.get("placed_by") == "mesh data matrix" and bone.get("vertices") == 7426
           and (bone.get("off_from_scene_mesh") is not None and bone["off_from_scene_mesh"] < 1e-6),
           str(bone.get("off_from_scene_mesh")))
    expect("deleted mesh still exported, flagged as unplaced",
           deleted.get("vertices") == 10240 and deleted.get("matrix_connected") is False
           and deleted.get("scene_mesh") is None, str({k: deleted.get(k) for k in ("placed_by", "matrix_connected")}))
    expect("mesh in the wrong space: caught", any("fake_wrong_space" in n for n in notes), str(notes)[:80])
    expect("only that one caught", len(notes) == 1, str(len(notes)))

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
