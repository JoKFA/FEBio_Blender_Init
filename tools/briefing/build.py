"""Build the one-file technical briefing page from the real exported data.

    uv run python tools/briefing/build.py <out.html>

Inlines template.html, app.js, the exported meshes, landmark weights and Blender renders, so the
result opens with no server and no network. The output contains lab meshes: it belongs in
data/briefing/, which goes to the private repo, and nowhere else (docs ADR-19). This folder holds
only the page source, no lab data. Rebuilding needs the .mb analysis output, which is not in git.

Needs: data/lab_export (tools/maya_export.py), data/asset_inventory.json (tools/mb_inventory.py on
the full v36 scene, for the attachment weights), data/preview (tools/blender_import_preview.py).
"""

import base64
import json
import re
import sys
from array import array
from collections import defaultdict
from pathlib import Path

from asrp_core.asset import coords

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EXPORT = REPO / "data" / "lab_export"
PREVIEW = REPO / "data" / "preview"
MM_PER_UNIT = 0.962  # provisional, docs 11 Q3
LIP_TISSUE, JAW_BONE = "zTissue1", "zBone1"  # docs/03 section 3

MESHES = {
    "lips": "mesh_middleres_OrbicularisOris.obj",
    "jaw": "mesh_middleres_Jaw.obj",
    "skull": "mesh_middleres_skull.obj",
    "teethU": "mesh_middleres_TeethUp.obj",
    "teethL": "mesh_middleres_TeethDown.obj",
    "skin": "context_skin_cloth_copy_v5_pull_back.obj",
}
IMAGES = ["01_all_parts", "02_lips_on_bone", "03_lips_and_landmarks", "04_side_hinge", "05_jaw_open_lips_stay"]


def b64(values, typecode):
    a = array(typecode, values)
    if sys.byteorder != "little":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode()


def read_mesh(path):
    """Positions in mm, Z up, and triangles (quads fanned), through asrp_core.asset.coords."""
    vertices, faces = coords.read_obj(path)
    return coords.to_mm_zup(vertices, MM_PER_UNIT).ravel().tolist(), coords.triangulate(faces).ravel().tolist()


def lip_attachments(inventory):
    """Lip vertices with an attachment weight, by target. Same reading as tools/asset_report.py."""
    inv = json.loads(inventory.read_text(encoding="utf-8"))
    nodes = {n["name"]: n for n in inv["nodes"]}
    into, out_of = defaultdict(list), defaultdict(list)
    for src, dst in inv["connections"]:
        into[dst.split(".")[0]].append((src.split(".")[0], dst))
        out_of[src.split(".")[0]].append(dst)
    body_of = {}  # zGeo -> the tissue or bone it belongs to
    for name, node in nodes.items():
        if node["type"] == "zGeo":
            for dst in out_of[name]:
                if dst.endswith(".iGo") and nodes[dst.split(".")[0]]["type"] in ("zTissue", "zBone", "zCloth"):
                    body_of[name] = dst.split(".")[0]

    targets = {}
    for name, node in nodes.items():
        if node["type"] != "zAttachment":
            continue
        g1 = next((s for s, d in into[name] if d.endswith(".iGo1")), None)
        g2 = next((s for s, d in into[name] if d.endswith(".iGo2")), None)
        if body_of.get(g1) != LIP_TISSUE:
            continue
        weights = {}
        for key, value in node["attrs"].items():
            m = re.match(r"wl\[0\]\.w\[(\d+)(?::(\d+))?\]$", key)
            if m:
                first, last = int(m.group(1)), int(m.group(2) or m.group(1))
                weights.update(zip(range(first, last + 1), value if isinstance(value, list) else [value]))
        vertices = sorted(i for i, w in weights.items() if isinstance(w, float) and w > 0)
        if vertices:
            targets["jaw" if body_of.get(g2) == JAW_BONE else f"corner_{body_of.get(g2)}"] = vertices
    return targets


def landmark_data():
    joints = json.loads((EXPORT / "joints.json").read_text())
    names = [f"oor_{i:02d}" for i in range(1, 301)]
    positions = coords.to_mm_zup([joints[n]["world_position"] for n in names], MM_PER_UNIT).ravel().tolist()

    skin = json.loads((EXPORT / "skin_skinCluster7.json").read_text())
    by_name = {n: i for i, n in enumerate(names)}
    per_landmark = [[] for _ in names]
    for vertex, row in enumerate(skin["weights"]):
        for influence, weight in row:
            per_landmark[by_name[skin["influences"][influence]]].append((vertex, weight))
    offsets, verts, weights = [0], [], []
    for entries in per_landmark:
        verts += [v for v, _ in entries]
        weights += [min(255, round(w * 255)) for _, w in entries]
        offsets.append(len(verts))
    return {
        "pos": b64(positions, "f"),
        "off": b64(offsets, "I"),
        "v": b64(verts, "H"),
        "w": base64.b64encode(bytes(weights)).decode(),
    }


def code(match):
    """{{code:tools/x.py:name}} -> the source of top-level def `name`, escaped for HTML."""
    path, name = match.group(1), match.group(2)
    text = (REPO / path).read_text(encoding="utf-8")
    found = re.search(rf"^def {name}\(.*?(?=^\S)", text, re.S | re.M)
    assert found, f"{name} not found in {path}"
    block = found.group(0).rstrip()
    return block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(out):
    report = json.loads((EXPORT / "mesh_report.json").read_text())
    data = {"meshes": {}, "mmPerUnit": MM_PER_UNIT}
    for name, filename in MESHES.items():
        positions, triangles = read_mesh(EXPORT / filename)
        data["meshes"][name] = {"p": b64(positions, "f"), "i": b64(triangles, "H")}
    data["hinge"] = coords.to_mm_zup([report["jaw_hinge"]["world_position"]], MM_PER_UNIT)[0].tolist()
    data["jawWorld"] = report["meshes"]["middleres_Jaw"]["world_matrix"]
    data["landmarks"] = landmark_data()

    attachments = lip_attachments(REPO / "data" / "asset_inventory.json")
    print({k: len(v) for k, v in attachments.items()})
    data["attach"] = {k: b64(v, "H") for k, v in attachments.items()}
    distinct = {v for vs in attachments.values() for v in vs}
    assert len(distinct) == 733, f"expected 733 attached lip vertices, got {len(distinct)}"

    images = {}
    for name in IMAGES:
        raw = (PREVIEW / f"{name}.webp").read_bytes()
        images[name] = "data:image/webp;base64," + base64.b64encode(raw).decode()

    page = (HERE / "template.html").read_text(encoding="utf-8")
    script = (HERE / "app.js").read_text(encoding="utf-8")
    glossary = script[script.index("const GLOSS = {") : script.index("(function glossary()")]
    defined = set(re.findall(r"^\s+'?([^':\n]+?)'?: '", glossary, re.M))
    used = set(re.findall(r'data-g="([^"]+)"', page + script))
    assert used and used <= defined, f"terms with no glossary entry: {sorted(used - defined)}"
    print(f"{len(used)} glossary terms linked, all defined")

    page = re.sub(r"\{\{code:([^:}]+):(\w+)\}\}", code, page)
    for name, uri in images.items():
        page = page.replace("{{img:%s}}" % name, uri)
    payload = "window.ASRP_DATA=" + json.dumps(data, separators=(",", ":")) + ";"
    page = page.replace("/*{{data}}*/", payload.replace("</", "<\\/"))
    page = page.replace("/*{{app}}*/", script)
    assert "{{" not in re.sub(r"<script>.*?</script>", "", page, flags=re.S), "unfilled placeholder"

    target = Path(out).resolve()
    if target.is_relative_to(REPO) and not target.is_relative_to(REPO / "data"):
        sys.exit(f"this page embeds lab meshes and belongs in data/briefing/, not {target}")
    target.write_text(page, encoding="utf-8", newline="\n")
    print(f"{target.stat().st_size / 1e6:.1f} MB -> {target}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
