"""What only a machine with Ziva can give us: run once in Maya's Script Editor (Python tab).

Migration tool, not product code (docs ADR-18). Steps are in docs/12-lab-export-checklist.md.
Before running: open the scene the researchers really use, load one motion, edit SETTINGS below.

Writes into OUT:
    ziva_attributes.json       every attribute of every Ziva node, defaults included  (item 2)
    ziva_setup.zBuilder        the same setup in Ziva's own format                    (item 2)
    ziva_<motion>_final.abc    lip shape per frame, landmarks on                      (item 4a)
    ziva_<motion>_physics.abc  lip shape per frame, before the landmark layer         (item 4b)
    motion_<motion>.json       world matrix per frame of jaw01 and the 300 landmarks  (item 5)
    session_report.json        versions, frame range, measurements, and every check

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


def dump_ziva_attributes(path):
    """Item 2. Reads every attribute, so defaults are included; the .mb only stores changed ones."""
    dump = {}
    for node_type in ZIVA_TYPES:
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


def size(path):
    return os.path.getsize(path) if os.path.isfile(path) else 0


def run(settings=SETTINGS):
    started = time.time()
    out, motion = settings["out"], settings["motion"]
    try:
        os.makedirs(out, exist_ok=True)
    except OSError:
        out = tempfile.mkdtemp(prefix="asrp_export_")
        print("Cannot write to %s, using %s" % (settings["out"], out))
    paths = {
        "attributes": os.path.join(out, "ziva_attributes.json"),
        "zbuilder": os.path.join(out, "ziva_setup.zBuilder"),
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
            if settings["require_simulation"]:
                if report["ziva_nodes"] == 0:
                    problems.append("no Ziva nodes found")
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
