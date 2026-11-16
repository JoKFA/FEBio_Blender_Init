"""Spike S3 (T-07 steps 1-2): do FEBio springs and gravity give the textbook answer, and do springs
stiffen into a hard bond?

Units: mm, N, MPa, s; mass in tonnes. Every node coordinate is written as geometric mm times k, all
physical parameters stay real, results are divided by k (docs/05 section 2, ADR-36).

Step 1 (checks that can fail): a nearly rigid cube (neo-Hookean, E = 1000 MPa) hangs on 4 linear
springs (physical stiffness K N/mm, each from a cube corner to an anchor node that a `rigid` boundary
condition ties to a rigid frame). The frame is fixed in all 6 degrees of freedom (the T-07 step-4
question: a rigid body fixed as a whole). Gravity is ramped in, then held. Each spring extends by
weight / (4K); in geometric mm, extension = rho * V * k^2 * g / (4K), V the geometric volume.
Run for k = 1 and k = 2, dynamic (generalized alpha, rhoi = 0). Static analysis is not used: four vertical
springs leave the sideways translations and the spin about the vertical with no stiffness, so a static
solve is singular there (it solved at k = 1 once and failed on repeats).

Step 2 (checks that can fail): a soft cube (E = 20 kPa) hangs under a rigid plate that turns about a
hinge. The top face is attached (a) hard: those nodes joined into the plate with a `rigid` boundary
condition, or (b) with springs: the same nodes, each with a spring to an anchor node of the plate.
Gravity plus a prescribed plate rotation. The base spring stiffness is swept over decades; the largest
node difference to (a) must shrink monotonically. Reports run time and where it gets slow or fails.

    uv run python tests/s3_attachment.py [out_dir]            # the checks: prints the tables, exits 1 on any FAIL
    uv run python tests/s3_attachment.py --extra [out_dir]    # also the studies behind docs/05 section 3: the
                                                               # spring offset, time step, E and mesh size
"""

import itertools
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from asrp_core import febio
from asrp_core.doctor import febio_exe

FPS = 30
G = 9810.0  # mm/s^2, physical direction -z. Written with its sign flipped (docs/05 pit 1).
RHO = 1.06e-9  # t/mm^3 (1060 kg/m^3)
RHOI = 0.0  # generalized-alpha spectral radius at infinity: 0 = strongest damping of fast modes


# ----------------------------------------------------------------------------- model builder

@dataclass
class Model:
    """Geometric-mm model. Node ids are 1-based, in creation order."""

    nodes: list = field(default_factory=list)

    def node(self, p) -> int:
        self.nodes.append(tuple(float(c) for c in p))
        return len(self.nodes)

    def box(self, origin, size, n):
        """n x n x n hexes cut into tets (Kuhn split, conforming). Returns {(i, j, k): id}, tets."""
        grid = {
            (i, j, k): self.node([origin[a] + size * idx[a] / n for a in range(3)])
            for k in range(n + 1) for j in range(n + 1) for i in range(n + 1)
            for idx in [(i, j, k)]
        }
        tets = []
        for i, j, k in itertools.product(range(n), repeat=3):
            for axes in itertools.permutations(range(3)):
                corner, tet = [0, 0, 0], [grid[i, j, k]]
                for axis in axes:
                    corner[axis] = 1
                    tet.append(grid[i + corner[0], j + corner[1], k + corner[2]])
                if signed_volume(*(self.nodes[t - 1] for t in tet)) < 0:
                    tet[1], tet[2] = tet[2], tet[1]
                tets.append(tet)
        return grid, tets

    def stub(self, p):
        """The small tet every rigid body needs for FEBio to accept it (as in tests/s2_lips_febio.py)."""
        x, y, z = p
        return [self.node(q) for q in [(x, y, z), (x + 1, y, z), (x, y + 1, z), (x, y, z + 1)]]


def signed_volume(a, b, c, d) -> float:
    return float(np.linalg.det(np.array([np.subtract(b, a), np.subtract(c, a), np.subtract(d, a)])) / 6.0)


def feb_xml(model: Model, *, k, soft, soft_mat, bodies, ties, springs, kbins, dynamic, steps, curves,
            probes, sub=1) -> str:
    """The .feb text.

    soft: tets of the deformable part. bodies: [{name, tet, pivot, fixed: [dof], rotate: (lc, value) | None}].
    ties: [(node_set_name, [ids], body_name)] (the `rigid` boundary condition).
    springs: [(node a, node b, bin index)]; kbins: [physical stiffness N/mm] per bin.
    curves: [[(t, v), ...]] load controllers 1.. (1 is gravity). probes: node ids logged.
    """
    dt = 1.0 / (FPS * sub)

    def p(q):
        return ",".join(repr(float(c) * k) for c in q)

    def nodes_xml():
        return "\n".join(f'      <node id="{i + 1}">{p(q)}</node>' for i, q in enumerate(model.nodes))

    eid = itertools.count(1)
    elems = "\n".join(f'      <elem id="{next(eid)}">{",".join(map(str, t))}</elem>' for t in soft)
    mats = [f"""    <material id="1" name="soft" type="neo-Hookean">
      <density>{soft_mat["density"]}</density>
      <E>{soft_mat["E"]}</E>
      <v>{soft_mat["v"]}</v>
    </material>"""]
    elem_sets = [f'    <Elements type="tet4" name="soft">\n{elems}\n    </Elements>'] if soft else []
    domains = ['    <SolidDomain name="soft" mat="soft"/>'] if soft else []
    rigid_bc = []
    for n, b in enumerate(bodies):
        mats.append(f"""    <material id="{n + 2}" name="{b["name"]}" type="rigid body">
      <density>1e-9</density>
      <center_of_mass>{p(b["pivot"])}</center_of_mass>
    </material>""")
        e = f'      <elem id="{next(eid)}">{",".join(map(str, b["tet"]))}</elem>'
        elem_sets.append(f'    <Elements type="tet4" name="{b["name"]}">\n{e}\n    </Elements>')
        domains.append(f'    <SolidDomain name="{b["name"]}" mat="{b["name"]}"/>')
        dofs = "\n".join(f"      <{d}_dof>1</{d}_dof>" for d in b["fixed"])
        rigid_bc.append(f'    <rigid_bc name="{b["name"]}_fixed" type="rigid_fixed">\n      <rb>{b["name"]}</rb>\n{dofs}\n    </rigid_bc>')
        if b.get("rotate"):
            lc, value = b["rotate"]
            rigid_bc.append(f"""    <rigid_bc name="{b["name"]}_turn" type="rigid_rotation">
      <rb>{b["name"]}</rb>
      <dof>Ru</dof>
      <value lc="{lc}">{value!r}</value>
    </rigid_bc>""")
    nodesets = "\n".join(f'    <NodeSet name="{name}">{",".join(map(str, ids))}</NodeSet>' for name, ids, _ in ties)
    ties_xml = "\n".join(
        f'    <bc name="{name}_tie" type="rigid" node_set="{name}">\n      <rb>{body}</rb>\n    </bc>'
        for name, _, body in ties
    )
    spring_sets, discrete = "", ""
    if springs:
        by_bin: dict[int, list] = {}
        for a, b, which in springs:
            by_bin.setdefault(which, []).append((a, b))
        sets, lines, count = [], [], 0
        for which, pairs in sorted(by_bin.items()):
            sets.append(f'    <DiscreteSet name="springs{which}">\n'
                        + "\n".join(f"      <delem>{a},{b}</delem>" for a, b in pairs) + "\n    </DiscreteSet>")
            lines.append(f'    <discrete_material id="{which + 1}" type="linear spring">\n      <E>{kbins[which]!r}</E>\n    </discrete_material>')
            lines.append(f'    <discrete dmat="{which + 1}" discrete_set="springs{which}"/>')
            count += len(pairs)
        spring_sets = "\n".join(sets)
        discrete = "  <Discrete>\n" + "\n".join(lines) + "\n  </Discrete>"
    control = (f"""    <analysis>DYNAMIC</analysis>
    <time_steps>{steps * sub}</time_steps>
    <step_size>{dt!r}</step_size>
    <solver type="solid">
      <qn_method type="BFGS"/>
      <rhoi>{RHOI}</rhoi>
    </solver>""" if dynamic else f"""    <analysis>STATIC</analysis>
    <time_steps>{steps * sub}</time_steps>
    <step_size>{dt!r}</step_size>
    <solver type="solid">
      <qn_method type="BFGS"/>
    </solver>""")
    lcs = "\n".join(
        f'    <load_controller id="{n + 1}" name="lc{n + 1}" type="loadcurve">\n      <points>\n'
        + "\n".join(f"        <pt>{t!r},{v!r}</pt>" for t, v in pts) + "\n      </points>\n    </load_controller>"
        for n, pts in enumerate(curves)
    )
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<febio_spec version="4.0">
  <Module type="solid"/>
  <Control>
{control}
  </Control>
  <Material>
{chr(10).join(mats)}
  </Material>
  <Mesh>
    <Nodes name="all">
{nodes_xml()}
    </Nodes>
{chr(10).join(elem_sets)}
{nodesets}
{spring_sets}
  </Mesh>
  <MeshDomains>
{chr(10).join(domains)}
  </MeshDomains>
  <Boundary>
{ties_xml}
  </Boundary>
  <Rigid>
{chr(10).join(rigid_bc)}
  </Rigid>
{discrete}
  <Loads>
    <body_load name="gravity" type="const">
      <z lc="1">{G}</z>
    </body_load>
  </Loads>
  <LoadData>
{lcs}
  </LoadData>
  <Output>
    <logfile>
      <node_data data="x;y;z" name="positions" delim="," />
    </logfile>
  </Output>
</febio_spec>
"""


def iterations(log: Path) -> int | None:
    """FEBio's total equilibrium iterations, from the end of its log."""
    m = re.search(r"Total number of equilibrium iterations \.+ : (\d+)", log.read_text(errors="replace")) if log.exists() else None
    return int(m.group(1)) if m else None


def solve(feb_text: str, out: Path, name: str):
    """Write, run, read. Returns (run, positions per frame as {id: xyz} in FEBio units, i.e. times k)."""
    out.mkdir(parents=True, exist_ok=True)
    feb = out / f"{name}.feb"
    feb.write_text(feb_text, encoding="ascii")
    result = febio.run(feb, febio_exe())
    hist = febio.read_node_data(result.log, "positions") if result.log.exists() else febio.NodeHistory([], [])
    return result, hist


# ----------------------------------------------------------------------------- step 1

CUBE_A = 10.0  # geometric mm
CUBE_E = 1000.0  # MPa, "nearly rigid" next to the springs
SPRING_GAP = 5.0  # geometric mm between cube top and anchors
K1 = 0.0025  # N/mm, physical: extension ~1 mm at k = 1


def cube_on_springs(out: Path, k: float, dynamic: bool, K: float = K1, n: int = 2):
    """Returns dict(theory, measured, error_pct, ...) in geometric mm."""
    m = Model()
    grid, tets = m.box((0, 0, 0), CUBE_A, n)
    corners = [grid[i, j, n] for i in (0, n) for j in (0, n)]
    anchors = [m.node((m.nodes[c - 1][0], m.nodes[c - 1][1], CUBE_A + SPRING_GAP)) for c in corners]
    frame = {"name": "frame", "tet": m.stub((CUBE_A / 2, CUBE_A / 2, CUBE_A + 3 * SPRING_GAP)),
             "pivot": (CUBE_A / 2, CUBE_A / 2, CUBE_A + 3 * SPRING_GAP), "fixed": ["Rx", "Ry", "Rz", "Ru", "Rv", "Rw"]}
    steps = 60
    text = feb_xml(
        m, k=k, soft=tets, soft_mat={"density": RHO, "E": CUBE_E, "v": 0.3}, bodies=[frame],
        ties=[("anchors", anchors, "frame")], springs=[(c, a, 0) for c, a in zip(corners, anchors)], kbins=[K],
        dynamic=dynamic, steps=steps, curves=[[(0, 0), (1.0, 1.0), (steps / FPS, 1.0)]], probes=[],
    )
    tag = f"cube_k{k:g}_{'dyn' if dynamic else 'static'}"
    result, hist = solve(text, out, tag)
    volume = CUBE_A ** 3
    theory = RHO * volume * k * k * G / (4 * K)
    row = {"tag": tag, "k": k, "dynamic": dynamic, "seconds": result.seconds, "theory": theory,
           "ok": result.normal_termination and result.returncode == 0 and len(hist.times) > steps}
    if not row["ok"]:
        return row | {"measured": float("nan"), "error_pct": float("inf"), "lateral": float("nan")}
    # extension of each spring: the anchors do not move, so it is the corner's drop
    last = hist.values[-1]
    first = hist.values[0]
    drops = [(first[c][2] - last[c][2]) / k for c in corners]
    lateral = max(math.hypot(last[c][0] - first[c][0], last[c][1] - first[c][1]) / k for c in corners)
    anchor_move = max(math.dist(last[a], first[a]) for a in anchors) / k
    # the tail of the run: mean of the last 10 frames (the cube may still ring a little)
    tail = np.mean([[(first[c][2] - f[c][2]) / k for c in corners] for f in hist.values[-10:]])
    measured = float(tail if dynamic else np.mean(drops))
    row |= {"measured": measured, "error_pct": 100 * abs(measured - theory) / theory, "lateral": lateral,
            "anchor_move": anchor_move, "spread": max(drops) - min(drops)}
    return row


# ----------------------------------------------------------------------------- step 2

SPRING_OFFSET = 2.0  # geometric mm, see soft_on_plate
SOFT_E = 0.02  # MPa
SOFT_NU = 0.45
SOFT_N = 4
HINGE = (5.0, -10.0, 10.0)  # the plate turns about the x axis through here
TURN = -0.5  # rad at the end of the turn
TURN_FRAMES = 30
HOLD_FRAMES = 15


def turn_angle(t: float) -> float:
    return TURN * min(1.0, t / (TURN_FRAMES / FPS))


def hinge_rotate(p, angle: float):
    y, z = p[1] - HINGE[1], p[2] - HINGE[2]
    c, s = math.cos(angle), math.sin(angle)
    return (p[0], HINGE[1] + c * y - s * z, HINGE[2] + s * y + c * z)


def soft_on_plate(out: Path, mode: str, K: float | None = None, k: float = 1.0, sub: int = 1, offset: float = SPRING_OFFSET,
                  E: float = SOFT_E, n: int = SOFT_N):
    """mode 'hard', 'spring' (3 offset springs per node, K each) or 'zero' (1 zero-length spring); K in N/mm. Returns row dict with positions."""
    m = Model()
    grid, tets = m.box((0, 0, 0), CUBE_A, n)
    top = [grid[i, j, n] for j in range(n + 1) for i in range(n + 1)]
    plate = {"name": "plate", "tet": m.stub(HINGE), "pivot": HINGE,
             "fixed": ["Rx", "Ry", "Rz", "Rv", "Rw"], "rotate": (2, TURN)}
    springs, ties = [], []
    if mode == "hard":
        ties.append(("attach", top, "plate"))
    elif mode == "zero":
        # the 'obvious' way: one spring per node, anchor exactly on the tissue node (zero length)
        anchors = [m.node(m.nodes[t - 1]) for t in top]
        ties.append(("anchors", anchors, "plate"))
        springs = [(t, a, 0) for t, a in zip(top, anchors)]
    else:
        # A zero-length spring has no direction, FEBio cannot build its stiffness and diverges for stiff
        # springs (see the report). So each attached node gets three springs along x, y, z to anchors
        # `offset` away; each resists one axis, together they are an isotropic spring of stiffness K.
        anchors = []
        for t in top:
            for axis in range(3):
                q = list(m.nodes[t - 1])
                q[axis] += offset
                anchors.append(m.node(q))
                springs.append((t, anchors[-1], 0))
        ties.append(("anchors", anchors, "plate"))
    steps = TURN_FRAMES + HOLD_FRAMES
    text = feb_xml(
        m, k=k, soft=tets, soft_mat={"density": RHO, "E": E, "v": SOFT_NU}, bodies=[plate], ties=ties,
        springs=springs, kbins=[K] if K else [], dynamic=True, steps=steps,
        curves=[[(0, 0), (TURN_FRAMES / FPS, 1.0), (steps / FPS, 1.0)],
                [(0, 0), (TURN_FRAMES / FPS, 1.0), (steps / FPS, 1.0)]], probes=[], sub=sub,
    )
    tag = f"soft_E{E:g}_n{n}_" + ("hard" if mode == "hard" else f"{mode}_{K:g}")
    result, hist = solve(text, out, tag)
    ok = result.normal_termination and result.returncode == 0 and len(hist.times) == steps * sub + 1
    row = {"tag": tag, "mode": mode, "K": K, "seconds": result.seconds, "ok": ok, "iterations": iterations(result.log), "tissue": list(grid.values()),
           "top": top, "initial": {i: m.nodes[i - 1] for i in grid.values()}}
    if ok:
        row["final"] = {i: tuple(c / k for c in hist.values[-1][i]) for i in grid.values()}
        row["tail"] = [{i: tuple(c / k for c in f[i]) for i in grid.values()} for f in hist.values[-5:]]
        # tied nodes in the hard model are rigid nodes: do they sit where the plate puts them?
        row["tie_error"] = max(
            math.dist(row["final"][i], hinge_rotate(m.nodes[i - 1], turn_angle(hist.times[-1]))) for i in top
        ) if mode == "hard" else None
        row["frames"] = hist.times
        if mode == "spring":
            # slip u of each node from its rest place on the moving plate, over all frames, against the offset
            ax = anchors[0::3]  # the x anchors, offset +offset along x from their node
            u = max(
                math.dist(tuple(c / k for c in f[t]), (f[a][0] / k - offset, f[a][1] / k, f[a][2] / k))
                for f in hist.values for t, a in zip(top, ax)
            )
            row["max_slip"], row["slip_ratio"] = u, u / offset
    return row


STIFFNESS_SWEEP = [10.0 ** e for e in range(-3, 11)]  # N/mm per attached node, 1e-3 .. 1e10
LIMIT_PROBE = 1e12  # reported, not a check: where FEBio stops converging
# the tissue's own scale: E * node spacing = 0.02 MPa * 2.5 mm
TISSUE_SCALE = SOFT_E * CUBE_A / SOFT_N


def max_node_difference(a: dict, b: dict) -> float:
    return max(math.dist(a["final"][i], b["final"][i]) for i in a["tissue"])


def sweep(out: Path, stiffnesses=STIFFNESS_SWEEP):
    hard = soft_on_plate(out, "hard")
    rows = []
    for K in stiffnesses:
        r = soft_on_plate(out, "spring", K)
        r["diff"] = max_node_difference(r, hard) if r["ok"] and hard["ok"] else float("nan")
        rows.append(r)
    return hard, rows


def is_monotone(rows) -> bool:
    """Every finished run is closer to hard than the one with the next softer spring."""
    diffs = [r["diff"] for r in rows if r["ok"]]
    return len(diffs) >= 2 and all(b < a for a, b in zip(diffs, diffs[1:]))


# ----------------------------------------------------------------------------- report

def main(out: Path) -> int:
    fails = []

    def check(name, cond, detail):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}: {detail}")
        if not cond:
            fails.append(name)

    print(f"Step 1: cube on 4 springs (K = {K1:g} N/mm each, cube side {CUBE_A:g} mm, rho {RHO:g} t/mm3)")
    print(f"{'run':<22}{'theory mm':>11}{'measured mm':>13}{'error %':>10}{'lateral mm':>12}{'s':>7}")
    for k in (1.0, 2.0):
        r = cube_on_springs(out, k, True)
        print(f"{r['tag']:<22}{r['theory']:>11.5f}{r['measured']:>13.5f}{r['error_pct']:>10.4f}"
              f"{r.get('lateral', float('nan')):>12.2e}{r['seconds']:>7.2f}")
        check(f"{r['tag']} within 1%", r["ok"] and r["error_pct"] < 1.0, f"{r['error_pct']:.4f} %")
        if r["ok"]:
            check(f"{r['tag']} frame holds", r["anchor_move"] < 1e-6,
                  f"anchors moved {r['anchor_move']:.1e} mm (frame fixed in all 6 DOF, T-07 step 4 question)")
    print(f"\nStep 2: soft cube (E {SOFT_E} MPa, v {SOFT_NU}, {SOFT_N}^3 hexes, {(SOFT_N + 1) ** 2} attached nodes) "
          f"under a plate turning {TURN} rad about a hinge, gravity on, {TURN_FRAMES + HOLD_FRAMES} frames; "
          f"tissue scale E*h = {TISSUE_SCALE:g} N/mm")
    hard, rows = sweep(out)
    check("hard run finished", hard["ok"], f"{hard['seconds']:.2f} s, {hard['iterations']} iterations")
    if hard["ok"]:
        check("hard: tied nodes sit on the turned plate", hard["tie_error"] < 1e-6, f"{hard['tie_error']:.2e} mm")
        moved = max(math.dist(hard["final"][i], hard["initial"][i]) for i in hard["tissue"])
        check("hard: the plate really carried the tissue", moved > 5.0, f"max node travel {moved:.2f} mm")
        sag = max(math.dist(hard["final"][i], hinge_rotate(hard["initial"][i], TURN)) for i in hard["tissue"])
        check("hard: gravity deforms the tissue", sag > 1e-3, f"max distance from a pure turn {sag:.4f} mm")
    print(f"{'base K N/mm':>12}{'K/(E*h)':>10}{'max |dx| vs hard mm':>21}{'|dx|*K N':>10}{'s':>7}{'iter':>6}  status")
    for r in rows:
        d = r["diff"]
        print(f"{r['K']:>12g}{r['K'] / TISSUE_SCALE:>10.3g}{d:>21.3e}{d * r['K']:>10.2e}{r['seconds']:>7.2f}"
              f"{str(r['iterations']):>6}  {'ok' if r['ok'] else 'FAILED'}")
    print(f"{'hard':>12}{'inf':>10}{0.0:>21.3e}{'':>10}{hard['seconds']:>7.2f}{str(hard['iterations']):>6}  ok")
    check("all spring runs finished", all(r["ok"] for r in rows), f"{sum(r['ok'] for r in rows)}/{len(rows)}")
    check("difference to hard shrinks monotonically with K", is_monotone(rows),
          " > ".join(f"{r['diff']:.0e}" for r in rows if r["ok"]))
    best = rows[-1]["diff"]
    check("the stiffest spring is indistinguishable from hard", best < 1e-6 * CUBE_A,
          f"{best:.2e} mm = {best / CUBE_A:.1e} of the cube side")
    slow = max(r["seconds"] for r in rows) / hard["seconds"]
    print(f"  run time: hard {hard['seconds']:.2f} s; springs {min(r['seconds'] for r in rows):.2f}-"
          f"{max(r['seconds'] for r in rows):.2f} s (worst {slow:.1f}x hard)")

    print("\nWhere it breaks (reported, not checks):")
    for mode, K in [("zero", 0.1), ("zero", 1.0), ("zero", 1000.0), ("spring", LIMIT_PROBE)]:
        r = soft_on_plate(out, mode, K)
        what = "one zero-length spring per node" if mode == "zero" else "3 offset springs per node"
        print(f"  {what}, K = {K:g}: {'converged' if r['ok'] else 'FAILED to converge'} ({r['seconds']:.2f} s)")
        if mode == "zero" and K >= 1.0:
            check(f"zero-length spring, K = {K:g}, does not solve (so the generator must not use it)", not r["ok"], "see docs/05 section 3")
    print("\nFAIL: " + ", ".join(fails) if fails else "\nALL S3 CHECKS PASSED")
    return 1 if fails else 0


def extras(out: Path) -> None:
    """The studies behind docs/05 section 3. Printed, not pass/fail (the point is the numbers)."""
    hard = soft_on_plate(out, "hard")
    print("\nExtra 1: spring offset delta vs stiffness (max node difference to hard, mm; slip = max |u|/delta)")
    print(f"{'K N/mm':>8}{'delta mm':>10}{'diff mm':>11}{'max |u| mm':>12}{'|u|/delta':>11}")
    for K in (1e-3, 0.05, 1.0, 100.0):
        for delta in (0.1, 0.5, 1.0, 2.0, 5.0, 10.0):
            r = soft_on_plate(out, "spring", K, offset=delta)
            print(f"{K:>8g}{delta:>10g}{max_node_difference(r, hard):>11.4e}{r['max_slip']:>12.3e}{r['slip_ratio']:>11.2e}")
    print("\nExtra 2: one zero-length spring per node, 1/30 s steps vs 1/120 s steps")
    for sub in (1, 4):
        h = soft_on_plate(out, "hard", sub=sub)
        print(f"  step 1/{FPS * sub} s: " + ", ".join(
            f"K={K:g} {'ok' if soft_on_plate(out, 'zero', K, sub=sub)['ok'] else 'FAILED'}" for K in (0.01, 0.1, 1.0, 1000.0)
        ) + ("" if h["ok"] else "  (hard failed!)"))
    print("\nExtra 3: tissue stiffness E and mesh size (n^3 hexes), spring K, 3 springs/node, offset 2 mm")
    print(f"{'E MPa':>7}{'n':>3}{'nodes':>6}{'E*h N/mm':>10}{'K':>7}{'diff mm':>11}{'diff*K*N':>10}")
    for E, n in [(0.02, 2), (0.02, 4), (0.02, 6), (0.2, 4), (2.0, 4)]:
        h = soft_on_plate(out, "hard", E=E, n=n)
        for K in (0.05, 1.0, 100.0):
            r = soft_on_plate(out, "spring", K, E=E, n=n)
            d = max_node_difference(r, h)
            print(f"{E:>7g}{n:>3}{(n + 1) ** 2:>6}{E * CUBE_A / n:>10.3g}{K:>7g}{d:>11.3e}{d * K * (n + 1) ** 2:>10.3f}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--extra"]
    folder = Path(args[0]) if args else Path("runs/s3_attachment")
    code = main(folder)
    if "--extra" in sys.argv:
        extras(folder)
    sys.exit(code)
