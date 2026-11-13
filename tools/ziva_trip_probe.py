"""Small read-only helpers for the Ziva machine, to run before and beside tools/ziva_machine_export.py.

Paste the whole file into Maya's Script Editor (Python tab) and run it once; then call, one at a time:

    start_log("D:/asrp_export")        # Maya writes everything the Script Editor prints (Ziva's timing lines too) to a file
    probe("D:/asrp_export")            # what is this scene: versions, names, counts, solver values, landmark positions
    dump_keys("D:/asrp_export", "neutral_to_AA")   # after a motion is keyed: every keyed joint and bone, every frame
    head_shake_keys()                  # CHANGES THE SCENE (keys on the two bone meshes); never save the scene after it

probe and dump_keys do not step the timeline and do not change the scene. Nothing here opens, saves or
unpickles anything. Each part of probe is tried on its own, so one failure does not lose the rest.
"""
import json
import os
import sys
import time

try:
    import maya.cmds as cmds
except ImportError:  # the pure parts are tested without Maya
    cmds = None

LIPS = "middleres_OrbicularisOris"
BONES = ["middleres_skull", "middleres_Jaw"]
JAW = "jaw01"
LANDMARK_PREFIXES = ["oor_", "ooc_l_", "ooc_r_", "frontalis_"]
ZIVA_TYPES = ["zSolverTransform", "zSolver", "zTissue", "zBone", "zTet", "zMaterial", "zGeo", "zAttachment",
              "zEmbedder", "zFiber", "zCloth", "zCache", "zCacheTransform"]
SOLVER_TYPES = ["zSolverTransform", "zSolver"]
SUMMARY_TYPES = ["zMaterial", "zTissue", "zAttachment", "zTet", "zCloth", "zBone"]
SHAKE = {"start": 16, "loops": 3, "frames_per_loop": 10, "magnitude": 5.0}  # the lab's values, docs/03 section 13.8


def shake_keys(initial, start=16, loops=3, frames_per_loop=10, magnitude=5.0):
    """(frame, value) keys of the lab's head shake: still to `start`, then centre, +, centre, -, centre per loop."""
    keys, frame, quarter = [(0, initial), (start, initial)], float(start), frames_per_loop / 4.0
    for _ in range(loops):
        keys += [(frame + quarter, initial + magnitude), (frame + 2 * quarter, initial),
                 (frame + 3 * quarter, initial - magnitude), (frame + frames_per_loop, initial)]
        frame += frames_per_loop
    return keys


def summarize(values):
    """Distinct values with how many nodes have each, so 43 equal materials read as one line."""
    counts = {}
    for value in values:
        key = json.dumps(value, sort_keys=True)
        counts[key] = counts.get(key, 0) + 1
    return [{"value": json.loads(k), "nodes": n} for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]


def _write(folder, name, value):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, sort_keys=True)
    print("WROTE %s (%d bytes)" % (path, os.path.getsize(path)))
    return path


def _nodes(node_type):
    try:
        return sorted(cmds.ls(type=node_type) or [])
    except RuntimeError:  # the type does not exist when the plug-in is not loaded
        return []


def _scalars(node):
    out = {}
    for attr in cmds.listAttr(node, scalar=True) or []:
        try:
            out[attr] = cmds.getAttr(node + "." + attr)
        except (RuntimeError, ValueError):
            pass
    return out


def _landmarks():
    joints = cmds.ls(type="joint") or []
    return sorted(j for j in joints if j.split("|")[-1].split(":")[-1].startswith(tuple(LANDMARK_PREFIXES)))


def start_log(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "script_editor_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    cmds.scriptEditorInfo(historyFilename=path, writeHistory=True)
    print("Script Editor history is now also written to " + path)
    return path


def probe(folder):
    report, parts = {"errors": {}}, {}

    def part(name):
        def wrap(fn):
            parts[name] = fn
            return fn
        return wrap

    @part("session")
    def _session():
        return {"maya": cmds.about(version=True), "maya_api": cmds.about(apiVersion=True), "python": sys.version,
                "scene": cmds.file(query=True, sceneName=True), "modified": cmds.file(query=True, modified=True),
                "time_unit": cmds.currentUnit(query=True, time=True),
                "linear_unit": cmds.currentUnit(query=True, linear=True), "up_axis": cmds.upAxis(query=True, axis=True),
                "animation_range": [cmds.playbackOptions(query=True, animationStartTime=True),
                                    cmds.playbackOptions(query=True, animationEndTime=True)],
                "playback_range": [cmds.playbackOptions(query=True, minTime=True),
                                   cmds.playbackOptions(query=True, maxTime=True)],
                "current_time": cmds.currentTime(query=True),
                "evaluation_mode": cmds.evaluationManager(query=True, mode=True)}

    @part("plugins")
    def _plugins():
        return {p: cmds.pluginInfo(p, query=True, version=True) for p in cmds.pluginInfo(query=True, listPlugins=True) or []
                if "ziva" in p.lower() or "abc" in p.lower()}

    @part("ziva_counts")
    def _counts():
        return {t: len(_nodes(t)) for t in ZIVA_TYPES}

    @part("solver")
    def _solver():
        return {n: _scalars(n) for t in SOLVER_TYPES for n in _nodes(t)}

    @part("ziva_value_summary")
    def _summary():
        out = {}
        for node_type in SUMMARY_TYPES:
            per_attr = {}
            for node in _nodes(node_type):
                for attr, value in _scalars(node).items():
                    per_attr.setdefault(attr, []).append(value)
            out[node_type] = {a: summarize(v) for a, v in sorted(per_attr.items())}
        return out

    @part("lips")
    def _lips():
        found = cmds.ls(LIPS) or cmds.ls("*:" + LIPS) or []
        out = {"found": found}
        for mesh in found:
            skins = cmds.ls(cmds.listHistory(mesh) or [], type="skinCluster") or []
            out[mesh] = {"vertices": cmds.polyEvaluate(mesh, vertex=True), "skin_clusters": {
                s: {"influences": len(cmds.skinCluster(s, query=True, influence=True) or []),
                    "first": (cmds.skinCluster(s, query=True, influence=True) or [])[:3],
                    "envelope": cmds.getAttr(s + ".envelope")} for s in skins}}
        return out

    @part("landmarks")
    def _marks():
        marks = _landmarks()
        out = {"count": len(marks), "per_prefix": {p: sum(1 for j in marks if j.split("|")[-1].split(":")[-1].startswith(p))
                                                    for p in LANDMARK_PREFIXES},
               "jaw": cmds.ls(JAW) or cmds.ls("*:" + JAW) or []}
        out["world_position"] = {j: cmds.xform(j, query=True, worldSpace=True, translation=True)
                                 for j in marks + out["jaw"]}
        parents = sorted(set((cmds.listRelatives(j, parent=True, fullPath=True) or [""])[0] for j in marks))
        out["parent_world_matrix"] = {p: cmds.xform(p, query=True, worldSpace=True, matrix=True) for p in parents if p}
        return out

    @part("keys")
    def _keys():
        marks = _landmarks()
        names = [JAW] + BONES + marks[:1] + marks[-1:] + [n for t in SOLVER_TYPES for n in _nodes(t)]
        return {n: {"exists": bool(cmds.objExists(n)), "keys": cmds.keyframe(n, query=True, keyframeCount=True)
                    if cmds.objExists(n) else None,
                    "last_key": max(cmds.keyframe(n, query=True) or [0]) if cmds.objExists(n) else None} for n in names}

    for name, fn in parts.items():
        try:
            report[name] = fn()
        except Exception as error:  # every part stands alone; the reason is kept
            report["errors"][name] = "%s: %s" % (type(error).__name__, error)
    path = _write(folder, "probe_%s.json" % time.strftime("%Y%m%d_%H%M%S"), report)
    brief = {k: report.get(k) for k in ("session", "plugins", "ziva_counts", "lips", "keys")}
    brief["landmarks"] = {k: v for k, v in (report.get("landmarks") or {}).items() if k in ("count", "per_prefix", "jaw")}
    brief["damping_like"] = {t: {a: v for a, v in attrs.items() if "amp" in a.lower()}
                             for t, attrs in (report.get("ziva_value_summary") or {}).items()}
    brief["solver"] = report.get("solver")
    print(json.dumps(brief, indent=1, sort_keys=True))
    print("PROBE %s  errors: %s" % ("OK" if not report["errors"] else "INCOMPLETE", report["errors"] or "none"))
    return path


def dump_keys(folder, name, first=None, last=None):
    """Every frame of the keyed joints and bones, read from the animation curves; the solver is not stepped."""
    first = int(cmds.playbackOptions(query=True, animationStartTime=True)) if first is None else int(first)
    last = int(cmds.playbackOptions(query=True, animationEndTime=True)) if last is None else int(last)
    nodes = [n for n in [JAW] + BONES + _landmarks() if cmds.objExists(n)]
    attrs = ["tx", "ty", "tz", "rx", "ry", "rz"]
    frames = list(range(first, last + 1))
    values = {n: [[cmds.getAttr("%s.%s" % (n, a), time=f) for a in attrs] for f in frames] for n in nodes}
    keyed = sorted(n for n in nodes if cmds.keyframe(n, query=True, keyframeCount=True))
    parent_of = {n: (cmds.listRelatives(n, parent=True, fullPath=True) or [""])[0] for n in nodes}
    parents = sorted(set(parent_of.values()))
    out = {"name": name, "parent_of": parent_of, "scene": cmds.file(query=True, sceneName=True), "frames": frames, "attributes": attrs,
           "space": "local translate and rotate of each node, scene units and degrees", "values": values,
           "keyed_nodes": len(keyed), "nodes": len(nodes), "time_unit": cmds.currentUnit(query=True, time=True),
           "parent_world_matrix": {p: cmds.xform(p, query=True, worldSpace=True, matrix=True) for p in parents if p}}
    path = _write(folder, "keys_%s_%s.json" % (name, time.strftime("%Y%m%d_%H%M%S")), out)
    print("KEYS %s: %d nodes, %d keyed, frames %d..%d" % ("OK" if keyed else "NO KEYED NODE: is the motion loaded?",
                                                         len(nodes), len(keyed), first, last))
    return path


def head_shake_keys():
    """The lab's head shake (their passive_dynamics_test.py): tx keys on the two bone meshes. Changes the scene."""
    for target in BONES:
        initial = cmds.getAttr(target + ".tx")
        for frame, value in shake_keys(initial, SHAKE["start"], SHAKE["loops"], SHAKE["frames_per_loop"],
                                       SHAKE["magnitude"]):
            cmds.setKeyframe(target, attribute="tx", time=frame, value=value)
        end = SHAKE["start"] + SHAKE["loops"] * SHAKE["frames_per_loop"]
        cmds.keyTangent(target, attribute="tx", time=(0, end), inTangentType="auto", outTangentType="auto")
    end = SHAKE["start"] + SHAKE["loops"] * SHAKE["frames_per_loop"] + 40
    cmds.playbackOptions(minTime=0, maxTime=end, animationStartTime=0, animationEndTime=end)
    print("head shake keyed on %s, frames 0..%d. Do NOT save this scene." % (BONES, end))


if cmds is not None and __name__ == "__main__":
    print("ziva_trip_probe loaded: start_log(folder), probe(folder), dump_keys(folder, name), head_shake_keys()")
