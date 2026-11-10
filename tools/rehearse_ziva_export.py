"""T-19 real Maya rehearsal without Ziva, using the real lip OBJ and a synthetic rig.

    mayapy tools/rehearse_ziva_export.py data/lab_export data/ziva_rehearsal/t19

The rig has 300 influences, a keyed cluster as solver stand-in, a second tissue, non-identity
moving parent and sparse embedder indices. It never opens/saves the lab's research scene.
"""
import os
import sys

import maya.standalone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_lab_export import parse_obj  # noqa: E402


def main(export_dir, out):
    maya.standalone.initialize(name="python")
    import maya.api.OpenMaya as om
    import maya.cmds as cmds
    import ziva_machine_export as z

    os.makedirs(out, exist_ok=True)
    results, failures = {}, []
    vertices, faces = parse_obj(os.path.join(export_dir, "mesh_middleres_OrbicularisOris.obj"))
    assert len(vertices) == 10240 and len(faces) > 0

    def expect(name, ok, detail=""):
        results[name] = {"ok": bool(ok), "detail": detail}
        print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
        if not ok:
            failures.append(name)

    def rig(kind, namespace="", mode="off", keyed="head"):
        cmds.file(new=True, force=True)
        cmds.currentUnit(time="ntsc", linear="cm")
        cmds.evaluationManager(mode=mode)
        if namespace:
            cmds.namespace(add=namespace)
        ns = namespace + ":" if namespace else ""
        head = cmds.createNode("transform", name=ns + "head")
        cmds.setAttr(head + ".translate", 10, 20, 30, type="double3")
        cmds.setAttr(head + ".rotateY", 13)
        cmds.setAttr(head + ".scale", 1.2, 1.2, 1.2, type="double3")
        lip = cmds.createNode("transform", name=ns + z.LIPS, parent=head)
        selection = om.MSelectionList(); selection.add(lip)
        om.MFnMesh().create([om.MPoint(*p) for p in vertices], [len(f) for f in faces],
                           [i for f in faces for i in f], parent=selection.getDependNode(0))
        joints = []
        for i in range(1, 301):
            joint = cmds.createNode("joint", name=ns + "oor_%02d" % i, parent=head)
            cmds.setAttr(joint + ".translate", *vertices[(i * 31) % len(vertices)], type="double3")
            joints.append(joint)
        jaw = cmds.createNode("joint", name=ns + z.JAW, parent=head)
        skin = cmds.skinCluster(joints, lip, toSelectedBones=True, maximumInfluences=1, name=ns + z.LANDMARK_SKIN)[0]
        cmds.skinPercent(skin, lip + ".vtx[*]", transformValue=[(joints[99], 1.0)])
        cluster, handle = cmds.cluster(lip, frontOfChain=True)
        for frame, value in ((0, 0), (14, -2), (20, -4)):
            cmds.setKeyframe(handle, attribute="translateY", time=frame, value=value)
        if kind == "expression":
            for frame, angle in ((0, 0), (14, 0), (20, 10)):
                cmds.setKeyframe(jaw, attribute="rotateZ", time=frame, value=angle)
            value = cmds.getAttr(joints[99] + ".translateX")
            for frame, move in ((0, 0), (14, 0), (20, 3)):
                cmds.setKeyframe(joints[99], attribute="translateX", time=frame, value=value + move)
        elif keyed == "head":
            for frame, move in ((0, 10), (14, 10), (20, 18)):
                cmds.setKeyframe(head, attribute="translateX", time=frame, value=move)
        bones = {}
        if keyed == "bones":
            # The lab's head shake keys the bone MESH transforms; jaw01 and the head stay still.
            bone = cmds.polyCube(name=ns + "fake_bone_mesh")[0]
            for frame, move in ((0, 0), (14, 0), (20, 5)):
                cmds.setKeyframe(bone, attribute="translateX", time=frame, value=move)
            bones = {"fake_bone": bone + ".worldMatrix[0]"}
        cube = cmds.polyCube(name=ns + "second_tissue")[0]
        cmds.parent(cube, head)
        cmds.playbackOptions(minTime=0, maxTime=20)
        cmds.currentTime(0, update=True)
        embedder = cmds.createNode("network", name=ns + "fake_embedder")
        cmds.addAttr(embedder, longName="inputGeometry", shortName="iGo", attributeType="message", multi=True)
        cmds.addAttr(embedder, longName="outputGeometry", shortName="og", dataType="mesh", multi=True)
        bodies, geos = [], []
        for idx, mesh, src in ((3, lip, z.physics_source(skin)), (19, cube, cube + ".outMesh")):
            body = cmds.createNode("network", name=ns + "fake_tissue_%d" % idx)
            geo = cmds.createNode("network", name=ns + "fake_geo_%d" % idx)
            cmds.addAttr(body, longName="inputGeometry", shortName="iGo", attributeType="message")
            cmds.addAttr(geo, longName="outputGeometry", shortName="oGo", attributeType="message")
            cmds.addAttr(geo, longName="inputMesh", shortName=z.GEO_MESH, dataType="mesh")
            cmds.addAttr(geo, longName="inputMatrix", shortName=z.GEO_MATRIX, dataType="matrix")
            # A tissue's zGeo stores rest mesh DATA, not the solver's live output or worldMesh.
            source_fn = z.Sampler.fn(mesh)
            counts, indices = source_fn.getVertices()
            mesh_data = om.MFnMeshData().create()
            om.MFnMesh().create(source_fn.getPoints(om.MSpace.kObject), counts, indices, parent=mesh_data)
            om.MFnDependencyNode(z.depend_node(geo)).findPlug(z.GEO_MESH, False).setMObject(mesh_data)
            cmds.connectAttr(mesh + ".worldMatrix[0]", geo + "." + z.GEO_MATRIX)
            cmds.connectAttr(geo + ".oGo", body + ".iGo")
            cmds.connectAttr(geo + ".oGo", embedder + ".iGo[%d]" % idx)
            cmds.connectAttr(src, embedder + ".og[%d]" % idx)
            bodies.append(body); geos.append(geo)
        original_ls, original_connections = z.ls_type, cmds.listConnections

        def typed_connections(*args, **kwargs):
            if kwargs.get("type") == "zGeo":
                kwargs = {k: v for k, v in kwargs.items() if k != "type"}
                return [n for n in original_connections(*args, **kwargs) or [] if n in geos]
            return original_connections(*args, **kwargs)

        try:
            z.ls_type = lambda kind: {"zTissue": bodies, "zCloth": [], "zEmbedder": [embedder]}.get(kind, [])
            cmds.listConnections = typed_connections
            entries, problems = z.expected_outputs()
            expect("sparse discovery " + kind + namespace, len(entries) == 2 and not problems, str(problems))
            cmds.disconnectAttr(geos[1] + ".oGo", embedder + ".iGo[19]")
            broken, issues = z.expected_outputs()
            expect("missing body rejected " + kind + namespace, len(broken) == 2 and bool(issues))
            cmds.connectAttr(geos[1] + ".oGo", embedder + ".iGo[19]")
        finally:
            z.ls_type, cmds.listConnections = original_ls, original_connections
        return entries, skin, bones

    reports = []
    for kind, namespace, mode, keyed in (("expression", "", "off", "head"), ("head_translation", "lab", "parallel", "head"),
                                         ("head_translation", "", "off", "bones")):
        entries, skin, bones = rig(kind, namespace, mode, keyed)
        config = {"out": out, "motion": kind, "kind": kind, "namespace": namespace, "first": 0,
                  "last": 20, "stage": "export", "require_simulation": False, "_rehearsal_outputs": entries,
                  "_rehearsal_bones": bones}
        if keyed == "bones":
            blind = z.run({**config, "stage": "preflight", "_rehearsal_bones": {}})
            expect("head shake keyed on bone meshes is invisible from jaw01 alone", bool(blind["problems"]), str(blind["problems"]))
            kind = "bone-keyed head shake"
        before = cmds.getAttr(skin + ".envelope")
        report = z.run(config)
        reports.append(report)
        expect(kind + " full export", not report["problems"], str(report["problems"]))
        check = report.get("readback", {})
        expect(kind + " exact times/topology/every vertex readback", check.get("ok") and check.get("streams_checked") == 4, str(check))
        expect(kind + " 21 frames", report["stats"].get("frames_sampled") == 21)
        expect(kind + " skin unchanged", cmds.getAttr(skin + ".envelope") == before)
        expect(kind + " temporary taps removed", not cmds.ls("asrp_*", type="transform"))
        if kind == "bone-keyed head shake":
            expect("bone-keyed head shake measured from the bone inputs", report["stats"].get("bone_translation", 0) > 4, str(report["stats"].get("bone_translation")))
        if kind == "head_translation":
            expect("translation without jaw rotation", report["stats"].get("bone_translation", 0) > 5 and report["stats"].get("jaw_degrees", 1) < .001)
        preflight = z.run({**config, "stage": "preflight"})
        expect(kind + " attempts isolated", report["out"] != preflight["out"] and os.path.isfile(os.path.join(report["out"], "seal.json")))
        rejected = z.run({**config, "estimated_seconds_per_frame": 100, "budget_minutes": .01})
        expect(kind + " budget stops before solve", bool(rejected["problems"]) and not rejected["streams"])

    from alembic import Abc, AbcGeom
    path = os.path.join(out, "missing_middle_sample.abc").replace("\\", "/")
    cmds.file(new=True, force=True); cmds.currentUnit(time="ntsc")
    cube = cmds.polyCube()[0]
    cmds.setKeyframe(cube, attribute="translateX", time=0, value=0)
    cmds.setKeyframe(cube, attribute="translateX", time=2, value=2)
    cmds.keyTangent(cube, inTangentType="linear", outTangentType="linear")
    cmds.AbcExport(jobArg='-frameRange 0 2 -step 2 -worldSpace -root "%s" -file "%s"' % (cube, path))
    archive = Abc.IArchive(path)
    schema = AbcGeom.IXform(archive.getTop().getChild(0), Abc.WrapExistingFlag.kWrapExisting).getSchema()
    try:
        z.check_sample_times(schema, [0, 1 / 30, 2 / 30], "missing_middle")
        caught = False
    except ValueError:
        caught = True
    expect("actual linear archive missing middle sample rejected", caught)

    if reports[0]["streams"]:
        folder = reports[0]["out"]
        sample_path = os.path.join(folder, reports[0]["streams"][0]["samples"])
        with open(sample_path, "rb") as f:
            original = f.read()
        with open(sample_path, "wb") as f:
            f.write(original[:-12])
        expect("truncated copy rejected", not z.check_capture(folder)["ok"])
        with open(sample_path, "wb") as f:
            f.write(original)
        expect("restored copy verified", z.check_capture(folder)["ok"])
    expect("rehearsal never completes Ziva collection", not z.check_collection(out)["complete"])

    rig("expression")
    names = z.scene_names(z.SETTINGS)
    before = cmds.listConnections(names["jaw"] + ".rotateZ", source=True, destination=False, plugs=True)
    probe = z.probe_same_frame(names)
    after = cmds.listConnections(names["jaw"] + ".rotateZ", source=True, destination=False, plugs=True)
    expect("probe restores animated channel", before == after and probe["source_restored"] and probe["channel_restored"], str(probe))
    expect("probe keeps time fixed", probe["time_after"] == 14)
    node = cmds.createNode("network")
    cmds.addAttr(node, longName="weightList", shortName="wl", attributeType="compound", numberOfChildren=1, multi=True)
    cmds.addAttr(node, longName="weights", shortName="w", attributeType="double", defaultValue=1, parent="wl", multi=True)
    maps = z.weight_maps(node)
    expect("empty weight array preserves default one", maps["0"]["default"] == 1 and maps["0"]["indices"] == [])

    z.write_json(os.path.join(out, "rehearsal_report.json"), {"checks": results, "failures": failures,
                 "maya": cmds.about(version=True), "source_vertices": len(vertices), "captures": [r["out"] for r in reports]})
    print("REHEARSAL %s: %d checks, %d failures" % ("FAILED" if failures else "PASSED", len(results), len(failures)), flush=True)
    maya.standalone.uninitialize()
    os._exit(1 if failures else 0)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
