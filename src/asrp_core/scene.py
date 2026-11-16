"""The scene description, scene.json, and its checker (T-05; docs/04 section 5.1).

docs/04 section 5.1 says what a scene must contain and why. This docstring is the exact format.

Format `asrp-scene/1`, one JSON object. Paths are relative to the folder scene.json is in, with
forward slashes. Big arrays (meshes, tet meshes, landmark skin weights) live in referenced files;
scene.json only names them and records their hash.

    {
      "format_version": "asrp-scene/1",
      "origin": {"asset": str, "export": str, "tool": str, "notes": str},   # where it came from
      "units": {
        "system": "mm-N-MPa-s",                       # the only one (ADR-04); mass is in tonnes
        "mm_per_scene_unit": PARAM,                   # required (ADR-22)
        "physics_length_scale": PARAM,                # optional; absent means 1.0, source "ours"
        "axes_from_source": str                       # e.g. "(x, y, z) -> (x, -z, y)"
      },
      "soft_tissues": [{
        "name": str,
        "mesh": FILE,                                 # surface, OBJ, mm, Z up
        "source_obj": SOURCE,                         # the original OBJ it was converted from
        "tet_mesh": {"path": str, "content_sha256": str},   # asrp-tetmesh file (asrp_core.tetmesh)
        "material": {"model": "neo-Hookean", "E_mpa": PARAM, "nu": PARAM,
                     "density_t_per_mm3": PARAM}
      }],
      "bones": [{
        "name": str, "mesh": FILE, "source_obj": SOURCE,
        "mass_t": PARAM,                              # value may be null: unknown, and unused
                                                      #   while the motion is fixed or fully given
        "motion": "fixed" | "prescribed",
        "driver": str                                 # prescribed only: the driver it follows
      }],
      "drivers": [{
        "name": str,                                  # the key in trajectory.json (e.g. jaw01)
        "hinge": null | {"pivot_mm": [x, y, z], "axis": [x, y, z],   # optional note (ADR-21):
                         "source": SOURCE_TAG, "note": str},         #   stand-in motion, checks
        "blend": {"of": str, "factor": PARAM,         # optional (T-06a): a derived driver with no
                  "relative_to": str},                #   motion of its own; docs/04 section 5.1. relative_to
                                                      #   (optional, T-28): factor x the motion of `of` seen
                                                      #   from that driver, T_rel exp(a log(T_rel^-1 T_of))
        "absent_means_rest": true                     # optional (T-28), not with blend: a trajectory may leave
      }],                                             #   this driver out; it is then at rest
      "anchors": [{"name": str, "driver": str, "note": str}],   # optional (T-06a): invisible rigid
                                                      #   bodies with no mesh; attachments may go to one
      "simplifications": [str, ...],                  # optional: what this scene leaves out of the lab's
                                                      #   model, one sentence each (non-empty strings); the
                                                      #   run report copies the list
      "attachments": [{
        "name": str,
        "from": str,                                  # a soft tissue; weights are on its surface
        "to": str,                                    #   mesh vertices (0-based), as in Ziva
        "kind": "hard" | "spring",                    # hard: the vertices join the target
                                                      #   (stiffness value null); spring: stiffness
                                                      #   x weight (docs/05 section 3, A-23)
        "stiffness": PARAM,
        "weights": [[vertex, weight], ...]            # weight in [0, 1]; only nonzero ones needed
      }],
      "landmarks": null | {"names": [str], "rest_positions_mm": [[x, y, z]], "weights": FILE,
                           "note": str},
      "solver": {"analysis": "dynamic", "fps": PARAM, "substeps_per_frame": PARAM,
                 "damping": PARAM,                    # physical damping, mass-proportional: FEBio's "mass
                                                      #   damping" body load, f = -C rho v, C in 1/s; 0 = none
                 "gravity_mm_per_s2": PARAM,          # physical direction
                 "numerical_damping_rhoi": PARAM,     # optional (T-28): FEBio's rhoi, 0..1 or -2 (Newmark);
                                                      #   absent = the generator's default 0 (generate.RHOI)
                 "motion_between_frames": PARAM}      # optional (T-33): "linear" (absent = linear) or "smooth":
    }                                                 #   how a driven bone moves between two frames (docs/05 sec. 4)

    PARAM      = {"value": number | [x, y, z] | null, "source": SOURCE_TAG, "note": str (optional)}
    SOURCE_TAG = "lab_setting" | "ziva_default" | "ours"   (实验室设置 / Ziva 默认值 / 我们定的)
    FILE       = {"path": str, "sha256": str}               (sha256 of the file's bytes)
    SOURCE     = {"file": str, "sha256": str, "world_matrix": [16 numbers] (optional, Maya order,
                  already applied by the export, ADR-18)}

`check` reads a scene (and optionally a trajectory) and sorts what it finds into errors (the
scene cannot be solved, or would be solved wrong; `asrp check` fails) and warnings (it can be
solved, but something is still missing; `asrp check` passes). Every message says what is wrong
and what to do.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from asrp_core import tetmesh
from asrp_core import trajectory as trajectory_module

FORMAT_VERSION = "asrp-scene/1"
UNIT_SYSTEM = "mm-N-MPa-s"
SOURCES = ("lab_setting", "ziva_default", "ours")
MATERIAL_PARAMS = {"neo-Hookean": ("E_mpa", "nu", "density_t_per_mm3")}
# mm_per_scene_unit in a tet mesh and in the scene are both written by our own code from the same
# float; anything beyond rounding means the mesh was built for another unit.
UNIT_MATCH = 1e-12
NEWMARK_RHOI = -2.0  # FEBio's rhoi value for its Newmark rule (beta 1/4, gamma 1/2), no numerical damping
MOTION_BETWEEN_FRAMES = ("linear", "smooth")  # solver.motion_between_frames; absent means "linear" (T-33)


# --- the format ---------------------------------------------------------------------------------


@dataclass
class Param:
    value: object
    source: str
    note: str = ""

    def to_json(self) -> dict:
        d = {"value": self.value, "source": self.source}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class FileRef:
    path: str
    sha256: str

    def to_json(self) -> dict:
        return {"path": self.path, "sha256": self.sha256}


@dataclass
class SourceObj:
    file: str
    sha256: str
    world_matrix: list | None = None

    def to_json(self) -> dict:
        d = {"file": self.file, "sha256": self.sha256}
        if self.world_matrix is not None:
            d["world_matrix"] = self.world_matrix
        return d


@dataclass
class TetRef:
    path: str
    content_sha256: str

    def to_json(self) -> dict:
        return {"path": self.path, "content_sha256": self.content_sha256}


@dataclass
class Units:
    mm_per_scene_unit: Param
    physics_length_scale: Param
    axes_from_source: str
    physics_length_scale_defaulted: bool = False  # not in the file; written back the same way

    def to_json(self) -> dict:
        d = {"system": UNIT_SYSTEM, "mm_per_scene_unit": self.mm_per_scene_unit.to_json()}
        if not self.physics_length_scale_defaulted:
            d["physics_length_scale"] = self.physics_length_scale.to_json()
        d["axes_from_source"] = self.axes_from_source
        return d


@dataclass
class Material:
    model: str
    params: dict[str, Param]

    def to_json(self) -> dict:
        return {"model": self.model, **{k: v.to_json() for k, v in self.params.items()}}


@dataclass
class SoftTissue:
    name: str
    mesh: FileRef
    source_obj: SourceObj
    tet_mesh: TetRef
    material: Material

    def to_json(self) -> dict:
        return {"name": self.name, "mesh": self.mesh.to_json(), "source_obj": self.source_obj.to_json(),
                "tet_mesh": self.tet_mesh.to_json(), "material": self.material.to_json()}


@dataclass
class Bone:
    name: str
    mesh: FileRef
    source_obj: SourceObj
    mass_t: Param
    motion: str
    driver: str | None = None

    def to_json(self) -> dict:
        d = {"name": self.name, "mesh": self.mesh.to_json(), "source_obj": self.source_obj.to_json(),
             "mass_t": self.mass_t.to_json(), "motion": self.motion}
        if self.driver is not None:
            d["driver"] = self.driver
        return d


@dataclass
class Hinge:
    pivot_mm: list
    axis: list
    source: str
    note: str = ""

    def to_json(self) -> dict:
        d = {"pivot_mm": self.pivot_mm, "axis": self.axis, "source": self.source}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class Blend:
    """A derived driver: `factor` times the whole rigid motion of driver `of` (a pure hinge turn gives the turn by
    `factor` times the angle about the same hinge)."""

    of: str
    factor: Param
    relative_to: str | None = None  # set: `factor` of the motion of `of` relative to this driver (T-28)

    def to_json(self) -> dict:
        d = {"of": self.of, "factor": self.factor.to_json()}
        if self.relative_to is not None:  # absent when not set, so older scenes are written as before
            d["relative_to"] = self.relative_to
        return d


@dataclass
class Driver:
    name: str
    hinge: Hinge | None = None
    blend: Blend | None = None  # set: no motion of its own, computed from driver `blend.of`
    absent_means_rest: bool = False  # True: a trajectory that leaves this driver out keeps it at rest (T-28)

    def to_json(self) -> dict:
        d = {"name": self.name, "hinge": None if self.hinge is None else self.hinge.to_json()}
        if self.blend is not None:
            d["blend"] = self.blend.to_json()
        if self.absent_means_rest:
            d["absent_means_rest"] = True
        return d


@dataclass
class Anchor:
    """An invisible rigid body with no mesh that moves like a driver (docs/04 section 5.1)."""

    name: str
    driver: str
    note: str = ""

    def to_json(self) -> dict:
        d = {"name": self.name, "driver": self.driver}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class Attachment:
    name: str
    source: str  # "from" in the file
    target: str  # "to" in the file
    kind: str
    stiffness: Param
    weights: list

    def to_json(self) -> dict:
        return {"name": self.name, "from": self.source, "to": self.target, "kind": self.kind,
                "stiffness": self.stiffness.to_json(), "weights": self.weights}


@dataclass
class Landmarks:
    names: list
    rest_positions_mm: list
    weights: FileRef
    note: str = ""

    def to_json(self) -> dict:
        d = {"names": self.names, "rest_positions_mm": self.rest_positions_mm, "weights": self.weights.to_json()}
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class Solver:
    analysis: str
    fps: Param
    substeps_per_frame: Param
    damping: Param  # physical, mass-proportional: FEBio's "mass damping" C, 1/s (0: none)
    gravity_mm_per_s2: Param
    numerical_damping_rhoi: Param | None = None  # None: not in the file, the generator's default (generate.RHOI)
    motion_between_frames: Param | None = None  # None: not in the file = "linear" (T-33)

    def to_json(self) -> dict:
        d = {"analysis": self.analysis, "fps": self.fps.to_json(),
             "substeps_per_frame": self.substeps_per_frame.to_json(), "damping": self.damping.to_json(),
             "gravity_mm_per_s2": self.gravity_mm_per_s2.to_json()}
        if self.numerical_damping_rhoi is not None:  # absent when not set, so older scenes are written as before
            d["numerical_damping_rhoi"] = self.numerical_damping_rhoi.to_json()
        if self.motion_between_frames is not None:
            d["motion_between_frames"] = self.motion_between_frames.to_json()
        return d


@dataclass
class Scene:
    origin: dict
    units: Units
    soft_tissues: list[SoftTissue]
    bones: list[Bone]
    drivers: list[Driver]
    attachments: list[Attachment]
    landmarks: Landmarks | None
    solver: Solver
    anchors: list[Anchor] = field(default_factory=list)
    simplifications: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = {
            "format_version": FORMAT_VERSION,
            "origin": self.origin,
            "units": self.units.to_json(),
            "soft_tissues": [t.to_json() for t in self.soft_tissues],
            "bones": [b.to_json() for b in self.bones],
            "drivers": [d.to_json() for d in self.drivers],
            "attachments": [a.to_json() for a in self.attachments],
            "landmarks": None if self.landmarks is None else self.landmarks.to_json(),
            "solver": self.solver.to_json(),
        }
        if self.anchors:  # absent when empty, so scenes without an anchor are written as before
            d["anchors"] = [a.to_json() for a in self.anchors]
        if self.simplifications:  # likewise
            d["simplifications"] = list(self.simplifications)
        return d


def parameters(node, where=""):
    """(location, PARAM json) for every parameter in a scene's JSON, e.g. ("solver.fps", {...})."""
    if isinstance(node, dict):
        if "value" in node and "source" in node:
            yield where, node
            return
        for k, v in node.items():
            yield from parameters(v, f"{where}.{k}" if where else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = v.get("name", i) if isinstance(v, dict) else i
            yield from parameters(v, f"{where}[{label}]")


def write(path, scene: Scene) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(scene.to_json(), indent=2, ensure_ascii=False)
    Path(path).write_text(text + "\n", encoding="utf-8", newline="\n")


# --- reading: every structural problem becomes a sentence, not a KeyError -----------------------


class _Bad(Exception):
    """One part of the file cannot be read; the caller records it and moves on."""


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _get(d: dict, key: str, where: str):
    if key not in d:
        raise _Bad(f"{where}: '{key}' is missing")
    return d[key]


def _dict(v, where: str) -> dict:
    if not isinstance(v, dict):
        raise _Bad(f"{where}: expected an object {{...}}, got {type(v).__name__}")
    return v


def _str(v, where: str) -> str:
    if not isinstance(v, str) or not v:
        raise _Bad(f"{where}: expected a non-empty text, got {v!r}")
    return v


def _vec3(v, where: str) -> list:
    if not (isinstance(v, list) and len(v) == 3 and all(_is_number(c) for c in v)):
        raise _Bad(f"{where}: expected three numbers [x, y, z], got {v!r}")
    return v


def _param(d: dict, key: str, where: str) -> Param:
    raw = _get(d, key, where)
    if not isinstance(raw, dict) or "value" not in raw or "source" not in raw:
        raise _Bad(
            f"{where}.{key}: every parameter needs a value and where it came from, written as "
            f'{{"value": ..., "source": "lab_setting" | "ziva_default" | "ours"}}; got {raw!r}'
        )
    if raw["source"] not in SOURCES:
        raise _Bad(
            f"{where}.{key}: source {raw['source']!r} is not one of {', '.join(SOURCES)} "
            "(实验室设置 / Ziva 默认值 / 我们定的)"
        )
    value = raw["value"]
    if not (value is None or _is_number(value) or (isinstance(value, list) and all(_is_number(c) for c in value))):
        raise _Bad(f"{where}.{key}: value must be a number, a list of numbers or null, got {value!r}")
    return Param(value, raw["source"], raw.get("note", ""))


def _number_param(d: dict, key: str, where: str, *, positive=False, allow_null=False) -> Param:
    p = _param(d, key, where)
    if p.value is None and allow_null:
        return p
    if not _is_number(p.value):
        raise _Bad(f"{where}.{key}: value must be a number, got {p.value!r}")
    if positive and p.value <= 0:
        raise _Bad(f"{where}.{key}: value must be greater than 0, got {p.value!r}")
    return p


def _file(d: dict, key: str, where: str) -> FileRef:
    raw = _dict(_get(d, key, where), f"{where}.{key}")
    return FileRef(_str(_get(raw, "path", f"{where}.{key}"), f"{where}.{key}.path"),
                   _str(_get(raw, "sha256", f"{where}.{key}"), f"{where}.{key}.sha256"))


def _source_obj(d: dict, where: str) -> SourceObj:
    raw = _dict(_get(d, "source_obj", where), f"{where}.source_obj")
    matrix = raw.get("world_matrix")
    if matrix is not None and not (isinstance(matrix, list) and len(matrix) == 16 and all(map(_is_number, matrix))):
        raise _Bad(f"{where}.source_obj.world_matrix: expected 16 numbers, got {matrix!r}")
    return SourceObj(_str(_get(raw, "file", f"{where}.source_obj"), f"{where}.source_obj.file"),
                     _str(_get(raw, "sha256", f"{where}.source_obj"), f"{where}.source_obj.sha256"), matrix)


def _named_list(data: dict, key: str, problems: "Report", parse) -> list:
    if key not in data:
        problems.errors.append(f"'{key}' is missing (write an empty list [] if there are none)")
        return []
    raw = data[key]
    if not isinstance(raw, list):
        problems.errors.append(f"'{key}' must be a list, got {type(raw).__name__}")
        return []
    out = []
    for i, item in enumerate(raw):
        name = item.get("name") if isinstance(item, dict) else None
        where = f"{key}[{name!r}]" if isinstance(name, str) else f"{key}[{i}]"
        try:
            item = _dict(item, where)
            _str(_get(item, "name", where), f"{where}.name")
            out.append(parse(item, where))
        except _Bad as e:
            problems.errors.append(str(e))
    return out


def _units(data: dict) -> Units:
    if "units" not in data:
        raise _Bad("'units' is missing: the scene must say its unit system and mm_per_scene_unit (ADR-04, ADR-22)")
    u = _dict(data["units"], "units")
    if u.get("system") != UNIT_SYSTEM:
        raise _Bad(f"units.system is {u.get('system')!r}; it must be {UNIT_SYSTEM!r}, the only unit system (ADR-04)")
    if "mm_per_scene_unit" not in u:
        raise _Bad(
            "units.mm_per_scene_unit is missing: say how many mm one scene unit of the source asset is "
            '(0.962 for the lab asset, same as the lab controller, ADR-31), e.g. {"value": 0.962, "source": "ours"}'
        )
    mm = _number_param(u, "mm_per_scene_unit", "units", positive=True)
    if "physics_length_scale" in u:
        k, defaulted = _number_param(u, "physics_length_scale", "units", positive=True), False
    else:
        # ADR-22: not written means k = 1 and we chose it.
        k, defaulted = Param(1.0, "ours", "not in scene.json, so 1.0 (ADR-22)"), True
    axes = _str(_get(u, "axes_from_source", "units"), "units.axes_from_source")
    return Units(mm, k, axes, defaulted)


def _material(d: dict, where: str) -> Material:
    raw = _dict(_get(d, "material", where), f"{where}.material")
    model = raw.get("model")
    if model not in MATERIAL_PARAMS:
        raise _Bad(f"{where}.material.model is {model!r}; supported: {', '.join(MATERIAL_PARAMS)}")
    w = f"{where}.material"
    params = {
        "E_mpa": _number_param(raw, "E_mpa", w, positive=True),
        "nu": _number_param(raw, "nu", w),
        "density_t_per_mm3": _number_param(raw, "density_t_per_mm3", w, positive=True),
    }
    if not 0 <= params["nu"].value < 0.5:
        raise _Bad(f"{w}.nu: Poisson's ratio must be at least 0 and below 0.5, got {params['nu'].value}")
    return Material(model, params)


def _soft_tissue(d: dict, where: str) -> SoftTissue:
    tet = _dict(_get(d, "tet_mesh", where), f"{where}.tet_mesh")
    return SoftTissue(
        d["name"], _file(d, "mesh", where), _source_obj(d, where),
        TetRef(_str(_get(tet, "path", f"{where}.tet_mesh"), f"{where}.tet_mesh.path"),
               _str(_get(tet, "content_sha256", f"{where}.tet_mesh"), f"{where}.tet_mesh.content_sha256")),
        _material(d, where),
    )  # fmt: skip


def _bone(d: dict, where: str) -> Bone:
    motion = d.get("motion")
    if motion not in ("fixed", "prescribed"):
        raise _Bad(f'{where}.motion is {motion!r}; a bone is either "fixed" or "prescribed" (ADR-21)')
    driver = d.get("driver")
    if motion == "prescribed" and not isinstance(driver, str):
        raise _Bad(f"{where}: a prescribed bone must name the driver it follows ('driver'), e.g. \"jaw01\"")
    if motion == "fixed" and driver is not None:
        raise _Bad(f"{where}: a fixed bone does not move, so it cannot follow driver {driver!r}; remove 'driver' "
                   "or make it prescribed")
    mass = _number_param(d, "mass_t", where, positive=True, allow_null=True)
    return Bone(d["name"], _file(d, "mesh", where), _source_obj(d, where), mass, motion, driver)


def _blend(d: dict, where: str) -> Blend | None:
    raw = d.get("blend")
    if raw is None:
        return None
    raw = _dict(raw, f"{where}.blend")
    factor = _number_param(raw, "factor", f"{where}.blend")
    if not 0 <= factor.value <= 1:
        raise _Bad(f"{where}.blend.factor must be between 0 and 1 (0 stays with the skull, 1 follows "
                   f"{raw.get('of')!r}), got {factor.value}")
    relative_to = raw.get("relative_to")
    if relative_to is not None:
        relative_to = _str(relative_to, f"{where}.blend.relative_to")
    return Blend(_str(_get(raw, "of", f"{where}.blend"), f"{where}.blend.of"), factor, relative_to)


def _driver(d: dict, where: str) -> Driver:
    blend = _blend(d, where)
    rest = d.get("absent_means_rest", False)
    if not isinstance(rest, bool):
        raise _Bad(f"{where}.absent_means_rest must be true or false, got {rest!r}")
    if rest and blend is not None:
        raise _Bad(f"{where}: a derived driver ('blend') has no motion of its own, so 'absent_means_rest' means "
                   "nothing for it; remove one of them")
    raw = d.get("hinge")
    if raw is None:
        return Driver(d["name"], None, blend, rest)
    if blend is not None:
        raise _Bad(f"{where}: a driver is either derived ('blend') or has its own hinge, not both; "
                   "remove one of them")
    raw = _dict(raw, f"{where}.hinge")
    axis = _vec3(_get(raw, "axis", f"{where}.hinge"), f"{where}.hinge.axis")
    if not any(axis):
        raise _Bad(f"{where}.hinge.axis is the zero vector; give the hinge a direction")
    if raw.get("source") not in SOURCES:
        raise _Bad(f"{where}.hinge.source must be one of {', '.join(SOURCES)}, got {raw.get('source')!r}")
    pivot = _vec3(_get(raw, "pivot_mm", f"{where}.hinge"), f"{where}.hinge.pivot_mm")
    return Driver(d["name"], Hinge(pivot, axis, raw["source"], raw.get("note", "")), None, rest)


def _attachment(d: dict, where: str) -> Attachment:
    kind = d.get("kind")
    if kind not in ("hard", "spring"):
        raise _Bad(f'{where}.kind is {kind!r}; it is "hard" or "spring" (docs/05 section 3)')
    stiffness = _number_param(d, "stiffness", where, positive=True, allow_null=True)
    if kind == "hard" and stiffness.value is not None:
        raise _Bad(f"{where}: a hard attachment has no stiffness (its vertices join the target); set the "
                   "stiffness value to null, or make it a spring")
    if kind == "spring" and stiffness.value is None:
        raise _Bad(f"{where}: a spring attachment needs a stiffness value")
    weights = _get(d, "weights", where)
    if not isinstance(weights, list) or not all(
        isinstance(w, list) and len(w) == 2 and isinstance(w[0], int) and not isinstance(w[0], bool)
        and _is_number(w[1]) for w in weights
    ):  # fmt: skip
        raise _Bad(f"{where}.weights must be a list of [vertex index, weight] pairs")
    return Attachment(d["name"], _str(_get(d, "from", where), f"{where}.from"),
                      _str(_get(d, "to", where), f"{where}.to"), kind, stiffness, weights)


def _anchor(d: dict, where: str) -> Anchor:
    note = d.get("note", "")
    if not isinstance(note, str):
        raise _Bad(f"{where}.note must be text, got {note!r}")
    return Anchor(d["name"], _str(_get(d, "driver", where), f"{where}.driver"), note)


def _landmarks(data: dict) -> Landmarks | None:
    raw = data.get("landmarks")
    if raw is None:
        return None
    raw = _dict(raw, "landmarks")
    names = _get(raw, "names", "landmarks")
    positions = _get(raw, "rest_positions_mm", "landmarks")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise _Bad("landmarks.names must be a list of names")
    if not isinstance(positions, list):
        raise _Bad("landmarks.rest_positions_mm must be a list of [x, y, z]")
    for i, p in enumerate(positions):
        _vec3(p, f"landmarks.rest_positions_mm[{i}]")
    if len(names) != len(positions):
        raise _Bad(f"landmarks: {len(names)} names but {len(positions)} rest positions; give one position per name")
    if len(set(names)) != len(names):
        raise _Bad("landmarks.names has a name twice")
    return Landmarks(names, positions, _file(raw, "weights", "landmarks"), raw.get("note", ""))


def _solver(data: dict) -> Solver:
    s = _dict(_get(data, "solver", "scene"), "solver")
    if s.get("analysis") != "dynamic":
        raise _Bad(f"solver.analysis is {s.get('analysis')!r}; only \"dynamic\" is supported (ADR-05)")
    substeps = _number_param(s, "substeps_per_frame", "solver", positive=True)
    if substeps.value != int(substeps.value):
        raise _Bad(f"solver.substeps_per_frame must be a whole number, got {substeps.value}")
    damping = _number_param(s, "damping", "solver")
    if damping.value < 0:
        raise _Bad(f"solver.damping cannot be negative, got {damping.value}")
    gravity = _param(s, "gravity_mm_per_s2", "solver")
    _vec3(gravity.value, "solver.gravity_mm_per_s2.value")
    rhoi = None
    if "numerical_damping_rhoi" in s:
        rhoi = _number_param(s, "numerical_damping_rhoi", "solver")
        if not (rhoi.value == NEWMARK_RHOI or 0 <= rhoi.value <= 1):
            raise _Bad(f"solver.numerical_damping_rhoi must be between 0 (FEBio's strongest numerical damping) and 1, "
                       f"or {NEWMARK_RHOI:g} (FEBio's Newmark rule, none); got {rhoi.value}")
    between = None
    if "motion_between_frames" in s:
        raw = _dict(s["motion_between_frames"], "solver.motion_between_frames")
        if raw.get("source") not in SOURCES:
            raise _Bad(f"solver.motion_between_frames: source {raw.get('source')!r} is not one of {', '.join(SOURCES)}")
        if raw.get("value") not in MOTION_BETWEEN_FRAMES:
            raise _Bad(f'solver.motion_between_frames must be "linear" (the default) or "smooth", got {raw.get("value")!r}')
        between = Param(raw["value"], raw["source"], raw.get("note", ""))
    return Solver("dynamic", _number_param(s, "fps", "solver", positive=True), substeps, damping, gravity, rhoi, between)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scene: Scene | None = None
    trajectory: trajectory_module.Trajectory | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def parse(data, report: Report | None = None) -> Report:
    """Read parsed JSON into a Scene, recording every structural problem in the report."""
    report = report or Report()
    if not isinstance(data, dict):
        report.errors.append("a scene file must hold one JSON object")
        return report
    version = data.get("format_version")
    if version != FORMAT_VERSION:
        report.errors.append(
            f"format_version is {version!r}; this asrp reads {FORMAT_VERSION!r} only. Re-create the scene "
            "with `asrp import-asset`, or update asrp if the file is newer"
        )
        return report
    parts = {}
    for key, reader in (("units", _units), ("landmarks", _landmarks), ("solver", _solver)):
        try:
            parts[key] = reader(data)
        except _Bad as e:
            report.errors.append(str(e))
    origin = data.get("origin")
    if not isinstance(origin, dict):
        report.errors.append("'origin' is missing: say which asset and which export the scene came from")
    tissues = _named_list(data, "soft_tissues", report, _soft_tissue)
    bones = _named_list(data, "bones", report, _bone)
    drivers = _named_list(data, "drivers", report, _driver)
    attachments = _named_list(data, "attachments", report, _attachment)
    anchors = _named_list(data, "anchors", report, _anchor) if "anchors" in data else []
    simplifications = []
    if "simplifications" in data:
        raw = data["simplifications"]
        if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
            report.errors.append("'simplifications' must be a list of non-empty sentences (strings); remove the "
                                 "key if the scene leaves nothing out")
        else:
            simplifications = list(raw)
    if report.errors:
        return report
    report.scene = Scene(origin, parts["units"], tissues, bones, drivers, attachments, parts["landmarks"],
                         parts["solver"], anchors, simplifications)
    return report


def load(path) -> Scene:
    """Read scene.json; raise ValueError with every structural problem if it cannot be read."""
    report = Report()
    _read_json(Path(path), report)
    if report.errors:
        raise ValueError("; ".join(report.errors))
    return report.scene


def _read_json(path: Path, report: Report) -> None:
    if not path.is_file():
        report.errors.append(f"{path} does not exist; give the path of a scene.json")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.errors.append(f"{path} is not valid JSON (line {e.lineno}: {e.msg})")
        return
    parse(data, report)


# --- checking what the scene refers to -----------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def obj_vertex_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as f:
        return sum(1 for line in f if line.startswith("v "))


def _check_file(base: Path, ref: FileRef, what: str, report: Report) -> Path | None:
    path = base / ref.path
    if not path.is_file():
        report.errors.append(f"{what}: file {ref.path} is missing (looked in {base}); restore it or re-import the asset")
        return None
    digest = _sha256(path)
    if digest != ref.sha256:
        report.errors.append(
            f"{what}: {ref.path} has changed since the scene was written (sha256 {digest[:12]}, scene says "
            f"{ref.sha256[:12]}); re-import the asset so scene.json and the file agree"
        )
        return None
    return path


def _check_tet_mesh(base: Path, tissue: SoftTissue, units: Units, report: Report) -> None:
    what = f"soft tissue {tissue.name!r}"
    path = base / tissue.tet_mesh.path
    if not path.is_file():
        report.errors.append(f"{what}: tet mesh file {tissue.tet_mesh.path} is missing (looked in {base})")
        return
    regenerate = "regenerate the tet mesh with tools/build_tetmesh.py and re-import"
    try:
        _, meta = tetmesh.load(path)  # checks the hash the file records for itself
    except ValueError as e:
        report.errors.append(f"{what}: {e}")
        return
    if meta["content_sha256"] != tissue.tet_mesh.content_sha256:
        report.errors.append(
            f"{what}: tet mesh {tissue.tet_mesh.path} is not the one the scene names (content sha256 "
            f"{meta['content_sha256'][:12]}, scene says {tissue.tet_mesh.content_sha256[:12]}); {regenerate}"
        )
    if meta["source"]["sha256"] != tissue.source_obj.sha256:
        report.errors.append(
            f"{what}: tet mesh {tissue.tet_mesh.path} was made from another surface (source sha256 "
            f"{meta['source']['sha256'][:12]}, but {tissue.source_obj.file} is {tissue.source_obj.sha256[:12]}); "
            f"{regenerate}"
        )
    mm = units.mm_per_scene_unit.value
    if not _is_number(meta["mm_per_scene_unit"]) or abs(meta["mm_per_scene_unit"] - mm) > UNIT_MATCH * max(1.0, mm):
        report.errors.append(
            f"{what}: tet mesh {tissue.tet_mesh.path} was made with mm_per_scene_unit "
            f"{meta['mm_per_scene_unit']}, the scene uses {mm}; {regenerate}"
        )


NAME_OK = re.compile(r"[A-Za-z0-9_.-]+")


def _check_names(scene: Scene, report: Report) -> None:
    """Names go into the FEBio input (node sets, rigid bodies, load curves), so they stay plain ASCII."""
    kinds = (("soft tissue", scene.soft_tissues), ("bone", scene.bones), ("anchor", scene.anchors),
             ("driver", scene.drivers), ("attachment", scene.attachments))
    for kind, items in kinds:
        for i in items:
            if not NAME_OK.fullmatch(i.name):
                report.errors.append(
                    f"{kind} name {i.name!r} has characters outside ASCII letters, digits, _ - and .; names go into "
                    "the FEBio input file, where other characters (for example & < > or a space) break it. Rename it")


def _check_references(scene: Scene, base: Path, report: Report) -> None:
    _check_names(scene, report)
    names = [o.name for o in scene.soft_tissues] + [o.name for o in scene.bones] + [o.name for o in scene.anchors]
    seen = set()
    for n in names:
        if n in seen:
            report.errors.append(f"two objects are called {n!r}; every soft tissue, bone and anchor needs its own name")
        seen.add(n)
    for kind, items in (("driver", scene.drivers), ("attachment", scene.attachments)):
        listed = [i.name for i in items]
        for n in {n for n in listed if listed.count(n) > 1}:
            report.errors.append(f"two {kind}s are called {n!r}; give each its own name")

    vertex_counts = {}
    for t in scene.soft_tissues:
        path = _check_file(base, t.mesh, f"soft tissue {t.name!r}", report)
        if path is not None:
            vertex_counts[t.name] = obj_vertex_count(path)
        _check_tet_mesh(base, t, scene.units, report)
    for b in scene.bones:
        _check_file(base, b.mesh, f"bone {b.name!r}", report)

    drivers = {d.name for d in scene.drivers}
    listed_drivers = f"drivers: {', '.join(sorted(drivers)) or 'none'}"
    by_name = {d.name: d for d in scene.drivers}
    followed = set()
    for b in scene.bones:
        if b.motion == "prescribed":
            if b.driver not in drivers:
                report.errors.append(
                    f"bone {b.name!r} follows driver {b.driver!r}, which the scene does not list; add it to "
                    f"'drivers' or fix the name ({listed_drivers})"
                )
            followed.add(b.driver)
    for a in scene.anchors:
        if a.driver not in drivers:
            report.errors.append(
                f"anchor {a.name!r} follows driver {a.driver!r}, which the scene does not list; add it to "
                f"'drivers' or fix the name ({listed_drivers})"
            )
        followed.add(a.driver)
    for d in scene.drivers:
        if d.blend is None:
            continue
        parent = by_name.get(d.blend.of)
        if parent is None:
            report.errors.append(
                f"driver {d.name!r} is derived from driver {d.blend.of!r}, which the scene does not list; "
                f"add it to 'drivers' or fix the name ({listed_drivers})"
            )
        elif parent.blend is not None:
            report.errors.append(
                f"driver {d.name!r} is derived from {parent.name!r}, which is itself derived; derive it from "
                f"{parent.blend.of!r} directly (derived drivers do not chain)"
            )
        rel = d.blend.relative_to
        if rel is not None:
            base_driver = by_name.get(rel)
            if base_driver is None:
                report.errors.append(
                    f"driver {d.name!r} is relative to driver {rel!r} (blend.relative_to), which the scene does not "
                    f"list; add it to 'drivers' or fix the name ({listed_drivers})"
                )
            elif base_driver.blend is not None:
                report.errors.append(
                    f"driver {d.name!r} is relative to {rel!r}, which is itself derived; make it relative to a driver "
                    "with a motion of its own"
                )
            elif rel == d.blend.of:
                report.errors.append(
                    f"driver {d.name!r} is {d.blend.of!r}'s motion relative to {rel!r} itself, which is always the "
                    f"plain {rel!r}; remove 'relative_to' or name another driver"
                )
        if d.name in followed:
            followed.add(d.blend.of)  # the source is in use through the driver derived from it
            if rel is not None:
                followed.add(rel)
    for d in sorted(drivers - followed):
        report.warnings.append(f"driver {d!r} moves no bone; it is unused")

    tissues = {t.name for t in scene.soft_tissues}
    attached = set()
    for a in scene.attachments:
        what = f"attachment {a.name!r}"
        if a.source not in tissues:
            report.errors.append(
                f"{what} starts from {a.source!r}, which is not a soft tissue in this scene; 'from' must name "
                "the soft tissue whose vertices are attached"
            )
        if a.target not in seen:
            report.errors.append(f"{what} goes to {a.target!r}, which is not a bone, an anchor or a soft "
                                 "tissue in this scene")
        if a.target == a.source:
            report.errors.append(f"{what} attaches {a.source!r} to itself")
        attached.update({a.source, a.target})
        count = vertex_counts.get(a.source)
        bad_index = [i for i, _ in a.weights if count is not None and not 0 <= i < count]
        bad_weight = [w for _, w in a.weights if not 0 <= w <= 1]
        listed = [i for i, _ in a.weights]
        if bad_index:
            report.errors.append(
                f"{what}: {len(bad_index)} vertex numbers are outside {a.source!r}'s {count} vertices "
                f"(e.g. {bad_index[0]}); the weights do not belong to this mesh"
            )
        if bad_weight:
            report.errors.append(f"{what}: weights must be between 0 and 1 (found {bad_weight[0]})")
        if len(set(listed)) != len(listed):
            report.errors.append(f"{what}: a vertex is listed twice in its weights")
        out_of_range = set(bad_index)
        valid = [i for i, w in a.weights if 0 < w <= 1 and i not in out_of_range]
        if not valid:
            report.errors.append(
                f"{what} has no valid vertex (no vertex of {a.source!r} with a weight above 0); it would hold "
                "nothing. Give it weights or remove it"
            )
    for t in scene.soft_tissues:
        if t.name not in attached:
            report.warnings.append(
                f"soft tissue {t.name!r} has no attachment: nothing holds it, so under gravity it falls freely. "
                "Fine for checking the import; add attachments before a real run (docs/05 section 3, T-03)"
            )

    if scene.landmarks is not None:
        _check_file(base, scene.landmarks.weights, "landmark weights", report)


def _check_trajectory(scene: Scene, path: Path, report: Report) -> None:
    try:
        traj = trajectory_module.read(path)
    except trajectory_module.TrajectoryError as e:
        report.errors.append(f"trajectory: {e}")
        return
    report.trajectory = traj
    if traj.fps != scene.solver.fps.value:
        report.errors.append(
            f"trajectory: {traj.fps} frames per second, the scene's solver runs at {scene.solver.fps.value}; "
            "they must match"
        )
    if traj.landmarks is not None:
        if scene.landmarks is None:
            report.errors.append(
                "trajectory: it moves landmarks but the scene lists none; import the lab asset (it carries the "
                "landmarks) or take the 'landmarks' section out of the trajectory"
            )
        else:
            known = set(scene.landmarks.names)
            unknown = [n for n in traj.landmarks["names"] if n not in known]
            if unknown:
                report.errors.append(
                    f"trajectory: {len(unknown)} landmark names are not in the scene (first: {unknown[0]!r}); "
                    "use the names listed in scene.json under landmarks.names"
                )
    derived = {d.name: d for d in scene.drivers if d.blend is not None}
    resting = {d.name for d in scene.drivers if d.absent_means_rest}
    have =', '.join(sorted(traj.drivers)) or 'none'

    def need(who: str, driver: str) -> None:
        d = derived.get(driver)
        if d is not None:  # computed from its source, which is the one that needs a motion
            if d.blend.of not in traj.drivers:
                report.errors.append(
                    f"trajectory: {who} follows driver {driver!r}, derived from {d.blend.of!r}, but the "
                    f"trajectory has no motion for {d.blend.of!r} (it has: {have})"
                )
            rel = d.blend.relative_to
            if rel is not None and rel not in traj.drivers and rel not in resting:
                report.errors.append(
                    f"trajectory: {who} follows driver {driver!r}, relative to {rel!r}, but the trajectory has no "
                    f"motion for {rel!r} (it has: {have}); give it one, or mark {rel!r} absent_means_rest in the scene"
                )
        elif driver not in traj.drivers and driver not in resting:
            report.errors.append(
                f"trajectory: {who} follows driver {driver!r}, but the trajectory has no motion for "
                f"it (it has: {have})"
            )

    for b in scene.bones:
        if b.motion == "prescribed":
            need(f"bone {b.name!r}", b.driver)
    for a in scene.anchors:
        need(f"anchor {a.name!r}", a.driver)
    used = {b.driver for b in scene.bones if b.motion == "prescribed"} | {a.driver for a in scene.anchors}
    used |= {x for d in used if d in derived for x in (derived[d].blend.of, derived[d].blend.relative_to) if x}
    for d in sorted(set(traj.drivers) & set(derived)):
        report.warnings.append(
            f"trajectory: driver {d!r} is derived from {derived[d].blend.of!r} in the scene, so its own motion "
            "in the trajectory is ignored"
        )
    for d in sorted(set(traj.drivers) - used - set(derived)):
        report.warnings.append(f"trajectory: driver {d!r} moves no bone in this scene; its motion is ignored")


def check(scene_path, trajectory_path=None) -> Report:
    """Check a scene and everything it refers to; with a trajectory, check that they fit together.

    Without a trajectory, a prescribed bone needs no motion yet (T-05). Errors make `asrp check`
    fail; warnings do not.
    """
    scene_path = Path(scene_path)
    report = Report()
    _read_json(scene_path, report)
    if report.scene is None:
        return report
    _check_references(report.scene, scene_path.parent, report)
    if trajectory_path is not None:
        _check_trajectory(report.scene, Path(trajectory_path), report)
    return report


def driver_motion(scene: Scene, traj: trajectory_module.Trajectory) -> dict[str, list[list[float]]]:
    """Every driver's 4x4 transform per frame: the trajectory's own, plus each derived driver
    computed from its source's motion (docs/04 section 5.1). A driver marked absent_means_rest that the trajectory
    leaves out is not in the result (it is at rest; the generator writes what follows it as fixed). Raises ValueError
    if the scene and trajectory do not fit; run `check` first for a readable list of what is wrong."""
    out = {}
    by_name = {d.name: d for d in scene.drivers}
    # A derived driver is computed only when something uses it: a prescribed bone, or an anchor that an
    # attachment refers to. An unused one with no source motion is skipped (the trajectory check accepts it).
    referenced = {x for a in scene.attachments for x in (a.source, a.target)}
    used = {b.driver for b in scene.bones if b.motion == "prescribed"} | {
        a.driver for a in scene.anchors if a.name in referenced}
    for d in scene.drivers:
        if d.blend is None:
            if d.name in traj.drivers:
                out[d.name] = traj.drivers[d.name]
            continue
        if d.name not in used:
            continue
        parent = by_name.get(d.blend.of)
        if parent is None or parent.blend is not None:
            raise ValueError(f"driver {d.name!r}: its source {d.blend.of!r} is missing or is itself derived")
        if d.blend.of not in traj.drivers:
            raise ValueError(f"driver {d.name!r}: the trajectory has no motion for its source {d.blend.of!r}")
        rel = d.blend.relative_to
        if rel is not None and rel in traj.drivers:
            out[d.name] = trajectory_module.relative_blend_transforms(
                traj.drivers[rel], traj.drivers[d.blend.of], d.blend.factor.value)
            continue
        if rel is not None and not (rel in by_name and by_name[rel].absent_means_rest):
            raise ValueError(f"driver {d.name!r}: the trajectory has no motion for {rel!r}, the driver it is relative to")
        # no relative_to, or relative to a driver at rest: exactly the plain blend (the same numbers as before T-28)
        out[d.name] = trajectory_module.blend_transforms(traj.drivers[d.blend.of], d.blend.factor.value)
    return out
