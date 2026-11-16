"""Pictures of the lips and bones for docs/15: stills of the lips alone, and animated front views of the whole mouth.

    uv run python tools/render_comparison.py --coarse-aa <run> --fine-aa <run> --ziva <Ziva export folder>
                                             [--coarse-jaw <run> --fine-jaw <run>] [--coarse-shake <run>]
                                             [--out data/preview] [--no-animation]

Requirement of the animated pictures: ffmpeg (https://ffmpeg.org) must be on the PATH. It assembles the frames Blender
draws into GIFs and puts the panels side by side. Without it the tool stops at the start with one plain sentence
(`--no-animation` skips the GIFs and the front stills and needs no ffmpeg). No Python package is added.

Written for the page, and run again whenever its numbers change. It runs in two halves. This half (plain Python)
reads our runs with the product's reader and Ziva's export with the reader `asrp compare` uses (ziva_compare.read_ziva,
which sits on ziva_export.py), picks the frames, and writes the points into one temporary .npz. Then it starts Blender
with `--background` (never a window) on this same file, and that half renders PNG frames with the Workbench engine.
Back in this half, ffmpeg builds the GIFs (palettegen + paletteuse for a clean palette) and the stills.

Two kinds of picture, both from the same orthographic camera that looks along -Y (the face looks down +Y, docs/04
section 3):

  Lips alone (one colour, white background, 0.10 m wide, centred on the middle of the lips at rest). Triangles are the
  rest triangles of the lab's lip mesh (Ziva re-triangulates every frame, the vertex numbering does not change, so every
  source is drawn on the same triangles):

    prototype_aa36_physics_{coarse,fine,ziva}.png    the physics layer at frame 36 (the end of the AA motion)
    prototype_aa36_final_{coarse,fine,ziva}.png      the final shape (physics plus the landmark layer) at frame 36
    prototype_jaw32_{coarse,fine}.png                the jaw-opens-12-degrees motion at its widest frame, physics layer

  The lower face from the front (150 mm square: lips, upper teeth, lower teeth, jaw and chin, the skull behind), the
  bones light grey, the lips red, the same camera and shading in every panel, a small caption under each panel's name.
  The bones move by OUR motion file in every panel, including Ziva's: Ziva's export holds lips only, so the bones next
  to Ziva's lips are ours (the page says the jaw of our motion equals Ziva's recorded jaw01 to 1e-13 mm).

    prototype_aa_front.gif            AA motion, frames 0 to 46, final shape: ours coarse | ours fine | Ziva full face
    prototype_aa_front_physics.gif    the same, physics layer
    prototype_jaw_front.gif           jaw opens 12 degrees, frames 0 to 50, physics layer: ours coarse | ours fine
    prototype_shake_front.gif         head shake, frames 0 to 86, physics layer: ours coarse
    prototype_aa36_front_{final,physics}.png   frame 36 of the two AA pictures
    prototype_jaw32_front.png                  frame 32 of the jaw picture

  The GIFs run at 30 frames per second, loop forever and hold the last frame for about one second (HOLD_FRAMES
  repeats of it, so each GIF has FRAMES + HOLD_FRAMES images).

The pictures hold the lab's lip mesh drawn as an image: the repository is private and already holds pictures of that
mesh (ADR-19). No vertex data of Ziva's runs is written anywhere in the repository: the .npz lives in a temporary
folder that is deleted afterwards.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AA_FRAME = 36
JAW_FRAME = 32
WIDTH_M = 0.10
SIZE = (600, 600)
LIP_COLOUR = (0.86, 0.36, 0.38, 1.0)

# --- the front views ----------------------------------------------------------------------------------------
FPS = 30
HOLD_FRAMES = 30  # the last frame is repeated this often: one second
PANEL_PX = 420
CAPTION_PX = 56
FRONT_CENTRE_MM = (0.0, -92.0)  # left-right, up-down of the middle of the picture: lower face (chin at about -153, nose base at about -45)
FRONT_WIDTH_MM = 150.0
BACKGROUND = (0.93, 0.93, 0.93)
BONE_COLOUR = (0.80, 0.80, 0.80, 1.0)
TEETH_COLOUR = (0.96, 0.96, 0.94, 1.0)
CAPTION_COLOUR = (0.12, 0.12, 0.12, 1.0)
GIF_COLOURS = 48  # palette size; the size of each GIF is checked against GIF_LIMIT_BYTES by the caller of this tool
GIF_LIMIT_BYTES = 2_500_000

# name of the picture -> number of images in it (frames of the motion + the hold)
GIF_FRAMES = {
    "prototype_aa_front.gif": 47 + HOLD_FRAMES,
    "prototype_aa_front_physics.gif": 47 + HOLD_FRAMES,
    "prototype_jaw_front.gif": 51 + HOLD_FRAMES,
    "prototype_shake_front.gif": 87 + HOLD_FRAMES,
}
FRONT_STILLS = ["prototype_aa36_front_final.png", "prototype_aa36_front_physics.png", "prototype_jaw32_front.png"]
LIPS_STILLS = [f"prototype_aa36_{layer}_{who}.png" for layer in ("physics", "final") for who in ("coarse", "fine", "ziva")] + [
    "prototype_jaw32_coarse.png", "prototype_jaw32_fine.png"]
ANIMATED_PICTURES = sorted(GIF_FRAMES) + FRONT_STILLS


def ffmpeg_or_stop() -> str:
    found = shutil.which("ffmpeg")
    if found is None:
        raise SystemExit("ffmpeg was not found on the PATH. The animated pictures need it: install ffmpeg (https://ffmpeg.org; "
                         "on Windows `winget install Gyan.FFmpeg`), open a new terminal so that `ffmpeg -version` works, and run "
                         "this again (or add --no-animation to make the stills of the lips alone).")
    return found


def read_obj_triangles(path: Path):
    import numpy as np

    vertices, faces = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                vertices.append([float(c) for c in line.split()[1:4]])
            elif line.startswith("f "):
                ids = [int(c.split("/")[0]) - 1 for c in line.split()[1:]]
                faces += [[ids[0], ids[k], ids[k + 1]] for k in range(1, len(ids) - 1)]  # a fan: triangles stay, quads become two
    return np.array(vertices, dtype=np.float64), np.array(faces, dtype=np.int64)


def bone_motion(run, frames: int):
    """{bone: (frames, 4, 4) transforms in mm} of a run, read the way the panel's apply_result reads them: a prescribed bone
    follows the motion file's driver, a bone whose driver the motion leaves out (and that may be left out) stays at rest."""
    import numpy as np

    scene = json.loads(Path(run.scene_path).read_text(encoding="utf-8"))
    traj = json.loads((Path(run.scene_path).parent / "trajectory.json").read_text(encoding="utf-8"))
    drivers = {d["name"]: d for d in scene.get("drivers", [])}
    rest = np.tile(np.eye(4), (frames, 1, 1))
    out = {}
    for bone in scene["bones"]:
        out[bone["name"]] = rest
        if bone.get("motion") != "prescribed":
            continue
        driver = bone["driver"]
        if drivers.get(driver, {}).get("blend") is not None:
            raise SystemExit(f"bone {bone['name']!r} follows the derived driver {driver!r}; the pictures play only the motion file's own drivers")
        rows = traj["drivers"].get(driver)
        if rows is None:
            if drivers.get(driver, {}).get("absent_means_rest"):
                continue
            raise SystemExit(f"the motion has no transforms for {driver!r}, which the bone {bone['name']!r} follows")
        mats = np.asarray(rows, dtype=np.float64).reshape(-1, 4, 4)
        if len(mats) != frames:
            raise SystemExit(f"the motion of {Path(run.scene_path).parent.name} has {len(mats)} frames for {driver!r}, the run {frames}")
        out[bone["name"]] = mats
    return out


def main_python() -> None:
    sys.path.insert(0, str(REPO / "src"))
    import numpy as np

    from asrp_core import ziva_compare
    from asrp_core.doctor import BLENDER_CANDIDATES, locate

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--coarse-aa", required=True, help="run folder of the AA motion on the coarse lattice")
    parser.add_argument("--fine-aa", required=True, help="run folder of the AA motion on the fine mesh")
    parser.add_argument("--ziva", required=True, help="the Ziva export folder of the full-face AA run (outside the repo)")
    parser.add_argument("--coarse-jaw", help="run folder of the 12 degree jaw motion on the coarse lattice")
    parser.add_argument("--fine-jaw", help="run folder of the 12 degree jaw motion on the fine mesh")
    parser.add_argument("--coarse-shake", help="run folder of the head shake on the coarse lattice")
    parser.add_argument("--out", default=str(REPO / "data" / "preview"))
    parser.add_argument("--no-animation", action="store_true", help="only the stills of the lips alone (needs no ffmpeg)")
    args = parser.parse_args()
    ffmpeg = None if args.no_animation else ffmpeg_or_stop()

    ours = {"coarse": ziva_compare.read_run(args.coarse_aa), "fine": ziva_compare.read_run(args.fine_aa)}
    frames = ours["coarse"].side.physics.shape[0]
    ziva = ziva_compare.read_ziva(args.ziva, ours["coarse"].mm_per_scene_unit, frames)
    shown: dict[str, np.ndarray] = {}
    for name, run in ours.items():
        if run.side.final is None:
            raise SystemExit(f"the {name} AA run has no final shape: it is not a run of the lab's AA motion")
        shown[f"prototype_aa36_physics_{name}"] = run.side.physics[AA_FRAME]
        shown[f"prototype_aa36_final_{name}"] = run.side.final[AA_FRAME]
    if ziva.side.final is None:
        raise SystemExit(ziva.side.final_missing)
    shown["prototype_aa36_physics_ziva"] = ziva.side.physics[AA_FRAME]
    shown["prototype_aa36_final_ziva"] = ziva.side.final[AA_FRAME]
    jaw = {}
    for name, folder in (("coarse", args.coarse_jaw), ("fine", args.fine_jaw)):
        if folder:
            jaw[name] = ziva_compare.read_run(folder)
            shown[f"prototype_jaw32_{name}"] = jaw[name].side.physics[JAW_FRAME]

    rest = ours["coarse"].side.physics[0]
    centre = (rest.min(axis=0) + rest.max(axis=0)) / 2
    blender = locate("ASRP_BLENDER", ["blender"], BLENDER_CANDIDATES)
    if blender.path is None:
        raise SystemExit("Blender not found (set ASRP_BLENDER)")

    # --- the animated front views: what each panel shows -----------------------------------------------------
    arrays: dict[str, np.ndarray] = {}
    sequences, bone_names = [], []
    if ffmpeg is not None:
        def lips(key: str, points) -> str:
            arrays[key] = np.asarray(points, dtype=np.float32)
            return key

        for layer, still, gif in (("final", "prototype_aa36_front_final.png", "prototype_aa_front.gif"),
                                  ("physics", "prototype_aa36_front_physics.png", "prototype_aa_front_physics.gif")):
            sub = "final shape" if layer == "final" else "physics layer"
            pick = (lambda s: s.final) if layer == "final" else (lambda s: s.physics)
            panels = [
                {"id": "coarse", "title": "ours, coarse lattice", "subtitle": sub, "lips": lips(f"lips_aa_{layer}_coarse", pick(ours["coarse"].side))},
                {"id": "fine", "title": "ours, fine mesh", "subtitle": sub, "lips": lips(f"lips_aa_{layer}_fine", pick(ours["fine"].side))},
                {"id": "ziva", "title": "Ziva, full face", "subtitle": f"{sub}; bones are ours", "lips": lips(f"lips_aa_{layer}_ziva", pick(ziva.side))},
            ]
            sequences.append({"name": f"aa_{layer}", "motion": "aa", "frames": frames, "gif": gif, "still": still, "still_frame": AA_FRAME,
                              "panels": panels})
        motions = {"aa": ours["coarse"]}
        if len(jaw) == 2:
            motions["jaw"] = jaw["coarse"]
            sequences.append({"name": "jaw", "motion": "jaw", "frames": jaw["coarse"].side.physics.shape[0],
                              "gif": "prototype_jaw_front.gif", "still": "prototype_jaw32_front.png", "still_frame": JAW_FRAME,
                              "panels": [{"id": who, "title": f"ours, {label}", "subtitle": "physics layer, jaw opens 12 deg",
                                          "lips": lips(f"lips_jaw_{who}", jaw[who].side.physics)}
                                         for who, label in (("coarse", "coarse lattice"), ("fine", "fine mesh"))]})
        if args.coarse_shake:
            shake = ziva_compare.read_run(args.coarse_shake)
            motions["shake"] = shake
            sequences.append({"name": "shake", "motion": "shake", "frames": shake.side.physics.shape[0], "gif": "prototype_shake_front.gif",
                              "still": None, "still_frame": None,
                              "panels": [{"id": "coarse", "title": "ours, coarse lattice", "subtitle": "physics layer, head shake",
                                          "lips": lips("lips_shake_coarse", shake.side.physics)}]})
        for seq in sequences:
            assert seq["frames"] == GIF_FRAMES[seq["gif"]] - HOLD_FRAMES, (seq["gif"], seq["frames"])
            for panel in seq["panels"]:
                assert arrays[panel["lips"]].shape[0] == seq["frames"], (seq["name"], panel["id"])
        aa_scene = json.loads(Path(ours["coarse"].scene_path).read_text(encoding="utf-8"))
        bone_names = [b["name"] for b in aa_scene["bones"]]
        for bone in aa_scene["bones"]:
            vertices, faces = read_obj_triangles(Path(ours["coarse"].scene_path).parent / bone["mesh"]["path"])
            arrays[f"bone_verts_{bone['name']}"], arrays[f"bone_faces_{bone['name']}"] = vertices, faces
        for motion, run in motions.items():
            seq_frames = next(s["frames"] for s in sequences if s["motion"] == motion)
            moved = bone_motion(run, seq_frames)
            if list(moved) != bone_names:
                raise SystemExit(f"the {motion} run has other bones than the AA run")
            for name, mats in moved.items():
                arrays[f"mats_{motion}_{name}"] = mats

    work = Path(tempfile.mkdtemp(prefix="asrp_render_comparison_"))
    try:
        np.savez(work / "points.npz", triangles=np.asarray(ziva.triangles, dtype=np.int64), centre=centre,
                 names=np.array(sorted(shown)), bone_names=np.array(bone_names),
                 **{k: np.asarray(v, dtype=np.float64) for k, v in shown.items()}, **arrays)
        plan = {"sequences": sequences, "panel_px": PANEL_PX, "caption_px": CAPTION_PX}
        (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8", newline="\n")
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([str(blender.path), "--background", "--factory-startup", "--python-exit-code", "1",
                               "--python", str(Path(__file__).resolve()), "--", str(work / "points.npz"), str(out)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        sys.stdout.write("".join(ln + "\n" for ln in done.stdout.splitlines() if ln.startswith("rendered ")))
        if done.returncode != 0:
            raise SystemExit(f"Blender failed:\n{done.stdout[-1500:]}\n{done.stderr[-1500:]}")
        for seq in sequences:
            assemble(ffmpeg, work, out, seq)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_ffmpeg(ffmpeg: str, *args) -> None:
    done = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{done.stderr[-1500:]}")


def assemble(ffmpeg: str, work: Path, out: Path, seq: dict) -> None:
    """The panels of one sequence side by side, each under its caption: the GIF, and the still of one frame."""
    panels, n = seq["panels"], len(seq["panels"])
    frames = work / "frames" / seq["name"]
    captions = [work / "captions" / f"{seq['name']}_{p['id']}.png" for p in panels]

    def stack(first_inputs: list) -> tuple[list, str]:
        inputs = [*first_inputs]
        for cap in captions:
            inputs += ["-loop", "1", "-framerate", FPS, "-i", cap]
        chains = ";".join(f"[{n + i}:v][{i}:v]vstack=inputs=2:shortest=1[c{i}]" for i in range(n))
        row = "".join(f"[c{i}]" for i in range(n)) + (f"hstack=inputs={n}" if n > 1 else "null")
        return inputs, f"{chains};{row}"

    if seq["still"]:
        inputs, graph = stack([a for p in panels for a in ("-i", frames / p["id"] / f"f{seq['still_frame']:03d}.png")])
        run_ffmpeg(ffmpeg, *inputs, "-filter_complex", graph, "-frames:v", 1, "-update", 1, out / seq["still"])
        print(f"rendered {seq['still']}")
    inputs, graph = stack([a for p in panels for a in ("-framerate", FPS, "-i", frames / p["id"] / "f%03d.png")])
    graph += (f",tpad=stop_mode=clone:stop_duration={HOLD_FRAMES / FPS:g},split[a][b];[a]palettegen=max_colors={GIF_COLOURS}:stats_mode=full[p];"
              "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    run_ffmpeg(ffmpeg, *inputs, "-filter_complex", graph, "-loop", 0, out / seq["gif"])
    size = (out / seq["gif"]).stat().st_size
    print(f"rendered {seq['gif']}: {size / 1e6:.2f} MB" + ("" if size <= GIF_LIMIT_BYTES else f"  (OVER {GIF_LIMIT_BYTES / 1e6:.1f} MB)"))


def main_blender() -> None:
    import math

    import bpy
    import numpy as np
    from mathutils import Matrix

    args = sys.argv[sys.argv.index("--") + 1:]
    data = np.load(args[0], allow_pickle=False)
    work = Path(args[0]).parent
    out = Path(args[1])
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    triangles = data["triangles"].tolist()
    centre = data["centre"] / 1000.0  # millimetres to the metres the camera uses

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.render_aa = "8"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "SINGLE"
    shading.single_color = LIP_COLOUR[:3]
    shading.show_object_outline = False
    shading.show_xray = False
    scene.world.color = (1.0, 1.0, 1.0)
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"

    cam_data = bpy.data.cameras.new("front")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = WIDTH_M
    cam = bpy.data.objects.new("front", cam_data)
    cam.location = (centre[0], centre[1] + 0.4, centre[2] - 0.004)
    cam.rotation_euler = (math.pi / 2, 0, math.pi)  # looks along -Y at the face, Z up
    scene.collection.objects.link(cam)
    scene.camera = cam

    obj = None
    for name in [str(n) for n in data["names"]]:
        points = data[name]
        if obj is None:
            mesh = bpy.data.meshes.new("lips")
            mesh.from_pydata(points.tolist(), [], triangles)
            obj = bpy.data.objects.new("lips", mesh)
            obj.scale = (0.001,) * 3
            scene.collection.objects.link(obj)
        else:
            obj.data.vertices.foreach_set("co", points.reshape(-1).tolist())
            obj.data.update()
        scene.render.filepath = str(out / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print(f"rendered {name}: {scene.render.filepath}")

    if plan["sequences"]:
        bpy.data.objects.remove(obj)
        render_front(scene, data, plan, work, triangles, Matrix)


def render_front(scene, data, plan, work: Path, triangles, Matrix) -> None:
    """The animated front views: every frame of every panel as a PNG in <work>/frames/<sequence>/<panel>/, the captions
    as PNG strips in <work>/captions/. The camera, the light and the shading are the same for every panel."""
    import math

    import bpy
    import numpy as np

    px, cap_px = plan["panel_px"], plan["caption_px"]
    shading = scene.display.shading
    shading.color_type = "OBJECT"
    scene.world.color = BACKGROUND
    (work / "captions").mkdir(exist_ok=True)

    # the captions: flat dark text on the background, drawn from straight above in their own orthographic camera
    cap_cam_data = bpy.data.cameras.new("caption")
    cap_cam_data.type = "ORTHO"
    cap_cam_data.ortho_scale = px / 100.0  # 100 pixels to the unit, so a size-0.3 text is about 30 pixels high
    cap_cam = bpy.data.objects.new("caption", cap_cam_data)
    cap_cam.location = (0.0, 0.0, 5.0)
    scene.collection.objects.link(cap_cam)
    scene.camera = cap_cam
    scene.render.resolution_x, scene.render.resolution_y = px, cap_px
    shading.light = "FLAT"
    for seq in plan["sequences"]:
        for panel in seq["panels"]:
            texts = []
            for body, size, y in ((panel["title"], 0.30, 0.14), (panel["subtitle"], 0.21, -0.14)):
                curve = bpy.data.curves.new("text", "FONT")
                curve.body, curve.size, curve.align_x, curve.align_y = body, size, "CENTER", "CENTER"
                text = bpy.data.objects.new("text", curve)
                text.location = (0.0, y, 0.0)
                text.color = CAPTION_COLOUR
                scene.collection.objects.link(text)
                texts.append(text)
            scene.render.filepath = str(work / "captions" / f"{seq['name']}_{panel['id']}.png")
            bpy.ops.render.render(write_still=True)
            for text in texts:
                curve = text.data
                bpy.data.objects.remove(text)
                bpy.data.curves.remove(curve)

    # the panels
    scene.render.resolution_x, scene.render.resolution_y = px, px
    shading.light = "STUDIO"
    cam_data = bpy.data.cameras.new("panel")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = FRONT_WIDTH_MM / 1000.0
    cam = bpy.data.objects.new("panel", cam_data)
    cam.location = (FRONT_CENTRE_MM[0] / 1000.0, 0.5, FRONT_CENTRE_MM[1] / 1000.0)
    cam.rotation_euler = (math.pi / 2, 0, math.pi)  # looks along -Y at the face, Z up
    scene.collection.objects.link(cam)
    scene.camera = cam

    def make(name, vertices, faces, colour):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        obj = bpy.data.objects.new(name, mesh)
        obj.color = colour
        scene.collection.objects.link(obj)
        return obj

    scale = Matrix.Scale(0.001, 4)  # the points are millimetres
    bones = {}
    for name in [str(n) for n in data["bone_names"]]:
        colour = TEETH_COLOUR if name.startswith("teeth") else BONE_COLOUR
        bones[name] = make(name, data[f"bone_verts_{name}"].tolist(), data[f"bone_faces_{name}"].tolist(), colour)
    count = int(data["triangles"].max()) + 1
    lips = make("lips", np.zeros((count, 3)).tolist(), triangles, LIP_COLOUR)
    lips.scale = (0.001,) * 3
    for seq in plan["sequences"]:
        mats = {name: data[f"mats_{seq['motion']}_{name}"] for name in bones}
        for panel in seq["panels"]:
            points = data[panel["lips"]]
            folder = work / "frames" / seq["name"] / panel["id"]
            folder.mkdir(parents=True, exist_ok=True)
            for frame in range(seq["frames"]):
                lips.data.vertices.foreach_set("co", np.ascontiguousarray(points[frame], dtype=np.float32).reshape(-1))
                lips.data.update()
                for name, bone in bones.items():
                    bone.matrix_world = scale @ Matrix(mats[name][frame].tolist())
                scene.render.filepath = str(folder / f"f{frame:03d}.png")
                bpy.ops.render.render(write_still=True)
            print(f"rendered {seq['name']} {panel['id']}: {seq['frames']} frames")


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401  (only inside Blender)
    except ImportError:
        main_python()
    else:
        main_blender()
