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

Runs the tests, `asrp doctor`, the Blender add-on round trip (`tools/check_blender_addon.py`) and the playback check (`tools/check_playback.py`, which runs S1 through real FEBio, loads the result with the add-on, and compares Blender's evaluated mesh with the FEBio log frame by frame). Blender is located like `asrp doctor` does (`ASRP_BLENDER`, PATH, default install).

## Playing a result in Blender

A solved run is a folder with `playback.json` (surface mesh, mm) and `playback.pc2` (per-frame positions).
In Blender: sidebar > ASRP > Load Result, pick the folder, press play. The object is scaled 0.001 so mm data shows in metres.

To render a few frames from the side:

```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tools/render_playback.py -- runs/s1_dynamic_jaw runs/s1_dynamic_jaw/render 0 15 30 45
```

## Spikes

`spikes/` holds throwaway experiments that settle one assumption each; results are recorded in the assumption ledger (docs/11-risks-and-questions.md).

## Asset analysis (not product code)

```bash
uv run python tools/mb_inventory.py "assets/<scene>.mb" data/asset_inventory.json
uv run python tools/asset_report.py data/asset_inventory.json
```

Reads the lab's Maya binary scene without Maya: nodes, attributes, connections, keyframes. Mesh geometry is not decoded (see docs/03-asset.md).

```bash
uv run python spikes/s1_dynamic_jaw.py   # FEBio dynamics + rigid hinge + gravity on this machine
```
