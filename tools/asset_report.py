"""Print the facts docs/03-asset.md relies on, from the inventory that mb_inventory.py wrote.

    uv run python tools/mb_inventory.py <scene.mb> data/asset_inventory.json
    uv run python tools/asset_report.py data/asset_inventory.json

Analysis tool for the design docs, not product code. Every number in docs/03-asset.md
should be reproducible with these two commands.
"""

import itertools
import json
import math
import re
import sys
from collections import Counter, defaultdict

PROTOTYPE_MESHES = [
    "middleres_OrbicularisOrisShapeOrig",
    "middleres_JawShapeOrig",
    "middleres_skullShapeOrig",
    "middleres_TeethUpShapeOrig",
    "middleres_TeethDownShapeOrig",
]


def world_box_size(lo, hi, rot, scale):
    """Size of the box after Maya's default transform (scale, then rotate X, Y, Z); translation ignored."""

    def rotate(p, axis, a):
        c, s = math.cos(a), math.sin(a)
        x, y, z = p
        if axis == 0:
            return (x, c * y - s * z, s * y + c * z)
        if axis == 1:
            return (c * x + s * z, y, -s * x + c * z)
        return (c * x - s * y, s * x + c * y, z)

    corners = []
    for corner in itertools.product(*zip(lo, hi)):
        p = tuple(corner[i] * scale[i] for i in range(3))
        for axis in range(3):
            p = rotate(p, axis, rot[axis])
        corners.append(p)
    return [round(max(c[i] for c in corners) - min(c[i] for c in corners), 2) for i in range(3)]


# Maya leaves out of the file every list element that equals the attribute's default, and an
# element that is not in the file takes the default. For a zAttachment weight list the default is
# taken to be 1.0: a strong inference, not yet confirmed. Evidence: all 21 weight lists stored
# element by element hold only 0.0 (nobody stores thousands of zeros if 0 is the default), and the
# 74 lip indices left out of zAttachment1 sit on the skull exactly as the 76 stored ones of
# zAttachment2 sit on the jaw. To be confirmed by the `default` field of ziva_maps.json from the
# Ziva machine (docs/12 item 2).
ATTACHMENT_WEIGHT_DEFAULT = 1.0
DEFAULT_NOTE = ("default 1.0 is a strong inference, to be confirmed by the 'default' field "
                "in ziva_maps.json exported on the Ziva machine")


def attachment_weights(attrs, vertex_count):
    """Split an attachment's weight list into what the file stores and what takes the default.

    Returns (stored, defaulted): `stored` maps vertex index -> stored weight; `defaulted` is the set
    of source-vertex indices the file leaves out, which take ATTACHMENT_WEIGHT_DEFAULT. An
    attachment with no weight list at all therefore holds every vertex of its source body.
    """
    stored = {}
    for k, v in attrs.items():
        m = re.match(r"wl\[0\]\.w\[(\d+)(?::(\d+))?\]$", k)
        if m:
            first, last = int(m.group(1)), int(m.group(2) or m.group(1))
            stored.update(zip(range(first, last + 1), v if isinstance(v, list) else [v]))
    defaulted = set(range(vertex_count)) - stored.keys()
    return stored, defaulted


def attached_vertices(attrs, vertex_count):
    """(stored non-zero, defaulted) vertex index sets; their union is every vertex with weight > 0."""
    stored, defaulted = attachment_weights(attrs, vertex_count)
    nonzero = {i for i, w in stored.items() if isinstance(w, (int, float)) and w > 0}
    return nonzero, (defaulted if ATTACHMENT_WEIGHT_DEFAULT > 0 else set())


def read_attachments(inv):
    """Every zAttachment as (name, source body, target body, stored non-zero, defaulted,
    stored count, source vertex count), weights read by attached_vertices()."""
    nodes = {n["name"]: n for n in inv["nodes"]}
    src_of, dst_of = defaultdict(list), defaultdict(list)
    for s, d in inv["connections"]:
        src_of[d.split(".")[0]].append((s, d))
        dst_of[s.split(".")[0]].append((s, d))
    body_count = {}  # body -> vertex count of its zGeo
    for g in (n for n in inv["nodes"] if n["type"] == "zGeo"):
        for s, d in dst_of[g["name"]]:
            if d.endswith(".iGo") and nodes.get(d.split(".")[0], {}).get("type") in ("zTissue", "zBone", "zCloth"):
                body_count[d.split(".")[0]] = (g["attrs"].get("iNMh") or {}).get("vertex_count") or 0
    geo_body = {s.split(".")[0]: d.split(".")[0] for s, d in inv["connections"]
                if d.endswith(".iGo") and nodes.get(d.split(".")[0], {}).get("type") in ("zTissue", "zBone", "zCloth")
                and nodes.get(s.split(".")[0], {}).get("type") == "zGeo"}
    out = []
    for a in (n for n in inv["nodes"] if n["type"] == "zAttachment"):
        g1 = [s.split(".")[0] for s, d in src_of[a["name"]] if d.endswith(".iGo1")]
        g2 = [s.split(".")[0] for s, d in src_of[a["name"]] if d.endswith(".iGo2")]
        b1, b2 = (geo_body.get(g1[0]) if g1 else None), (geo_body.get(g2[0]) if g2 else None)
        n = body_count.get(b1, 0)
        stored, _ = attachment_weights(a["attrs"], n)
        nonzero, defaulted = attached_vertices(a["attrs"], n)
        out.append((a["name"], b1, b2, nonzero, defaulted, len(stored), n))
    return out


def main(path):
    inv = json.load(open(path, encoding="utf-8"))
    nodes = {n["name"]: n for n in inv["nodes"]}
    src_of, dst_of = defaultdict(list), defaultdict(list)
    for s, d in inv["connections"]:
        src_of[d.split(".")[0]].append((s, d))
        dst_of[s.split(".")[0]].append((s, d))
    typ = lambda n: nodes.get(n, {}).get("type")  # noqa: E731
    by_type = lambda t: [n for n in inv["nodes"] if n["type"] == t]  # noqa: E731

    h = inv["header"]
    print("## file")
    print(f"maya {h.get('product')}, linear unit {h.get('LUNI')}, time unit {h.get('TUNI')}, saved {h.get('CHNG')}")
    print("plugins:", ", ".join(f"{p['name']} {p['version']}" for p in inv["plugins"]))
    print(f"nodes {inv['node_count']}, connections {inv['connection_count']}, unparsed chunks {inv['unparsed_chunks']}")

    print("\n## ziva node counts")
    counts = Counter(n["type"] for n in inv["nodes"])
    print(", ".join(f"{t} {counts[t]}" for t in ["zTissue", "zBone", "zCloth", "zAttachment", "zMaterial", "zTet", "zFiber", "zEmbedder", "zGeo"]))

    # zGeo -> body, body -> mesh
    geo_body = {}
    for g in by_type("zGeo"):
        bodies = [d.split(".")[0] for s, d in dst_of[g["name"]] if d.endswith(".iGo") and typ(d.split(".")[0]) in ("zTissue", "zBone", "zCloth")]
        geo_body[g["name"]] = bodies[0] if bodies else None

    def tissue_mesh(t):
        tets = [d.split(".")[0] for s, d in dst_of[t] if d.endswith(".iGo") and typ(d.split(".")[0]) == "zTet"]
        if not tets:
            return None, None
        meshes = [s.split(".")[0] for s, d in src_of[tets[0]] if re.search(r"\.ip\[0\]\.ig$", d)]
        return (meshes[0] if meshes else None), nodes[tets[0]]["attrs"].get("tetSz")

    print("\n## bodies whose source mesh is still in the file")
    for t in by_type("zTissue"):
        mesh, tet = tissue_mesh(t["name"])
        if mesh:
            print(f"tissue {t['name']}: {mesh}, tet size {tet:.2f}, collisions {t['attrs'].get('eC')}")
    for b in by_type("zBone"):
        meshes = [s.split(".")[0] for s, d in src_of[b["name"]] if d.endswith(".aM")]
        if meshes:
            print(f"bone {b['name']}: {meshes[0]}")
    missing = sum(1 for t in by_type("zTissue") if tissue_mesh(t["name"])[0] is None)
    print(f"tissues whose source mesh was deleted from the file: {missing}")

    print("\n## materials: stored (non-default) values")
    stored = Counter(k for m in by_type("zMaterial") for k, v in m["attrs"].items() if isinstance(v, (int, float)))
    print(f"zMaterial numeric values stored: {sum(stored.values())} {dict(stored)}")
    # A value can also arrive through a connection; only the wiring plugs are expected here.
    wiring = ("iGo", "ip", "og", "oGo")
    driven = [d for m in by_type("zMaterial") for s, d in src_of[m["name"]] if d.split(".")[1].split("[")[0] not in wiring]
    print(f"connections driving zMaterial parameters: {len(driven)} {driven[:5]}")
    print(f"unparsed chunks anywhere in the file: {inv['unparsed_chunks']} (a stored value could hide there)")
    modes = Counter(k for a in by_type("zAttachment") for k in a["attrs"] if not k.startswith("wl"))
    print(f"zAttachment attributes stored (attachment mode is not among them -> default): {dict(modes)}")

    print("\n## fibers: which tissue each zFiber belongs to")
    for f in by_type("zFiber"):
        mats = [s.split(".")[0] for s, d in src_of[f["name"]] if d.endswith(".iGo")]
        tets = [s.split(".")[0] for m in mats for s, d in src_of[m] if d.endswith(".iGo")]
        tissues = [s.split(".")[0] for t in tets for s, d in src_of[t] if d.endswith(".iGo")]
        print(f"{f['name']}: {tissues}")

    attachments = read_attachments(inv)

    def line(name, b1, b2, nonzero, defaulted, n_stored, n):
        return (f"{name}: {b1} -> {b2}, source vertices {n}, stored {n_stored}; "
                f"stored non-zero {len(nonzero)}, by default {len(defaulted)}, attached {len(nonzero | defaulted)}")

    print("\n## attachment weights: how they are read")
    print("(the weight list lives on the SOURCE body, i.e. the first one named; an element the file")
    print(f" leaves out takes the default {ATTACHMENT_WEIGHT_DEFAULT}: {DEFAULT_NOTE})")
    no_list = [a for a in attachments if a[5] == 0]
    partly = [a for a in attachments if a[5] > 0 and a[4]]
    print(f"attachments {len(attachments)}; with some indices left out (taken as default): {len(partly)}; "
          f"with no weight list at all (whole source body attached): {len(no_list)}")

    print("\n## attachments touching the lip tissue (zTissue1)")
    lip_stored, lip_default = set(), set()
    for a in attachments:
        if "zTissue1" not in (a[1], a[2]):
            continue
        if a[1] == "zTissue1":
            lip_stored |= a[3]
            lip_default |= a[4]
        print(line(*a))
    print(f"distinct lip vertices with an attachment weight > 0 (lip as source): {len(lip_stored | lip_default)} of 10240 "
          f"(stored non-zero {len(lip_stored)}, by default {len(lip_default - lip_stored)})")

    print("\n## chain outward from the lip (follow the source -> target direction until bones)")
    frontier, seen = ["zTissue1"], {"zTissue1"}
    while frontier:
        body = frontier.pop(0)
        for a in attachments:
            if a[1] != body or a[1] == a[2]:
                continue
            print(line(*a))
            if typ(a[2]) == "zTissue" and a[2] not in seen:
                seen.add(a[2])
                frontier.append(a[2])
        if body != "zTissue1":
            for a in attachments:
                if a[2] == body and a[1] not in seen:
                    print("  into " + line(*a))

    print("\n## skin clusters (joint-driven deformation)")
    for sc in by_type("skinCluster"):
        joints = sorted({s.split(".")[0] for s, d in src_of[sc["name"]] if re.search(r"\.ma\[", d)})
        groups = Counter(re.sub(r"_?\d+$", "", j) for j in joints)
        inputs = [s for s, d in src_of[sc["name"]] if re.search(r"\.ip\[\d+\]\.ig$", d)]
        outputs = [d.split(".")[0] for s, d in dst_of[sc["name"]] if ".og[" in s]
        print(f"{sc['name']}: {len(joints)} joints {dict(groups)}; input {inputs}; output {outputs}")

    print("\n## landmarks and keyframes")
    joints = by_type("joint")
    print(f"joints {len(joints)}; oor landmarks {sum(1 for j in joints if re.fullmatch(r'oor_\d+', j['name']))}")
    tps = int(h["TDUR"])
    curves = [n for n in inv["nodes"] if n["type"].startswith("animCurve")]
    key_counts, frames, moving = Counter(), Counter(), 0
    for c in curves:
        keys = [k for a, v in c["attrs"].items() if a.startswith("ktv[") for k in v]
        key_counts[len(keys)] += 1
        frames[tuple(round(t / tps * 30, 2) for t, _ in keys)] += 1
        values = [v for _, v in keys]
        moving += bool(values) and max(values) - min(values) > 1e-9
    print(f"animation curves {len(curves)}; keys per curve {dict(key_counts)}; key frames at 30 fps {dict(frames)}")
    print(f"curves whose value changes over time: {moving}")

    print("\n## solver")
    shape = nodes["zSolver1Shape"]["attrs"]
    print({k: shape[k] for k in ("fPs", "inT", "newt", "unL") if k in shape}, "transform scale", nodes["zSolver1"]["attrs"].get("s"))
    print("solver inputs:", dict(Counter(typ(s.split(".")[0]) for s, d in src_of["zSolver1Shape"])))

    print("\n## prototype meshes (rest shape = the *ShapeOrig input; vertex positions decoded, faces not)")
    print("object space = the mesh's own coordinates; world space = after its transform (what Ziva reads)")
    for m in PROTOTYPE_MESHES:
        blob = nodes[m]["attrs"].get("o", {})
        lo, hi = blob.get("bbox_min"), blob.get("bbox_max")
        size = [round(hi[i] - lo[i], 2) for i in range(3)] if lo and hi else None
        tr = nodes[nodes[m]["parent"]]["attrs"] if nodes[m]["parent"] in nodes else {}
        t, r, s = tr.get("t", [0, 0, 0]), tr.get("r", [0, 0, 0]), tr.get("s", [1, 1, 1])
        world = world_box_size(lo, hi, r, s) if lo and hi else None
        print(f"{m}: {blob.get('vertex_count')} vertices; object-space size x/y/z {size}")
        print(f"    transform: translate {[round(v, 3) for v in t]}, rotate (deg) {[round(math.degrees(v), 1) for v in r]}, "
              f"scale {[round(v, 3) for v in s]}; world-space size x/y/z {world}")
    tet = nodes["zTet1"]["attrs"]
    lip_weights = max((int(k.split(":")[1].rstrip("]")) + 1 for k in tet if k.startswith("wl[0].w[") and ":" in k), default=0)
    print(f"cross-check: zTet1 per-vertex weight list has {lip_weights} entries (= lip vertex count)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(sys.argv[1])
