# ASRP — Project Instructions

Adds to E:\Codebase\AGENTS.md.

## What this is
Replace Ziva (physics under the lab's facial controller) with FEBio, and Maya with Blender.
Scope and open assumptions: docs/spec-v0.1.md. Questions waiting on the lab: docs/lab-questions.md.

## Layout rules
- `src/asrp_core/` never imports `bpy`. Blender talks to it only through the `asrp` CLI, as a subprocess.
- `blender_addon/asrp_blender/` is UI only: no solver logic, no third-party deps (Blender's Python can't install them).
- Units are mm–N–MPa–s everywhere; convert at the boundary and record the factor.

## Data
- Lab assets, Ziva reference output and runs go in `data/` and `runs/` (git-ignored). Never commit them; the asset may be a licensed commercial model.
- The lab paper and demo video are confidential (paper under review). They stay in E:\Codebase\3D模拟, outside the repo. Don't quote them in commits or anywhere public.

## Environment
- Python 3.13, matching Blender 5.2's bundled 3.13. `uv sync`, then `uv run asrp doctor`.
- Keep every path the solver sees ASCII-only; FEBio and other C++ tools may fail on non-ASCII paths.
- FEBio binaries come from febio.org (registration required). Set `ASRP_FEBIO` to `febio4.exe` if doctor can't find it.

## Verify
`.claude/verify.json` runs pytest, `asrp doctor`, and the add-on round trip inside real Blender (`tools/check_blender_addon.py`).
