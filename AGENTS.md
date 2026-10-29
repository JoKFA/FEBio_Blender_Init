# ASRP — Project Instructions

Adds to E:\Codebase\AGENTS.md.

## What this is
Replace Ziva (physics under the lab's facial controller) with FEBio, and Maya with Blender.
The design docs in docs/ are the single source of truth. Start at docs/README.md.
Work from one task card in docs/09-roadmap-and-tasks.md at a time and follow docs/08-engineering-standards.md.
Don't change the design in code: if the docs are wrong, stop and report; docs change first.

## Layout rules
- `src/asrp_core/` never imports `bpy`. Blender talks to it only through the `asrp` CLI, as a subprocess.
- `blender_addon/asrp_blender/` is UI only: no solver logic, no third-party deps (Blender's Python can't install them).
- Units are mm–N–MPa–s everywhere; convert at the boundary and record the factor.

## Data
- The lab's Maya scene goes in `assets/`, lab exports and derived data in `data/`, solver runs in `runs/` (all git-ignored). Never commit them; the asset may be a licensed commercial model.
- The lab paper and demo video are confidential (paper under review). They stay in E:\Codebase\3D模拟, outside the repo. Don't quote them in commits or anywhere public.

## Environment
- Python 3.13, matching Blender 5.2's bundled 3.13. `uv sync`, then `uv run asrp doctor`.
- Keep every path the solver sees ASCII-only; FEBio and other C++ tools may fail on non-ASCII paths.
- FEBio binaries come from febio.org (registration required). Set `ASRP_FEBIO` to `febio4.exe` if doctor can't find it.

## Verify
Definition of done: `uv run python tools/verify.py` (tests, `asrp doctor`, add-on round trip, playback check). `.claude/verify.json` calls the same command.
