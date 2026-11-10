"""Spike S2b (T-04): does the saved lip tet mesh solve in FEBio?

Two models on data/tetmesh/lips.json (mm, N, MPa, s; mass in tonnes), with placeholder material
(neo-Hookean, E 20 kPa, v 0.45, 1060 kg/m3, as S1; the real values wait for Q4):

- smoke (T-04 M4): the back band of the lips (BACK_BAND_MM from the back) fixed, gravity only,
  dynamic, SMOKE_FRAMES frames at 30 fps. Checks that can fail: normal termination, every frame
  present for every node, fixed nodes stay put, the rest sags under gravity on average.
- jaw (T-04 I1, a report, not a pass/fail gate): the same back band, split by height at the mouth
  slit: the upper part fixed, the lower part tied to a rigid jaw that turns about the real jaw01
  hinge (data/lab_export/joints.json, scene units -> mm, Maya Y up -> Z up) by JAW_DEG over
  JAW_FRAMES frames. Prints whether FEBio got there, where it failed, and the largest stretch.

    uv run python spikes/s2_lips_febio.py smoke [out_dir]
    uv run python spikes/s2_lips_febio.py jaw [out_dir] [free band mm around the slit, default 0]
"""

import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from asrp_core import febio, tetmesh
from asrp_core.doctor import febio_exe

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from build_tetmesh import read_lips_mm  # noqa: E402
SAVED = REPO / "data" / "tetmesh" / "lips.json"
JOINTS = REPO / "data" / "lab_export" / "joints.json"

FPS = 30
SMOKE_FRAMES = 15
JAW_FRAMES = 30
JAW_DEG = 15.0
BACK_BAND_MM = 5.0
GRAVITY = -9810.0  # mm/s^2, physical direction: -z. Written with its sign flipped (docs/05 pit 1).
TISSUE = {"density": 1.06e-9, "E": 0.02, "v": 0.45}
JAW_DENSITY = 1.9e-9


def hinge_mm(mm_per_scene_unit: float) -> tuple[float, float, float]:
    """jaw01's position in our frame: scene units -> mm, Maya (x, y, z) -> (x, -z, y)."""
    x, y, z = json.loads(JOINTS.read_text())["jaw01"]["world_position"]
    return (x * mm_per_scene_unit, -z * mm_per_scene_unit, y * mm_per_scene_unit)


def slit_height(vertices, triangles) -> float:
    """z of the mouth slit at the midline: halfway between the lower lip's top and the upper lip's
    bottom where the plane x = 0 cuts the surface into two pieces."""
    segments, labels = tetmesh._cross_section(vertices, triangles, 1.234e-4)
    pieces = [segments[labels == k][:, :, 1] for k in set(labels.tolist())]
    lower, upper = sorted(sorted(pieces, key=len)[-2:], key=lambda z: z.mean())
    return float((lower.max() + upper.min()) / 2)


def feb_xml(mesh, fixed, steps, rigid=None, hinge=None, angle_rad=0.0) -> str:
    """The .feb text. Node ids are 1-based. rigid: nodes tied to a rigid jaw turning about hinge."""
    dt = 1.0 / FPS
    nodes = mesh.nodes.tolist()
    n = len(nodes)
    node_lines = [f'      <node id="{i + 1}">{x!r},{y!r},{z!r}</node>' for i, (x, y, z) in enumerate(nodes)]
    elem_lines = [f'      <elem id="{i + 1}">{a + 1},{b + 1},{c + 1},{d + 1}</elem>'
                  for i, (a, b, c, d) in enumerate(mesh.tets.tolist())]
    jaw_material = jaw_mesh = jaw_domain = jaw_bc = jaw_rigid = jaw_curve = ""
    must_lc = 2  # FEBio wants load controller ids 1, 2, 3 ... with no gaps
    if rigid is not None:
        # The rigid body needs elements of its own: one small tet at the hinge. center_of_mass puts
        # its rotation centre on the hinge (the S1 trick); the lip nodes are tied to it.
        hx, hy, hz = hinge
        must_lc = 3
        tet = [(hx, hy, hz), (hx + 1, hy, hz), (hx, hy + 1, hz), (hx, hy, hz + 1)]
        node_lines += [f'      <node id="{n + k + 1}">{x!r},{y!r},{z!r}</node>' for k, (x, y, z) in enumerate(tet)]
        jaw_material = f"""
    <material id="2" name="jaw" type="rigid body">
      <density>{JAW_DENSITY}</density>
      <center_of_mass>{hx!r},{hy!r},{hz!r}</center_of_mass>
    </material>"""
        jaw_mesh = f"""
    <Elements type="tet4" name="jaw">
      <elem id="{len(elem_lines) + 1}">{n + 1},{n + 2},{n + 3},{n + 4}</elem>
    </Elements>
    <NodeSet name="lower">{",".join(str(i + 1) for i in rigid)}</NodeSet>"""
        jaw_domain = '\n    <SolidDomain name="jaw" mat="jaw"/>'
        jaw_bc = """
    <bc name="lower_to_jaw" type="rigid" node_set="lower">
      <rb>jaw</rb>
    </bc>"""
        jaw_rigid = f"""
  <Rigid>
    <rigid_bc name="hinge" type="rigid_fixed">
      <rb>jaw</rb>
      <Rx_dof>1</Rx_dof>
      <Ry_dof>1</Ry_dof>
      <Rz_dof>1</Rz_dof>
      <Rv_dof>1</Rv_dof>
      <Rw_dof>1</Rw_dof>
    </rigid_bc>
    <rigid_bc name="open" type="rigid_rotation">
      <rb>jaw</rb>
      <dof>Ru</dof>
      <value lc="2">{angle_rad!r}</value>
    </rigid_bc>
  </Rigid>"""
        jaw_curve = f"""
    <load_controller id="2" name="jaw_open" type="loadcurve">
      <points>
        <pt>0,0</pt>
        <pt>{steps * dt!r},1</pt>
      </points>
    </load_controller>"""
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<febio_spec version="4.0">
  <Module type="solid"/>
  <Control>
    <analysis>DYNAMIC</analysis>
    <time_steps>{steps}</time_steps>
    <step_size>{dt!r}</step_size>
    <plot_level>PLOT_MUST_POINTS</plot_level>
    <output_level>OUTPUT_MUST_POINTS</output_level>
    <time_stepper type="default">
      <max_retries>8</max_retries>
      <opt_iter>10</opt_iter>
      <dtmin>{dt / 256!r}</dtmin>
      <dtmax lc="{must_lc}">{dt!r}</dtmax>
    </time_stepper>
    <solver type="solid">
      <qn_method type="BFGS"/>
    </solver>
  </Control>
  <Material>
    <material id="1" name="lips" type="neo-Hookean">
      <density>{TISSUE["density"]}</density>
      <E>{TISSUE["E"]}</E>
      <v>{TISSUE["v"]}</v>
    </material>{jaw_material}
  </Material>
  <Mesh>
    <Nodes name="all">
{chr(10).join(node_lines)}
    </Nodes>
    <Elements type="tet4" name="lips">
{chr(10).join(elem_lines)}
    </Elements>{jaw_mesh}
    <NodeSet name="fixed">{",".join(str(i + 1) for i in fixed)}</NodeSet>
  </Mesh>
  <MeshDomains>
    <SolidDomain name="lips" mat="lips"/>{jaw_domain}
  </MeshDomains>
  <Boundary>
    <bc name="fixed" type="zero displacement" node_set="fixed">
      <x_dof>1</x_dof>
      <y_dof>1</y_dof>
      <z_dof>1</z_dof>
    </bc>{jaw_bc}
  </Boundary>{jaw_rigid}
  <Loads>
    <body_load name="gravity" type="const">
      <z lc="1">{-GRAVITY}</z>
    </body_load>
  </Loads>
  <LoadData>
    <load_controller id="1" name="gravity" type="loadcurve">
      <points>
        <pt>0,1</pt>
        <pt>{steps * dt!r},1</pt>
      </points>
    </load_controller>{jaw_curve}
    <load_controller id="{must_lc}" name="must_points" type="loadcurve">
      <interpolate>STEP</interpolate>
      <points>
{chr(10).join(f"        <pt>{k * dt!r},{dt!r}</pt>" for k in range(steps + 1))}
      </points>
    </load_controller>
  </LoadData>
  <Output>
    <logfile>
      <node_data data="x;y;z" name="positions" delim=","/>
    </logfile>
  </Output>
</febio_spec>
"""


def positions(hist, n_nodes) -> list[np.ndarray]:
    return [np.array([frame[i + 1] for i in range(n_nodes)]) for frame in hist.values]


def max_stretch(nodes0, nodes1, tets):
    """Largest principal stretch of each tet between two configurations."""
    def edges(p):
        a = p[tets[:, 0]]
        return np.stack([p[tets[:, k]] - a for k in (1, 2, 3)], axis=2)

    f = edges(nodes1) @ np.linalg.inv(edges(nodes0))
    return np.sqrt(np.linalg.eigvalsh(np.transpose(f, (0, 2, 1)) @ f)[:, -1])


def back_band(nodes) -> np.ndarray:
    return np.nonzero(nodes[:, 1] < nodes[:, 1].min() + BACK_BAND_MM)[0]


def smoke(out: Path, saved: Path = SAVED) -> dict:
    mesh, _ = tetmesh.load(saved)
    fixed = back_band(mesh.nodes)
    out.mkdir(parents=True, exist_ok=True)
    feb = out / "lips_smoke.feb"
    feb.write_text(feb_xml(mesh, fixed, SMOKE_FRAMES), encoding="ascii")
    result = febio.run(feb, febio_exe())
    hist = febio.read_node_data(result.log, "positions")
    frames = positions(hist, len(mesh.nodes)) if hist.values else []
    free = np.setdiff1d(np.arange(len(mesh.nodes)), fixed)
    fixed_move = max((np.abs(p[fixed] - mesh.nodes[fixed]).max() for p in frames), default=math.inf)
    sag = [float((p[free, 2] - mesh.nodes[free, 2]).mean()) for p in frames]
    return {"result": result, "frames": len(hist.times), "times": hist.times, "fixed": len(fixed),
            "nodes": len(mesh.nodes), "fixed_move": fixed_move, "mean_sag": float(np.mean(sag)) if sag else math.nan,
            "sag": sag, "stretch": float(max_stretch(mesh.nodes, frames[-1], mesh.tets).max()) if frames else math.nan}


# Mean z change of the free nodes over the run, mm. The range is docs/07 section 3's gravity-sag
# check (0.1 to 10 mm, down), so a sag of the wrong size fails the smoke test, not only the wrong
# sign. It is a mean over frames of an undamped run, which oscillates frame to frame.
SAG_RANGE_MM = (-10.0, -0.1)


def passed(r: dict) -> bool:
    """Normal termination, every frame there at its time, fixed nodes still, the rest sagging by
    an amount in SAG_RANGE_MM.

    With must points FEBio logs frames 1..N, not the initial state."""
    times_ok = r["frames"] == SMOKE_FRAMES and all(
        abs(t - (k + 1) / FPS) < 1e-6 for k, t in enumerate(r["times"]))
    return (r["result"].returncode == 0 and r["result"].normal_termination and times_ok
            and r["fixed_move"] < 1e-6 and SAG_RANGE_MM[0] < r["mean_sag"] < SAG_RANGE_MM[1])


def first_failure(log_text: str):
    """The time of FEBio's first 'failed to converge', or None. Its log does not name elements."""
    m = re.search(r"failed to converge at time : ([0-9.eE+-]+)", log_text)
    return float(m.group(1)) if m else None


def volume_ratio(nodes0, nodes1, tets):
    return tetmesh.signed_volumes(nodes1, tets) / tetmesh.signed_volumes(nodes0, tets)


def jaw(out: Path, saved: Path = SAVED, gap_mm: float = 0.0) -> dict:
    """gap_mm: back-band nodes within this height of the slit stay free, so fixed and jaw-tied
    nodes are not neighbours (0 = the plain split by height that T-04 I1 asked for)."""
    mesh, meta = tetmesh.load(saved)
    band = back_band(mesh.nodes)
    split = slit_height(*read_lips_mm())
    z = mesh.nodes[band, 2]
    upper, lower = band[z >= split + gap_mm], band[z < split - gap_mm]
    hinge = hinge_mm(meta["mm_per_scene_unit"])
    # Turning about +x by a negative angle swings what is in front of and below the hinge down:
    # the jaw opens (checked below on the tied nodes).
    angle = -math.radians(JAW_DEG)
    out.mkdir(parents=True, exist_ok=True)
    feb = out / f"lips_jaw_gap{gap_mm:g}.feb"
    feb.write_text(feb_xml(mesh, upper, JAW_FRAMES, rigid=lower, hinge=hinge, angle_rad=angle), encoding="ascii")
    result = febio.run(feb, febio_exe())
    hist = febio.read_node_data(result.log, "positions")
    frames = positions(hist, len(mesh.nodes)) if hist.values else []
    last = frames[-1] if frames else mesh.nodes
    stretch = max_stretch(mesh.nodes, last, mesh.tets)
    worst = int(np.argmax(stretch))
    centre = mesh.nodes[mesh.tets[worst]].mean(axis=0)
    text = result.log.read_text(errors="replace") if result.log.exists() else ""
    j = volume_ratio(mesh.nodes, last, mesh.tets)
    bad = stretch > 3
    band = mesh.nodes[mesh.tets[bad]].mean(axis=1) if bad.any() else np.zeros((0, 3))
    return {"result": result, "frames": len(hist.times), "last_time": hist.times[-1] if hist.times else None,
            "hinge": hinge, "split": split, "upper": len(upper), "lower": len(lower),
            "lower_dz": float((last[lower, 2] - mesh.nodes[lower, 2]).mean()),
            "stretch": float(stretch.max()), "stretch_at": centre.tolist(),
            "stretch_over_1_5": int((stretch > 1.5).sum()), "stretch_over_3": int(bad.sum()),
            "band_x": (round(float(band[:, 0].min()), 1), round(float(band[:, 0].max()), 1)) if len(band) else None,
            "band_z": (round(float(band[:, 2].min()), 1), round(float(band[:, 2].max()), 1)) if len(band) else None,
            "min_j": float(j.min()), "first_failure": first_failure(text),
            "retries": text.count("Retrying time step")}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "runs" / f"s2_lips_{which}"
    if which == "smoke":
        r = smoke(out)
        res = r["result"]
        print(f"FEBio: return code {res.returncode}, normal termination {res.normal_termination}, {res.seconds:.1f} s")
        print(f"{r['nodes']} nodes, {r['fixed']} fixed; {r['frames']} of {SMOKE_FRAMES} frames converged")
        print(f"fixed nodes moved at most {r['fixed_move']:.2e} mm")
        print(f"free nodes mean z change over frames 1-{SMOKE_FRAMES}: {r['mean_sag']:+.4f} mm; "
              f"per frame: {' '.join(f'{s:+.3f}' for s in r['sag'])}")
        print(f"largest stretch at the end {r['stretch']:.3f}")
        ok = passed(r)
        print("S2 FEBIO SMOKE PASSED" if ok else "S2 FEBIO SMOKE FAILED")
        sys.exit(0 if ok else 1)
    gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    r = jaw(out, gap_mm=gap)
    res = r["result"]
    print(f"free band around the slit: +-{gap} mm")
    print(f"hinge jaw01 at {tuple(round(c, 2) for c in r['hinge'])} mm; slit at z {r['split']:.2f} mm; "
          f"upper band {r['upper']} nodes fixed, lower band {r['lower']} nodes on the jaw")
    print(f"FEBio: return code {res.returncode}, normal termination {res.normal_termination}, {res.seconds:.1f} s, "
          f"{r['retries']} step retries")
    print(f"converged frames {r['frames']} of {JAW_FRAMES}; last converged time {r['last_time']} s "
          f"= {JAW_DEG * (r['last_time'] or 0) * FPS / JAW_FRAMES:.2f} deg of {JAW_DEG}")
    print(f"tied lower nodes moved {r['lower_dz']:+.2f} mm in z on average (negative = down, the jaw opened)")
    print(f"largest stretch {r['stretch']:.2f} at {tuple(round(c, 1) for c in r['stretch_at'])} mm; "
          f"{r['stretch_over_1_5']} tets stretched over 1.5")
    print(f"smallest volume ratio J {r['min_j']:.3f}; {r['stretch_over_3']} tets stretched over 3, centres x "
          f"{r['band_x']} z {r['band_z']} mm")
    print(f"first 'failed to converge' at t = {r['first_failure']} s")


if __name__ == "__main__":
    main()
