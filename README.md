# ASRP

Replace Ziva (the physics backend under the lab's facial controller) with FEBio, and Maya (the host) with Blender.

- `src/asrp_core/`: solver core. Runs in its own process with its own venv; no `bpy`.
- `blender_addon/asrp_blender/`: thin Blender add-on. UI only; calls the core as a subprocess.
- `docs/`: spec, decisions, open questions for the lab.

Scope and acceptance: [docs/spec-v0.1.md](docs/spec-v0.1.md).

## Setup (Windows)

```bash
uv sync
uv run asrp doctor
```

`doctor` reports Python, FEBio, Blender and whether the project path is ASCII-only.
FEBio binaries need a free registration at febio.org (GitHub releases are source only).
Override tool locations with `ASRP_FEBIO` / `ASRP_BLENDER`.

Lab assets, Ziva reference output and solver runs go in `data/` and `runs/`; both are git-ignored.

## Checks

```bash
uv run pytest -q
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tools/check_blender_addon.py
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tools/check_playback.py
```

`check_playback.py` runs S1 through real FEBio, loads the result with the add-on, and compares Blender's evaluated mesh with the FEBio log frame by frame.

## Playing a result in Blender

A solved run is a folder with `playback.json` (surface mesh, mm) and `playback.pc2` (per-frame positions).
In Blender: sidebar > ASRP > Load Result, pick the folder, press play. The object is scaled 0.001 so mm data shows in metres.

To render a few frames from the side:

```bash
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background --factory-startup --python tools/render_playback.py -- runs/s1_dynamic_jaw runs/s1_dynamic_jaw/render 0 15 30 45
```

## Spikes

`spikes/` holds throwaway experiments that settle one assumption each; results are recorded in the spec's assumption ledger.

```bash
uv run python spikes/s1_dynamic_jaw.py   # FEBio dynamics + rigid hinge + gravity on this machine
```
