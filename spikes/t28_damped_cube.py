"""Spike for T-28 stage 1 (not product code): does FEBio 4's physical damping give the textbook decay?

Where physical damping is in FEBio 4.13 (read in the FEBio User's Manual 4.13 in the install folder's doc/,
and in the strings of febiomech.dll): the "mass damping" body load (manual 3.13.3.7) adds the body force
f = -C rho v per volume, v the velocity, C a rate (1/s). The other forms the manual has are not a Rayleigh
damping of a solid: `dyn_damping` belongs to the explicit solver only (3.3.9), the rigid damper and rigid
angular damper join two rigid bodies (3.12.4.8-9), the viscoelastic materials (4.4) are a relaxation law,
not a damping coefficient, and there is no stiffness-proportional (Rayleigh beta) option in the Control
section. So the form tried here is the mass damping body load:

    <body_load name="damping" type="mass damping">
      <C>6.283</C>
    </body_load>

The model is a one-degree-of-freedom oscillator whose answer is in every textbook: a nearly rigid cube (edge
A = 10 mm, neo-Hookean E = 1000 MPa, nu = 0.3, rho = 1.06e-9 t/mm^3, so mass m = rho A^3) hangs on four
vertical linear springs (stiffness K N/mm each, 10 mm long) from a rigid frame fixed in all six degrees of
freedom, as in spikes/s3_attachment.py step 1. Gravity (9810 mm/s^2 down) is switched on at t = 0 and held, so
the cube bounces about its hanging position. Its vertical motion obeys

    m x'' + C m x' + 4 K x = m g        (the mass damping force on a body translating as a whole is C m v)

so, with omega = sqrt(4 K / m): the undamped period is T = 2 pi / omega; with damping the amplitude decays as
exp(-sigma t) with sigma = C / 2 (exactly, for any C below 2 omega), and the damped period is
2 pi / sqrt(omega^2 - sigma^2). K is chosen so that T = 0.1 s (10 Hz), C so that the damping ratio
zeta = C / (2 omega) is 0.05 (a value we chose; it is not the lab's, which is D6).

Time step 1/600 s (60 steps a period). "Numerical damping off" is FEBio's Newmark rule with beta 1/4, gamma 1/2
(rhoi = -2, FEBio's own default; the trapezoidal rule, which has no numerical damping and a period error of
about (omega dt)^2 / 12 = 0.09 % here). Not rhoi = 1: measured here, on this cube with springs, the
generalized-alpha rule at rhoi = 1 takes away part of the bounce although it should not (reported below as
it is, with the same cube without springs as the comparison that shows it is the springs). Measured on the
cube's centre (mean of its nodes): the times of its turning points (parabola through the three samples around
each), the period from the spacing of every second turning point, the decay rate from a least-squares line
through log |peak-to-trough height| against time (the height between successive turning points decays like
the amplitude; no equilibrium value needed).

Pass/fail (docs/09 T-28): undamped period within 2 % of 2 pi / omega; damped decay rate within 10 % of C / 2.
Controls, each must come out as stated or the spike exits 1: the undamped run's decay rate must fail the 10 %
test against C / 2; a run with C / 10 (wrong by 10 x) must fail the 10 % test against C / 2.

For information (no pass/fail; the numbers are archived):
- the spring cube with rhoi = 1, undamped and with C: the extra decay the springs bring at rhoi = 1, and
  whether the mass damping still adds C / 2 on top of it;
- the spring cube, undamped, rhoi = 0 at 1/600 s and at one step per frame (1/30 s, the lip runs' step): how
  much of the bounce today's numerical damping takes away;
- the same cube without springs, soft (E = 0.005 MPa) with its base tied to the frame, bouncing under the
  gravity step: Newmark, rhoi = 1 and Newmark with C. Mass damping damps every mode at the same rate C / 2,
  so this checks C / 2 on a deforming solid as well (no textbook period: its first mode is a 3D cube's).

    uv run python spikes/t28_damped_cube.py [work folder]     # writes data/preview/t28_damped_cube.json
"""

import itertools
import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

from asrp_core import febio
from asrp_core.doctor import febio_exe

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "preview" / "t28_damped_cube.json"
EDGE = 10.0  # mm
CELLS = 2
E_MPA, NU = 1000.0, 0.3
E_SOFT_MPA = 0.005  # the cube without springs
RHO = 1.06e-9  # t/mm^3
G = 9810.0  # mm/s^2 down; FEBio's const body load wants +9810 for a pull down (docs/05 pit 1)
SPRING_LENGTH = 10.0  # mm, vertical, from each top corner up to its anchor
PERIOD_S = 0.1  # the undamped period we design for
ZETA = 0.05  # damping ratio we choose (ours, not the lab's)
DT = 1.0 / 600
DURATION = 1.0  # s: 10 periods
NEWMARK = -2.0  # FEBio's rhoi value for Newmark beta 1/4, gamma 1/2 (manual 3.3.5): no numerical damping
PERIOD_TOL, DECAY_TOL = 0.02, 0.10

MASS = RHO * EDGE**3
OMEGA = 2 * math.pi / PERIOD_S
K_SPRING = MASS * OMEGA**2 / 4  # N/mm, each of four
C_NOMINAL = 2 * ZETA * OMEGA  # 1/s


def signed_volume(a, b, c, d) -> float:
    return float(np.linalg.det(np.array([np.subtract(b, a), np.subtract(c, a), np.subtract(d, a)])) / 6.0)


def feb_text(*, c_damping: float | None, rhoi: float, dt: float, springs: bool = True) -> tuple[str, list[int]]:
    """The .feb and the FEBio ids of the nodes to measure: the whole cube (springs) or its top face (no springs,
    the base tied to the frame)."""
    nodes = []

    def node(p):
        nodes.append(tuple(float(x) for x in p))
        return len(nodes)

    grid = {(i, j, k): node((EDGE * i / CELLS, EDGE * j / CELLS, EDGE * k / CELLS))
            for k in range(CELLS + 1) for j in range(CELLS + 1) for i in range(CELLS + 1)}
    tets = []
    for i, j, k in itertools.product(range(CELLS), repeat=3):
        for axes in itertools.permutations(range(3)):
            corner, tet = [0, 0, 0], [grid[i, j, k]]
            for axis in axes:
                corner[axis] = 1
                tet.append(grid[i + corner[0], j + corner[1], k + corner[2]])
            if signed_volume(*(nodes[t - 1] for t in tet)) < 0:
                tet[1], tet[2] = tet[2], tet[1]
            tets.append(tet)
    if springs:
        top = [grid[i, j, CELLS] for i in (0, CELLS) for j in (0, CELLS)]
        tied = [node(np.add(nodes[t - 1], (0, 0, SPRING_LENGTH))) for t in top]
        measured = list(grid.values())
    else:
        top, tied = [], [n for (i, j, k), n in grid.items() if k == 0]
        measured = [n for (i, j, k), n in grid.items() if k == CELLS]
    centre = (EDGE / 2, EDGE / 2, EDGE + SPRING_LENGTH)
    stub = [node(np.add(centre, d)) for d in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))]
    steps = round(DURATION / dt)
    damping = "" if c_damping is None else (
        f'    <body_load name="damping" type="mass damping">\n      <C>{c_damping!r}</C>\n    </body_load>\n')
    node_xml = "\n".join(f'      <node id="{i + 1}">{",".join(repr(c) for c in p)}</node>' for i, p in enumerate(nodes))
    elems = "\n".join(f'      <elem id="{n + 1}">{",".join(map(str, t))}</elem>' for n, t in enumerate(tets))
    spring_set = discrete = ""
    if springs:
        spring_set = ('    <DiscreteSet name="springs">\n'
                      + "\n".join(f"      <delem>{t},{a}</delem>" for t, a in zip(top, tied)) + "\n    </DiscreteSet>\n")
        discrete = f"""  <Discrete>
    <discrete_material id="1" name="spring" type="linear spring">
      <E>{K_SPRING!r}</E>
    </discrete_material>
    <discrete dmat="1" discrete_set="springs"/>
  </Discrete>
"""
    text = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<febio_spec version="4.0">
  <Module type="solid"/>
  <Control>
    <analysis>DYNAMIC</analysis>
    <time_steps>{steps}</time_steps>
    <step_size>{dt!r}</step_size>
    <solver type="solid">
      <qn_method type="BFGS"/>
      <rhoi>{rhoi!r}</rhoi>
    </solver>
  </Control>
  <Material>
    <material id="1" name="cube" type="neo-Hookean">
      <density>{RHO!r}</density>
      <E>{(E_MPA if springs else E_SOFT_MPA)!r}</E>
      <v>{NU!r}</v>
    </material>
    <material id="2" name="frame" type="rigid body">
      <density>1e-9</density>
      <center_of_mass>{",".join(repr(c) for c in centre)}</center_of_mass>
    </material>
  </Material>
  <Mesh>
    <Nodes name="all">
{node_xml}
    </Nodes>
    <Elements type="tet4" name="cube">
{elems}
    </Elements>
    <Elements type="tet4" name="frame">
      <elem id="{len(tets) + 1}">{",".join(map(str, stub))}</elem>
    </Elements>
    <NodeSet name="tied">{",".join(map(str, tied))}</NodeSet>
{spring_set}  </Mesh>
  <MeshDomains>
    <SolidDomain name="cube" mat="cube"/>
    <SolidDomain name="frame" mat="frame"/>
  </MeshDomains>
  <Boundary>
    <bc name="tied" type="rigid" node_set="tied">
      <rb>frame</rb>
    </bc>
  </Boundary>
  <Rigid>
    <rigid_bc name="frame_fixed" type="rigid_fixed">
      <rb>frame</rb>
{chr(10).join(f"      <{d}_dof>1</{d}_dof>" for d in ("Rx", "Ry", "Rz", "Ru", "Rv", "Rw"))}
    </rigid_bc>
  </Rigid>
{discrete}  <Loads>
    <body_load name="gravity" type="const">
      <z lc="1">{G!r}</z>
    </body_load>
{damping}  </Loads>
  <LoadData>
    <load_controller id="1" name="gravity_on" type="loadcurve">
      <interpolate>LINEAR</interpolate>
      <points>
        <pt>0.0,1.0</pt>
        <pt>{DURATION!r},1.0</pt>
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
    return text, measured


def turning_points(t: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Times and values of the local extrema of z(t), each refined by a parabola through three samples."""
    out_t, out_z = [], []
    for i in range(1, len(z) - 1):
        if (z[i] - z[i - 1]) * (z[i + 1] - z[i]) < 0:
            a, b, c = z[i - 1], z[i], z[i + 1]
            den = a - 2 * b + c
            s = 0.5 * (a - c) / den if den != 0 else 0.0
            h = t[i + 1] - t[i]
            out_t.append(t[i] + s * h)
            out_z.append(b - 0.25 * (a - c) * s)
    return np.array(out_t), np.array(out_z)


def measure(t: np.ndarray, z: np.ndarray) -> dict:
    tt, zz = turning_points(t, z)
    if len(tt) < 4:
        return {"turning_points": int(len(tt)), "period_s": None, "decay_rate_per_s": None}
    period = float(np.mean(tt[2:] - tt[:-2]))  # every second turning point is one full period apart
    heights = np.abs(np.diff(zz))
    mid = (tt[1:] + tt[:-1]) / 2
    keep = heights > heights.max() * 1e-6  # below this, round-off, not the decay
    slope = float(np.polyfit(mid[keep], np.log(heights[keep]), 1)[0])
    return {"turning_points": int(len(tt)), "period_s": period, "decay_rate_per_s": -slope,
            "first_height_mm": float(heights[0]), "last_height_mm": float(heights[keep][-1])}


def run_case(work: Path, name: str, exe: Path, *, c_damping, rhoi, dt, springs=True) -> dict:
    folder = work / name
    folder.mkdir(parents=True, exist_ok=True)
    text, measured = feb_text(c_damping=c_damping, rhoi=rhoi, dt=dt, springs=springs)
    feb = folder / "cube.feb"
    feb.write_text(text, encoding="ascii", newline="\n")
    result = febio.run(feb, exe, threads=1)
    out = {"case": name, "springs": springs, "mass_damping_C_per_s": c_damping, "rhoi": rhoi, "dt_s": dt,
           "normal_termination": result.normal_termination, "febio_version": febio.version(result.log)}
    if not result.normal_termination:
        failure = febio.read_failure(result.log)
        out["failure"] = failure.message if failure else "no normal termination"
        return out
    hist = febio.read_node_data(result.log, "positions")
    t = np.array([0.0, *hist.times])
    z0 = EDGE / 2 if springs else EDGE
    z = np.array([z0] + [float(np.mean([v[i][2] for i in measured])) for v in hist.values])
    out |= measure(t, z)
    out["steps_logged"] = len(hist.times)
    return out


def main() -> None:
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="t28_cube_"))
    exe = febio_exe()
    sigma = C_NOMINAL / 2
    theory = {
        "mass_t": MASS, "spring_stiffness_n_per_mm_each": K_SPRING, "springs": 4,
        "omega_rad_per_s": OMEGA, "undamped_period_s": 2 * math.pi / OMEGA,
        "damping_ratio_zeta": ZETA, "mass_damping_C_per_s": C_NOMINAL,
        "decay_rate_per_s": sigma, "damped_period_s": 2 * math.pi / math.sqrt(OMEGA**2 - sigma**2),
        "static_extension_mm": G / OMEGA**2,
        "formulas": "omega = sqrt(4K/m), m = rho A^3; T = 2 pi / omega; mass damping f = -C rho v gives "
                    "m x'' + C m x' + 4K x = m g, so the amplitude decays as exp(-(C/2) t) and the damped period "
                    "is 2 pi / sqrt(omega^2 - (C/2)^2)",
    }
    specs = {  # name: (C, rhoi, dt, springs)
        "undamped": (None, NEWMARK, DT, True),
        "damped": (C_NOMINAL, NEWMARK, DT, True),
        "damped_C_over_10": (C_NOMINAL / 10, NEWMARK, DT, True),
        "info_springs_undamped_rhoi1": (None, 1.0, DT, True),
        "info_springs_damped_rhoi1": (C_NOMINAL, 1.0, DT, True),
        "info_springs_undamped_rhoi0_dt600": (None, 0.0, DT, True),
        "info_springs_undamped_rhoi0_dt30": (None, 0.0, 1 / 30, True),
        "info_nosprings_undamped_newmark": (None, NEWMARK, DT, False),
        "info_nosprings_undamped_rhoi1": (None, 1.0, DT, False),
        "info_nosprings_damped_newmark": (C_NOMINAL, NEWMARK, DT, False),
    }
    cases = {}
    for name, (c, rhoi, dt, springs) in specs.items():
        cases[name] = run_case(work, name, exe, c_damping=c, rhoi=rhoi, dt=dt, springs=springs)
        if not cases[name]["normal_termination"]:
            print(f"{name}: FEBio did not finish: {cases[name].get('failure')}")

    def rate(name):
        return cases[name].get("decay_rate_per_s")

    def rel(measured, expected):
        return None if measured is None or expected is None else (measured - expected) / expected

    def minus(a, b):
        return None if a is None or b is None else a - b

    results = {
        "a_undamped_period_error": rel(cases["undamped"].get("period_s"), theory["undamped_period_s"]),
        "a_undamped_decay_rate_per_s": rate("undamped"),
        "b_damped_decay_rate_error": rel(rate("damped"), sigma),
        "b_damped_period_error": rel(cases["damped"].get("period_s"), theory["damped_period_s"]),
        "control_undamped_decay_vs_damped_theory": rel(rate("undamped"), sigma),
        "control_C_over_10_decay_vs_damped_theory": rel(rate("damped_C_over_10"), sigma),
        "C_over_10_decay_vs_its_own_theory": rel(rate("damped_C_over_10"), sigma / 10),
        "info_springs_rhoi1_undamped_decay_rate_per_s": rate("info_springs_undamped_rhoi1"),
        "info_springs_rhoi1_damping_adds_vs_theory": rel(minus(rate("info_springs_damped_rhoi1"),
                                                               rate("info_springs_undamped_rhoi1")), sigma),
        "info_springs_rhoi0_dt600_decay_rate_per_s": rate("info_springs_undamped_rhoi0_dt600"),
        "info_springs_rhoi0_dt30_decay_rate_per_s": rate("info_springs_undamped_rhoi0_dt30"),
        "info_springs_rhoi0_dt30_period_error": rel(cases["info_springs_undamped_rhoi0_dt30"].get("period_s"),
                                                    theory["undamped_period_s"]),
        "info_nosprings_newmark_decay_rate_per_s": rate("info_nosprings_undamped_newmark"),
        "info_nosprings_rhoi1_decay_rate_per_s": rate("info_nosprings_undamped_rhoi1"),
        "info_nosprings_damping_adds_vs_theory": rel(minus(rate("info_nosprings_damped_newmark"),
                                                           rate("info_nosprings_undamped_newmark")), sigma),
    }

    def ok(x, tol):
        return x is not None and abs(x) <= tol

    verdicts = {
        "a_period_within_2_percent": ok(results["a_undamped_period_error"], PERIOD_TOL),
        "b_decay_within_10_percent": ok(results["b_damped_decay_rate_error"], DECAY_TOL),
        "control_undamped_fails_the_10_percent_test": (rate("undamped") is not None
                                                       and not ok(results["control_undamped_decay_vs_damped_theory"],
                                                                  DECAY_TOL)),
        "control_C_over_10_fails_the_10_percent_test": (rate("damped_C_over_10") is not None
                                                        and not ok(results["control_C_over_10_decay_vs_damped_theory"],
                                                                   DECAY_TOL)),
    }
    archive = {
        "format": "asrp-spike/1",
        "spike": "spikes/t28_damped_cube.py",
        "command": "uv run python spikes/t28_damped_cube.py",
        "febio_version": cases["undamped"].get("febio_version"),
        "damping_form": '<body_load name="damping" type="mass damping"><C>(1/s)</C></body_load>',
        "numerical_damping_off": "rhoi -2: FEBio's Newmark rule, beta 1/4, gamma 1/2 (manual 3.3.5)",
        "model": {"edge_mm": EDGE, "cells": CELLS, "E_mpa": E_MPA, "E_mpa_without_springs": E_SOFT_MPA, "nu": NU,
                  "density_t_per_mm3": RHO, "gravity_mm_per_s2": G, "spring_length_mm": SPRING_LENGTH, "dt_s": DT,
                  "duration_s": DURATION, "threads": 1,
                  "zeta_note": "zeta 0.05 is ours, not the lab's (their damping is D6)"},
        "theory": theory,
        "cases": cases,
        "results": results,
        "tolerances": {"period": PERIOD_TOL, "decay_rate": DECAY_TOL},
        "verdicts": verdicts,
        "passed": all(verdicts.values()),
    }
    ARCHIVE.write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8", newline="\n")
    for key, value in results.items():
        shown = "None" if value is None else f"{value:+.4%}" if ("error" in key or "vs" in key) else f"{value:.5g}"
        print(f"{key:48s} {shown}")
    for key, value in verdicts.items():
        print(f"{'PASS' if value else 'FAIL'}  {key}")
    print(f"wrote {ARCHIVE.relative_to(ROOT).as_posix()}")
    if not archive["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
