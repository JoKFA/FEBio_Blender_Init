"""The FEBio scene generator (T-06a): scene.json + trajectory.json -> one .feb, plus everything needed
to read the result back (docs/05, ADR-21, ADR-32, ADR-36).

What it writes, all in mm, N, MPa, s (mass in tonnes):

- **Real size (ADR-36, docs/05 section 2).** Every coordinate in the .feb is geometric mm times k
  (`units.physics_length_scale`): tet nodes, rigid reference points, rigid-body translations, spring
  anchors. Physical values stay real: E, ν, density, gravity 9810 mm/s², spring stiffness in N/mm.
  `run` divides the positions FEBio writes (to positions.txt, next to the .feb) by k again. Multiplying by k = 1.0 is exact, so k = 1 gives
  the same .feb as an unscaled model, byte for byte.
- **Gravity** is written with its sign flipped (docs/05 pit 1, ADR-10): FEBio's `const` body load pushes
  the other way from the manual's formula. It is on from t = 0, as in the lab's frames 0-14.
- **Soft tissue**: the tet mesh (`tetmesh.load`, hash checked; fTetWild's tets are already positive,
  pit 11) with its neo-Hookean material. Exactly one soft tissue in phase 1.
- **Rigid bodies**: every attachment target becomes one. A fixed bone is fixed in all six degrees of
  freedom; a prescribed bone and an anchor follow their driver (`scene.driver_motion`, which also
  computes derived drivers: the lip-corner anchor turns α × the jaw's angle about jaw01's hinge). The
  per-frame transform T = [R | t] is written as the body's reference point moving by T(c) - c (times
  k) and a rotation vector log(R), six load curves, linear between frames; the reference point c is
  the driver's hinge pivot (the source's pivot for a derived driver), else the origin. FEBio reads the
  three prescribed rotations Ru, Rv, Rw as a rotation vector (checked: a turn about (1, 1, 0.5) is
  followed to 5×10⁻¹² mm). Each rigid body owns one small stub tet (FEBio drops nodes that belong to
  no element). Its density means nothing: every rigid body here is fixed or fully prescribed. Bones
  that nothing is attached to (the teeth) are not written.
- **Attachments (ADR-36, docs/05 section 3)**: each attached display vertex uses the tet `embed` gives
  it (the containing tet, else the boundary tet nearest to it) and its barycentric λ there.
  `hard`: the union of those tets' nodes joins the target with a `rigid` boundary condition.
  `spring`: the same node set; node j gets three linear springs along the world x, y, z axes (the
  target's axes at frame 0, which is the rest pose) to anchor nodes δ away that join the target (δ is
  SPRING_OFFSET_EDGES median tet edges, times k), each
  of stiffness base × Σ_v w_v λ̂_vj with λ̂ = (λ̃ + 1/4) / 2 (`embed.spread`). FEBio gives one stiffness
  per spring material, so the stiffnesses of a group are put into log-spaced levels between the
  group's smallest and largest, as few as keep every node's binned stiffness within
  SPRING_LEVEL_TOLERANCE (2 %) of its own value (each level's stiffness is the mean of its members,
  so the group's total stiffness is kept), one material per level (cheap).
  Conflicts: a node held hard and wanted by a spring stays hard and loses its springs (counted); a
  node wanted hard by two different rigid bodies is an error. A node wanted by two spring groups
  gets the springs of both (counted, not an error).
- **Nodes in no element** are refused: FEBio drops them with only a warning (docs/05 pit 18).
- **Guard**: a display vertex farther than MAX_DISTANCE_EDGES × the median tet edge from its tet is
  an error; nothing is written (the correspondence cannot be trusted, docs/05 section 3 rule 5).
- **Dynamic analysis** at the scene's fps and substeps, one must point per frame (FEBio then writes
  frames 1..N and no frame 0, pit 15), adaptive stepping as in spikes/s2_lips_febio.py (up to
  MAX_RETRIES retries, the step may shrink to dt × DTMIN_FRACTION), generalized-α with spectral radius
  RHOI = 0 (the strongest damping of fast modes FEBio offers; T-07's runs used it; a value we chose).
  The scene's physical damping must be 0: physical damping is not built yet (T-12).

Load controller ids run 1, 2, 3 ... with no gaps (pit 15). Every number is written through `_num`,
so a numpy scalar never reaches the file (FEBio reads the text "np.float64(0.1)" as 0 and says
nothing; found while building this, docs/05 pit 16). FEBio runs with `febio.DEFAULT_THREADS` threads (pit 17): the same .feb
gives the same positions within 1e-9 mm, and to the last digit with one thread (`asrp run --threads 1`).
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from asrp_core import embed, febio, scene as scene_module, tetmesh
from asrp_core.asset import coords

FEBIO_GRAVITY_SIGN = -1.0  # docs/05 pit 1: FEBio's const body load acts opposite to the manual
RHOI = 0.0
SPRING_LEVEL_TOLERANCE = 0.02  # each node's binned stiffness is within 2 % of its own value (T-06a review)
MAX_SPRING_LEVELS = 5000  # a stop for the search for the level count; one FEBio material per level is cheap
MAX_DISTANCE_EDGES = 2.0
MAX_RETRIES = 8
OPT_ITER = 10
DTMIN_FRACTION = 1 / 256
REST_TOLERANCE = 1e-9  # frame 0 of every motion must be the rest pose (identity) to this
RIGID_DENSITY = 1e-9  # t/mm^3; no meaning, every rigid body is fixed or fully prescribed
# The spring offset δ in FEBio coordinates is this many median tet edges (times k). docs/05 section 3 wants
# δ >= 10 x the largest slip; the first lip run slipped 0.30 mm (FEBio coordinates) on the lower lip, which is
# 0.19 of one edge (1.62 mm) and 0.04 of five. T-07: for stiff springs δ from 0.1 to 10 mm changes nothing.
SPRING_OFFSET_EDGES = 5.0


class GenerateError(ValueError):
    """The scene cannot be turned into a FEBio model; the message says what and what to do."""


@dataclass
class Body:
    name: str
    motion: str  # "fixed" | "prescribed"
    driver: str | None
    reference_mm: np.ndarray  # geometric mm
    transforms: list | None  # per frame, geometric mm (column vectors, row by row); None when fixed
    material_id: int = 0
    stub: list = field(default_factory=list)  # FEBio node ids of its stub tet


@dataclass
class Group:
    name: str
    kind: str
    target: str
    vertices: np.ndarray  # display vertex indices with weight > 0
    weights: np.ndarray
    nodes: np.ndarray  # tet node indices (0-based), sorted
    clipped: int  # barycentric coordinates < 0 among the group's vertices (set to 0 in λ̃)
    max_distance_mm: float
    base_stiffness: float | None = None
    stiffness: dict = field(default_factory=dict)  # spring: node -> N/mm, after conflicts
    conflicts: int = 0  # spring nodes dropped because a hard attachment holds them
    shared: int = 0  # spring nodes also wanted by another spring group
    levels: list = field(default_factory=list)  # spring: stiffness of each level, N/mm
    level_of: dict = field(default_factory=dict)  # spring: node -> level index
    max_level_error: float = 0.0


@dataclass
class Spring:
    node: int  # tet node index (0-based)
    anchor: int  # FEBio node id of the anchor
    axis: int
    group: str
    level: int


@dataclass
class Model:
    scene: scene_module.Scene
    scene_path: Path
    trajectory: object
    k: float
    fps: float
    substeps: int
    frames: int
    mesh: tetmesh.TetMesh
    display: np.ndarray  # (v, 3) rest display vertices, geometric mm
    faces: list
    embedding: embed.Embedding
    median_edge_mm: float
    delta: float  # spring offset in FEBio coordinates (geometric mm x k)
    bodies: dict  # name -> Body
    groups: list  # [Group]
    hard: dict  # tet node index -> body name
    springs: list  # [Spring]
    gravity: list  # physical direction, mm/s^2
    node_count: int = 0
    feb_text: str = ""
    report: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)  # from `asrp check`, carried into the run report


def _x(name: str) -> str:
    """A scene name written into the .feb (attribute or text): XML-escaped. Scene validation already limits names to
    letters, digits, _ - . ; this is the second line of defence."""
    return escape(name, {'"': "&quot;"})


def _num(v) -> str:
    """A number as FEBio reads it: Python's float repr (round-trips exactly), never a numpy repr."""
    return repr(float(v))


def _vec(p) -> str:
    return ",".join(_num(c) for c in p)


def _matrix(m) -> tuple[np.ndarray, np.ndarray]:
    a = np.array(m, dtype=float).reshape(4, 4)
    return a[:3, :3], a[:3, 3]


def rotation_vector(r: np.ndarray) -> np.ndarray:
    """log(R): axis times angle (rad), for a rotation of less than pi."""
    angle = math.acos(max(-1.0, min(1.0, (np.trace(r) - 1) / 2)))
    w = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if angle > math.pi - 1e-3:
        raise GenerateError(f"a driver turns by {math.degrees(angle):.1f} degrees in one frame relative to rest; "
                            "rotations near 180 degrees are not supported")
    if angle < 1e-12:
        return w / 2
    return w * (angle / (2 * math.sin(angle)))


def _reference(s: scene_module.Scene, driver: str | None) -> np.ndarray:
    by_name = {d.name: d for d in s.drivers}
    d = by_name.get(driver)
    if d is not None and d.blend is not None:
        d = by_name.get(d.blend.of)
    if d is not None and d.hinge is not None:
        return np.array(d.hinge.pivot_mm, dtype=float)
    return np.zeros(3)


def _bin(values: np.ndarray, n_levels: int) -> tuple[np.ndarray, np.ndarray, float]:
    lo, hi = float(values.min()), float(values.max())
    if n_levels == 1 or hi <= lo * (1 + 1e-12):
        which = np.zeros(len(values), dtype=int)
    else:
        edges = np.geomspace(lo, hi, n_levels + 1)
        which = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, n_levels - 1)
    used = sorted(set(which.tolist()))
    renumber = {old: new for new, old in enumerate(used)}
    levels = np.array([values[which == old].mean() for old in used])
    which = np.array([renumber[int(w)] for w in which])
    return levels, which, float((np.abs(levels[which] - values) / values).max())


def _levels(stiffness: dict, tolerance: float = SPRING_LEVEL_TOLERANCE) -> tuple[list, dict, float]:
    """Put node stiffnesses into log-spaced levels, as few as keep every node's level within `tolerance` (relative)
    of its own value; each level gets its members' mean, so the total is kept. Returns (levels, node -> level, worst error)."""
    nodes = sorted(stiffness)
    values = np.array([stiffness[n] for n in nodes])
    n = 1
    while True:
        levels, which, error = _bin(values, n)
        if error <= tolerance:
            break
        n += 1
        if n > MAX_SPRING_LEVELS:
            raise GenerateError(f"{n} stiffness levels are not enough to keep every spring within {tolerance:.0%} of its "
                                "value; the stiffnesses of this group spread too widely")
    return levels.tolist(), {nd: int(w) for nd, w in zip(nodes, which)}, error


def build(scene_path, trajectory_path, *, delta: float | None = None,
          level_tolerance: float = SPRING_LEVEL_TOLERANCE) -> Model:
    """Read and check the scene and the trajectory, map the attachments and write the .feb text.
    `delta` is the spring offset in FEBio coordinates (default: SPRING_OFFSET_EDGES x the median tet edge x k)."""
    scene_path, trajectory_path = Path(scene_path), Path(trajectory_path)
    checked = scene_module.check(scene_path, trajectory_path)
    if checked.errors:
        raise GenerateError("the scene or trajectory has errors (see `asrp check`): " + "; ".join(checked.errors))
    s, traj = checked.scene, checked.trajectory
    base = scene_path.parent
    if len(s.soft_tissues) != 1:
        raise GenerateError(f"the generator builds exactly one soft tissue (phase 1), the scene has {len(s.soft_tissues)}")
    tissue = s.soft_tissues[0]
    mesh, _ = tetmesh.load(base / tissue.tet_mesh.path)
    if len(np.unique(mesh.tets)) != len(mesh.nodes):
        raise GenerateError(f"tet mesh {tissue.tet_mesh.path} has nodes that belong to no tet; FEBio drops such nodes "
                            "with only a warning (docs/05 pit 18), so they would have no result. Regenerate the tet mesh")
    display, faces = coords.read_obj(base / tissue.mesh.path)
    k = float(s.units.physics_length_scale.value)
    fps = float(s.solver.fps.value)
    substeps = int(s.solver.substeps_per_frame.value)
    if s.solver.damping.value != 0:
        raise GenerateError(f"solver.damping is {s.solver.damping.value}; physical damping is not built yet "
                            "(T-12). Set it to 0 (FEBio's numerical damping rhoi is the generator's setting)")
    if traj.frames < 2:
        raise GenerateError("the trajectory needs at least 2 frames (frame 0 is the rest pose)")
    motions = scene_module.driver_motion(s, traj)

    # Bodies: every attachment target. A soft tissue as target is not built in phase 1.
    bones = {b.name: b for b in s.bones}
    anchors = {a.name: a for a in s.anchors}
    bodies: dict[str, Body] = {}
    for a in s.attachments:
        if a.target in bodies:
            continue
        if a.target in bones:
            b = bones[a.target]
            driver = b.driver if b.motion == "prescribed" else None
        elif a.target in anchors:
            driver = anchors[a.target].driver
        else:
            raise GenerateError(f"attachment {a.name!r} goes to {a.target!r}, a soft tissue; attachments between soft "
                                "tissues are not built in phase 1 (ADR-32)")
        transforms = None
        if driver is not None:
            transforms = motions[driver]
            rest = np.array(transforms[0], dtype=float)
            if np.abs(rest - np.eye(4).ravel()).max() > REST_TOLERANCE:
                raise GenerateError(f"driver {driver!r}: frame 0 is not the rest pose (identity); the model starts "
                                    "at rest, so a trajectory must too")
        bodies[a.target] = Body(a.target, "fixed" if driver is None else "prescribed", driver,
                                _reference(s, driver), transforms)

    e = embed.embed(mesh, display)
    h = tetmesh.quality(mesh).median_edge_mm
    limit = MAX_DISTANCE_EDGES * h
    worst = int(np.argmax(e.distance_mm))
    if e.distance_mm[worst] > limit:
        raise GenerateError(
            f"display vertex {worst} is {e.distance_mm[worst]:.3f} mm from its tet, more than {MAX_DISTANCE_EDGES:g} x the "
            f"median tet edge ({limit:.3f} mm): the display mesh and the tet mesh do not fit together (docs/05 "
            "section 3 rule 5). Regenerate the tet mesh from this surface")

    groups, hard = [], {}
    for a in s.attachments:
        w = np.array([[i, x] for i, x in a.weights if x > 0], dtype=float).reshape(-1, 2)
        verts, weights = w[:, 0].astype(int), w[:, 1]
        g = Group(a.name, a.kind, a.target, verts, weights, np.unique(e.nodes[verts]),
                  int((e.bary[verts] < 0).sum()), float(e.distance_mm[verts].max()))
        if a.kind == "hard":
            for n in g.nodes.tolist():
                other = hard.get(n)
                if other is not None and other[0] != a.target:
                    raise GenerateError(
                        f"tet node {n} is held hard by {other[1]!r} (to {other[0]!r}) and by {a.name!r} (to {a.target!r}): "
                        "one node cannot join two rigid bodies (docs/05 section 3 rule 4)")
                hard.setdefault(n, (a.target, a.name))
        else:
            g.base_stiffness = float(a.stiffness.value)
            share = np.zeros(len(mesh.nodes))
            np.add.at(share, e.nodes[verts], weights[:, None] * embed.spread(e.bary[verts]))
            g.stiffness = {int(n): g.base_stiffness * float(share[n]) for n in g.nodes}
        groups.append(g)
    spring_groups = [g for g in groups if g.kind == "spring"]
    for g in spring_groups:
        held = [n for n in g.stiffness if n in hard]
        g.conflicts = len(held)
        for n in held:
            del g.stiffness[n]
    for g in spring_groups:
        others = set().union(*[set(o.stiffness) for o in spring_groups if o is not g])
        g.shared = len(set(g.stiffness) & others)
        if g.stiffness:
            g.levels, g.level_of, g.max_level_error = _levels(g.stiffness, level_tolerance)

    model = Model(s, scene_path, traj, k, fps, substeps, traj.frames, mesh, display, faces, e, h,
                  SPRING_OFFSET_EDGES * h * k if delta is None else float(delta), bodies, groups,
                  {n: t for n, (t, _) in hard.items()}, [], list(s.solver.gravity_mm_per_s2.value))
    model.warnings = list(checked.warnings)
    model.feb_text = _feb(model)
    # docs/05 pit 16: FEBio reads "np.float64(0.1)" as 0 and says nothing
    found = re.search(r"\bnp\.|float64", model.feb_text)
    if found:
        at = found.start()
        raise GenerateError(f"the .feb text contains {found.group()!r} (near {model.feb_text[max(0, at - 30):at + 30]!r}): "
                            "a numpy value was written with its repr instead of a plain float. FEBio would read it as 0 "
                            "without a message (docs/05 pit 16); write every number through generate._num")
    model.report = _report(model)
    return model


def _feb(m: Model) -> str:
    n = len(m.mesh.nodes)
    k = m.k
    node_lines = [f'      <node id="{i + 1}">{_vec(p * k)}</node>' for i, p in enumerate(m.mesh.nodes)]
    next_id = n + 1
    stub_size = m.median_edge_mm * k
    bodies = list(m.bodies.values())
    for i, b in enumerate(bodies):
        b.material_id = i + 2
        c = b.reference_mm * k
        b.stub = list(range(next_id, next_id + 4))
        for q in (c, c + [stub_size, 0, 0], c + [0, stub_size, 0], c + [0, 0, stub_size]):
            node_lines.append(f'      <node id="{next_id}">{_vec(q)}</node>')
            next_id += 1
    springs, anchors_of = [], {b.name: [] for b in bodies}
    for g in m.groups:
        for node in sorted(g.stiffness):
            for axis in range(3):
                q = m.mesh.nodes[node] * k
                q = q + np.eye(3)[axis] * m.delta
                node_lines.append(f'      <node id="{next_id}">{_vec(q)}</node>')
                springs.append(Spring(node, next_id, axis, g.name, g.level_of[node]))
                anchors_of[g.target].append(next_id)
                next_id += 1
    m.springs = springs
    m.node_count = next_id - 1

    mat = m.scene.soft_tissues[0].material.params
    materials = [f"""    <material id="1" name="tissue" type="neo-Hookean">
      <density>{_num(mat["density_t_per_mm3"].value)}</density>
      <E>{_num(mat["E_mpa"].value)}</E>
      <v>{_num(mat["nu"].value)}</v>
    </material>"""]
    elements = ['    <Elements type="tet4" name="tissue">\n' + "\n".join(
        f'      <elem id="{i + 1}">{",".join(str(int(c) + 1) for c in t)}</elem>' for i, t in enumerate(m.mesh.tets)
    ) + "\n    </Elements>"]
    domains = ['    <SolidDomain name="tissue" mat="tissue"/>']
    eid = len(m.mesh.tets) + 1
    for b in bodies:
        rb = f"rb_{_x(b.name)}"
        materials.append(f"""    <material id="{b.material_id}" name="{rb}" type="rigid body">
      <density>{_num(RIGID_DENSITY)}</density>
      <center_of_mass>{_vec(b.reference_mm * k)}</center_of_mass>
    </material>""")
        elements.append(f'    <Elements type="tet4" name="{rb}">\n      <elem id="{eid}">{",".join(map(str, b.stub))}</elem>\n    </Elements>')
        domains.append(f'    <SolidDomain name="{rb}" mat="{rb}"/>')
        eid += 1

    nodesets, ties = [], []
    for b in bodies:
        held = sorted(node + 1 for node, t in m.hard.items() if t == b.name)
        for label, ids in (("hard", held), ("anchors", anchors_of[b.name])):
            if ids:
                nodesets.append(f'    <NodeSet name="{label}_{_x(b.name)}">{",".join(map(str, ids))}</NodeSet>')
                ties.append(f'    <bc name="{label}_{_x(b.name)}" type="rigid" node_set="{label}_{_x(b.name)}">\n'
                            f'      <rb>rb_{_x(b.name)}</rb>\n    </bc>')

    sets, discrete, dmat = [], [], 0
    for g in m.groups:
        for level, stiffness in enumerate(g.levels):
            pairs = [(sp.node + 1, sp.anchor) for sp in springs if sp.group == g.name and sp.level == level]
            dmat += 1
            name = f"springs_{_x(g.name)}_{level}"
            sets.append(f'    <DiscreteSet name="{name}">\n'
                        + "\n".join(f"      <delem>{a},{b}</delem>" for a, b in pairs) + "\n    </DiscreteSet>")
            discrete.append(f'    <discrete_material id="{dmat}" name="{name}" type="linear spring">\n'
                            f"      <E>{_num(stiffness)}</E>\n    </discrete_material>")
            discrete.append(f'    <discrete dmat="{dmat}" discrete_set="{name}"/>')

    dt_frame = 1.0 / m.fps
    dt = dt_frame / m.substeps
    times = [f * dt_frame for f in range(m.frames)]
    curves = [[(0.0, 1.0), (times[-1], 1.0)], None]  # 1 gravity, 2 must points (written below)
    rigid = []
    for b in bodies:
        rb = f"rb_{_x(b.name)}"
        if b.motion == "fixed":
            rigid.append(f'    <rigid_bc name="{_x(b.name)}_fixed" type="rigid_fixed">\n      <rb>{rb}</rb>\n'
                         + "\n".join(f"      <{d}_dof>1</{d}_dof>" for d in ("Rx", "Ry", "Rz", "Ru", "Rv", "Rw"))
                         + "\n    </rigid_bc>")
            continue
        c = b.reference_mm
        moves, turns = [], []
        for t in b.transforms:
            r, tr = _matrix(t)
            moves.append((r @ c + tr - c) * k)
            turns.append(rotation_vector(r))
        # FEBio 4 names the translation dofs x, y, z in rigid_displacement and Ru, Rv, Rw in rigid_rotation.
        for dof, values, kind in [("x", [p[0] for p in moves], "rigid_displacement"),
                                  ("y", [p[1] for p in moves], "rigid_displacement"),
                                  ("z", [p[2] for p in moves], "rigid_displacement"),
                                  ("Ru", [w[0] for w in turns], "rigid_rotation"),
                                  ("Rv", [w[1] for w in turns], "rigid_rotation"),
                                  ("Rw", [w[2] for w in turns], "rigid_rotation")]:
            curves.append(list(zip(times, values)))
            rigid.append(f'    <rigid_bc name="{_x(b.name)}_{dof}" type="{kind}">\n      <rb>{rb}</rb>\n'
                         f'      <dof>{dof}</dof>\n      <value lc="{len(curves)}">1.0</value>\n    </rigid_bc>')

    load_lines = []
    for i, pts in enumerate(curves):
        if pts is None:
            load_lines.append('    <load_controller id="2" name="must_points" type="loadcurve">\n'
                              "      <interpolate>STEP</interpolate>\n      <points>\n"
                              + "\n".join(f"        <pt>{_num(t)},{_num(dt)}</pt>" for t in times)
                              + "\n      </points>\n    </load_controller>")
            continue
        load_lines.append(f'    <load_controller id="{i + 1}" name="lc{i + 1}" type="loadcurve">\n'
                          "      <interpolate>LINEAR</interpolate>\n      <points>\n"
                          + "\n".join(f"        <pt>{_num(t)},{_num(v)}</pt>" for t, v in pts)
                          + "\n      </points>\n    </load_controller>")
    gravity = "\n".join(f'      <{axis} lc="1">{_num(FEBIO_GRAVITY_SIGN * g)}</{axis}>' for axis, g in zip("xyz", m.gravity))
    return f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<!-- written by asrp_core.generate (T-06a): coordinates are geometric mm x k = {_num(k)} (ADR-36) -->
<febio_spec version="4.0">
  <Module type="solid"/>
  <Control>
    <analysis>DYNAMIC</analysis>
    <time_steps>{(m.frames - 1) * m.substeps}</time_steps>
    <step_size>{_num(dt)}</step_size>
    <plot_level>PLOT_MUST_POINTS</plot_level>
    <output_level>OUTPUT_MUST_POINTS</output_level>
    <time_stepper type="default">
      <max_retries>{MAX_RETRIES}</max_retries>
      <opt_iter>{OPT_ITER}</opt_iter>
      <dtmin>{_num(dt * DTMIN_FRACTION)}</dtmin>
      <dtmax lc="2">{_num(dt)}</dtmax>
    </time_stepper>
    <solver type="solid">
      <qn_method type="BFGS"/>
      <rhoi>{_num(RHOI)}</rhoi>
    </solver>
  </Control>
  <Material>
{chr(10).join(materials)}
  </Material>
  <Mesh>
    <Nodes name="all">
{chr(10).join(node_lines)}
    </Nodes>
{chr(10).join(elements)}
{chr(10).join(nodesets)}
{chr(10).join(sets)}
  </Mesh>
  <MeshDomains>
{chr(10).join(domains)}
  </MeshDomains>
  <Boundary>
{chr(10).join(ties)}
  </Boundary>
  <Rigid>
{chr(10).join(rigid)}
  </Rigid>
  <Discrete>
{chr(10).join(discrete)}
  </Discrete>
  <Loads>
    <body_load name="gravity" type="const">
{gravity}
    </body_load>
  </Loads>
  <LoadData>
{chr(10).join(load_lines)}
  </LoadData>
  <Output>
    <logfile>
      <node_data data="x;y;z" name="{febio.NODE_DATA_NAME}" delim="," file="{febio.NODE_DATA_FILE}"/>
    </logfile>
  </Output>
</febio_spec>
"""


def node_rest_febio(m: Model) -> dict[int, np.ndarray]:
    """FEBio node id -> rest position in FEBio coordinates, for every node the .feb writes (parsed back)."""
    out = {}
    for line in m.feb_text.splitlines():
        line = line.strip()
        if line.startswith("<node id="):
            nid = int(line.split('"')[1])
            out[nid] = np.array([float(c) for c in line.split(">")[1].split("<")[0].split(",")])
    return out


def _report(m: Model) -> dict:
    groups = []
    for g in m.groups:
        r = {"name": g.name, "kind": g.kind, "to": g.target, "display_vertices": int(len(g.vertices)),
             "nodes": int(len(g.nodes)), "clipped_coordinates": g.clipped,
             "max_distance_mm": g.max_distance_mm, "conflicts": g.conflicts}
        if g.kind == "spring":
            values = list(g.stiffness.values())
            r |= {"spring_nodes": len(g.stiffness), "springs": 3 * len(g.stiffness),
                  "nodes_shared_with_other_spring_groups": g.shared,
                  "base_stiffness_n_per_mm": g.base_stiffness,
                  "node_stiffness_n_per_mm": {"min": min(values), "max": max(values), "sum": sum(values)} if values else None,
                  "weight_sum": float(g.weights.sum()),
                  "level_count": len(g.levels), "levels_n_per_mm": g.levels, "max_level_error": g.max_level_error,
                  "level_error_limit": SPRING_LEVEL_TOLERANCE,
                  "binned_total_n_per_mm": float(sum(g.levels[g.level_of[n]] for n in g.stiffness))}
        groups.append(r)
    attached = {b.name for b in m.bodies.values()}
    return {
        "physics_length_scale_k": m.k,
        "median_tet_edge_mm": m.median_edge_mm,
        "max_distance_limit_mm": MAX_DISTANCE_EDGES * m.median_edge_mm,
        "display_vertices": int(len(m.display)),
        "display_vertices_outside_tets": int(m.embedding.outside.sum()),
        "display_max_distance_mm": float(m.embedding.distance_mm.max()),
        "most_negative_barycentric": float(m.embedding.bary.min()),
        "spring_offset_delta_febio_mm": m.delta,
        "spring_offset_delta_geometric_mm": m.delta / m.k,
        "groups": groups,
        "rigid_bodies": [{"name": b.name, "motion": b.motion, "driver": b.driver,
                          "reference_mm": b.reference_mm.tolist()} for b in m.bodies.values()],
        "bones_not_written": [b.name for b in m.scene.bones if b.name not in attached],
        "febio_nodes": {"tissue": int(len(m.mesh.nodes)), "rigid_stubs": 4 * len(m.bodies),
                        "spring_anchors": len(m.springs), "total": m.node_count},
        "tets": int(len(m.mesh.tets)),
        "springs": len(m.springs),
        "hard_nodes": len(m.hard),
    }
