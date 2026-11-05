"""What only a machine with Ziva can give us: run once in Maya's Script Editor (Python tab).

Migration tool, not product code (docs ADR-18). Steps are in docs/12-lab-export-checklist.md.
Before running: open the scene the researchers really use, load one motion, edit SETTINGS below.

Writes into OUT:
    ziva_attributes.json       every scalar attribute of every Ziva node, defaults included  (item 2)
    ziva_maps.json             every weight map (weightList) and connection of every Ziva node (item 2)
    ziva_setup.zBuilder        the same setup in Ziva's own format                    (item 2)
    ziva_meshes/<zGeo>.obj     the mesh Ziva keeps for each body, scene coordinates   (item 7)
    ziva_meshes.json           which body each mesh belongs to, and how it was placed (item 7)
    ziva_<motion>_final.abc    lip shape per frame, landmarks on                      (item 4a)
    ziva_<motion>_physics.abc  lip shape per frame, before the landmark layer         (item 4b)
    motion_<motion>.json       world matrix per frame of jaw01 and the 300 landmarks  (item 5)
    session_report.json        versions, frame range, measurements, and every check

Items 2 and 7 need no solve. The weight maps get their own file because listAttr(scalar=True)
cannot read them: on plain Maya it records a deformer's weightList as "unreadable". The meshes
come from each zGeo's input mesh, which Ziva keeps even after the Maya mesh was deleted; that is
the only copy of the six muscles around the lips (docs/12 item 7). Trouble in either is a note,
not a failure: it must not cost the reference solve.

Both Alembic files come from ONE solve: a temporary mesh taps the shape going into skinCluster7,
so the two are guaranteed to be the same simulation and skinCluster7 is never touched. The
temporary mesh is deleted at the end, and the scene is never saved.

Checks run before the solve (cheap) and after it (did Ziva really move the lips, on every frame,
starting from rest?). The last line says PASSED or FAILED, whatever happens: do not leave the
machine until it says PASSED. If a researcher looks at a failed check and confirms the data is
fine, add a word from that problem to "accepted": it then counts as a note, on the record.
"""

import json
import math
import os
import tempfile
import time
import traceback

try:
    import maya.api.OpenMaya as om
    import maya.cmds as cmds
except ImportError:  # the checks below are unit-tested without Maya
    om = cmds = None

SETTINGS = {
    "out": r"D:\asrp_export",  # any folder you can copy from afterwards
    "motion": "neutral_to_AA",  # a short name with no spaces
    "first": None,  # None = use the timeline
    "last": None,
    "require_simulation": True,  # False only for tools/rehearse_ziva_export.py on plain Maya
    "accepted": [],  # words from problems a researcher has checked by eye, e.g. ["zCache"]
}
ZIVA_TYPES = ["zSolverTransform", "zSolver", "zTissue", "zBone", "zTet", "zMaterial", "zGeo",
              "zAttachment", "zEmbedder", "zFiber", "zCloth", "zCache"]
LIPS = "middleres_OrbicularisOris"
LANDMARK_SKIN = "skinCluster7"
JAW = "jaw01"
JOINTS = [JAW] + ["oor_%02d" % i for i in range(1, 301)]
LIP_VERTICES = 10240
GRAVITY_SETTLE_FRAMES = 14  # the lab's motions keep frames 0..14 still (docs/03 section 7)
MIN_MOVEMENT = 0.01  # scene units; real motion is far bigger, numerical noise far smaller
MIN_JAW_DEGREES = 1.0
MAX_MOVEMENT = 300.0  # scene units; the head is about 300 long, so beyond this the solve diverged
MAX_REST_OFFSET = 1.0  # a leftover from a previous solve is far bigger than this, noise far smaller
BODY_TYPES = ("zTissue", "zBone", "zCloth")
GEO_MESH, GEO_MATRIX, GEO_OUT = "iNMh", "iNMx", "oGo"  # zGeo plugs, short names as stored in the .mb
MESH_MATCH = 1e-3  # scene units; a mesh read in the wrong space is off by far more
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def ls_type(node_type):
    try:
        return cmds.ls(type=node_type) or []
    except RuntimeError:  # type unknown: the Ziva plug-in is not loaded
        return []


def rotation_between(a, b):
    """Largest angle in degrees between the X and Y axes of two flat world matrices."""
    worst = 0.0
    for start in (0, 4):
        u, v = a[start:start + 3], b[start:start + 3]
        cosine = sum(x * y for x, y in zip(u, v)) / (
            math.sqrt(sum(x * x for x in u)) * math.sqrt(sum(y * y for y in v)))
        worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return worst


def largest_move(a, b):
    """Largest distance between matching points."""
    return max(math.dist(p, q) for p, q in zip(a, b))


def apply_matrix(points, m):
    """Maya's row-vector convention: p' = p * M, with M a flat 4x4 list."""
    return [(x * m[0] + y * m[4] + z * m[8] + m[12],
             x * m[1] + y * m[5] + z * m[9] + m[13],
             x * m[2] + y * m[6] + z * m[10] + m[14]) for x, y, z in points]


def placing_matrix(data_matrix, input_matrix):
    """The matrix that takes a zGeo's mesh points to the scene, and its name.

    Mesh data that arrives through a worldMesh plug (a bone) carries its own world matrix; checked
    on plain Maya. A stored copy (a tissue) is in object space and placed by the zGeo's iNMx.
    """
    if any(abs(a - b) > 1e-12 for a, b in zip(data_matrix, IDENTITY)):
        return list(data_matrix), "mesh data matrix"
    if input_matrix is not None:
        return list(input_matrix), GEO_MATRIX
    return list(IDENTITY), "none"


def mesh_mismatch(geo, mesh, off):
    """A note when an exported mesh does not sit on the scene mesh it was copied from."""
    if off is None or off <= MESH_MATCH:
        return None
    return ("IMPORTANT: the mesh of %s is %.4f away from %s in the scene: ziva_meshes may be in the "
            "wrong place, tell the developers (docs/12 item 7)" % (geo, off, mesh))


def file_name(node):
    """A node name that is safe as a file name (namespaces and paths use : and |)."""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in node)


def check_motion(stats):
    """Did the motion really play? True on any machine, with or without Ziva."""
    problems = []
    if stats["frames_sampled"] != stats["frames_expected"]:
        problems.append("sampled %d frames, expected %d" % (stats["frames_sampled"], stats["frames_expected"]))
    if stats["jaw_degrees"] < MIN_JAW_DEGREES:
        problems.append("jaw01 turned only %.3f degrees: is the motion loaded?" % stats["jaw_degrees"])
    if stats["landmark_travel"] < MIN_MOVEMENT:
        problems.append("no landmark moved: is the motion loaded?")
    if stats["final_vs_physics"] < MIN_MOVEMENT:
        problems.append("final and physics shapes are identical: the landmark layer did nothing")
    return problems


def check_simulation(stats):
    """Did Ziva really solve, on every frame, from rest? Returns (problems, notes).

    A little or no gravity sag is only a note: gravity may be off or the tissue stiff, and the
    file does not say. A shape that ignores the jaw has no such excuse.
    """
    problems, notes = [], []
    if stats["motion_move"] < MIN_MOVEMENT:
        problems.append("the physics shape did not move after frame 14: Ziva did not follow the jaw")
    if stats["frozen_frames"]:
        problems.append("the physics shape froze on %d frames while the jaw moved: the solve stopped "
                        "part way" % stats["frozen_frames"])
    if stats["rest_offset"] > MAX_REST_OFFSET:
        problems.append("the first frame is %.2f from rest: Ziva did not reset, clear the cache and "
                        "run again" % stats["rest_offset"])
    if not stats["finite"] or stats["largest_move"] > MAX_MOVEMENT:
        problems.append("the solve diverged: a vertex moved %.1f" % stats["largest_move"])
    if stats["gravity_sag"] < MIN_MOVEMENT:
        notes.append("almost no gravity sag in frames 0-14 (%.4f): ask the researcher if that is "
                     "normal for this scene" % stats["gravity_sag"])
    return problems, notes


def split_accepted(problems, accepted):
    """Problems a person has accepted become notes, so they stay on the record."""
    waived = [p for p in problems if any(word in p for word in accepted)]
    return [p for p in problems if p not in waived], ["accepted by a person: " + p for p in waived]


def preflight(settings, first, last):
    """Everything that can be found out before spending a solve. Returns (problems, notes)."""
    problems, notes = [], []
    if first != 0 or last <= GRAVITY_SETTLE_FRAMES:
        problems.append("frame range %d..%d must start at 0 and go past frame %d" % (
            first, last, GRAVITY_SETTLE_FRAMES))
    found = cmds.ls(LIPS, long=True) or []
    if len(found) != 1:
        problems.append("expected one %s, found %d" % (LIPS, len(found)))
    elif cmds.polyEvaluate(found[0], vertex=True) != LIP_VERTICES:
        problems.append("the lip mesh is not %d vertices" % LIP_VERTICES)
    if not cmds.objExists(LANDMARK_SKIN):
        problems.append("%s not found" % LANDMARK_SKIN)
    elif not physics_source():
        problems.append("nothing feeds %s, so the physics shape cannot be tapped" % LANDMARK_SKIN)
    missing = [j for j in JOINTS if not cmds.objExists(j)]
    if missing:
        problems.append("%d joints not found, for example %s" % (len(missing), missing[0]))
    else:
        # getAttr at a time evaluates the jaw alone, so this costs no Ziva solve.
        rest = cmds.getAttr(JAW + ".worldMatrix[0]", time=first)
        turned = max(rotation_between(rest, cmds.getAttr(JAW + ".worldMatrix[0]", time=f))
                     for f in range(first, last + 1))
        if turned < MIN_JAW_DEGREES:
            problems.append("jaw01 does not turn on the timeline (%.3f degrees): is the motion "
                            "loaded and keyed? A script-driven motion cannot be exported" % turned)
    if settings["require_simulation"]:
        if not cmds.pluginInfo("ziva", query=True, loaded=True):
            problems.append("the Ziva plug-in is not loaded")
        solvers = ls_type("zSolverTransform")
        if not solvers:
            problems.append("no Ziva solver in this scene")
        for solver in solvers:
            if cmds.attributeQuery("sF", node=solver, exists=True):
                start = cmds.getAttr(solver + ".sF")
                if start < first or start >= GRAVITY_SETTLE_FRAMES:
                    problems.append("%s starts at frame %s: going back to frame %d would not reset it, "
                                    "or it would skip the gravity frames" % (solver, start, first))
                elif start > first:
                    notes.append("%s starts at frame %s, not %d" % (solver, start, first))
            if cmds.attributeQuery("enable", node=solver, exists=True) and not cmds.getAttr(solver + ".enable"):
                problems.append("%s is switched off" % solver)
        caches = ls_type("zCache")
        if caches:
            problems.append("zCache nodes exist (%s): clear them, then add \"zCache\" to accepted"
                            % ", ".join(caches))
    return problems, notes


def physics_source():
    """The plug that feeds skinCluster7: the lip shape before the landmark layer."""
    plugs = cmds.listConnections(LANDMARK_SKIN + ".input[0].inputGeometry", source=True,
                                 destination=False, plugs=True)
    return plugs[0] if plugs else None


def make_physics_mesh():
    """A temporary mesh showing the shape before landmarks. skinCluster7 itself stays untouched."""
    transform = cmds.createNode("transform", name="asrp_physics_only")
    shape = cmds.createNode("mesh", name="asrp_physics_onlyShape", parent=transform)
    cmds.connectAttr(physics_source(), shape + ".inMesh")
    cmds.xform(transform, matrix=cmds.xform(LIPS, query=True, matrix=True, worldSpace=True), worldSpace=True)
    return transform


class Sampler:
    """Called by AbcExport on every frame: records the joints and measures the two shapes."""

    def __init__(self, final, physics, first, last):
        self.final, self.physics = self.fn(final), self.fn(physics)
        self.first, self.last = first, last
        self.frames, self.started = [], time.time()
        self.physics0 = self.physics14 = self.joints0 = self.previous = None
        self.rest = None
        if cmds.objExists(LIPS + "ShapeOrig"):
            sel = om.MSelectionList()
            sel.add(LIPS + "ShapeOrig")
            self.rest = [tuple(p)[:3] for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]
        self.stats = {
            "frames_expected": last - first + 1, "frames_sampled": 0, "jaw_degrees": 0.0,
            "landmark_travel": 0.0, "final_vs_physics": 0.0, "gravity_sag": 0.0, "motion_move": 0.0,
            "frozen_frames": 0, "rest_offset": 0.0, "largest_move": 0.0, "finite": True, "physics_track": [],
        }

    @staticmethod
    def fn(node):
        sel = om.MSelectionList()
        sel.add(node)
        return om.MFnMesh(sel.getDagPath(0).extendToShape())

    def __call__(self, frame):
        frame = int(frame)
        final = [tuple(p)[:3] for p in self.final.getPoints(om.MSpace.kWorld)]
        physics = [tuple(p)[:3] for p in self.physics.getPoints(om.MSpace.kWorld)]
        joints = {j: cmds.xform(j, query=True, matrix=True, worldSpace=True) for j in JOINTS}
        self.frames.append(joints)
        s = self.stats
        s["frames_sampled"] += 1
        if self.physics0 is None:
            self.physics0, self.joints0 = physics, joints
            s["final_vs_physics_first_frame"] = largest_move(final, physics)
            if self.rest:
                s["rest_offset"] = largest_move(physics, self.rest)
        s["finite"] = s["finite"] and all(math.isfinite(c) for p in physics for c in p)
        moved = largest_move(physics, self.physics0)
        s["physics_track"].append(moved)
        s["largest_move"] = max(s["largest_move"], moved)
        if frame > GRAVITY_SETTLE_FRAMES and self.previous:
            jaw_turned = rotation_between(self.previous[1], joints[JAW]) > 1e-4
            if jaw_turned and largest_move(physics, self.previous[0]) < 1e-6:
                s["frozen_frames"] += 1
        self.previous = (physics, joints[JAW])
        if frame <= GRAVITY_SETTLE_FRAMES:
            s["gravity_sag"] = max(s["gravity_sag"], largest_move(physics, self.physics0))
        if frame == GRAVITY_SETTLE_FRAMES:
            self.physics14 = physics
        if frame > GRAVITY_SETTLE_FRAMES and self.physics14:
            s["motion_move"] = max(s["motion_move"], largest_move(physics, self.physics14))
        s["final_vs_physics"] = max(s["final_vs_physics"], largest_move(final, physics))
        s["jaw_degrees"] = max(s["jaw_degrees"], rotation_between(self.joints0[JAW], joints[JAW]))
        for j in JOINTS[1:]:
            s["landmark_travel"] = max(s["landmark_travel"], math.dist(self.joints0[j][12:15], joints[j][12:15]))
        done = s["frames_sampled"]
        if done == 1 or done % 5 == 0:
            spent = time.time() - self.started
            print("frame %d: %d of %d done, %.1f minutes left" % (
                frame, done, s["frames_expected"], spent / done * (s["frames_expected"] - done) / 60))


def export_alembic(jobs, first, last, sampler):
    """One AbcExport, so one solve, writing every file. It steps frame by frame, as Ziva requires."""
    import __main__

    __main__.asrp_sample = sampler  # AbcExport evaluates its callback in __main__
    cmds.loadPlugin("AbcExport", quiet=True)
    cmds.currentTime(first, update=True)
    args = []
    for i, (node, path) in enumerate(jobs):
        # On the last job, so both meshes have been evaluated for this frame when it reads them.
        callback = ' -pythonPerFrameCallback "asrp_sample(#FRAME#)"' if i == len(jobs) - 1 else ""
        args.append('-frameRange %d %d -worldSpace -dataFormat ogawa%s -root %s -file "%s"' % (
            first, last, callback, cmds.ls(node, long=True)[0], path.replace("\\", "/")))
    cmds.AbcExport(jobArg=args)


def dump_ziva_attributes(path, types=ZIVA_TYPES):
    """Item 2. Reads every attribute, so defaults are included; the .mb only stores changed ones."""
    dump = {}
    for node_type in types:
        for node in ls_type(node_type):
            values = {}
            for attr in cmds.listAttr(node, scalar=True) or []:
                plug = node + "." + attr
                try:
                    values[attr] = cmds.getAttr(plug)
                    if cmds.getAttr(plug, type=True) == "enum":
                        values[attr + "__label"] = cmds.getAttr(plug, asString=True)
                except Exception as exc:
                    values[attr] = "unreadable: %s" % exc
            dump[node] = {"type": node_type, "attributes": values}
    with open(path, "w") as f:
        json.dump(dump, f, indent=1, default=str)
    return len(dump)


def dump_zbuilder(path):
    """Item 2, second form. Returns an error string instead of stopping the session."""
    try:
        import zBuilder.builders.ziva as zva

        builder = zva.Ziva()
        builder.retrieve_from_scene()
        builder.write(path)
        return None
    except Exception as exc:
        return "zBuilder export failed: %s" % exc


def depend_node(name):
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getDependNode(0)


def weight_maps(node):
    """Every weightList entry of a node, sparse as stored: {index: default, indices, values}.

    Vertices that are not listed take the default. Short names wl/w are how the .mb stores
    zAttachment weights, and Maya's own deformers use the same ones.
    """
    fn = om.MFnDependencyNode(depend_node(node))
    if not (fn.hasAttribute("wl") and fn.hasAttribute("w")):
        return {}
    weights_attr = fn.attribute("w")
    default = om.MFnNumericAttribute(weights_attr).default
    weight_list = fn.findPlug("wl", False)
    maps = {}
    for p in range(weight_list.evaluateNumElements()):
        element = weight_list.elementByPhysicalIndex(p)
        weights = element.child(weights_attr)
        indices, values = [], []
        for q in range(weights.evaluateNumElements()):
            plug = weights.elementByPhysicalIndex(q)
            indices.append(plug.logicalIndex())
            values.append(plug.asDouble())
        maps[str(element.logicalIndex())] = {"default": default, "indices": indices, "values": values}
    return maps


def connections(node):
    """Every connection of a node as [source plug, destination plug] pairs."""
    pairs = {}
    for incoming in (True, False):
        flat = cmds.listConnections(node, source=incoming, destination=not incoming, connections=True,
                                    plugs=True) or []
        own, other = flat[0::2], flat[1::2]
        pairs["in" if incoming else "out"] = [[o, n] if incoming else [n, o] for n, o in zip(own, other)]
    return pairs


def dump_ziva_maps(path, types=ZIVA_TYPES):
    """Item 2, second half: the weight maps and wiring that ziva_attributes.json cannot hold."""
    dump, count = {}, 0
    for node_type in types:
        for node in ls_type(node_type):
            maps = weight_maps(node)
            count += len(maps)
            dump[node] = {"type": node_type, "connections": connections(node), "weight_maps": maps}
    with open(path, "w") as f:
        json.dump(dump, f, separators=(",", ":"))
    return count


def source_node(plug):
    found = cmds.listConnections(plug, source=True, destination=False) or []
    return found[0] if found else None


def mesh_from_plug(node, attr):
    """Object-space points, polygons and the data's own matrix of a mesh-typed plug.

    Works on stored data whose source mesh was deleted, even after the file is reopened.
    """
    data = om.MFnDependencyNode(depend_node(node)).findPlug(attr, False).asMObject()
    fn = om.MFnMesh(data)
    counts, connects = fn.getVertices()
    points = [tuple(p)[:3] for p in fn.getPoints(om.MSpace.kObject)]
    return points, list(counts), list(connects), list(om.MFnGeometryData(data).matrix)


def rest_points(name):
    """World rest shape of a scene mesh: its ShapeOrig, or the shape itself if nothing deforms it."""
    if not name or not cmds.objExists(name):
        return None
    if cmds.nodeType(name) != "transform":
        name = (cmds.listRelatives(name, parent=True, fullPath=True) or [None])[0]
        if name is None:
            return None
    shapes = cmds.listRelatives(name, shapes=True, fullPath=True, type="mesh") or []
    undriven = [s for s in shapes if not source_node(s + ".inMesh")]
    origs = [s for s in undriven if cmds.getAttr(s + ".intermediateObject")]
    pick = origs or [s for s in undriven if not cmds.getAttr(s + ".intermediateObject")]
    if len(pick) != 1:
        return None
    sel = om.MSelectionList()
    sel.add(pick[0])
    return [tuple(p)[:3] for p in om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kWorld)]


def write_obj(path, title, points, counts, connects):
    """Same convention as tools/maya_export.py: scene coordinates, Maya vertex order and polygons."""
    with open(path, "w", newline="\n") as f:
        f.write("# %s, scene coordinates, Maya vertex order\n" % title)
        for p in points:
            f.write("v %.9f %.9f %.9f\n" % p)
        at = 0
        for n in counts:
            f.write("f " + " ".join(str(i + 1) for i in connects[at:at + n]) + "\n")
            at += n


def export_ziva_meshes(folder, path, geos=None, first=0):
    """Item 7. Returns (meshes written, notes). Reads at frame `first`, so bones are at rest."""
    geos = ls_type("zGeo") if geos is None else geos
    cmds.currentTime(first, update=False)
    os.makedirs(folder, exist_ok=True)
    entries, notes = {}, []
    for geo in geos:
        try:
            points, counts, connects, data_matrix = mesh_from_plug(geo, GEO_MESH)
            def plug_of(attr):
                return geo + "." + attr if cmds.attributeQuery(attr, node=geo, exists=True) else None

            matrix_plug, out_plug = plug_of(GEO_MATRIX), plug_of(GEO_OUT)
            input_matrix = cmds.getAttr(matrix_plug) if matrix_plug else None
            matrix, rule = placing_matrix(data_matrix, input_matrix)
            world = apply_matrix(points, matrix)
            mesh_source = source_node(geo + "." + GEO_MESH)
            matrix_source = source_node(matrix_plug) if matrix_plug else None
            mesh = mesh_source or matrix_source
            targets = cmds.listConnections(out_plug, source=False, destination=True) or [] if out_plug else []
            bodies = [n for n in targets if cmds.nodeType(n) in BODY_TYPES]
            body = bodies[0] if bodies else None
            obj = file_name(geo) + ".obj"
            write_obj(os.path.join(folder, obj), "%s (%s) mesh kept by Ziva" % (geo, body), world, counts, connects)
            rest = rest_points(mesh)
            off = largest_move(world, rest) if rest and len(rest) == len(world) else None
            note = mesh_mismatch(geo, mesh, off)
            if note:
                notes.append(note)
            entries[geo] = {
                "file": obj, "body": body, "body_type": cmds.nodeType(body) if body else None,
                "scene_mesh": mesh, "mesh_copy_stored": mesh_source is None,
                "matrix_connected": matrix_source is not None,
                "vertices": len(world), "faces": len(counts), "placed_by": rule, "matrix": matrix,
                "bbox_min": [min(p[i] for p in world) for i in range(3)],
                "bbox_max": [max(p[i] for p in world) for i in range(3)],
                "off_from_scene_mesh": off,
            }
        except Exception as exc:
            notes.append("IMPORTANT: %s mesh not exported (%s): tell the developers (docs/12 item 7)" % (geo, exc))
    with open(path, "w") as f:
        json.dump({"frame": first, "geos": entries}, f, indent=1)
    return len(entries), notes


def size(path):
    return os.path.getsize(path) if os.path.isfile(path) else 0


def run(settings=SETTINGS):
    started = time.time()
    # AbcExport resolves a relative path against Maya's project folder, so make it absolute.
    out, motion = os.path.abspath(settings["out"]), settings["motion"]
    try:
        os.makedirs(out, exist_ok=True)
    except OSError:
        out = tempfile.mkdtemp(prefix="asrp_export_")
        print("Cannot write to %s, using %s" % (settings["out"], out))
    paths = {
        "attributes": os.path.join(out, "ziva_attributes.json"),
        "maps": os.path.join(out, "ziva_maps.json"),
        "zbuilder": os.path.join(out, "ziva_setup.zBuilder"),
        "meshes": os.path.join(out, "ziva_meshes.json"),
        "final": os.path.join(out, "ziva_%s_final.abc" % motion),
        "physics": os.path.join(out, "ziva_%s_physics.abc" % motion),
        "motion": os.path.join(out, "motion_%s.json" % motion),
    }
    report = {"motion": motion, "require_simulation": settings["require_simulation"], "stats": {}}
    problems, notes, temporary, sampler = [], [], None, None
    try:
        report["scene"] = cmds.file(query=True, sceneName=True)
        report["maya"] = cmds.about(version=True)
        ziva_loaded = cmds.pluginInfo("ziva", query=True, loaded=True)
        report["ziva"] = cmds.pluginInfo("ziva", query=True, version=True) if ziva_loaded else None
        first = int(cmds.playbackOptions(query=True, minTime=True) if settings["first"] is None else settings["first"])
        last = int(cmds.playbackOptions(query=True, maxTime=True) if settings["last"] is None else settings["last"])
        report["frames"] = [first, last]

        found, notes = preflight(settings, first, last)
        problems += found
        if not problems:
            print("Preflight passed. Solving frames %d to %d..." % (first, last))
            report["ziva_nodes"] = dump_ziva_attributes(paths["attributes"])
            # Items 2 and 7 without a solve. Trouble here is a note: it must not cost the solve.
            try:
                report["ziva_maps"] = dump_ziva_maps(paths["maps"])
            except Exception as exc:
                report["ziva_maps"] = 0
                notes.append("IMPORTANT: weight maps not exported (%s): tell the developers (docs/12 item 2)" % exc)
            try:
                report["ziva_meshes"], more = export_ziva_meshes(os.path.join(out, "ziva_meshes"),
                                                                 paths["meshes"], first=first)
                notes += more
            except Exception as exc:
                report["ziva_meshes"] = 0
                notes.append("IMPORTANT: meshes not exported (%s): tell the developers (docs/12 item 7)" % exc)
            if settings["require_simulation"]:
                if report["ziva_nodes"] == 0:
                    problems.append("no Ziva nodes found")
                for key, item in (("ziva_maps", 2), ("ziva_meshes", 7)):
                    if report[key] == 0:
                        notes.append("IMPORTANT: %s is 0: check docs/12 item %d" % (key, item))
                error = dump_zbuilder(paths["zbuilder"])
                if error:  # the attribute dump holds the same values, so this needs no second solve
                    notes.append(error + ". Do the zBuilder step by hand (docs/12)")

            temporary = make_physics_mesh()
            sampler = Sampler(LIPS, temporary, first, last)
            export_alembic([(LIPS, paths["final"]), (temporary, paths["physics"])], first, last, sampler)
            with open(paths["motion"], "w") as f:
                json.dump({"first": first, "last": last, "joints": JOINTS, "frames": sampler.frames}, f)

            problems += check_motion(sampler.stats)
            if settings["require_simulation"]:
                found, more = check_simulation(sampler.stats)
                problems += found
                notes += more
            for key in ("final", "physics", "motion"):
                if size(paths[key]) == 0:
                    problems.append("missing or empty: %s" % paths[key])
    except Exception:
        problems.append("stopped with an error:\n" + traceback.format_exc())
    finally:
        if temporary and cmds.objExists(temporary):
            cmds.delete(temporary)

    problems, waived = split_accepted(problems, settings.get("accepted", []))
    notes += waived
    report["stats"] = sampler.stats if sampler else {}
    report["files"] = {os.path.basename(p): size(p) for p in paths.values()}
    report["minutes"] = round((time.time() - started) / 60, 1)
    report["notes"], report["problems"] = notes, problems
    with open(os.path.join(out, "session_report.json"), "w") as f:
        json.dump(report, f, indent=1)

    print(json.dumps(report, indent=1))
    print("ZIVA SESSION " + ("FAILED: see problems above" if problems else "PASSED"))
    return report


if __name__ == "__main__":
    run()
