"""Portable Ziva field capture (T-19). Maya 2022+ in Python 3 mode, no pip installation.

Launch show_ui() from Maya's Python Script Editor; see docs/12-lab-export-checklist.md.
Stages: preflight, static, pilot, export, probe. Researcher loads each motion with the lab's
own tools. Every attempt gets a unique directory; no scene is opened, saved or overwritten.
All body caches and lip physics/final caches use one AbcExport traversal. Every cache also
has world-space float32 samples and topology; direct Alembic readback checks actual sample
times and every vertex without reevaluating the live scene. Missing data remains INCOMPLETE.

Receiver commands (Maya's bundled mayapy, without initializing Maya):
    mayapy ziva_machine_export.py --check <capture-directory>
    mayapy ziva_machine_export.py --collection <export-root>

Unknown Ziva versions/coordinates remain field risks (A-28): a plain-Maya rehearsal does not
prove Ziva behavior. Never execute the copied pickle. Never waive file/coverage errors.
"""

import array
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
import uuid

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
    "stage": "preflight",  # preflight | static | pilot | export | probe
    "kind": "expression",  # expression | head_translation
    "namespace": "",  # e.g. character: ; leave empty for the lab's unreferenced scene
    "pilot_last": 30,
    "budget_minutes": 60,
    "estimated_seconds_per_frame": None,  # copy the pilot report's value
    "motion_source": "",  # original .pkl, copied as bytes only; NEVER executed
    "researcher": "",  # operator/researcher who checked the loaded motion
    "motion_notes": "",  # how this motion was loaded; required for a full export
    "cache_checked": False,  # researcher cleared/disabled caches, not a general waiver
    "nodes": {},  # optional exact names: {"lips": "...", "skin": "...", "jaw": "..."}
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


def distance(a, b):
    # Maya 2022's Python 3.7 predates math.dist.
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


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
    if not a or len(a) != len(b):
        raise ValueError("empty mesh or changed vertex count")
    if not all(math.isfinite(c) for points in (a, b) for p in points for c in p):
        raise ValueError("non-finite mesh coordinates")
    return max(distance(p, q) for p, q in zip(a, b))


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


def check_motion(stats, kind="expression"):
    """Did the motion really play? True on any machine, with or without Ziva."""
    problems = []
    if stats["frames_sampled"] != stats["frames_expected"]:
        problems.append("sampled %d frames, expected %d" % (stats["frames_sampled"], stats["frames_expected"]))
    if kind == "head_translation":
        if stats.get("bone_translation", 0) < MIN_MOVEMENT:
            problems.append("no bone translation: load the head-translation motion")
        return problems
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
    # Legacy helper only. Export completion never waives structural/data failures.
    waived = [p for p in problems if "zCache" in p and "zCache" in accepted]
    return [p for p in problems if p not in waived], ["accepted by a person: " + p for p in waived]


def resolve_name(name, namespace=""):
    target = namespace.rstrip(":") + ":" + name if namespace else name
    found = cmds.ls(target, long=True) or []
    if len(found) != 1:
        raise ValueError("expected exactly one %s, found %d; set namespace explicitly" % (target, len(found)))
    return found[0]


def scene_names(settings):
    ns = settings.get("namespace", "")
    override = settings.get("nodes", {})
    names = {key: resolve_name(override[key]) if key in override else resolve_name(default, ns)
             for key, default in (("lips", LIPS), ("skin", LANDMARK_SKIN), ("jaw", JAW))}
    if names["skin"] not in (cmds.listHistory(names["lips"]) or []):
        raise ValueError("selected skinCluster is not in the selected lips' history")
    influences = cmds.skinCluster(names["skin"], query=True, influence=True) or []
    if len(influences) != 300:
        raise ValueError("expected 300 lip skin influences, got %d" % len(influences))
    names["joints"] = [names["jaw"]] + [resolve_name(j) for j in influences]
    return names


def ziva_plugin():
    for plugin in cmds.pluginInfo(query=True, listPlugins=True) or []:
        if "ziva" in plugin.lower():
            return {"name": plugin, "version": cmds.pluginInfo(plugin, query=True, version=True)}
    return None


def bone_matrix_plugs(settings):
    """Each Ziva bone's input matrix plug. The lab's head shake keys the bone MESH transforms
    (docs/03 section 13), so the bones can travel while the jaw01 joint stays where it is."""
    plugs = dict(settings.get("_rehearsal_bones") or {})
    for bone in ls_type("zBone"):
        geos = cmds.listConnections(bone + ".iGo", source=True, destination=False, type="zGeo") or []
        if len(set(geos)) != 1:
            raise ValueError("bone has no unique input zGeo: " + bone)
        plugs[bone] = geos[0] + "." + GEO_MATRIX
    return plugs


def bone_travel(plugs, first, last):
    """Largest translation of any bone input over the timeline. Reads the transform that feeds
    each plug, so it costs no Ziva solve."""
    worst = 0.0
    for plug in plugs.values():
        source = cmds.listConnections(plug, source=True, destination=False, plugs=True) or [plug]
        rest = cmds.getAttr(source[0], time=first)
        worst = max([worst] + [distance(rest[12:15], cmds.getAttr(source[0], time=f)[12:15])
                               for f in range(first, last + 1)])
    return worst


def preflight(settings, first, last):
    """Everything that can be found out before spending a solve. Returns (problems, notes)."""
    problems, notes = [], []
    if first != 0 or last <= GRAVITY_SETTLE_FRAMES:
        problems.append("frame range %d..%d must start at 0 and go past frame %d" % (
            first, last, GRAVITY_SETTLE_FRAMES))
    names = scene_names(settings)
    found = [names["lips"]]
    if len(found) != 1:
        problems.append("expected one %s, found %d" % (LIPS, len(found)))
    elif cmds.polyEvaluate(found[0], vertex=True) != LIP_VERTICES:
        problems.append("the lip mesh is not %d vertices" % LIP_VERTICES)
    if not cmds.objExists(names["skin"]):
        problems.append("%s not found" % LANDMARK_SKIN)
    elif not physics_source(names["skin"]):
        problems.append("nothing feeds %s, so the physics shape cannot be tapped" % LANDMARK_SKIN)
    missing = [j for j in names["joints"] if not cmds.objExists(j)]
    if missing:
        problems.append("%d joints not found, for example %s" % (len(missing), missing[0]))
    else:
        # getAttr at a time evaluates the jaw alone, so this costs no Ziva solve.
        jaw = names["jaw"]
        rest = cmds.getAttr(jaw + ".worldMatrix[0]", time=first)
        matrices = [cmds.getAttr(jaw + ".worldMatrix[0]", time=f) for f in range(first, last + 1)]
        turned = max(rotation_between(rest, m) for m in matrices)
        translated = max(distance(rest[12:15], m[12:15]) for m in matrices)
        if settings.get("kind", "expression") == "head_translation":
            try:
                translated = max(translated, bone_travel(bone_matrix_plugs(settings), first, last))
            except Exception as exc:
                problems.append("cannot read the bone inputs: %s" % exc)
            if translated < MIN_MOVEMENT:
                problems.append("neither the bones nor jaw01 translate on the timeline; load and key "
                                "the head motion")
        elif turned < MIN_JAW_DEGREES:
            problems.append("jaw01 does not turn on the timeline (%.3f degrees): is the motion "
                            "loaded and keyed? A script-driven motion cannot be exported" % turned)
    if settings["require_simulation"]:
        if not ziva_plugin():
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
        if caches and not settings.get("cache_checked"):
            problems.append("zCache nodes exist (%s): researcher must clear/disable caches and set cache_checked"
                            % ", ".join(caches))
    if abs(om.MTime(1, om.MTime.uiUnit()).asUnits(om.MTime.kSeconds) - 1 / 30.0) > 1e-8:
        problems.append("scene must use 30 fps; do not change it blindly: ask the researcher")
    for plugin in ("AbcExport", "AbcImport"):
        try:
            cmds.loadPlugin(plugin, quiet=True)
        except Exception as exc:
            problems.append("cannot load %s: %s" % (plugin, exc))
    return problems, notes


def physics_source(skin=LANDMARK_SKIN):
    """The plug that feeds skinCluster7: the lip shape before the landmark layer."""
    plugs = cmds.listConnections(skin + ".input[0].inputGeometry", source=True,
                                 destination=False, plugs=True)
    return plugs[0] if plugs else None


def make_physics_mesh(lips=LIPS, skin=LANDMARK_SKIN):
    """A temporary mesh showing the shape before landmarks. skinCluster7 itself stays untouched."""
    transform = cmds.createNode("transform", name="asrp_physics_only")
    shape = cmds.createNode("mesh", name="asrp_physics_onlyShape", parent=transform)
    cmds.connectAttr(physics_source(skin), shape + ".inMesh")
    drive_transform(transform, lips + ".worldMatrix[0]")
    return transform


def drive_transform(transform, matrix_plug):
    # AbcExport does not consistently serialize offsetParentMatrix. Drive ordinary TRS/shear.
    driver = cmds.createNode("decomposeMatrix", name="asrp_matrix")
    cmds.addAttr(transform, longName="asrp_matrix_driver", attributeType="message")
    cmds.connectAttr(driver + ".message", transform + ".asrp_matrix_driver")
    cmds.connectAttr(matrix_plug, driver + ".inputMatrix")
    for source, dest in (("outputTranslate", "translate"), ("outputRotate", "rotate"),
                         ("outputScale", "scale"), ("outputShear", "shear")):
        cmds.connectAttr(driver + "." + source, transform + "." + dest)


def delete_tap(transform):
    drivers = cmds.listConnections(transform + ".asrp_matrix_driver", source=True, destination=False) or []
    cmds.delete(transform, *drivers)


class Sampler:
    """Called by AbcExport on every frame: records the joints and measures the two shapes."""

    def __init__(self, final, physics, first, last, joints=None, bone_plugs=None):
        self.final, self.physics = self.fn(final), self.fn(physics)
        self.first, self.last = first, last
        self.joints = JOINTS if joints is None else joints
        self.jaw = self.joints[0]
        self.bone_plugs = bone_plugs or {}
        self.frames, self.started = [], time.time()
        self.physics0 = self.physics14 = self.joints0 = self.bones0 = self.previous = None
        self.rest = None
        self.rest = rest_points(final)
        self.stats = {
            "frames_expected": last - first + 1, "frames_sampled": 0, "jaw_degrees": 0.0,
            "landmark_travel": 0.0, "final_vs_physics": 0.0, "gravity_sag": 0.0, "motion_move": 0.0,
            "frozen_frames": 0, "rest_offset": 0.0, "largest_move": 0.0, "finite": True, "physics_track": [],
            "bone_translation": 0.0,
        }

    @staticmethod
    def fn(node):
        sel = om.MSelectionList()
        sel.add(node)
        return om.MFnMesh(sel.getDagPath(0).extendToShape())

    def __call__(self, frame):
        if frame != int(frame) or int(frame) != self.first + len(self.frames):
            raise ValueError("missing, duplicate, or out-of-order sample frame: %s" % frame)
        frame = int(frame)
        final = [tuple(p)[:3] for p in self.final.getPoints(om.MSpace.kWorld)]
        physics = [tuple(p)[:3] for p in self.physics.getPoints(om.MSpace.kWorld)]
        joints = {j: cmds.xform(j, query=True, matrix=True, worldSpace=True) for j in self.joints}
        bones = {b: cmds.getAttr(plug) for b, plug in self.bone_plugs.items()}
        self.frames.append(joints)
        s = self.stats
        s["frames_sampled"] += 1
        if self.physics0 is None:
            self.physics0, self.joints0, self.bones0 = physics, joints, bones
            s["final_vs_physics_first_frame"] = largest_move(final, physics)
            if self.rest:
                s["rest_offset"] = largest_move(physics, self.rest)
        s["finite"] = s["finite"] and all(math.isfinite(c) for p in physics for c in p)
        moved = largest_move(physics, self.physics0)
        s["physics_track"].append(moved)
        s["largest_move"] = max(s["largest_move"], moved)
        if frame > GRAVITY_SETTLE_FRAMES and self.previous:
            jaw_turned = (rotation_between(self.previous[1], joints[self.jaw]) > 1e-4 or
                          distance(self.previous[1][12:15], joints[self.jaw][12:15]) > 1e-6 or
                          any(distance(self.previous[2][b][12:15], m[12:15]) > 1e-6 for b, m in bones.items()))
            if jaw_turned and largest_move(physics, self.previous[0]) < 1e-6:
                s["frozen_frames"] += 1
        self.previous = (physics, joints[self.jaw], bones)
        if frame <= GRAVITY_SETTLE_FRAMES:
            s["gravity_sag"] = max(s["gravity_sag"], largest_move(physics, self.physics0))
        if frame == GRAVITY_SETTLE_FRAMES:
            self.physics14 = physics
        if frame > GRAVITY_SETTLE_FRAMES and self.physics14:
            s["motion_move"] = max(s["motion_move"], largest_move(physics, self.physics14))
        s["final_vs_physics"] = max(s["final_vs_physics"], largest_move(final, physics))
        s["jaw_degrees"] = max(s["jaw_degrees"], rotation_between(self.joints0[self.jaw], joints[self.jaw]))
        # The bones themselves, not only jaw01: a head shake keyed on the bone meshes leaves the joint still.
        s["bone_translation"] = max([s["bone_translation"], distance(self.joints0[self.jaw][12:15], joints[self.jaw][12:15])] +
                                    [distance(self.bones0[b][12:15], m[12:15]) for b, m in bones.items()])
        for j in self.joints[1:]:
            s["landmark_travel"] = max(s["landmark_travel"], distance(self.joints0[j][12:15], joints[j][12:15]))
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
        args.append('-frameRange %d %d -worldSpace -dataFormat ogawa%s -root "%s" -file "%s"' % (
            first, last, callback, cmds.ls(node, long=True)[0], path.replace("\\", "/")))
    try:
        cmds.AbcExport(jobArg=args, dontSkipUnwrittenFrames=True)
    finally:
        del __main__.asrp_sample


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
    if not maps:
        maps["0"] = {"default": default, "indices": [], "values": [], "implicit_default": True}
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
            try:
                maps = weight_maps(node)
            except Exception as exc:
                dump[node] = {"type": node_type, "error": str(exc), "connections": connections(node)}
                continue
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
            obj = stable_name(geo) + ".obj"
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


def stable_name(node):
    return file_name(node)[-70:] + "_" + hashlib.sha256(node.encode("utf-8")).hexdigest()[:12]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=1, allow_nan=False)
    os.replace(path + ".tmp", path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def topology_digest(counts, indices):
    return hashlib.sha256(json.dumps([list(counts), list(indices)], separators=(",", ":")).encode()).hexdigest()


def maya_indices(counts, alembic_indices):
    # Maya's AbcExport reverses EACH polygon's winding; vertex identities/order stay unchanged.
    indices, at, result = list(alembic_indices), 0, []
    for count in counts:
        result.extend(reversed(indices[at:at + count]))
        at += count
    return result


def expected_outputs():
    """Start with ALL simulated bodies, never with only the output plugs that happened to exist."""
    entries, problems = [], []
    for body in sorted(ls_type("zTissue") + ls_type("zCloth")):
        try:
            geos = cmds.listConnections(body + ".iGo", source=True, destination=False, type="zGeo") or []
            geos = sorted(set(geos))
            if len(geos) != 1:
                raise ValueError("expected one input zGeo, got %s" % geos)
            geo = geos[0]
            outputs = []
            for dest in cmds.listConnections(geo + ".oGo", source=False, destination=True, plugs=True) or []:
                node, attr = dest.split(".", 1)
                if node not in ls_type("zEmbedder"):
                    continue
                selected = om.MSelectionList()
                selected.add(dest)
                plug = selected.getPlug(0)
                if not plug.isElement:
                    raise ValueError("embedder input has no logical index: %s" % dest)
                outputs.append(node + ".og[%d]" % plug.logicalIndex())
            if len(outputs) != 1:
                raise ValueError("expected one embedder output, got %s" % outputs)
            points, counts, indices, data_matrix = mesh_from_plug(geo, GEO_MESH)
            if not points or not counts or not all(math.isfinite(c) for p in points for c in p):
                raise ValueError("empty/non-finite rest mesh")
            matrix = cmds.getAttr(geo + "." + GEO_MATRIX)
            placed, rule = placing_matrix(data_matrix, matrix)
            if rule != GEO_MATRIX:
                raise ValueError("unconfirmed soft-body output space (%s); explicit adapter required" % rule)
            entries.append({"id": stable_name(body), "body": body, "geo": geo,
                            "body_type": cmds.nodeType(body), "plug": outputs[0],
                            "matrix_plug": geo + "." + GEO_MATRIX,
                            "space": "object mesh, live zGeo.iNMx -> world",
                            "vertices": len(points), "topology": topology_digest(counts, indices),
                            "rest_matrix": placed})
        except Exception as exc:
            entries.append({"id": stable_name(body), "body": body, "error": str(exc), "traceback": traceback.format_exc()})
            problems.append("%s: %s" % (body, exc))
    if not entries:
        problems.append("no simulated tissues or cloth found")
    return entries, problems


def make_output_tap(entry, temporary):
    transform = cmds.createNode("transform", name="asrp_" + entry["id"])
    temporary.append(transform)
    shape = cmds.createNode("mesh", parent=transform)
    cmds.connectAttr(entry["plug"], shape + ".inMesh")
    drive_transform(transform, entry["matrix_plug"])
    fn = Sampler.fn(transform)
    counts, indices = fn.getVertices()
    if fn.numVertices != entry["vertices"] or topology_digest(counts, indices) != entry["topology"]:
        raise ValueError("%s output/rest topology mismatch" % entry["body"])
    return transform


class CaptureSampler:
    """One callback for every cache; binary samples are also a recoverable, open-format backup."""

    def __init__(self, sampler, streams, out, bone_plugs):
        self.sampler, self.streams, self.out = sampler, streams, out
        self.bone_plugs, self.bones, self.frames = bone_plugs, [], []
        self.handles, self.functions, self.errors = {}, {}, []
        try:
            for entry in streams:
                sid = entry["id"]
                fn = Sampler.fn(entry["node"])
                counts, indices = fn.getVertices()
                entry.update(vertices=fn.numVertices, topology=topology_digest(counts, indices), frames=[])
                points = [tuple(p)[:3] for p in fn.getPoints(om.MSpace.kWorld)]
                if not points:
                    raise ValueError("empty stream: " + sid)
                entry["rest_obj"] = sid + ".obj"
                write_obj(os.path.join(out, entry["rest_obj"]), sid, points, counts, indices)
                entry["samples"] = sid + ".points.f32"
                entry["alembic"] = sid + ".abc"
                self.handles[sid] = open(os.path.join(out, entry["samples"]), "wb")
                self.functions[sid] = fn
        except Exception:
            self.close()
            raise

    def __call__(self, frame):
        if self.errors:
            return  # Some Maya versions print callback exceptions and continue exporting.
        try:
            self.sampler(frame)
            self.frames.append(int(frame))
            self.bones.append({body: cmds.getAttr(plug) for body, plug in self.bone_plugs.items()})
            for entry in self.streams:
                fn = self.functions[entry["id"]]
                counts, indices = fn.getVertices()
                if fn.numVertices != entry["vertices"] or topology_digest(counts, indices) != entry["topology"]:
                    raise ValueError("topology changed: " + entry["id"])
                coords = array.array("f", (c for p in fn.getPoints(om.MSpace.kWorld) for c in tuple(p)[:3]))
                if not all(math.isfinite(c) for c in coords):
                    raise ValueError("non-finite coordinates: " + entry["id"])
                if sys.byteorder != "little":
                    coords.byteswap()
                coords.tofile(self.handles[entry["id"]])
                entry["frames"].append(int(frame))
        except Exception:
            self.errors.append(traceback.format_exc())

    def close(self):
        for handle in self.handles.values():
            handle.close()


def check_samples(entry, first, last, folder):
    frames = list(range(first, last + 1))
    if entry.get("frames") != frames or entry.get("vertices", 0) <= 0:
        raise ValueError("%s: missing/duplicate/out-of-order frames or empty mesh" % entry["id"])
    path = safe_child(folder, entry["samples"])
    expected = len(frames) * entry["vertices"] * 3 * 4
    if size(path) != expected:
        raise ValueError("%s: sample byte length %d != %d" % (entry["id"], size(path), expected))
    with open(path, "rb") as f:
        for _ in frames:
            values = array.array("f")
            values.fromfile(f, entry["vertices"] * 3)
            if sys.byteorder != "little":
                values.byteswap()
            if not all(math.isfinite(x) for x in values):
                raise ValueError("non-finite backup: " + entry["id"])


def check_sample_times(schema, times, label, identity_transform=False):
    count = schema.getNumSamples()
    if count == 0 and identity_transform and schema.getValue().getNumOps() == 0:
        return
    # Alembic can legitimately store a static shape once, while its parent transform animates.
    if count == 1 and schema.isConstant():
        return
    if count != len(times):
        raise ValueError("%s: actual sample count %d != %d" % (label, count, len(times)))
    sampling = schema.getTimeSampling()
    if any(abs(sampling.getSampleTime(i) - t) > 1e-8 for i, t in enumerate(times)):
        raise ValueError(label + ": actual Alembic sample times differ")


def check_alembic(entry, folder, times):
    """Read the archive API directly: no live Maya time change, interpolation cannot hide missing frames."""
    from alembic import Abc, AbcGeom

    archive = Abc.IArchive(safe_child(folder, entry["alembic"]))
    meshes = []

    def walk(obj, parents):
        if AbcGeom.IXform.matches(obj.getHeader()):
            parents = parents + [AbcGeom.IXform(obj, Abc.WrapExistingFlag.kWrapExisting).getSchema()]
        if AbcGeom.IPolyMesh.matches(obj.getHeader()):
            meshes.append((AbcGeom.IPolyMesh(obj, Abc.WrapExistingFlag.kWrapExisting).getSchema(), parents))
        for i in range(obj.getNumChildren()):
            walk(obj.getChild(i), parents)

    walk(archive.getTop(), [])
    if len(meshes) != 1:
        raise ValueError("expected one mesh in " + entry["alembic"])
    schema, parents = meshes[0]
    check_sample_times(schema, times, entry["id"])
    for obj in parents:
        check_sample_times(obj, times, entry["id"], identity_transform=True)
    worst = 0.0
    with open(safe_child(folder, entry["samples"]), "rb") as f:
        for t in times:
            selector = Abc.ISampleSelector(float(t))
            sample = schema.getValue(selector)
            counts = sample.getFaceCounts()
            if topology_digest(counts, maya_indices(counts, sample.getFaceIndices())) != entry["topology"]:
                raise ValueError("Alembic topology changed: " + entry["id"])
            points = [tuple(p) for p in sample.getPositions()]
            for parent in reversed(parents):
                matrix = parent.getValue(selector).getMatrix()
                points = apply_matrix(points, [matrix[i][j] for i in range(4) for j in range(4)])
            values = array.array("f")
            values.fromfile(f, entry["vertices"] * 3)
            if sys.byteorder != "little":
                values.byteswap()
            truth = list(zip(values[0::3], values[1::3], values[2::3]))
            worst = max(worst, largest_move(points, truth))
    if worst > MESH_MATCH:
        raise ValueError("%s: Alembic differs from captured vertices by %.6g scene units" % (entry["id"], worst))
    return worst


def safe_child(folder, name):
    base = os.path.realpath(folder)
    path = os.path.realpath(os.path.join(base, name))
    if os.path.commonpath([base, path]) != base or path == base:
        raise ValueError("file escapes capture directory: " + name)
    return path


def seal_capture(folder):
    files = {}
    for root, _, names in os.walk(folder):
        for name in names:
            if name in ("seal.json", "readback_report.json") or name.endswith(".tmp"):
                continue
            path = os.path.join(root, name)
            files[os.path.relpath(path, folder).replace("\\", "/")] = {"bytes": size(path), "sha256": sha256(path)}
    write_json(os.path.join(folder, "seal.json"), {"files": files})


def check_seal(folder):
    """Integrity only: every sealed file is present and unchanged. Returns the seal's file table."""
    seal = read_json(os.path.join(folder, "seal.json"))["files"]
    if not seal or "session_report.json" not in seal:
        raise ValueError("missing manifest seal")
    for name, meta in seal.items():
        path = safe_child(folder, name)
        if size(path) <= 0 or size(path) != meta["bytes"] or sha256(path) != meta["sha256"]:
            raise ValueError("missing, empty, or changed file: " + name)
    return seal


def check_capture(folder, read_alembic=True):
    """Portable receiver check. A structural check alone is never a full Alembic readback."""
    result = {"problems": [], "alembic_verified": False, "streams_checked": 0, "max_error": 0.0}
    try:
        seal = check_seal(folder)
        report = read_json(os.path.join(folder, "session_report.json"))
        result["problems"].extend(report.get("problems", []))
        streams = report.get("streams", [])
        if not streams:
            raise ValueError("no motion streams (preflight/static/probe is not a full capture)")
        first, last = report["frames"]
        motion = read_json(os.path.join(folder, "motion.json"))
        if motion["frame_ids"] != list(range(first, last + 1)) or len(motion["frames"]) != last - first + 1:
            raise ValueError("motion frames missing or duplicated")
        if len(motion.get("bones", [])) != len(motion["frames"]):
            raise ValueError("bone frames missing")
        covered = {s.get("body") for s in streams if s.get("body")}
        expected = {e["body"] for e in report["expected_outputs"]}
        if report["require_simulation"] and (not expected or covered != expected):
            raise ValueError("simulated-body coverage is incomplete")
        times = [f / report["fps"] for f in range(first, last + 1)]
        for entry in streams:
            for field in ("samples", "alembic", "rest_obj"):
                if entry[field] not in seal:
                    raise ValueError("unsealed stream file: " + entry[field])
            check_samples(entry, first, last, folder)
            if read_alembic:
                result["max_error"] = max(result["max_error"], check_alembic(entry, folder, times))
            result["streams_checked"] += 1
        result["alembic_verified"] = bool(read_alembic and result["streams_checked"])
    except Exception as exc:
        result["problems"].append(str(exc))
    result["ok"] = not result["problems"] and result["alembic_verified"]
    write_json(os.path.join(folder, "readback_report.json"), result)
    return result


def static_export(out, report):
    """Collect independent items even when another fails; report every incomplete item."""
    operations = (
        ("attributes", lambda: dump_ziva_attributes(os.path.join(out, "ziva_attributes.json"))),
        ("maps", lambda: dump_ziva_maps(os.path.join(out, "ziva_maps.json"))),
        ("meshes", lambda: export_ziva_meshes(os.path.join(out, "ziva_meshes"), os.path.join(out, "ziva_meshes.json"))),
        ("zbuilder", lambda: dump_zbuilder(os.path.join(out, "ziva_setup.zBuilder"))),
    )
    for name, operation in operations:
        try:
            value = operation()
            if name == "meshes":
                count, notes = value
                report["notes"].extend(notes)
                if notes or count != len(ls_type("zGeo")) or count == 0:
                    raise ValueError("static mesh coverage/placement unresolved; see notes")
            elif name == "zbuilder":
                if value or size(os.path.join(out, "ziva_setup.zBuilder")) == 0:
                    raise ValueError(value or "empty zBuilder")
            elif value <= 0:
                raise ValueError("empty " + name)
            if name == "maps":
                maps = read_json(os.path.join(out, "ziva_maps.json"))
                bad = [n for n, v in maps.items() if v.get("error") or
                       (v["type"] == "zAttachment" and not v.get("weight_maps"))]
                if bad:
                    raise ValueError("unreadable attachment defaults/maps: " + ", ".join(bad))
            report["static"][name] = "complete"
        except Exception as exc:
            report["static"][name] = "incomplete: " + str(exc)
            report["problems"].append(name + ": " + str(exc))


def probe_same_frame(names, result=None):
    """A diagnostic, never part of a reference capture. Caller must reload scene after it."""
    plug = names["jaw"] + ".rotateZ"
    if cmds.getAttr(plug, lock=True):
        raise ValueError("jaw rotateZ is locked; diagnostic requires researcher assistance")
    source = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    temporary = None
    value = None
    result = {} if result is None else result
    result.update(frame=14, channel=plug, source=source, reload_required=True)
    try:
        for frame in range(15):
            cmds.currentTime(frame, update=True)
        temporary = make_physics_mesh(names["lips"], names["skin"])
        fn = Sampler.fn(temporary)
        points = lambda: [tuple(p)[:3] for p in fn.getPoints(om.MSpace.kWorld)]
        before, repeat = points(), points()
        result["baseline_repeat_error"] = largest_move(before, repeat)
        value = cmds.getAttr(plug)
        if source:
            cmds.disconnectAttr(source[0], plug)
        cmds.setAttr(plug, value + 2.0)
        started = time.time()
        moved = points()
        result.update(physics_change=largest_move(before, moved), read_seconds=time.time() - started,
                      time_after=cmds.currentTime(query=True))
    finally:
        try:
            if value is not None:
                try:
                    if not source or not cmds.isConnected(source[0], plug):
                        cmds.setAttr(plug, value)
                finally:
                    if source and not cmds.isConnected(source[0], plug):
                        cmds.connectAttr(source[0], plug)
                result["channel_restored"] = abs(cmds.getAttr(plug) - value) < 1e-8
                result["source_restored"] = not source or cmds.isConnected(source[0], plug)
                result["restored_physics_difference"] = largest_move(before, points())
        finally:
            if temporary and cmds.objExists(temporary):
                delete_tap(temporary)
    return result


def validate_settings(settings):
    if settings["stage"] not in ("preflight", "static", "pilot", "export", "probe"):
        raise ValueError("unknown stage")
    if settings["kind"] not in ("expression", "head_translation"):
        raise ValueError("kind must be expression or head_translation")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", settings["motion"]):
        raise ValueError("motion name must use ASCII letters, digits, _ or -")
    out = os.path.abspath(settings["out"])
    if not out.isascii() or '"' in out:
        raise ValueError("export path must be ASCII with no quote characters")
    if settings.get("accepted"):
        raise ValueError("accepted no longer bypasses failures; inspect the problem, use cache_checked only for caches")
    if settings["stage"] == "export" and settings["require_simulation"]:
        if not settings.get("researcher") or not settings.get("motion_notes"):
            raise ValueError("full export requires researcher and motion_notes")
        if settings["kind"] == "expression" and not os.path.isfile(settings.get("motion_source", "")):
            raise ValueError("select the original expression motion file (copied, never loaded)")
    return out


def run(settings=None):
    config = dict(SETTINGS)
    config.update(settings or {})
    out_base = validate_settings(config)
    os.makedirs(out_base, exist_ok=True)
    out = os.path.join(out_base, "%s_%s_%s_%s" % (config["motion"], config["stage"],
                       time.strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8]))
    os.makedirs(out)  # unique directory; no overwrite and no silent fallback to a hidden temp folder
    started = time.time()
    report = {"format": "asrp-ziva-capture/2", "out": out, "motion": config["motion"],
              "kind": config["kind"], "stage": config["stage"], "require_simulation": config["require_simulation"],
              "status": "running", "problems": [], "notes": [], "static": {}, "stats": {}, "streams": [],
              "expected_outputs": [], "researcher": config["researcher"], "motion_notes": config["motion_notes"],
              "sample_format": "little-endian float32 xyz, vertex-major then frame-major; scene units/world space"}
    temporary, capture, sampler = [], None, None
    old_selection = cmds.ls(selection=True, long=True) or []
    manifest = os.path.join(out, "session_report.json")
    write_json(manifest, report)
    try:
        if sys.version_info < (3, 7) or int(cmds.about(apiVersion=True)) < 20220000:
            raise ValueError("requires Maya 2022+ in Python 3 mode; no supported runtime detected")
        names = None if config["stage"] == "static" else scene_names(config)
        scene_path = cmds.file(query=True, sceneName=True)
        report.update(scene=scene_path, scene_modified=cmds.file(query=True, modified=True),
                      maya=cmds.about(version=True), python=sys.version, ziva=ziva_plugin(),
                      scene_sha256=sha256(scene_path) if os.path.isfile(scene_path) else None,
                      fps=1 / om.MTime(1, om.MTime.uiUnit()).asUnits(om.MTime.kSeconds),
                      time_unit=cmds.currentUnit(query=True, time=True),
                      linear_unit=cmds.currentUnit(query=True, linear=True),
                      matrix_convention="Maya row-vector, world matrices, translation at indices 12:15")
        script = globals().get("__file__")
        if script and os.path.isfile(script):
            shutil.copyfile(script, os.path.join(out, "export_script.py"))
        first = config["first"] if config["first"] is not None else cmds.playbackOptions(query=True, minTime=True)
        last = config["last"] if config["last"] is not None else cmds.playbackOptions(query=True, maxTime=True)
        if int(first) != first or int(last) != last:
            raise ValueError("frame boundaries must be integers")
        first, last = int(first), int(last)
        report["requested_frames"] = [first, last]
        if config["stage"] == "pilot":
            last = min(last, int(config["pilot_last"]))
        report["frames"] = [first, last]
        if config["require_simulation"]:
            entries, issues = expected_outputs()
        else:
            entries, issues = config.get("_rehearsal_outputs", []), []
        report["expected_outputs"] = entries
        report["problems"].extend(issues)
        if config["stage"] == "static":
            static_export(out, report)
        elif config["stage"] == "probe":
            if config["require_simulation"] and not ziva_plugin():
                raise ValueError("Ziva plug-in not loaded")
            report["probe"] = {}
            probe_same_frame(names, report["probe"])
        else:
            found, notes = preflight(config, first, last)
            report["problems"].extend(found)
            report["notes"].extend(notes)
            try:
                from alembic import Abc, AbcGeom  # noqa: F401
                report["alembic_reader"] = True
            except ImportError:
                report["alembic_reader"] = False
                report["problems"].append("Maya Alembic Python reader unavailable; use a Maya installation with it for verified capture")
            estimate = config.get("estimated_seconds_per_frame")
            report["estimated_minutes"] = (last - first + 1) * float(estimate) / 60 if estimate else None
            if report["estimated_minutes"] is not None:
                print("Estimated solve: %.1f minutes; budget: %.1f" % (report["estimated_minutes"], config["budget_minutes"]))
                if report["estimated_minutes"] > float(config["budget_minutes"]):
                    raise ValueError("estimated run exceeds budget: export fewer motions now or increase budget explicitly")
            if config["stage"] in ("pilot", "export") and not report["problems"]:
                if config["require_simulation"]:
                    static_export(out, report)  # even a failed static item must not destroy useful dynamic capture
                if config.get("motion_source"):
                    target = "motion_source" + os.path.splitext(config["motion_source"])[1]
                    shutil.copyfile(config["motion_source"], os.path.join(out, target))
                    report["motion_source"] = target
                cmds.currentTime(first, update=True)
                physics = make_physics_mesh(names["lips"], names["skin"])
                temporary.append(physics)
                streams = [{"id": "lips_final", "node": names["lips"], "role": "final"},
                           {"id": "lips_physics", "node": physics, "role": "physics"}]
                for entry in entries:
                    streams.append(dict(entry, node=make_output_tap(entry, temporary), role="body_physics"))
                bone_plugs = bone_matrix_plugs(config)
                # Include other tissue landmarks as well, while keeping jaw first for motion checks.
                joints = names["joints"] + sorted(set(cmds.ls(type="joint", long=True) or []) - set(names["joints"]))
                sampler = Sampler(names["lips"], physics, first, last, joints, bone_plugs)
                capture = CaptureSampler(sampler, streams, out, bone_plugs)
                report["streams"] = streams
                export_alembic([(s["node"], os.path.join(out, s["alembic"])) for s in streams], first, last, capture)
                capture.close()
                report["problems"].extend(capture.errors)
                report["problems"].extend(check_motion(sampler.stats, config["kind"]))
                if config["require_simulation"]:
                    found, more = check_simulation(sampler.stats)
                    report["problems"].extend(found)
                    report["notes"].extend(more)
                report["notes"].append("motion checks measure output activity, not proof that caches are disabled or Ziva physically solved")
                write_json(os.path.join(out, "motion.json"), {"first": first, "last": last, "fps": report["fps"],
                           "frame_ids": capture.frames, "joints": joints, "frames": sampler.frames,
                           "bones": capture.bones, "bone_matrix_plugs": bone_plugs,
                           "matrix_convention": report["matrix_convention"]})
    except Exception:
        report["problems"].append(traceback.format_exc())
    finally:
        if capture:
            capture.close()
        for node in reversed(temporary):
            try:
                if cmds.objExists(node):
                    delete_tap(node)
            except Exception as exc:
                report["problems"].append("cleanup %s: %s" % (node, exc))
        cmds.select([s for s in old_selection if cmds.objExists(s)], replace=True) if old_selection else cmds.select(clear=True)
    report["stats"] = sampler.stats if sampler else {}
    report["seconds"] = time.time() - started
    report["seconds_per_frame"] = report["seconds"] / max(1, report["stats"].get("frames_sampled", 0))
    report["status"] = "incomplete" if report["problems"] else config["stage"] + "_captured"
    for entry in report["streams"]:
        entry.pop("node", None)
    write_json(manifest, report)
    seal_capture(out)
    if report["streams"]:
        report["readback"] = check_capture(out)
    print("ASRP %s: %s\nOUTPUT: %s" % (config["stage"].upper(), report["status"], out))
    for problem in report["problems"]:
        print("INCOMPLETE: " + problem)
    if report.get("readback"):
        print("ALEMBIC READBACK: " + json.dumps(report["readback"]))
    return report


def check_collection(folder):
    """An explicit list of accepted full exports; partial attempts and pilots never count."""
    receipt = {"complete": False, "accepted": [], "incomplete_attempts": [], "problems": []}
    baselines, kinds, probe_ok = [], set(), False
    for name in sorted(os.listdir(folder)):
        capture_dir = os.path.join(folder, name)
        path = os.path.join(capture_dir, "session_report.json")
        if not os.path.isfile(path):
            continue
        try:
            r = read_json(path)
            if r.get("stage") == "probe":
                check_seal(capture_dir)  # a copied or edited diagnostic must not count; raises if so
                probe = r.get("probe", {})
                probe_ok |= (r.get("require_simulation") and not r.get("problems") and
                             probe.get("source_restored") and probe.get("channel_restored") and
                             probe.get("time_after") == 14 and probe.get("baseline_repeat_error", 1) < 1e-6)
            if r.get("stage") != "export":
                continue
            checked = check_capture(capture_dir)
            issues = list(checked["problems"])
            if not r.get("require_simulation") or not r.get("ziva"):
                issues.append("rehearsal is not Ziva data")
            if set(r.get("static", {})) != {"attributes", "maps", "meshes", "zbuilder"} or any(
                    v != "complete" for v in r.get("static", {}).values()):
                issues.append("static data incomplete")
            if not r.get("researcher") or not r.get("motion_notes"):
                issues.append("researcher/motion provenance missing")
            if r.get("kind") == "expression" and not r.get("motion_source"):
                issues.append("original motion file missing")
            if r.get("frames") != r.get("requested_frames"):
                issues.append("partial frame range")
            if issues:
                receipt["incomplete_attempts"].append({"folder": name, "problems": issues})
            else:
                receipt["accepted"].append(name)
                kinds.add(r["kind"])
                baselines.append({e["body"]: e["topology"] for e in r["expected_outputs"]})
        except Exception as exc:
            receipt["incomplete_attempts"].append({"folder": name, "problems": [str(exc)]})
    if not {"expression", "head_translation"}.issubset(kinds):
        receipt["problems"].append("need verified full expression AND head_translation captures")
    if baselines and any(b != baselines[0] for b in baselines[1:]):
        receipt["problems"].append("motion captures have different body inventory/topology; reconcile before receipt")
    if not probe_ok:
        receipt["problems"].append("same-frame diagnostic with verified channel restoration missing")
    receipt["complete"] = bool(receipt["accepted"]) and not receipt["problems"]
    write_json(os.path.join(folder, "collection_report.json"), receipt)
    print("COLLECTION " + ("COMPLETE" if receipt["complete"] else "INCOMPLETE"))
    print(json.dumps(receipt, indent=1))
    return receipt


def show_ui():
    """Small native Maya control panel; loading/changing research motions remains the researcher's job."""
    window = "asrp_ziva_capture"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="ASRP Ziva capture", widthHeight=(650, 650))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=7)
    cmds.text(label="Load/key each motion with the lab's own tools. This script never opens or saves scenes.", align="left")
    controls = {}
    for key, label in (("out", "Export root (ASCII)"), ("motion", "Motion name (ASCII)"),
                       ("namespace", "Namespace (optional)"), ("researcher", "Researcher/operator"),
                       ("motion_notes", "How this motion was loaded"), ("motion_source", "Original motion file (.pkl)")):
        controls[key] = cmds.textFieldGrp(label=label, text=str(SETTINGS[key]), columnWidth2=(200, 420))
    controls["kind"] = cmds.optionMenuGrp(label="Motion kind")
    for kind in ("expression", "head_translation"):
        cmds.menuItem(label=kind)
    controls["last"] = cmds.intFieldGrp(label="Full last frame (-1 = timeline)", value1=-1)
    controls["pilot_last"] = cmds.intFieldGrp(label="Pilot last frame", value1=30)
    controls["budget_minutes"] = cmds.floatFieldGrp(label="Budget for this motion (min)", value1=60)
    controls["cache_checked"] = cmds.checkBoxGrp(label="Researcher cleared/disabled Ziva cache", value1=False)
    status = cmds.scrollField(editable=False, wordWrap=True, height=150, text="Start with Preflight. Outputs never overwrite earlier attempts.")
    pilot = {"rate": None, "signature": None}

    def settings():
        cfg = dict(SETTINGS)
        for key in ("out", "motion", "namespace", "researcher", "motion_notes", "motion_source"):
            cfg[key] = cmds.textFieldGrp(controls[key], query=True, text=True).strip()
        cfg["kind"] = cmds.optionMenuGrp(controls["kind"], query=True, value=True)
        cfg["first"] = 0
        last = cmds.intFieldGrp(controls["last"], query=True, value1=True)
        cfg["last"] = None if last == -1 else last
        cfg["pilot_last"] = cmds.intFieldGrp(controls["pilot_last"], query=True, value1=True)
        cfg["budget_minutes"] = cmds.floatFieldGrp(controls["budget_minutes"], query=True, value1=True)
        cfg["cache_checked"] = cmds.checkBoxGrp(controls["cache_checked"], query=True, value1=True)
        signature = (cmds.file(query=True, sceneName=True), cfg["motion"], cfg["kind"], cfg["namespace"])
        cfg["estimated_seconds_per_frame"] = pilot["rate"] if signature == pilot["signature"] else None
        return cfg, signature

    def action(stage):
        try:
            cfg, signature = settings()
            cfg["stage"] = stage
            if stage == "probe":
                answer = cmds.confirmDialog(title="Diagnostic changes jaw temporarily", message=
                    "First finish reference exports. Reopen a clean scene now. After this diagnostic, manually reopen it again. Continue?",
                    button=["Cancel", "Run diagnostic"], defaultButton="Cancel", cancelButton="Cancel", dismissString="Cancel")
                if answer != "Run diagnostic":
                    return
            if stage == "export" and cfg["estimated_seconds_per_frame"] is None:
                raise ValueError("Run a pilot for this motion first; verify its output, then export.")
            if stage == "collection":
                result = check_collection(cfg["out"])
            else:
                result = run(cfg)
                if stage == "pilot" and not result["problems"] and result.get("readback", {}).get("ok"):
                    pilot.update(rate=result["seconds_per_frame"], signature=signature)
                if stage == "probe":
                    pilot.update(rate=None, signature=None)
            text = json.dumps({k: result.get(k) for k in ("out", "status", "problems", "readback", "complete", "accepted")}, indent=1)
            cmds.scrollField(status, edit=True, text=text)
        except Exception:
            cmds.scrollField(status, edit=True, text=traceback.format_exc())
            traceback.print_exc()

    for label, stage in (("1  Preflight (no full solve)", "preflight"), ("2  Rescue static data", "static"),
                         ("3  Pilot current motion", "pilot"), ("4  Export full current motion", "export"),
                         ("5  Same-frame diagnostic (after captures)", "probe"), ("6  Check entire collection", "collection")):
        cmds.button(label=label, command=lambda _, stage=stage: action(stage))
    cmds.text(label="INCOMPLETE means keep the folder and fix the named item. Never treat a pilot as the full motion.", align="left")
    cmds.showWindow(window)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("--check", "--collection"):
        result = check_capture(sys.argv[2]) if sys.argv[1] == "--check" else check_collection(sys.argv[2])
        print(json.dumps(result, indent=1))
        sys.exit(0 if result.get("ok", result.get("complete")) else 1)
    elif cmds is not None:
        show_ui()
    else:
        sys.exit("Use Maya Python 3 to launch UI; mayapy ziva_machine_export.py --check <capture> or --collection <root>")
