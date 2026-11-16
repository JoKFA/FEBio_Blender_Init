"""Export the four lip attachment sets for T-06a: the lips as the source side (docs/09 T-03).

    uv run python tools/lip_attachments.py --inventory data/asset_inventory.json

Reads the inventory tools/mb_inventory.py wrote from the v36 .mb, takes the attachments that
tools/asset_report.py's read_attachments() finds for the four lip groups, and writes
data/lab_export/lip_attachments.json. The weights are read by asset_report.attachment_weights(): an
element the file does not store takes ATTACHMENT_WEIGHT_DEFAULT (1.0, ADR-32). That default was
confirmed on 2026-11-12 by the 'default' field of ziva_maps.json (A-33).

Analysis tool, not product code. Importing the product module (asrp import-asset) is T-06a's job.
"""

import argparse
import hashlib
import json
from pathlib import Path

from asset_report import ATTACHMENT_WEIGHT_DEFAULT, attachment_weights, read_attachments

REPO = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = "data/asset_inventory.json"
DEFAULT_OUT = "data/lab_export/lip_attachments.json"
FORMAT_VERSION = 1
NOTE = "2026-11-12 已证实：权重表的默认值是 1.0（A-33）"

# (attachment, label, source body, target body, expected vertex count from docs/09 T-03).
# zTissue4 / zTissue5 are the two mouth-corner nodes; the names are the ones in the inventory.
GROUPS = [
    ("zAttachment1", "上唇 → 颅骨", "zTissue1", "zBone2", 74),
    ("zAttachment2", "下唇 → 下颌", "zTissue1", "zBone1", 76),
    ("zAttachment9", "左口角 → 口角 node (zTissue4)", "zTissue1", "zTissue4", 348),
    ("zAttachment10", "右口角 → 口角 node (zTissue5)", "zTissue1", "zTissue5", 309),
]


def resolve(path):
    p = Path(path)
    return p if p.is_absolute() else REPO / p


def bone_mesh(inv, body):
    """The Maya mesh a zBone is driven by (its .aM connection), or None for a node or tissue."""
    return next((s.split(".")[0] for s, d in inv["connections"]
                 if d.split(".")[0] == body and d.endswith(".aM")), None)


def build(inv, inventory_sha256, groups=GROUPS):
    """The export dict. Raises ValueError when a group is missing, goes to the wrong body, has the
    wrong vertex count, or shares a vertex with another group."""
    nodes = {n["name"]: n for n in inv["nodes"]}
    rows = {r[0]: r for r in read_attachments(inv)}
    out_groups, claimed = [], {}
    for name, label, source, target, expected in groups:
        if name not in rows:
            raise ValueError(f"{name} is not in the inventory")
        _, src, dst, nonzero, defaulted, _, n = rows[name]
        if (src, dst) != (source, target):
            raise ValueError(f"{name} goes {src} -> {dst}, expected {source} -> {target}")
        stored, _ = attachment_weights(nodes[name]["attrs"], n)
        weights = {v: float(stored[v]) for v in nonzero}
        weights.update({v: ATTACHMENT_WEIGHT_DEFAULT for v in defaulted})
        if expected is not None and len(weights) != expected:
            raise ValueError(f"{name} has {len(weights)} vertices, expected {expected}")
        for other, vertices in claimed.items():
            if vertices & weights.keys():
                raise ValueError(f"{name} and {other} share vertices")
        claimed[name] = set(weights)
        out_groups.append({
            "attachment": name,
            "label": label,
            "source": source,
            "source_vertex_count": n,
            "target": target,
            "target_mesh": bone_mesh(inv, target),
            "count": len(weights),
            "vertices": [[v, weights[v]] for v in sorted(weights)],
            "defaulted_vertices": sorted(defaulted),
            "default_weight": ATTACHMENT_WEIGHT_DEFAULT,
            "note": NOTE,
        })
    return {
        "format_version": FORMAT_VERSION,
        "inventory_sha256": inventory_sha256,
        "note": NOTE,
        "groups": out_groups,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", default=DEFAULT_INVENTORY)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    raw = resolve(args.inventory).read_bytes()
    export = build(json.loads(raw), hashlib.sha256(raw).hexdigest())
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(export, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"inventory sha256 {export['inventory_sha256']}")
    for g in export["groups"]:
        print(f"{g['attachment']}: {g['source']} -> {g['target']} ({g['target_mesh']}), "
              f"{g['count']} vertices, {len(g['defaulted_vertices'])} by default")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
