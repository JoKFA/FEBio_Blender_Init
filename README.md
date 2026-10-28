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
```
