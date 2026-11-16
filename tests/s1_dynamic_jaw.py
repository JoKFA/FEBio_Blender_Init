"""Spike S1: can FEBio on this machine run the kind of model the lab's pipeline needs?

Model (units mm, N, MPa, s; mass in tonnes):
- a soft-tissue column (neo-Hookean tet4) hanging from a fixed "skull" face at z = 30,
- its bottom face shared with a rigid "jaw" block (z in [-5, 0]),
- the jaw hinged about the x axis through PIVOT (center_of_mass trick: a rigid
  body's rotation dofs act about its reference point),
- gravity from t = 0, a 15-frame settle, then the jaw opens to JAW_OPEN rad
  over frames 15-30, then holds until frame 45. Dynamic analysis, 30 fps.

Checks that can fail: normal termination; every frame present for every node;
skull nodes do not move; jaw nodes follow the prescribed hinge rotation exactly;
tissue sags under gravity and is pulled further down when the jaw opens.

    uv run python tests/s1_dynamic_jaw.py [out_dir]
"""

import itertools
import math
import sys
from pathlib import Path

from asrp_core import febio, playback
from asrp_core.doctor import febio_exe

FPS = 30
FRAMES = 45
SETTLE_END = 0.5  # s, frame 15
OPEN_END = 1.0  # s, frame 30
JAW_OPEN = -0.147  # rad, about 8.4 degrees (paper, appendix V)
PIVOT = (5.0, -30.0, 0.0)
GRAVITY = -9810.0  # mm/s^2, physical direction: -z
TISSUE = {"density": 1.06e-9, "E": 0.02, "v": 0.45}  # 1060 kg/m^3, 20 kPa
JAW_DENSITY = 1.9e-9

XS = [0.0, 5.0, 10.0]
YS = [0.0, 5.0, 10.0]
ZS = [-5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0]


def node_id(i: int, j: int, k: int) -> int:
    return 1 + i + len(XS) * (j + len(YS) * k)


def signed_volume(a, b, c, d) -> float:
    u = [b[n] - a[n] for n in range(3)]
    v = [c[n] - a[n] for n in range(3)]
    w = [d[n] - a[n] for n in range(3)]
    return (
        u[0] * (v[1] * w[2] - v[2] * w[1])
        - u[1] * (v[0] * w[2] - v[2] * w[0])
        + u[2] * (v[0] * w[1] - v[1] * w[0])
    ) / 6.0


def build_mesh():
    nodes = {
        node_id(i, j, k): (x, y, z)
        for k, z in enumerate(ZS)
        for j, y in enumerate(YS)
        for i, x in enumerate(XS)
    }
    jaw, tissue = [], []
    for i, j, k in itertools.product(range(len(XS) - 1), range(len(YS) - 1), range(len(ZS) - 1)):
        # Kuhn split: 6 tets per hex, conforming across neighbouring hexes.
        for axes in itertools.permutations(range(3)):
            corner = [0, 0, 0]
            tet = [node_id(i, j, k)]
            for axis in axes:
                corner[axis] = 1
                tet.append(node_id(i + corner[0], j + corner[1], k + corner[2]))
            if signed_volume(*(nodes[n] for n in tet)) < 0:
                tet[1], tet[2] = tet[2], tet[1]
            (jaw if ZS[k] < 0 else tissue).append(tet)
    return nodes, tissue, jaw


def build_feb(path: Path) -> dict:
    """Write the S1 model.

    FEBio 4.13's const body_load acts opposite to the manual's rho*a = div(sigma) + rho*b:
    z = -9810 lifted a hanging bar by 0.20 mm, z = +9810 lowered it by 0.20 mm. So gravity
    is written with its sign flipped; the mean-sag check in run_and_check guards this.
    """
    nodes, tissue, jaw = build_mesh()
    skull = [nid for nid, (_, _, z) in nodes.items() if z == ZS[-1]]
    dt = 1.0 / FPS

    def elems(tets, first_id):
        return "\n".join(
            f'      <elem id="{first_id + n}">{",".join(map(str, t))}</elem>' for n, t in enumerate(tets)
        )

    xml = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<febio_spec version="4.0">
  <Module type="solid"/>
  <Control>
    <analysis>DYNAMIC</analysis>
    <time_steps>{FRAMES}</time_steps>
    <step_size>{dt!r}</step_size>
    <solver type="solid">
      <qn_method type="BFGS"/>
    </solver>
  </Control>
  <Material>
    <material id="1" name="tissue" type="neo-Hookean">
      <density>{TISSUE["density"]}</density>
      <E>{TISSUE["E"]}</E>
      <v>{TISSUE["v"]}</v>
    </material>
    <material id="2" name="jaw" type="rigid body">
      <density>{JAW_DENSITY}</density>
      <center_of_mass>{",".join(map(str, PIVOT))}</center_of_mass>
    </material>
  </Material>
  <Mesh>
    <Nodes name="all">
{chr(10).join(f'      <node id="{nid}">{x},{y},{z}</node>' for nid, (x, y, z) in sorted(nodes.items()))}
    </Nodes>
    <Elements type="tet4" name="tissue">
{elems(tissue, 1)}
    </Elements>
    <Elements type="tet4" name="jaw">
{elems(jaw, 1 + len(tissue))}
    </Elements>
    <NodeSet name="skull">{",".join(map(str, skull))}</NodeSet>
  </Mesh>
  <MeshDomains>
    <SolidDomain name="tissue" mat="tissue"/>
    <SolidDomain name="jaw" mat="jaw"/>
  </MeshDomains>
  <Boundary>
    <bc name="skull" type="zero displacement" node_set="skull">
      <x_dof>1</x_dof>
      <y_dof>1</y_dof>
      <z_dof>1</z_dof>
    </bc>
  </Boundary>
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
      <value lc="2">{JAW_OPEN}</value>
    </rigid_bc>
  </Rigid>
  <Loads>
    <body_load name="gravity" type="const">
      <z lc="1">{-GRAVITY}</z>
    </body_load>
  </Loads>
  <LoadData>
    <load_controller id="1" name="gravity" type="loadcurve">
      <points>
        <pt>0,1</pt>
        <pt>{FRAMES * dt!r},1</pt>
      </points>
    </load_controller>
    <load_controller id="2" name="jaw_open" type="loadcurve">
      <points>
        <pt>0,0</pt>
        <pt>{SETTLE_END},0</pt>
        <pt>{OPEN_END},1</pt>
        <pt>{FRAMES * dt!r},1</pt>
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
    path.write_text(xml, encoding="ascii")
    return {"nodes": nodes, "skull": skull, "tissue": tissue, "jaw": jaw}


def jaw_angle(t: float) -> float:
    """The prescribed hinge angle, i.e. load curve 2 times JAW_OPEN."""
    if t <= SETTLE_END:
        return 0.0
    return JAW_OPEN * min(1.0, (t - SETTLE_END) / (OPEN_END - SETTLE_END))


def hinge_rotate(p, angle: float):
    """Rotate p about the x axis through PIVOT (right-handed, like FEBio's Ru)."""
    y, z = p[1] - PIVOT[1], p[2] - PIVOT[2]
    c, s = math.cos(angle), math.sin(angle)
    return (p[0], PIVOT[1] + c * y - s * z, PIVOT[2] + s * y + c * z)


def run_and_check(out: Path, threads: int = febio.DEFAULT_THREADS) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    model = build_feb(out / "s1.feb")
    result = febio.run(out / "s1.feb", febio_exe(), threads=threads)
    assert result.returncode == 0 and result.normal_termination, f"FEBio failed, see {result.log}"

    hist = febio.read_node_data(result.log, "positions")
    nodes = model["nodes"]
    assert len(hist.times) == FRAMES + 1, f"{len(hist.times)} frames, expected {FRAMES + 1}"
    assert all(len(frame) == len(nodes) for frame in hist.values), "a frame is missing nodes"
    assert all(abs(t - n / FPS) < 1e-6 for n, t in enumerate(hist.times)), "frame times drifted"

    skull_move = max(
        math.dist(frame[n], nodes[n]) for frame in hist.values for n in model["skull"]
    )
    assert skull_move < 1e-9, f"skull moved {skull_move} mm"

    jaw_nodes = [n for n, p in nodes.items() if p[2] <= 0.0]
    jaw_error = max(
        math.dist(frame[n], hinge_rotate(nodes[n], jaw_angle(t)))
        for t, frame in zip(hist.times, hist.values)
        for n in jaw_nodes
    )
    assert jaw_error < 1e-6, f"jaw nodes are {jaw_error} mm off the prescribed hinge rotation"

    mid = node_id(1, 1, 4)  # centre of the z = 15 layer, halfway down the tissue
    uz = [frame[mid][2] - nodes[mid][2] for frame in hist.values]
    settle_frame, open_frame = round(SETTLE_END * FPS), round(OPEN_END * FPS)
    # The column's axial period (~14 ms) is shorter than a frame, so single frames alias;
    # the mean over the settle phase approximates the static sag (~ -0.06 mm here).
    settle_mean = sum(uz[1 : settle_frame + 1]) / settle_frame
    assert settle_mean < -0.01, f"tissue did not sag under gravity (mean uz={settle_mean:+.4f})"
    assert uz[FRAMES] < settle_mean - 0.5, "tissue was not pulled down by the opening jaw"

    bundle = playback.write_bundle(
        out, nodes, {"tissue": model["tissue"], "jaw": model["jaw"]}, hist.values, FPS, result.feb
    )

    return {
        "bundle": bundle,
        "seconds": result.seconds,
        "frames": len(hist.times),
        "nodes": len(nodes),
        "skull_move": skull_move,
        "jaw_error": jaw_error,
        "mid_uz": uz,
        "settle_mean": settle_mean,
        "settle_frame": settle_frame,
        "open_frame": open_frame,
    }


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs/s1_dynamic_jaw")
    r = run_and_check(out)
    print(f"FEBio solved {r['frames']} frames x {r['nodes']} nodes in {r['seconds']:.2f} s (wall, incl. startup)")
    print(f"skull max displacement : {r['skull_move']:.2e} mm")
    print(f"jaw vs prescribed hinge: {r['jaw_error']:.2e} mm max error")
    print(f"mid-tissue mean sag over settle frames 1-{r['settle_frame']}: {r['settle_mean']:+.4f} mm")
    print("mid-tissue node uz (mm), every 3 frames:")
    for f in range(0, r["frames"], 3):
        tag = " <- settle ends" if f == r["settle_frame"] else " <- jaw fully open" if f == r["open_frame"] else ""
        print(f"  frame {f:2d}: {r['mid_uz'][f]:+8.3f}{tag}")
    print(f"playback bundle: {r['bundle']}")
    print("S1 CHECKS PASSED")
