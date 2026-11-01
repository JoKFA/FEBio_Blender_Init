# ASRP

Replace Ziva (the physics backend under the lab's facial controller) with FEBio, and Maya (the host) with Blender.

- `src/asrp_core/`: solver core. Runs in its own process with its own venv; no `bpy`.
- `blender_addon/asrp_blender/`: thin Blender add-on. UI only; calls the core as a subprocess.
- `docs/`: the project's design documents (Chinese). They are the single source of truth for scope, design, standards and tasks.

**Start here: [docs/README.md](docs/README.md).**

## Setup (Windows)

```bash
uv sync
uv run asrp doctor
```

`doctor` reports Python, FEBio, Blender and whether the project path is ASCII-only.
FEBio binaries need a free registration at febio.org (GitHub releases are source only).
Override tool locations with `ASRP_FEBIO` / `ASRP_BLENDER`.

The lab's Maya scene goes in `assets/` and solver runs in `runs/`: both are git-ignored and must never be committed. Exports and derived data go in `data/`; `data/lab_export/`, `data/preview/` and `data/briefing/` are committed because this repo is private (docs ADR-19). The lab's `.mb` files, paper and video are never committed.

## Checks (definition of done)

```bash
uv run python tools/verify.py
```

Runs the tests, `asrp doctor`, Blender's own validation of the add-on manifest, the Blender add-on round trip (`tools/check_blender_addon.py`) and the playback check (`tools/check_playback.py`, which runs S1 through real FEBio, loads the result with the add-on, and compares Blender's evaluated mesh with the FEBio log frame by frame). Blender is located like `asrp doctor` does (`ASRP_BLENDER`, PATH, default install).

## Install the Blender add-on

Run from the repo root, and again after changing the add-on:

```bash
mkdir -p dist
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --factory-startup --command extension build --source-dir blender_addon/asrp_blender --output-dir dist
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --command extension install-file -r user_default -e dist/asrp_blender-0.0.1.zip
```

In PowerShell, put `&` in front of the quoted path.
Installed this way the add-on lives outside the repo, so Check Backend needs `ASRP_PROJECT` set to the repo path. Load Result does not.

## Playing a result in Blender

So far this is spike S1 only: a 10 × 10 × 35 mm test block, not the lab's lips. The lab asset has not been through FEBio yet (docs/09-roadmap-and-tasks.md).

A solved run is a folder with `playback.json` (surface mesh, mm) and `playback.pc2` (per-frame positions). `runs/` is git-ignored, so a fresh clone has to solve S1 first, which needs FEBio:

```bash
uv run python spikes/s1_dynamic_jaw.py
```

In Blender: delete the default cube (the result is 3.5 cm tall and sits inside it), then sidebar (N) > ASRP > Load Result, pick the run folder, View > Frame Selected (numpad `.`), press play. The object is scaled 0.001 so mm data shows in metres.

To render a few frames from the side (the camera and context props fit S1's geometry, so this works for S1 only). In PowerShell, put `&` in front of the quoted path:

```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python-exit-code 1 --python tools/render_playback.py -- runs/s1_dynamic_jaw runs/s1_dynamic_jaw/render 0 15 30 45
```

## Spikes

`spikes/` holds throwaway experiments that settle one assumption each; results are recorded in the assumption ledger (docs/11-risks-and-questions.md).

## Lab asset (not product code)

Migration tools, run once per scene (docs ADR-18): the product needs neither Maya nor Ziva. The results in `data/lab_export/` and `data/preview/` are committed, so these are only needed when the scene changes. `data/briefing/asrp-briefing.html` is the newcomer's guide to all of this: open it locally, because GitHub doesn't run HTML. In PowerShell, put `&` in front of the commands below that start with a quoted path.

Read the scene without Maya: nodes, attributes, connections, keyframes. This step doesn't decode mesh geometry (see docs/03-asset.md). The report needs the Ziva scene (v36): the non-Ziva copy has no Ziva nodes to report on.

```bash
uv run python tools/mb_inventory.py "assets/<ziva scene>.mb" data/asset_inventory.json
uv run python tools/asset_report.py data/asset_inventory.json
```

Export meshes, weights and joints from the non-Ziva scene with plain Maya, then check them against the `.mb`:

```bash
"C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tools/maya_export.py "assets/<non-ziva scene>.mb" data/lab_export
uv run python tools/check_lab_export.py data/lab_export "assets/<non-ziva scene>.mb"
```

Bring the export into Blender and render the preview. This checks the meshes landed right; there is no physics in it.

```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python-exit-code 1 --python tools/blender_import_preview.py -- data/lab_export data/preview
```

What only Ziva can give us comes from `tools/ziva_machine_export.py`, run once in Maya's Script Editor on the Ziva machine (steps in docs/12-lab-export-checklist.md). `tools/rehearse_ziva_export.py` rehearses its plumbing without Ziva.
