"""Audit (not product code): why does FEBio's rhoi = 1 damp a cube on discrete springs more than rhoi = 0?

The finding (spikes/t28_damped_cube.py, docs/05 pit 20): FEBio's manual says rhoi = 1 is no numerical damping and
rhoi = 0 the strongest, but the cube on 4 linear springs, undamped, decayed at 1.64 /s with rhoi = 1 and at
0.035 /s with rhoi = 0 (Newmark, rhoi = -2: 3.4e-6 /s), dt = 1/600 s. This spike maps it and tests, one at a
time, what could cause it. It reuses the cube of spikes/t28_damped_cube.py (feb_text, measure) and changes its
.feb text in one place per experiment.

Q1  the map: decay rate and period error of the bounce for rhoi in RHOS at dt 1/300, 1/600, 1/1200, with springs
    (period error against the theory 2 pi / omega) and without (t28's soft cube, base tied; the reference period
    is Richardson's extrapolation of the Newmark runs at 1/600 and 1/1200). Next to each FEBio number, what a
    one-degree-of-freedom generalized-alpha oscillator gives (FEBio's alpha_f = 1 / (1 + rho),
    alpha_m = (2 - rho) / (1 + rho), beta, gamma from the FEBio Theory Manual 3.6.5) in two versions:
    "consistent", the spring force taken at t_{n+alpha_f} like every other internal force, and "spring at n+1",
    the spring force taken at the end of the step. They differ only for 0 < rho, where alpha_f < 1.
Q2  one change at a time at dt 1/600, rhoi 1 (and 0.5 and Newmark as the controls): (a) the spring built another
    way FEBio 4.13 has (a linear truss element; a "rigid spring" connector with the cube made a rigid body);
    (b) the spring's far end on fixed nodes instead of a rigid body; (c) the discrete material type ("linear
    spring" as the generator writes it, "tension-only linear spring", "nonlinear spring" with force = x);
    (d) the Control settings the generator adds (its time stepper and must points), and the solver's
    quasi-Newton method (Broyden), full Newton (max_ups 0), an unsymmetric matrix, the line search off.
Q3  convergence: rhoi 1 (and 0.5) with dtol, etol 100x tighter, rtol on, full Newton, max_refs 50; iteration
    counts per step from the log before and after.
Q4  energy: rhoi 1, 0.5 and Newmark with velocities and strain energy density logged: kinetic + spring + strain +
    gravity potential, and where the motion settles against the static extension.
Q5  the real lips, nothing moving (gravity on at t = 0): rhoi 0, 0.5, 1 and Newmark through the scene's
    solver.numerical_damping_rhoi on a copy of the scene, default substeps, no physical damping; the vertical
    motion of the free lower lip over frames 1..30.

    uv run python spikes/audit_rhoi_springs.py --work <folder outside the repo> [--scene S --motion M] [--only cube|lips]

Without --scene the lips are imported from data/lab_export into the work folder; without --motion a still motion
(87 frames, head and jaw01 at rest, settle until frame 14) is written there. Writes data/preview/audit_rhoi_springs.json
(--only merges into it).
"""

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t28_damped_cube as cube  # noqa: E402  (the cube builder and the turning-point measure)

from asrp_core import febio, generate, run, simulate, trajectory  # noqa: E402
from asrp_core.doctor import febio_exe  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "preview" / "audit_rhoi_springs.json"
COMMAND = "uv run python spikes/audit_rhoi_springs.py --work <folder outside the repo>"
RHOS = (-2.0, 0.0, 0.25, 0.5, 0.7, 0.9, 1.0)
DTS = (1 / 300, 1 / 600, 1 / 1200)
DT = cube.DT  # 1/600
TOP = [(0.0, 0.0), (cube.EDGE, 0.0), (0.0, cube.EDGE), (cube.EDGE, cube.EDGE)]  # the spring corners, as t28 orders them
LIP_RHOS = (0.0, 0.5, 1.0, -2.0)
LIP_FRAMES = (1, 30)
STILL_FRAMES, SETTLE = 87, 14


# ---------------------------------------------------------------- the one-degree-of-freedom model

def alpha_parameters(rho: float) -> tuple[float, float, float, float]:
    """FEBio's alpha_f, alpha_m, beta, gamma (Theory Manual 3.6.5; rhoi -2 is Newmark beta 1/4, gamma 1/2)."""
    if rho == -2:
        return 1.0, 1.0, 0.25, 0.5
    af, am = 1 / (1 + rho), (2 - rho) / (1 + rho)
    return af, am, 0.25 * (1 + am - af) ** 2, 0.5 + am - af


def sdof(rho: float, omega: float, dt: float, spring_at_end: bool) -> dict:
    """Decay rate (1/s) and period of x'' + omega^2 x = 0 under FEBio's generalized-alpha rule: inertia at n+alpha_m,
    the spring at n+alpha_f (consistent) or at n+1 (spring_at_end). From the eigenvalues of the step matrix."""
    af, am, b, g = alpha_parameters(rho)
    s = 1.0 if spring_at_end else af
    w2 = omega * omega
    lhs = np.array([[1, 0, -b * dt * dt], [0, 1, -g * dt], [s * w2, 0, am]])
    rhs = np.array([[1, dt, (0.5 - b) * dt * dt], [0, 1, (1 - g) * dt], [-(1 - s) * w2, 0, -(1 - am)]])
    ev = np.linalg.eigvals(np.linalg.solve(lhs, rhs))
    lam = ev[np.argmax(np.abs(ev.imag))]
    if abs(lam.imag) < 1e-14:
        return {"decay_rate_per_s": None, "period_s": None, "spectral_radius": float(np.abs(ev).max())}
    return {"decay_rate_per_s": -math.log(abs(lam)) / dt, "period_s": 2 * math.pi * dt / abs(math.atan2(lam.imag, lam.real)),
            "spectral_radius": float(abs(lam))}


# ---------------------------------------------------------------- the .feb variants (one change each)

def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"the cube .feb no longer contains {old[:60]!r}; spikes/t28_damped_cube.py changed")
    return text.replace(old, new, 1)


def _block(text: str, start: str, end: str) -> str:
    """The text from `start` through the first `end` after it."""
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]


SOLVER_HEAD = '    <solver type="solid">\n      <qn_method type="BFGS"/>\n'
SOLVER_EXTRAS = {
    "broyden": ('      <qn_method type="Broyden"/>\n', ""),
    "full_newton": ('      <qn_method type="BFGS">\n        <max_ups>0</max_ups>\n      </qn_method>\n',
                    "      <max_refs>50</max_refs>\n"),
    "unsymmetric": (None, "      <symmetric_stiffness>0</symmetric_stiffness>\n"),
    "no_line_search": (None, "      <lstol>0</lstol>\n"),
}
FULL_NEWTON = '      <qn_method type="BFGS">\n        <max_ups>0</max_ups>\n      </qn_method>\n'
# Q3: FEBio's defaults (which the generator keeps: dtol 0.001, etol 0.01, rtol 0 = off, BFGS with max_ups 10,
# max_refs 15), then a full Newton update every iteration (max_ups 0, max_refs 50) with dtol and etol 10x and 100x
# tighter, and with the residual test switched on.
TOLERANCES = {
    "default": None,
    "full_newton_x10": "      <dtol>0.0001</dtol>\n      <etol>0.001</etol>\n      <max_refs>50</max_refs>\n",
    "full_newton_x100": "      <dtol>1e-05</dtol>\n      <etol>0.0001</etol>\n      <max_refs>50</max_refs>\n",
    "full_newton_rtol_1e-6": "      <rtol>1e-06</rtol>\n      <max_refs>50</max_refs>\n",
}
Q3_RHOS = (1.0, 0.9, 0.5, 0.25, 0.0, -2.0)
LOG_TAIL = '      <node_data data="x;y;z" name="positions" delim=","/>\n'


def variant(name: str, rhoi: float, dt: float) -> tuple[str, list[int], dict]:
    """The spring cube's .feb with one change, the node ids to measure, and what was changed."""
    text, measured = cube.feb_text(c_damping=None, rhoi=rhoi, dt=dt, springs=True)
    steps = round(cube.DURATION / dt)
    note = {"change": name}
    if name == "baseline":
        note["what"] = "spikes/t28_damped_cube.py as it is: 4 'linear spring' discrete elements, far end on a fixed rigid body"
    elif name == "anchors_fixed_nodes":
        text = _swap(text, _block(text, '    <bc name="tied" type="rigid"', "</bc>\n"),
                     '    <bc name="tied" type="zero displacement" node_set="tied">\n'
                     "      <x_dof>1</x_dof>\n      <y_dof>1</y_dof>\n      <z_dof>1</z_dof>\n    </bc>\n")
        note["what"] = "the springs' far ends fixed by a zero displacement boundary condition, not joined to the rigid frame"
    elif name in ("tension_only", "nonlinear_spring"):
        old = _block(text, '<discrete_material id="1" name="spring"', "</discrete_material>")
        if name == "tension_only":
            new = (f'<discrete_material id="1" name="spring" type="tension-only linear spring">\n'
                   f"      <E>{cube.K_SPRING!r}</E>\n    </discrete_material>")
        else:
            new = (f'<discrete_material id="1" name="spring" type="nonlinear spring">\n'
                   f"      <scale>{cube.K_SPRING!r}</scale>\n      <measure>elongation</measure>\n"
                   '      <force type="math">\n        <math>x</math>\n      </force>\n    </discrete_material>')
        text = _swap(text, old, new)
        note["what"] = f"discrete material '{new.split('type=')[1].split(chr(34))[1]}' instead of 'linear spring'"
    elif name == "truss":
        pairs = re.findall(r"<delem>(\d+),(\d+)</delem>", text)
        first = len(re.findall(r"<elem id=", text)) + 1
        area = 1.0
        e_truss = cube.K_SPRING * cube.SPRING_LENGTH / area  # E A / L = K
        text = _swap(text, _block(text, '    <DiscreteSet name="springs">', "</DiscreteSet>\n"),
                     '    <Elements type="line2" name="trusses">\n'
                     + "".join(f'      <elem id="{first + i}">{a},{b}</elem>\n' for i, (a, b) in enumerate(pairs))
                     + "    </Elements>\n")
        text = _swap(text, _block(text, "  <Discrete>\n", "  </Discrete>\n"), "")
        text = _swap(text, "  </Material>\n",
                     f'    <material id="3" name="truss" type="linear truss">\n      <density>{cube.RHO * 1e-6!r}</density>\n'
                     f"      <E>{e_truss!r}</E>\n      <v>0.3</v>\n    </material>\n  </Material>\n")
        text = _swap(text, "  </MeshDomains>\n",
                     '    <BeamDomain name="trusses" mat="truss" type="linear-truss">\n'
                     f"      <cross_sectional_area>{area!r}</cross_sectional_area>\n    </BeamDomain>\n  </MeshDomains>\n")
        note["what"] = (f"4 line2 'linear-truss' elements (E A / L = K, A = {area}, density 1e-6 of the cube's) instead of "
                        "the discrete springs")
    elif name == "rigid_spring":
        text = _swap(text, _block(text, '<material id="1" name="cube" type="neo-Hookean">', "</material>"),
                     f'<material id="1" name="cube" type="rigid body">\n      <density>{cube.RHO!r}</density>\n'
                     f"      <center_of_mass>{cube.EDGE / 2!r},{cube.EDGE / 2!r},{cube.EDGE / 2!r}</center_of_mass>\n"
                     "    </material>")
        text = _swap(text, _block(text, '    <bc name="tied" type="rigid"', "</bc>\n"), "")
        text = _swap(text, _block(text, '    <NodeSet name="tied">', "</NodeSet>\n"), "")
        text = _swap(text, _block(text, '    <DiscreteSet name="springs">', "</DiscreteSet>\n"), "")
        text = _swap(text, _block(text, "  <Discrete>\n", "  </Discrete>\n"), "")
        conns = "".join(
            f'    <rigid_connector name="spring{i + 1}" type="rigid spring">\n      <body_a>1</body_a>\n      <body_b>2</body_b>\n'
            f"      <insertion_a>{x!r},{y!r},{cube.EDGE!r}</insertion_a>\n"
            f"      <insertion_b>{x!r},{y!r},{cube.EDGE + cube.SPRING_LENGTH!r}</insertion_b>\n"
            f"      <k>{cube.K_SPRING!r}</k>\n    </rigid_connector>\n" for i, (x, y) in enumerate(TOP))
        text = _swap(text, "  </Rigid>\n", conns + "  </Rigid>\n")
        note["what"] = ("the cube made a rigid body (same density) and the 4 springs written as 'rigid spring' connectors to "
                        "the fixed frame (the springs' far-end nodes are then in no element; FEBio removes them)")
    elif name == "generator_control":
        must = "\n".join(f"        <pt>{(i * dt)!r},{dt!r}</pt>" for i in range(steps + 1))
        text = _swap(text, SOLVER_HEAD.splitlines(keepends=True)[0],
                     "    <plot_level>PLOT_MUST_POINTS</plot_level>\n    <output_level>OUTPUT_MUST_POINTS</output_level>\n"
                     f'    <time_stepper type="default">\n      <max_retries>{generate.MAX_RETRIES}</max_retries>\n'
                     f"      <opt_iter>{generate.OPT_ITER}</opt_iter>\n      <dtmin>{dt * generate.DTMIN_FRACTION!r}</dtmin>\n"
                     f'      <dtmax lc="2">{dt!r}</dtmax>\n    </time_stepper>\n' + SOLVER_HEAD.splitlines(keepends=True)[0])
        text = _swap(text, "  </LoadData>\n",
                     '    <load_controller id="2" name="must_points" type="loadcurve">\n      <interpolate>STEP</interpolate>\n'
                     f"      <points>\n{must}\n      </points>\n    </load_controller>\n  </LoadData>\n")
        note["what"] = ("the Control lines generate.py adds: plot/output at must points, the default time stepper with "
                        f"max_retries {generate.MAX_RETRIES}, opt_iter {generate.OPT_ITER}, dtmin dt/{round(1 / generate.DTMIN_FRACTION)}, "
                        "dtmax dt on a must-point curve (here a must point every step)")
    elif name in SOLVER_EXTRAS:
        qn, extra = SOLVER_EXTRAS[name]
        head = SOLVER_HEAD if qn is None else SOLVER_HEAD.splitlines(keepends=True)[0] + qn
        text = _swap(text, SOLVER_HEAD, head + extra)
        note["what"] = "solver lines: " + " ".join((head.splitlines()[1:] if qn else []) + extra.split()).strip()
    else:
        raise ValueError(name)
    return text, measured, note


# ---------------------------------------------------------------- running and measuring

def iterations(log: Path) -> dict:
    text = log.read_text(errors="replace")
    its = [int(x) for x in re.findall(r"number of iterations\s*:\s*(\d+)", text)]
    refs = [int(x) for x in re.findall(r"number of reformations\s*:\s*(\d+)", text)]
    if not its:
        return {"steps": 0}
    return {"steps": len(its), "iterations_mean": float(np.mean(its)), "iterations_max": int(max(its)),
            "iterations_min": int(min(its)), "iterations_total": int(sum(its)), "reformations_total": int(sum(refs)),
            "first_steps": its[:5]}


def run_feb(folder: Path, text: str, exe: Path) -> febio.Run:
    folder.mkdir(parents=True, exist_ok=True)
    feb = folder / "cube.feb"
    feb.write_text(text, encoding="ascii", newline="\n")
    return febio.run(feb, exe, threads=1)


def z_series(log: Path, measured: list[int], z0: float) -> tuple[np.ndarray, np.ndarray]:
    hist = febio.read_node_data(log, "positions")
    t = np.array([0.0, *hist.times])
    z = np.array([z0] + [float(np.mean([v[i][2] for i in measured])) for v in hist.values])
    return t, z


def cube_case(work: Path, name: str, exe: Path, text: str, measured: list[int], springs: bool = True) -> dict:
    r = run_feb(work / name, text, exe)
    out = {"normal_termination": r.normal_termination, "febio_version": febio.version(r.log)}
    if not r.normal_termination:
        failure = febio.read_failure(r.log)
        out["failure"] = failure.message if failure else "no normal termination"
        done = r.log.read_text(errors="replace").count("------- converged at time")
        out["steps_converged_before_failure"] = done
        out["failed_step"] = step_norms(r.log, done + 1)
        if done < 60:  # less than one period: nothing to measure
            return out
        out["measured_over_the_converged_steps_only"] = True
    t, z = z_series(r.log, measured, cube.EDGE / 2 if springs else cube.EDGE)
    out |= cube.measure(t, z)
    out["iterations"] = iterations(r.log)
    return out


def rel(a, b):
    return None if a is None or b is None else (a - b) / b


def q1(work: Path, exe: Path) -> dict:
    rows = []
    for springs in (True, False):
        for dt in DTS:
            for rho in RHOS:
                text, measured = cube.feb_text(c_damping=None, rhoi=rho, dt=dt, springs=springs)
                name = f"q1_{'springs' if springs else 'nosprings'}_dt{round(1 / dt)}_rhoi{rho:g}"
                case = cube_case(work, name, exe, text, measured, springs)
                rows.append({"springs": springs, "dt_s": dt, "steps_per_s": round(1 / dt), "rhoi": rho, **case})
                print(f"{name}: decay {case.get('decay_rate_per_s')} period {case.get('period_s')}", flush=True)
    newmark = {r["steps_per_s"]: r["period_s"] for r in rows if not r["springs"] and r["rhoi"] == -2}
    t_ref = (4 * newmark[1200] - newmark[600]) / 3  # Richardson: Newmark's period error goes as dt^2
    for r in rows:
        omega_ref = cube.OMEGA if r["springs"] else 2 * math.pi / t_ref
        r["period_error"] = rel(r.get("period_s"), 2 * math.pi / omega_ref)
        r["omega_dt"] = omega_ref * r["dt_s"]
        for key, end in (("model_consistent", False), ("model_spring_at_n_plus_1", True)):
            m = sdof(r["rhoi"], omega_ref, r["dt_s"], end)
            r[key] = {"decay_rate_per_s": m["decay_rate_per_s"], "period_error": rel(m["period_s"], 2 * math.pi / omega_ref)}
    return {"rows": rows, "nosprings_reference_period_s": t_ref,
            "nosprings_reference": "Richardson extrapolation of the Newmark periods at dt 1/600 and 1/1200: (4 T_1200 - T_600) / 3",
            "springs_reference_period_s": 2 * math.pi / cube.OMEGA}


Q2_CHANGES = ("baseline", "anchors_fixed_nodes", "tension_only", "nonlinear_spring", "truss", "rigid_spring",
              "generator_control", "broyden", "full_newton", "unsymmetric", "no_line_search")


def q2(work: Path, exe: Path, changes=Q2_CHANGES, prefix="q2") -> dict:
    out = {}
    for name in changes:
        out[name] = {}
        for rho in (1.0, 0.5, -2.0):
            text, measured, note = variant(name, rho, DT)
            case = cube_case(work, f"{prefix}_{name}_rhoi{rho:g}", exe, text, measured)
            case["period_error"] = rel(case.get("period_s"), 2 * math.pi / cube.OMEGA)
            out[name]["what"] = note["what"]
            out[name][f"rhoi_{rho:g}"] = case
            print(f"{prefix} {name} rhoi {rho:g}: decay {case.get('decay_rate_per_s')} period_error {case.get('period_error')} "
                  f"{case.get('failure', '')}", flush=True)
    return out


def q4(work: Path, exe: Path) -> dict:
    out = {}
    m, ktot = cube.MASS, 4 * cube.K_SPRING
    x_static = cube.G / cube.OMEGA**2
    for rho in (1.0, 0.5, -2.0):
        text, measured = cube.feb_text(c_damping=None, rhoi=rho, dt=DT, springs=True)
        text = _swap(text, LOG_TAIL, LOG_TAIL + '      <node_data data="vx;vy;vz" name="vel" delim=","/>\n'
                     '      <element_data data="sed" name="sed" delim=","/>\n')
        r = run_feb(work / f"q4_energy_rhoi{rho:g}", text, exe)
        if not r.normal_termination:
            out[f"rhoi_{rho:g}"] = {"normal_termination": False}
            continue
        pos = febio.read_node_data(r.log, "positions")
        vel = febio.read_node_data(r.log, "vel")
        sed = febio.read_node_data(r.log, "sed")
        rest = {}
        for line in text.splitlines():
            hit = re.match(r'\s*<node id="(\d+)">([^<]+)</node>', line)
            if hit:
                rest[int(hit.group(1))] = np.array([float(c) for c in hit.group(2).split(",")])
        pairs = [(int(a), int(b)) for a, b in re.findall(r"<delem>(\d+),(\d+)</delem>", text)]
        ntets = len(re.findall(r"<elem id=", text)) - 1  # the last element is the frame's stub
        v_tet = cube.EDGE**3 / ntets
        z0 = cube.EDGE / 2
        rows = []
        for t, p, v, s in zip(pos.times, pos.values, vel.values, sed.values):
            zc = float(np.mean([p[i][2] for i in measured]))
            vc = np.mean([v[i] for i in measured], axis=0)
            kinetic = 0.5 * m * float(vc @ vc)
            spring = sum(0.5 * cube.K_SPRING * (np.linalg.norm(np.array(p[a]) - rest[b]) - cube.SPRING_LENGTH) ** 2
                         for a, b in pairs)
            strain = sum(s[e][0] * v_tet for e in range(1, ntets + 1))
            gravity = m * cube.G * (zc - z0)  # gravity pulls -z
            rows.append((t, zc, kinetic, spring, strain, gravity))
        a = np.array(rows)
        total = a[:, 2:].sum(axis=1)
        e_osc0 = 0.5 * ktot * x_static**2  # the bounce's energy about the hanging position at t = 0
        e_eq = -0.5 * ktot * x_static**2  # total energy once the cube hangs at rest
        osc = total - e_eq
        last = a[:, 0] >= cube.DURATION - 0.5  # the last 0.5 s: five periods, so the mean is the centre of the bounce
        out[f"rhoi_{rho:g}"] = {
            "total_energy_start_mJ": float(total[0]), "total_energy_end_mJ": float(total[-1]),
            "bounce_energy_about_rest_t0_mJ": e_osc0,
            "bounce_energy_fraction_left_at_end": float(osc[-1] / e_osc0),
            "bounce_energy_fraction_left_mean_last_0p1s": float(np.mean(osc[a[:, 0] >= cube.DURATION - 0.1]) / e_osc0),
            "strain_energy_max_mJ": float(a[:, 4].max()),
            "terms": "kinetic 0.5 M |v_centre|^2, springs 0.5 K (L - L0)^2 each, cube strain sum(sed x V_tet), gravity M g (z - z0)",
            "centre_mean_last_0p5s_mm": float(np.mean(a[last, 1])),
            "centre_expected_at_rest_mm": z0 - x_static,
            "sag_error_vs_static_extension": float((z0 - np.mean(a[last, 1]) - x_static) / x_static),
        }
        print(f"q4 rhoi {rho:g}: bounce energy left {osc[-1] / e_osc0:.4f}", flush=True)
    return out


def step_norms(log: Path, step: int = 1) -> dict | None:
    """The residual and displacement norms (FEBio prints squared norms) of every iteration of one time step."""
    text = log.read_text(errors="replace")
    start = text.find(f"===== beginning time step {step} :")
    if start < 0:
        return None
    end = text.find("===== beginning time step", start + 10)
    chunk = text[start:end if end > 0 else len(text)]
    num = r"([0-9][0-9.eE+-]*)"
    res = [(float(a), float(b)) for a, b in re.findall(rf"^\s+residual\s+{num}\s+{num}\s", chunk, re.M)]
    disp = [float(b) for _, b in re.findall(rf"^\s+displacement\s+{num}\s+{num}\s", chunk, re.M)]
    if not res:
        return None
    return {"iterations": len(res), "residual_initial": res[0][0], "residual_last": res[-1][1],
            "residual_last_over_initial": res[-1][1] / res[0][0] if res[0][0] else None,
            "residual_per_iteration": [r[1] for r in res[:12]], "displacement_increment_per_iteration": disp[:12],
            "converged": "------- converged at time" in chunk}


def q3(work: Path, exe: Path) -> dict:
    out = {"note": "FEBio's convergence norms are squared norms; 'residual_last_over_initial' is of those"}
    for springs in (True, False):
        for rho in Q3_RHOS:
            for tol, extra in TOLERANCES.items():
                text, measured = cube.feb_text(c_damping=None, rhoi=rho, dt=DT, springs=springs)
                if extra is not None:
                    text = _swap(text, SOLVER_HEAD, SOLVER_HEAD.splitlines(keepends=True)[0] + FULL_NEWTON + extra)
                name = f"q3_{'springs' if springs else 'nosprings'}_rhoi{rho:g}_{tol}"
                case = cube_case(work, name, exe, text, measured, springs)
                case["step_1"] = step_norms(work / name / "cube.log", 1)
                case["step_100"] = step_norms(work / name / "cube.log", 100)
                out[name] = {"springs": springs, "rhoi": rho, "tolerances": tol, **case}
                print(f"{name}: {case.get('normal_termination')} decay {case.get('decay_rate_per_s')} "
                      f"its {case.get('iterations', {}).get('iterations_mean')} {case.get('failure', '')}", flush=True)
    return out


# ---------------------------------------------------------------- Q5, the lips

def still_motion(path: Path, scene: dict) -> None:
    drivers = [d["name"] for d in scene["drivers"] if d.get("hinge") or d.get("absent_means_rest")]
    eye = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    trajectory.write(path, trajectory.Trajectory(
        fps=float(scene["solver"]["fps"]["value"]), frames=STILL_FRAMES, drivers={d: [eye] * STILL_FRAMES for d in drivers},
        source_tag="ours", settle_until_frame=SETTLE, source="audit (ours): nothing moves; spikes/audit_rhoi_springs.py"))


def lips(work: Path, exe: Path, scene_dir: Path | None, motion: Path | None) -> dict:
    lw = work / "lips"
    lw.mkdir(parents=True, exist_ok=True)
    if scene_dir is None:
        from asrp_core.asset import lab
        scene_dir = lw / "imported"
        shutil.rmtree(scene_dir, ignore_errors=True)
        lab.import_asset(ROOT / "data" / "lab_export", scene_dir, ROOT / "data" / "tetmesh" / "lips.json")
        source = "imported from data/lab_export by this spike"
    else:
        source = "given with --scene (an imported lip scene)"
    base = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    if motion is None:
        motion = lw / "still.json"
        still_motion(motion, base)
        motion_source = "written by this spike: 87 frames, every driver at rest, settle until frame 14"
    else:
        motion_source = "given with --motion (head_still.json: 87 frames, nothing moves)"
    out = {"scene": source, "motion": motion_source, "cases": {}}
    region = None
    for rho in LIP_RHOS:
        folder = lw / f"scene_rhoi{rho:g}"
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(scene_dir, folder)
        data = json.loads((folder / "scene.json").read_text(encoding="utf-8"))
        assert float(data["solver"]["damping"]["value"]) == 0.0, "Q5 is without physical damping"
        data["solver"]["numerical_damping_rhoi"] = {"value": rho, "source": "ours",
                                                    "note": "audit of the rhoi finding (spikes/audit_rhoi_springs.py)"}
        (folder / "scene.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                           newline="\n")
        model = generate.build(folder / "scene.json", motion)
        if region is None:
            region = lower_lip_region(model)
        r = simulate.run_scene(folder / "scene.json", motion, lw / "runs", exe, f"still-rhoi{rho:g}")
        case = {"status": r.status, "substeps_per_frame": model.substeps, "rhoi_written": model.rhoi,
                "febio_s": r.report.get("timing", {}).get("febio_s"),
                "iterations": iterations(r.run_dir / run.LOG_NAME)}
        if r.status != "complete":
            case["failed_after_frame"] = febio.steps_done(r.run_dir / run.LOG_NAME) // model.substeps
            case["failure"] = r.report.get("checks", {}).get("a", {}).get("message")
        else:
            case |= ring(r.run_dir, model, region["nodes"])
        out["cases"][f"rhoi_{rho:g}"] = case
        print(f"lips rhoi {rho:g}: {r.status} {case.get('mean_z_turning_points_frames_1_30')} "
              f"{case.get('decay_per_frame')}", flush=True)
    out["region"] = {k: v for k, v in region.items() if k != "nodes"}
    return out


def lower_lip_region(model: generate.Model) -> dict:
    """Tet nodes no attachment holds whose nearest held node belongs to the lower lip's spring group."""
    nodes = np.asarray(model.mesh.nodes, dtype=float)
    owner = {n: "hard:" + str(b) for n, b in model.hard.items()}
    for g in model.groups:
        if g.kind == "spring":
            for n in g.stiffness:
                owner.setdefault(n, g.name)
    held = np.array(sorted(owner))
    free = np.array(sorted(set(range(len(nodes))) - set(owner)))
    d = np.linalg.norm(nodes[free][:, None, :] - nodes[held][None, :, :], axis=2)
    nearest = held[np.argmin(d, axis=1)]
    lower = [int(f) for f, n in zip(free, nearest) if owner[int(n)] == "lower_lip_on_jaw"]
    return {"nodes": lower, "node_count": len(lower), "free_tet_nodes": int(len(free)), "tet_nodes": int(len(nodes)),
            "rule": "tet nodes held by no attachment whose nearest held node is one of lower_lip_on_jaw's spring nodes"}


def ring(run_dir: Path, model: generate.Model, region: list[int]) -> dict:
    pos = run.read_positions(run_dir / run.POSITIONS)
    frames = [round(t * model.fps) for t in pos["times_s"]]
    index = {int(i): j for j, i in enumerate(pos["node_ids"])}
    cols = [index[n + 1] for n in region]
    z = np.empty(model.frames)
    z[0] = float(np.mean(np.asarray(model.mesh.nodes)[region, 2]))
    z[frames] = pos["positions"][:, cols, 2].mean(axis=1)
    per_node = np.empty((model.frames, len(region)))
    per_node[0] = np.asarray(model.mesh.nodes)[region, 2]
    per_node[frames] = pos["positions"][:, cols, 2]
    a, b = LIP_FRAMES
    rest = float(np.mean(z[-10:]))  # where it hangs at the end (frames 77-86)
    x = z[a:b + 1] - rest
    turns = [f for f in range(a + 1, b) if (z[f] - z[f - 1]) * (z[f + 1] - z[f]) < 0]
    heights = [abs(z[turns[i + 1]] - z[turns[i]]) for i in range(len(turns) - 1)]
    decay = None
    if len(heights) >= 2 and heights[0] > 0 and heights[-1] > 0:
        decay = (heights[-1] / heights[0]) ** (1 / (turns[-1] - turns[1]))
    node_x = per_node[a:b + 1] - per_node[-10:].mean(axis=0)
    node_sign_changes = (np.diff(np.sign(node_x), axis=0) != 0).sum(axis=0)
    return {
        "mean_z_rest_end_mm": rest,
        "mean_z_sag_frame_1_mm": float(z[1] - z[0]),
        "mean_z_sag_total_mm": float(rest - z[0]),
        "mean_z_minus_rest_frames_1_30_mm": [round(float(v), 6) for v in x],
        "mean_z_turning_points_frames_1_30": turns,
        "mean_z_peak_to_trough_mm": [round(float(h), 6) for h in heights],
        "decay_per_frame": decay,
        "mean_z_crosses_rest_frames_1_30": int((np.diff(np.sign(x)) != 0).sum()),
        "nodes_median_crossings_of_rest_frames_1_30": float(np.median(node_sign_changes)),
        "nodes_max_crossings_of_rest_frames_1_30": int(node_sign_changes.max()),
        "fraction_of_sag_done_by_frame_1": float((z[1] - z[0]) / (rest - z[0])) if rest != z[0] else None,
    }


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", required=True, help="work folder outside the repo (ASCII path)")
    ap.add_argument("--scene", help="an imported lip scene folder (with scene.json); default: import one")
    ap.add_argument("--motion", help="a still trajectory.json for it; default: write one")
    ap.add_argument("--only", choices=("cube", "lips"), help="run one part and merge it into the archive")
    args = ap.parse_args()
    work = Path(args.work).resolve()
    if ROOT in work.parents or work == ROOT:
        raise SystemExit("--work must be outside the repo")
    work.mkdir(parents=True, exist_ok=True)
    exe = febio_exe()
    archive = {
        "format": "asrp-spike/1", "spike": "spikes/audit_rhoi_springs.py", "command": COMMAND,
        "model": {"cube": "spikes/t28_damped_cube.py feb_text: edge 10 mm, 48 tets, E 1000 MPa (soft cube without springs "
                          "0.005 MPa, base tied), 4 vertical linear springs K each to a fixed rigid frame, gravity from t = 0, "
                          "1 s, single thread; undamped (no mass damping) everywhere here",
                  "omega_rad_per_s": cube.OMEGA, "spring_stiffness_n_per_mm_each": cube.K_SPRING, "mass_t": cube.MASS},
        "model_formulas": "alpha_f = 1/(1+rho), alpha_m = (2-rho)/(1+rho), beta = (1+alpha_m-alpha_f)^2/4, "
                          "gamma = 1/2+alpha_m-alpha_f (FEBio Theory Manual 3.6.5); rhoi -2: alpha 1, beta 1/4, gamma 1/2",
    }
    if args.only != "lips":
        archive["q1_map"] = q1(work / "cube", exe)
        archive["q2_one_change_at_a_time"] = q2(work / "cube", exe)
        archive["q3_convergence"] = q3(work / "cube", exe)
        archive["q4_energy"] = q4(work / "cube", exe)
        archive["febio_version"] = archive["q1_map"]["rows"][0].get("febio_version")
    if args.only != "cube":
        archive["q5_lips"] = lips(work, exe, Path(args.scene).resolve() if args.scene else None,
                                  Path(args.motion).resolve() if args.motion else None)
        lip_omega = 2 * math.pi / 0.014  # docs/05 pit 2: the lips' sway period, about 14 ms
        archive["q5_lips"]["model_one_frame_step"] = {
            "note": "the 1-dof model at the lips' ~14 ms period and one step per frame (1/30 s): amplitude kept per step "
                    "(spectral radius) and the period it would show; the lips mix tissue (consistent) and springs, so model only",
            "omega_dt": lip_omega / 30,
            **{f"rhoi_{rho:g}": {"consistent": sdof(rho, lip_omega, 1 / 30, False),
                                 "spring_at_n_plus_1": sdof(rho, lip_omega, 1 / 30, True)} for rho in LIP_RHOS}}
    if args.only and ARCHIVE.exists():  # read at the end, so two --only runs at the same time both land
        archive = json.loads(ARCHIVE.read_text(encoding="utf-8")) | archive
    ARCHIVE.write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {ARCHIVE.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
