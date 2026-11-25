# 16 The whole pipeline from Maya to Blender

> **Scope:** This page records the delivered prototype (v1, single lip) 12-step pipeline.
> For the foundation stage (v2) CLI commands, see [architecture/README.md](architecture/README.md);
> this page will be updated after [T-47](tasks/T-47.md) switches `asrp run`.

> **English translation.** The Chinese page [16-pipeline.md](16-pipeline.md) is the source; where the two differ, the Chinese page is right. The
> other documents this page links to are in Chinese.

**In one sentence**: once the lab's meshes are exported from Maya, they **do not go through Blender**.
The core program `asrp_core` reads them directly, cuts them into tetrahedra, builds the scene and the motion, hands them to FEBio to compute,
adds the landmark layer, packs the result into a point cache, and finally plays it in
Blender, where it can be compared side by side with Ziva's result.
In this pipeline Blender is the player and the remote control: the buttons on the panel only call `asrp` commands, and the computation is never
done inside Blender ([ADR-03](decisions/ADR-03.md)).

This document strings the whole pipeline together in order and lists the commands and `.py` files each step uses (the code as of 2026-11-16). The
design details of each step are in other documents.
This page only helps you find your way, and the links are in the last section.

```
① Maya export ─→ ② Tetrahedralisation ─→ ③ Build scene description ─→ ④ Prepare motion ─→ ⑤ Build model.feb ─→ ⑥ FEBio computes
   (once only)      (once only)            scene.json                   trajectory.json
                                                                                                                 │
⑪ Blender playback ←─ ⑩ Build PC2 playback package ←─ ⑨ Plausibility checks ←─ ⑧ Add landmark skinning ←─ ⑦ Read back results, embed display mesh
                        │                                                      (only if the motion has landmarks)
                        └─→ ⑫ Compare with Ziva: reads the run folder, does not go through Blender (needs the reference results exported on the Ziva machine)
```

- ① and ② are already done and the results are committed in `data/` ([ADR-19](decisions/ADR-19.md)), so you normally start from ③. Three
  ready-made motions are also committed (section 5);
- ⑤ to ⑩ are all done at once by one command, `asrp run`;
- In the Blender panel, ③ to ⑪ are three buttons: **Open asset** (③ plus reading the motion list), choosing a motion, and **Run** (⑤ to ⑩, and
  the result plays straight away). ⑫ is **Compare with Ziva**.

## 0. Before you start (once per computer)

These are not part of the pipeline itself, but the first step gets stuck without them.
The full commands are in "Setup (Windows)" and "Install the Blender add-on" of the repository's root [README](../README.md) , and in
[15](15-prototype.en.md) section 2.1.

1. **Core program**: install `uv` , install FEBio (free to download after registering at febio.org), run `uv sync` in the project folder, then
   run `uv run asrp doctor` . Every line should say `ok` ;
2. **Blender add-on**: in the project folder, build the add-on package with Blender's `extension build` command. It lands under `dist/` . In
   Blender, go to Edit > Preferences > Add-ons > Install from Disk, choose this package, and tick ASRP;
3. **Project folder**: the first time you open the panel (press N in the 3D view, ASRP tab), choose the project folder once when prompted (Choose
   project folder). The panel uses it to find `data/` and the `asrp` command;
4. **Ziva reference data** (only needed for ⑫): in the panel, choose once the folder that holds the Ziva export (Ziva reference folder). It is
   the lab's data, it lives outside the repository, and its location is recorded only in the add-on's preferences.

## 1. The whole pipeline at a glance

| # | Step | Command (panel button) | Main `.py` files | Input → output | How often |
|---|---|---|---|---|---|
| ① | Maya export | `"<Maya install folder>\bin\mayapy.exe" tools/maya_export.py <scene.mb> data/lab_export` | `tools/maya_export.py` | the lab's `.mb` → OBJ, joints and landmark weights in `data/lab_export/` | Once ([ADR-18](decisions/ADR-18.md)) |
| ② | Tetrahedralisation | `uv run python tools/build_tetmesh.py [--method lattice]` | `tools/build_tetmesh.py`, `src/asrp_core/tetmesh.py` | lips OBJ → `data/tetmesh/lips.json` (fine mesh), `lips_lattice.json` (coarse lattice) | Once ([ADR-20](decisions/ADR-20.md), [ADR-44](decisions/ADR-44.md)) |
| ③ | Build scene description | `uv run asrp import-asset data/lab_export <scene folder>` (**Open asset**) | `src/asrp_core/asset/lab.py`, `asset/coords.py`, `asset/skin.py`, `scene.py` | `data/lab_export/` + a tet mesh → `scene.json` etc. | Whenever the asset, mesh or settings change |
| ④ | Prepare motion | `uv run asrp convert-motion …`, or use a ready-made one (choose a motion) | `src/asrp_core/trajectory.py`, `motions.py` | the lab's motion file → `trajectory.json` | For each new motion |
| ⑤ | Build `model.feb` | `uv run asrp run <scene.json> <trajectory.json>` (**Run**) | `src/asrp_core/generate.py` | `scene.json` + the bones part of the motion → `model.feb` | Every run |
| ⑥ | FEBio computes | same as above | `src/asrp_core/run.py`, `febio.py` | `model.feb` → the position of every tet node in each frame | Every run |
| ⑦ | Read back results, embed display mesh | same as above | `src/asrp_core/run.py`, `embed.py` | tet results → per-frame positions of the 10,240 lip surface vertices; the settled shape | Every run |
| ⑧ | Add landmark skinning | same as above | `src/asrp_core/skinning.py` | physics result + landmark displacement + weights → final shape | When the motion has landmarks |
| ⑨ | Plausibility checks | same as above | `src/asrp_core/plausibility.py` | result → five checks, plus flipped faces and too-short edges, which are only reported | Every run |
| ⑩ | Build PC2 playback package | same as above | `src/asrp_core/playback.py`, `provenance.py` | result → `playback.json` + `playback.pc2` (plus a point cache of the final shape when ⑧ was done) | Every run |
| ⑪ | Blender playback | the panel loads it automatically (or sidebar Load Result) | `blender_addon/asrp_blender/__init__.py`, `asset.py`, `session.py` | playback package → the asset's five objects move on the timeline | After every run |
| ⑫ | Compare with Ziva | `asrp compare` (**Compare with Ziva**, full command in section 8) | `src/asrp_core/ziva_compare.py`, `ziva_export.py`, `compare.py`; `blender_addon/asrp_blender/compare.py` | our run + Ziva's export → comparison report, heat-map data, a playback package of Ziva's lips | Whenever you want to compare |

The overall scheduler for ⑤ to ⑩ is `src/asrp_core/simulate.py` , and the command-line entry point is `src/asrp_core/cli.py` (the `asrp` command
is generated from `[project.scripts]` in `pyproject.toml` ).

## 2. ① Maya export (once only)

**What it does**: open the lab's scene in ordinary Maya (Ziva is not needed) and export what the prototype needs in open formats.
Maya appears only in this step, and the product itself never needs Maya ([ADR-18](decisions/ADR-18.md)).

- `tools/maya_export.py` : runs inside `mayapy` . Exports the rest shape of 5 meshes (lips, jaw, skull, upper and lower teeth) as OBJ in scene
  coordinates; `joints.json` (the jaw joint `jaw01` and 300 landmarks);
  `skin_skinCluster7.json` (the skinning weights of the landmarks on the lips); `mesh_report.json`.
- `tools/check_lab_export.py`: without Maya, reads the vertices straight from the `.mb` and checks them point by point against the exported OBJ.
- `tools/mb_inventory.py` , `tools/lip_attachments.py` : parse the `.mb` without Maya, read out the four groups of attachment vertices on the
  lips, and write them to `data/lab_export/lip_attachments.json` .

**Result**: `data/lab_export/`, committed. The export on the Ziva machine (the reference results ⑫ needs) is a separate matter, see section 8.

## 3. ② Tetrahedralisation (once only)

**What it does**: FEBio can only compute on volume meshes, and the lips the lab gave us are only a surface, so they must first be filled with
tetrahedra (why this is necessary: see [E-02](archive/explanations/E-02.md) ).
The mesh is read directly from the lips OBJ and **does not go through Blender**. There are now two meshes. They exist side by side, and you pick
one as the research needs:

| Mesh | Command | File | Features | Who uses it by default |
|---|---|---|---|---|
| Fine mesh | `uv run python tools/build_tetmesh.py` | `data/tetmesh/lips.json` | Made by fTetWild, about 26,700 tetrahedra; the upper and lower lips are separated along the lip line and can move on their own ([ADR-20](decisions/ADR-20.md)) | The command line's `import-asset` |
| Coarse lattice | `uv run python tools/build_tetmesh.py --method lattice` | `data/tetmesh/lips_lattice.json` | A regular cubic lattice whose edge equals Ziva's tetrahedron size, 126 tetrahedra; the upper and lower lips form one block and are carried along by the jaw, as in Ziva; the output is deterministic and fast to compute ([ADR-44](decisions/ADR-44.md)) | The Blender panel |

Both are checked and read by `src/asrp_core/tetmesh.py` , which verifies the content hash on reading. **They are never regenerated at run time**;
only an explicit run of `tools/build_tetmesh.py` changes
these two files.
The files record the sha256 of the lips OBJ. If the bytes of the OBJ change (for example, line endings get converted), ③ reports an error. When
that happens, check `data/` out again byte for byte
([08](08-engineering-standards.md) section 10, `.gitattributes`) and do not regenerate the meshes.

## 4. ③ Build the scene description `scene.json`

**What it does**: converts the exported asset into the project's common units and axes (mm, Z axis up) and writes it as the project's own scene
description, in the format `asrp-scene/1` .
It answers "what is this model": the soft tissue and materials, which bone moves with what, the attachments, the landmarks, the solver settings,
and where each parameter came from (the lab's setting, or a temporary value we chose).

| File | Role |
|---|---|
| `src/asrp_core/cli.py` | Entry point and options of `asrp import-asset` |
| `src/asrp_core/asset/lab.py` | The main part: reads `data/lab_export/`, writes `scene.json`, the converted meshes, a copy of the tet mesh, and `import_report.json` |
| `src/asrp_core/asset/coords.py` | The only unit and axis conversion in the whole project (× 0.962, Y up → Z up) |
| `src/asrp_core/asset/skin.py` | Converts the landmark skinning weights to millimetres and Z up, and writes `landmarks/skin_mm.json` |
| `src/asrp_core/scene.py` | Format definition and validation of the scene description; `uv run asrp check <scene.json>` uses it too |

**Common options**:

| Option | Default | Notes |
|---|---|---|
| `--tetmesh` | `export folder/../tetmesh/lips.json` (with `data/lab_export` as export folder this is `data/tetmesh/lips.json`, the fine mesh) | To use the coarse lattice, write `--tetmesh data/tetmesh/lips_lattice.json` |
| `--tissue-settings` | `lab` | The material measured in Ziva (Young's modulus 12 kPa, Poisson's ratio 0.4, density, substeps); `ours` is our earlier values |
| `--attachments` | `ours` | The upper lip is hard-attached to the skull and the rest use springs; `ziva-soft` makes all four groups springs, converted from Ziva's soft constraints. The coarse lattice needs `ziva-soft`: in the coarse lattice the upper and lower lips share nodes, so a hard attachment would pin those nodes together with the other lip ([ADR-44](decisions/ADR-44.md)) |
| `--mm-per-scene-unit` | `0.962` | Length conversion |

The panel's Open asset runs this command in the background, using the coarse lattice with `--attachments ziva-soft` (the fine mesh when Fine is
chosen).

**Result**: `scene.json` , `meshes/` , `landmarks/` and `import_report.json` in the scene folder. For what the format must contain, see
[04](archive/prototype/04-v1-architecture.md) section 5.1, and for how the fields are written, see the notes at the top of `scene.py` .

## 5. ④ Prepare the motion `trajectory.json`

**What it does**: writes out "how it moves this time", in the format `asrp-trajectory/1` : the transform of each bone driver per frame (how far
the jaw `jaw01` rotates, how far the head translates),
a settling section in the first few frames with gravity only, optionally the displacement of the 300 landmarks per frame, and the title shown on
the panel. The same `scene.json` can be paired with different motions.

**Three ready-made motions**, committed in `data/lab_export/trajectories/`. The panel's motion list is exactly these:

| File | What it is | Where it comes from |
|---|---|---|
| `neutral_to_AA.json` | The lab's real neutral to AA: the jaw rotates −5.16°, plus landmark displacement | The lab's motion file, converted with `asrp convert-motion` ([T-34](archive/tasks/T-34.md), [ADR-42](archive/decisions/ADR-42.md)) |
| `jaw_open_12deg.json` | Prototype one's stand-in jaw opening: the jaw opens to 12° and closes again | `tools/placeholder_jaw_motion.py` |
| `head_shake.json` | Head shake, following the keyframes in the lab's script | `tools/head_shake_motion.py` |

**A new motion**: the output of the lab's controller is a Python pickle file (`combined_checkpoints.pkl`). Convert it with one command, and **no
new code needs to be written**:

```bash
uv run asrp convert-motion <the lab's motion file> <scene.json> <output trajectory.json> --starts-at-rest --title "<name shown on the panel>"
```

- `src/asrp_core/trajectory.py` : format, reading, writing and validation of the motion file; generation of hinge motions; `read_lab_motion`
  reads the lab's pickle safely (it accepts only basic containers and
  arrays and never runs code in the file), and `from_lab_motion` does the conversion.
- `src/asrp_core/motions.py`: lists the motions in an export folder (`asrp list-motions`, which the panel's motion list uses).
- `tools/placeholder_jaw_motion.py`, `tools/head_shake_motion.py`: the two motions we made ourselves.

`asrp set-motion-title <file> "<title>"` changes the name shown on the panel.
The conversion today handles only "one transition starting from neutral". How to convert the lab's motion files in general is still open under
[T-10](tasks/T-10.md) .
For what the format must contain, see [04](archive/prototype/04-v1-architecture.md) section 5.2, and for how the fields are written, see the notes at the top of
`trajectory.py` .

## 6. ⑤–⑩ One run: `asrp run`

```bash
uv run asrp run <scene.json> <trajectory.json>
```

`src/asrp_core/simulate.py` does all the steps below in order, and puts every input and result into the same run folder (by default under `runs/`
, [04](archive/prototype/04-v1-architecture.md) section 4).
The panel's Run runs this command in the background.

- **⑤ Build `model.feb` **: `generate.py` translates the scene and the motion into FEBio's input: coordinates multiplied by k
  ([ADR-36](decisions/ADR-36.md)), gravity sign reversed
  ([05 pitfalls](05-febio-pits.md) pitfall 1), rigid bodies, attachments, dynamics settings. **It reads only the bones part of the motion, and
  the landmark section does not go into FEBio.**
  When the scene fails its checks it refuses to build, and no run folder is created.
- **⑥ FEBio computes**: `run.py` creates the run folder, copies the inputs in, starts FEBio, reads the progress, and can cancel; `febio.py` does
  the actual call to `febio4.exe` (4 threads by default,
  [ADR-38](decisions/ADR-38.md)).
- **⑦ Read back results, embed display mesh**: `run.py` reads back the position of every tet node in each frame and divides by k; `embed.py`
  makes the lab's detailed lip surface (10,240 vertices) follow the tet mesh by
  barycentric coordinates. Later steps and playback all use this surface. The shape of the last settling frame (frame n; frame 14 for the lab's
  motions) is saved separately for playback comparison and new experiments; it is not the starting point of controller training, whose base is
  the rest shape without settling ([ADR-30](decisions/ADR-30.md) 2026-11-13 status line, [ADR-42](archive/decisions/ADR-42.md) ).
- **⑧ Add landmark skinning**: done only when the motion has a `landmarks` section. `skinning.py` computes final shape = physics result + weights
  × landmark displacement. The physics result is
  kept as it is, and the final shape is saved as a separate copy. Why it comes after the physics: the lab's scene and source code do physics
  first and skinning after ([ADR-29](decisions/ADR-29.md), [04](archive/prototype/04-v1-architecture.md) section 2).
- **⑨ Plausibility checks**: `plausibility.py` makes five checks ([07](07-validation.md) section 3): whether the motion finished computing,
  whether the hard-attached places follow the bones, whether the spring
  anchors follow the rigid bodies, whether gravity pulls downwards, and whether any tetrahedra were crushed inside out.
  - If any one fails, the command exits with a code other than 0; "not run" does not count as failed. With the coarse lattice and `ziva-soft`
    there is no hard attachment, so the second check (the hard-attached places) always shows **not run** (NOT RUN), and this is
    normal.
  - The report also shows the display surface's flipped faces and too-short edges, to be read side by side with Ziva's own numbers. They are
    reported only and not judged against a pass line ([ADR-43](decisions/ADR-43.md)).
- **⑩ Build the PC2 playback package**: `playback.py` writes `playback.json` (the surface mesh and metadata) and `playback.pc2` (the vertex
  coordinates of each frame); when ⑧ was done it adds a point cache of the
  final shape. `provenance.py` writes the provenance record. For the PC2 format and the playback package, see [04](archive/prototype/04-v1-architecture.md) section
  5.3.

## 7. ⑪ Blender playback

**What it does**: the asset's five objects (skull, jaw, upper teeth, lower teeth, lips) were already built at Open asset.
When Run finishes, the lips get a Mesh Cache modifier that reads the PC2, the bones get a keyframe on every frame from `trajectory.json` , the
timeline is set to the motion's frame count and frame rate, and you press Space to play.
Running again only replaces the modifier and the keyframes, not the objects. Blender does no computation.

**Which layer is shown by default**: when the run result has a final shape (the motion carries landmarks, for example neutral to AA), the lips
show the **final shape** (physics + landmark layer) by default.
When there is only a physics layer (for example jaw open 12°, head shake), the physics layer is shown.
The panel has two buttons, **Final shape** and **Physics only**. The one that is pressed is the layer being shown, and clicking the other
switches to it (when there is only a physics layer there is only one button).

- `blender_addon/asrp_blender/__init__.py` : the panel and buttons: the three steps, Checks (the five checks and flipped faces), the read-only
  Physics setup, and Load Result (load a run folder by hand, with switching between the physics layer and the final shape).
- `blender_addon/asrp_blender/asset.py` : implementation of the three steps: Open asset runs `asrp import-asset` and `asrp list-motions` in the
  background and builds the objects; when a run finishes it puts the result onto these objects.
- `blender_addon/asrp_blender/session.py`: starts `asrp run` (and `asrp compare`) in the background, shows progress, and can cancel.
- `tools/render_prototype.py` : optional: without opening the interface, renders a run to images and checks frame by frame the lips in Blender
  against FEBio's numbers.

For what you should see at each step of the panel, with screenshots, see [15](15-prototype.en.md) section 2. For installing the add-on, see the
repository root's [README](../README.md) . For the panel design, see [06](06-ui.md) .

## 8. ⑫ Compare with Ziva

**What it does**: compares the lips from one of our runs (read directly from the physics layer and the final shape in the run folder) with Ziva's
lips for the same motion and the same frame, vertex by vertex.
The physics layer (before skinning) and the final shape (after skinning) are reported separately, and each frame gives three numbers: mean, 95%
and max ([07](07-validation.md) section 4.2).
The difference from Ziva is for reference only, with no pass line ([ADR-17](decisions/ADR-17.md)).

```bash
uv run asrp compare <our run folder> <Ziva's export folder> --out <output folder>
```

- `src/asrp_core/ziva_export.py` : reads Ziva's export folder (the points of each data stream, the rest shape, the motion record) and takes the
  frames that are really in the files.
- `src/asrp_core/compare.py`: computes the difference between two sets of shapes: mean, 95%, max. Numbers only, no judgement.
- `src/asrp_core/ziva_compare.py` : the body of `asrp compare` : converts Ziva's coordinates, compares frame by frame, and writes
  `compare_report.json` , the heat-map data (`heatmap_*.f32`) and a playback package of Ziva's lips.
- `blender_addon/asrp_blender/compare.py` : the panel's Compare with Ziva: shows the difference numbers, adds Ziva's lips as a second object, and
  colours it by each vertex's difference.
- `tools/ziva_comparison.py` : does the whole comparison in one go (import, convert the motion, run AA and head shake, compare the two runs with
  Ziva) and writes a report of numbers ([T-34](archive/tasks/T-34.md)).
- `tools/render_comparison.py`: comparison images and animations for the results page.

**Where Ziva's export comes from**: it is exported on the Ziva machine with `tools/ziva_machine_export.py` ([12](12-lab-export-checklist.md); for
the results of the visit to the machine, see [E-11](explanations/E-11.md) ).
This is the lab's data and it is **kept outside the repository**: `tools/lab_trip_manifest.py` builds an inventory of the files brought back, the
location on this machine is recorded in `.local/` , which git ignores, and the code reads it through `tools/local_paths.py` .
The output of `asrp compare` contains Ziva's shapes, so the output folder must also be outside the repository, or under `runs/` , which git does
not take.

**The current numbers** (neutral to AA, frame 36, physics layer, against Ziva full face): coarse lattice mean 1.88 mm, max 5.12 mm
([01](01-overview.md); for details see
[E-19](13-explanations.md#e-19-用实验室的真实运动重跑以后我们的嘴唇和-ziva-差多少t-34-的基线) and [15](15-prototype.en.md)).

## 9. A few easy misunderstandings

- **Blender is not in the middle**: the exported OBJ is read directly by `asrp_core` . The buttons on the panel also only call `asrp` commands.
  `tools/blender_import_preview.py` imports the meshes into Blender, but it only
  produces preview images so that someone can check at a glance that the export is right. It is not part of the computation pipeline.
- **Not every input goes into FEBio**: `scene.json` and the bones part of the motion go into FEBio through `generate.py` . The landmark
  displacement and the skinning weights do not. They are used only after
  FEBio has finished (⑧).
- **`scene.json` and `trajectory.json` are formats the project defines itself**, not FEBio's. The project's own formats all begin with `asrp-` ,
  for example `asrp-scene/1` , `asrp-trajectory/1` , `asrp-playback/1` ,
  `asrp-skin/1` . They are split into intermediate files so that the same model can be paired with different motions, so that embedding, checks
  and playback can read them too, and so that changing the solver later only means rewriting ⑤ ([04](archive/prototype/04-v1-architecture.md) section 6).
- **The tet mesh is not generated on every run**: both meshes are generated only once, explicitly, by `tools/build_tetmesh.py`
  ([ADR-20](decisions/ADR-20.md), [ADR-44](decisions/ADR-44.md) ).
- **A new motion needs no new code**: the lab's motion files are converted with `asrp convert-motion` . Only the stand-in motions we made
  ourselves have a script each.
- **The training line and the playback line are two different paths**: this document is about the playback line, where the physics is computed
  frame by frame and the landmark layer is added on top.
  When the lab trains the controller it needs something else: at each step, lips given as "rest shape + landmark displacement", with no FEBio
  run. This interface is `src/asrp_core/final_shape.py` ([T-31](archive/tasks/T-31.md), [E-13](explanations/E-13.md) ).

## 10. What is not finished yet

| What | Status | Task |
|---|---|---|
| How to convert the lab's motion files in general (today only one transition starting from neutral is handled) | The motion files have been collected, the single transition is done | [T-10](tasks/T-10.md) |
| Aligning the physical scale and gravity with Ziva: our gravity sag is much smaller than Ziva's | Not started, needs another visit to the Ziva machine to calibrate | [T-41](tasks/T-41.md) |
| Bringing the code's defaults in line with the measured facts | Partly done | [T-37](archive/tasks/T-37.md) |
| Building the scene in Blender ourselves by following Ziva's workflow (marking bones and soft tissue, building the tetrahedra, seeing the attachments) | Not started | [T-39](tasks/T-39.md) |

## 11. Where the details of each step are

| To find out | See |
|---|---|
| How the system is divided, what each module is responsible for, what is in the run folder | [04](archive/prototype/04-v1-architecture.md) sections 1, 3, 4 |
| The steps after `asrp run` is clicked (from the add-on's point of view) | [04](archive/prototype/04-v1-architecture.md) section 8 |
| What `scene.json`, `trajectory.json` and the playback package must contain | [04](archive/prototype/04-v1-architecture.md) section 5 |
| How each Ziva setting is expressed in the new system, and the pitfalls we hit | [05](05-ziva-to-febio.md), [05 pitfalls](05-febio-pits.md) |
| How to operate the panel, what you should see at each step, and how to do it from the command line | [15](15-prototype.en.md) section 2 |
| How far we are from Ziva, and why | [15](15-prototype.en.md), [E-19](13-explanations.md#e-19-用实验室的真实运动重跑以后我们的嘴唇和-ziva-差多少t-34-的基线) |
| The Maya export and the export on the Ziva machine | [12](12-lab-export-checklist.md) |
| Why tetrahedralise, and why there are two meshes | [E-02](archive/explanations/E-02.md), [ADR-20](decisions/ADR-20.md), [ADR-44](decisions/ADR-44.md) |
| What the plausibility checks look at | [07](07-validation.md) section 3 |
