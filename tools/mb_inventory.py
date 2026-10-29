"""Inventory of a Maya binary scene (.mb) without Maya: nodes, attributes, connections, keyframes.

Analysis tool for the design docs, not product code. Read-only; stdlib only.

    uv run python tools/mb_inventory.py <scene.mb> <out.json>

What it can read: the node list and hierarchy, plugin node types, attribute values that differ
from defaults (Maya only stores those), every connection, animation keys, and each mesh's
vertex count and bounding box. What it cannot: mesh faces. Their encoding is undocumented,
so meshes for the product must be exported from Maya in an open format (docs ADR-07).

Format notes (Maya 64-bit IFF, verified on a Maya 2023 file):
- chunk = tag(4) + 4 unused bytes + size(8, big endian) + payload;
- groups (FOR8/LIS8/CAT8/PRO8) start with a 4-byte type; their children start right after it;
- leaf chunks are padded to 8 bytes relative to the start of their group's children,
  group sizes already include padding;
- a node is a group whose first child is CREA (flags byte, name, parent name);
- connections are CWFL chunks under CONS/CONN: flags byte, "src.attr", "dst.attr".
"""

import json
import mmap
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GROUPS = {b"FOR8", b"LIS8", b"CAT8", b"PRO8"}

# Plugin node type ids are stored as raw 4-byte tags. Names come from the Ziva plugin's
# node list in the header; the tag -> name pairing is inferred from node names (see main).
STANDARD_TAGS = {
    "XFRM": "transform", "DMSH": "mesh", "JOIN": "joint", "PCTL": "animCurveTL",
    "PCTA": "animCurveTA", "PCTU": "animCurveTU", "FWRP": "wrap", "NCRV": "nurbsCurve",
    "SHAD": "shadingEngine", "DSPL": "displayLayer", "GPID": "groupId", "DMTI": "materialInfo",
}


def align8(n):
    return (n + 7) & ~7


def walk(mm, start, end, base, depth, out):
    pos = start
    while pos + 16 <= end:
        tag = bytes(mm[pos : pos + 4])
        size = struct.unpack(">Q", mm[pos + 8 : pos + 16])[0]
        data = pos + 16
        if not all(32 <= c <= 126 for c in tag) or data + size > end:
            out.append(("BAD", depth, pos, tag, size))
            return
        if tag in GROUPS:
            out.append(("GROUP", depth, pos, bytes(mm[data : data + 4]), size))
            walk(mm, data + 4, data + size, data + 4, depth + 1, out)
            pos = data + size
        else:
            out.append(("CHUNK", depth, pos, tag, size))
            pos = base + align8(data + size - base)


def cstr(b):
    return b.split(b"\0")[0].decode("utf-8", "replace")


def decode_attr(tag, payload):
    """Return (attribute name, value). Payload = name, NUL, one flag byte, data."""
    name = cstr(payload)
    body = payload[len(name.encode()) + 2 :]
    if tag == "DBLE":
        n = len(body) // 8
        vals = list(struct.unpack(f">{n}d", body[: 8 * n]))
        return name, vals[0] if n == 1 else vals
    if tag == "DBL3":
        return name, list(struct.unpack(">3d", body[:24]))
    if tag == "FLT3":
        return name, list(struct.unpack(">3f", body[:12]))
    if tag in ("STR ",):
        return name, cstr(body)
    if tag == "MATR":
        n = len(body) // 8
        return name, list(struct.unpack(f">{n}d", body[: 8 * n]))
    if tag == "CMPD" and name.startswith("ktv[") and len(body) % 16 == 0:
        # animation keys: (time as int64 ticks, value as double) pairs; see header TDUR for ticks/s
        n = len(body) // 16
        return name, [list(struct.unpack(">qd", body[16 * k : 16 * k + 16])) for k in range(n)]
    if tag == "MESH":
        # The blob starts with a float count (3 per vertex) followed by the vertex positions as
        # big-endian float32. Checked: lip 30,720 floats = 10,240 vertices, matching zTet1's
        # 10,240-entry weight list. Faces/edges follow in an undecoded encoding.
        if len(body) < 4:
            return name, {"mesh_blob_bytes": len(body)}
        floats = struct.unpack(">I", body[:4])[0]
        info: dict = {"mesh_blob_bytes": len(body), "float_count": floats, "vertex_count": floats // 3}
        if floats % 3 == 0 and 4 + 4 * floats <= len(body):
            xyz = struct.unpack(f">{floats}f", body[4 : 4 + 4 * floats])
            info["bbox_min"] = [min(xyz[i::3]) for i in range(3)] if floats else None
            info["bbox_max"] = [max(xyz[i::3]) for i in range(3)] if floats else None
        return name, info
    return name, {"raw_type": tag, "bytes": len(body)}


def main(path, out_path):
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        entries = []
        walk(mm, 20, 16 + struct.unpack(">Q", mm[8:16])[0], 20, 1, entries)
        bad = [e for e in entries if e[0] == "BAD"]

        header, plugins = {}, []
        nodes, connections = [], []
        i = 0
        while i < len(entries):
            kind, depth, pos, tag, size = entries[i]
            if kind == "GROUP" and tag == b"HEAD":
                j = i + 1
                while j < len(entries) and entries[j][1] > depth:
                    _, _, p, t, s = entries[j]
                    parts = [x.decode("utf-8", "replace") for x in bytes(mm[p + 16 : p + 16 + s]).split(b"\0") if x]
                    if t == b"PLUG":
                        plugins.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else ""})
                    elif t == b"FINF":
                        header[parts[0]] = parts[1] if len(parts) > 1 else ""
                    elif parts:
                        header[t.decode()] = parts[0]
                    j += 1
                i = j
                continue
            if kind == "GROUP" and i + 1 < len(entries) and entries[i + 1][3] == b"CREA":
                cpos, csz = entries[i + 1][2], entries[i + 1][4]
                crea = bytes(mm[cpos + 17 : cpos + 16 + csz]).split(b"\0")
                node = {
                    "name": crea[0].decode("utf-8", "replace"),
                    "parent": crea[1].decode("utf-8", "replace") if len(crea) > 1 else "",
                    "tag": tag.decode("latin-1"),
                    "attrs": {},
                }
                j = i + 2
                while j < len(entries) and entries[j][1] > depth:
                    _, _, p, t, s = entries[j]
                    if entries[j][0] == "CHUNK":
                        name, value = decode_attr(t.decode("latin-1"), bytes(mm[p + 16 : p + 16 + s]))
                        node["attrs"][name] = value
                    j += 1
                nodes.append(node)
                i = j
                continue
            if kind == "CHUNK" and tag == b"CWFL":
                parts = bytes(mm[pos + 17 : pos + 16 + size]).split(b"\0")
                connections.append([parts[0].decode("utf-8", "replace"), parts[1].decode("utf-8", "replace")])
            i += 1

    # Name plugin tags by the most common node-name prefix (zTissue12 -> zTissue).
    prefixes = defaultdict(Counter)
    for n in nodes:
        prefixes[n["tag"]][n["name"].rstrip("0123456789")] += 1
    type_of = {}
    for tag, counts in prefixes.items():
        type_of[tag] = STANDARD_TAGS.get(tag) or counts.most_common(1)[0][0]
    for n in nodes:
        n["type"] = type_of[n["tag"]]
        n["parent"] = n["parent"] if n["parent"].isprintable() else ""

    result = {
        "file": Path(path).name,
        "header": header,
        "plugins": plugins,
        "unparsed_chunks": len(bad),
        "node_count": len(nodes),
        "type_counts": Counter(n["type"] for n in nodes).most_common(),
        "connection_count": len(connections),
        "nodes": nodes,
        "connections": connections,
    }
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"{len(nodes)} nodes, {len(connections)} connections, {len(bad)} unparsed chunks -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
