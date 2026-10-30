"""Export what the prototype needs from a Maya scene, using plain Maya (no Ziva).

    "C:\\Program Files\\Autodesk\\Maya2027\\bin\\mayapy.exe" tools/maya_export.py <scene.mb> data/lab_export

Migration tool, not product code (docs ADR-18): the product never needs Maya. Runs under
mayapy, stdlib and Maya only. Opens the scene read-only in spirit: it never saves it, because
an education-licence Maya would stamp the lab's file.

Writes into <out>:
    mesh_<name>.obj      rest shape (the ShapeOrig mesh), in SCENE coordinates, faces as stored
    mesh_report.json     vertex/face counts, bounding box and world matrix per mesh
    skin_<cluster>.json  per-vertex weights and bind matrices of each deformer we rebuild
    joints.json          rest world matrix of jaw01 and the 300 oor_ landmarks

Then checks its own output against numbers known from the .mb, and exits non-zero on a mismatch.
"""

import json
import os
import sys
import time

import maya.standalone

MESHES = {  # name -> vertex count read from the .mb (docs/03-asset.md)
    "middleres_OrbicularisOris": 10240,
    "middleres_Jaw": 7426,
    "middleres_skull": 28414,
    "middleres_TeethUp": 24608,
    "middleres_TeethDown": 24608,
}
# Face context only, never simulated: lets the briefing and previews show where the lips sit.
CONTEXT_MESHES = ["skin_cloth_copy_v5_pull_back"]
SKIN_CLUSTERS = {"skinCluster7": "middleres_OrbicularisOris"}  # the landmark layer (docs/03 section 4)
JAW_JOINT = "jaw01"
LANDMARK_COUNT = 300
JAW_SCENE_Z = 155.92  # paper appendix V, docs ADR-16


def rest_dag_path(om, name):
    """The DAG path of a mesh's ShapeOrig, the undeformed input to Ziva and skinning."""
    sel = om.MSelectionList()
    sel.add(name + "ShapeOrig")
    return sel.getDagPath(0)


def write_obj(om, name, path):
    """Write the rest shape in scene coordinates, keeping Maya's vertex order and polygons.

    We write the file ourselves so its coordinate space is a fact of this function, not of the
    OBJ plug-in. Vertex order must survive: the skin weights and the .mb cross-check index by it.
    """
    mesh = om.MFnMesh(rest_dag_path(om, name))
    points = mesh.getPoints(om.MSpace.kWorld)
    counts, indices = mesh.getVertices()
    with open(path, "w", newline="\n") as f:
        f.write("# %s rest shape (ShapeOrig), scene coordinates, Maya vertex order\n" % name)
        for p in points:
            f.write("v %.9f %.9f %.9f\n" % (p.x, p.y, p.z))
        at = 0
        for n in counts:
            f.write("f " + " ".join(str(i + 1) for i in indices[at:at + n]) + "\n")
            at += n
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return {
        "vertices": len(points),
        "faces": len(counts),
        "triangles": sum(n - 2 for n in counts),
        "bbox_min": lo,
        "bbox_max": hi,
        "size": [h - l for l, h in zip(lo, hi)],
    }


def export_skin(om, oma, cmds, cluster, mesh_name, path):
    """Dump one skinCluster: sparse per-vertex weights plus the matrices the skinning formula needs."""
    sel = om.MSelectionList()
    sel.add(cluster)
    fn = oma.MFnSkinCluster(sel.getDependNode(0))
    influences = fn.influenceObjects()
    names = [i.partialPathName() for i in influences]

    sel = om.MSelectionList()
    sel.add(mesh_name + "Shape")
    shape = sel.getDagPath(0)
    all_vertices = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
    om.MFnSingleIndexedComponent(all_vertices).setCompleteData(om.MFnMesh(shape).numVertices)
    weights, count = fn.getWeights(shape, all_vertices)

    sparse = []
    for v in range(len(weights) // count):
        row = weights[v * count:(v + 1) * count]
        sparse.append([[i, round(w, 9)] for i, w in enumerate(row) if w > 1e-9])
    bind = {}
    for i in range(count):
        plug = "%s.bindPreMatrix[%d]" % (cluster, fn.indexForInfluenceObject(influences[i]))
        bind[names[i]] = list(cmds.getAttr(plug))
    with open(path, "w") as f:
        json.dump({
            "cluster": cluster,
            "mesh": mesh_name,
            "influences": names,
            "geom_matrix": list(cmds.getAttr(cluster + ".geomMatrix")),
            "bind_pre_matrix": bind,
            "weights": sparse,
        }, f)
    totals = [sum(w for _, w in row) for row in sparse]
    return {
        "influences": count,
        "vertices": len(sparse),
        "weight_sum_min": min(totals),
        "weight_sum_max": max(totals),
        "max_influences_on_a_vertex": max(len(row) for row in sparse),
        "names": names,
        "bind_error": bind_error(cmds, bind),
    }


def bind_error(cmds, bind):
    """At rest every bindPreMatrix must undo its joint: T-09's formula is identity with no motion."""
    worst = 0.0
    for name, pre in bind.items():
        world = cmds.getAttr(name + ".worldMatrix[0]")
        for r in range(4):
            for c in range(4):
                value = sum(pre[r * 4 + k] * world[k * 4 + c] for k in range(4))
                worst = max(worst, abs(value - (1.0 if r == c else 0.0)))
    return worst


def export_joints(cmds, path):
    """Rest transforms: the jaw hinge (position and axes) and every landmark."""
    joints = {}
    names = [JAW_JOINT] + ["oor_%02d" % i for i in range(1, LANDMARK_COUNT + 1)]
    for name in names:
        joints[name] = {
            "world_matrix": cmds.xform(name, query=True, matrix=True, worldSpace=True),
            "world_position": cmds.xform(name, query=True, translation=True, worldSpace=True),
            "parent": (cmds.listRelatives(name, parent=True) or [None])[0],
        }
    with open(path, "w") as f:
        json.dump(joints, f, indent=0)
    return joints


def check(report, joints):
    """Fail loudly here, at the source, rather than three tasks later."""
    problems = []
    for name, want in MESHES.items():
        got = report["meshes"][name]["vertices"]
        if got != want:
            problems.append("%s: %d vertices, the .mb says %d" % (name, got, want))
        if report["meshes"][name]["faces"] <= 0:
            problems.append("%s: no faces" % name)
    jaw_z = report["meshes"]["middleres_Jaw"]["size"][2]
    if abs(jaw_z - JAW_SCENE_Z) > 0.01:
        problems.append("jaw z size %.3f, expected %.2f: wrong coordinate space" % (jaw_z, JAW_SCENE_Z))
    for cluster, skin in report["skin"].items():
        if skin["influences"] != LANDMARK_COUNT:
            problems.append("%s: %d influences" % (cluster, skin["influences"]))
        if skin["vertices"] != MESHES[SKIN_CLUSTERS[cluster]]:
            problems.append("%s: weights for %d vertices" % (cluster, skin["vertices"]))
        if abs(skin["weight_sum_min"] - 1) > 1e-3 or abs(skin["weight_sum_max"] - 1) > 1e-3:
            problems.append("%s: weights do not sum to 1 (%.6f to %.6f)" % (
                cluster, skin["weight_sum_min"], skin["weight_sum_max"]))
        if set(skin["names"]) != set(joints) - {JAW_JOINT}:
            problems.append("%s: influences are not exactly oor_01..oor_%d" % (cluster, LANDMARK_COUNT))
        if skin["bind_error"] > 1e-6:
            problems.append("%s: bindPreMatrix does not undo its joint (%.3g)" % (cluster, skin["bind_error"]))
    return problems


def main(scene, out):
    maya.standalone.initialize(name="python")
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    import maya.cmds as cmds

    started = time.time()
    cmds.file(scene, open=True, force=True, ignoreVersion=True, prompt=False)
    if not os.path.isdir(out):
        os.makedirs(out)

    report = {
        "scene": os.path.basename(scene),
        "maya": cmds.about(version=True),
        "linear_unit": cmds.currentUnit(query=True, linear=True),
        "up_axis": cmds.upAxis(query=True, axis=True),
        "playback_range": [cmds.playbackOptions(query=True, minTime=True),
                           cmds.playbackOptions(query=True, maxTime=True)],
        "obj_coordinates": "scene",
        "meshes": {},
        "context_meshes": {},
        "skin": {},
    }
    for name in MESHES:
        info = write_obj(om, name, os.path.join(out, "mesh_%s.obj" % name))
        info["world_matrix"] = cmds.xform(name, query=True, matrix=True, worldSpace=True)
        report["meshes"][name] = info
    for name in CONTEXT_MESHES:
        report["context_meshes"][name] = write_obj(om, name, os.path.join(out, "context_%s.obj" % name))
    for cluster, mesh_name in SKIN_CLUSTERS.items():
        report["skin"][cluster] = export_skin(
            om, oma, cmds, cluster, mesh_name, os.path.join(out, "skin_%s.json" % cluster))
    joints = export_joints(cmds, os.path.join(out, "joints.json"))
    report["jaw_hinge"] = joints[JAW_JOINT]
    report["seconds"] = round(time.time() - started, 1)

    problems = check(report, joints)
    report["problems"] = problems
    with open(os.path.join(out, "mesh_report.json"), "w") as f:
        json.dump(report, f, indent=1)

    for name, m in report["meshes"].items():
        print("%-28s %6d v %6d f  size %s" % (name, m["vertices"], m["faces"], [round(s, 2) for s in m["size"]]))
    for cluster, s in report["skin"].items():
        print("%s: %d influences, %d vertices, weight sum %.6f..%.6f, at most %d per vertex, bind error %.1e" % (
            cluster, s["influences"], s["vertices"], s["weight_sum_min"], s["weight_sum_max"],
            s["max_influences_on_a_vertex"], s["bind_error"]))
    print("%d joints, jaw hinge at %s" % (len(joints), [round(v, 3) for v in joints[JAW_JOINT]["world_position"]]))
    print("%.1f s -> %s" % (report["seconds"], out))
    maya.standalone.uninitialize()
    if problems:
        print("EXPORT CHECK FAILED")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print("EXPORT CHECK PASSED")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
