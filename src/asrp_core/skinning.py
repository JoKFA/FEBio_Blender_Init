"""Landmark skinning (T-09; docs/03 section 4): the lab's second layer, applied on top of the physics.

The lab moves 300 landmarks and skins the lip mesh with them. Every landmark only translates and its
rest matrix is a pure translation, so full linear blend skinning reduces exactly to

    v' = v + sum_i w_i t_i          (rows of the weights sum to 1)

for any input vertex v, including the physics result. `deform` is that formula and is the one kernel
the run (and, through T-31, the lab's training code) calls: arrays in, array out, no files, no
globals, no unit conversion. `deform_matrices` is the general matrix form; it is used to prove the
conversion and the reduction in the tests, not by a run.

All matrices are column vectors written as (4, 4) arrays, mm, Z up (see asrp_core.asset.skin).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FORMAT = "asrp-skin/1"
SUM_TOLERANCE = 1e-6  # how far a vertex's weights may be from summing to 1


class SkinError(ValueError):
    """The skin file or the arrays cannot be used; the message says what is wrong and what to do."""


@dataclass
class Skin:
    names: list[str]
    rest_world: np.ndarray  # (K, 4, 4)
    bind_pre: np.ndarray  # (K, 4, 4)
    geom: np.ndarray  # (4, 4)
    weights: np.ndarray  # (V, K) float64, dense; row v holds vertex v's weight on each landmark


def load(path) -> Skin:
    """Read an `asrp-skin/1` file (written by the importer)."""
    path = Path(path)
    if not path.is_file():
        raise SkinError(f"{path} does not exist; re-run the asset import")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SkinError(f"{path} is not valid JSON (line {e.lineno}: {e.msg}); re-run the asset import") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        found = data.get("format") if isinstance(data, dict) else type(data).__name__
        raise SkinError(f"{path} has format {found!r}; this asrp reads {FORMAT!r}. Re-run the asset import")
    try:
        names = [str(n) for n in data["names"]]
        k = len(names)
        rest_world = np.asarray(data["rest_world"], dtype=np.float64)
        bind_pre = np.asarray(data["bind_pre"], dtype=np.float64)
        geom = np.asarray(data["geom"], dtype=np.float64)
        sparse = data["weights"]
    except (KeyError, TypeError, ValueError) as e:
        raise SkinError(f"{path} is damaged ({type(e).__name__}: {e}); re-run the asset import") from None
    if rest_world.shape != (k, 16) or bind_pre.shape != (k, 16) or geom.shape != (16,):
        raise SkinError(
            f"{path}: rest_world {rest_world.shape}, bind_pre {bind_pre.shape}, geom {geom.shape} do not fit "
            f"{k} landmarks of 16 numbers each; re-run the asset import"
        )
    dense = np.zeros((len(sparse), k), dtype=np.float64)
    for v, pairs in enumerate(sparse):
        for i, w in pairs:
            if not 0 <= i < k:
                raise SkinError(f"{path}: vertex {v} names landmark {i}, but there are {k}; re-run the asset import")
            dense[v, i] += w
    sums = dense.sum(axis=1)
    bad = np.flatnonzero(np.abs(sums - 1.0) > SUM_TOLERANCE)
    if len(bad):
        raise SkinError(
            f"{path}: {len(bad)} vertices have weights that do not sum to 1 (first: vertex {int(bad[0])}, "
            f"sum {sums[bad[0]]!r}); the skin file is damaged, re-run the asset import"
        )
    return Skin(names, rest_world.reshape(k, 4, 4), bind_pre.reshape(k, 4, 4), geom.reshape(4, 4), dense)


def deform(base, weights, translations) -> np.ndarray:
    """base + weights @ translations.

    base: (V, 3) or (F, V, 3); weights: (V, K); translations: (K, 3) or (F, K, 3), relative to rest.
    Returns float64 with base's shape. With every translation exactly zero the result equals `base`
    bit for bit."""
    base = np.asarray(base, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    t = np.asarray(translations, dtype=np.float64)
    if weights.ndim != 2:
        raise SkinError(f"weights must be (vertices, landmarks), got shape {weights.shape}")
    v, k = weights.shape
    if base.ndim not in (2, 3) or base.shape[-2:] != (v, 3):
        raise SkinError(f"base must be ({v}, 3) or (frames, {v}, 3) for these weights, got shape {base.shape}")
    if t.ndim not in (2, 3) or t.shape[-2:] != (k, 3):
        raise SkinError(
            f"translations must be ({k}, 3) or (frames, {k}, 3) for these weights, got shape {t.shape}"
        )
    if t.ndim == 3 and base.ndim == 3 and t.shape[0] != base.shape[0]:
        raise SkinError(f"base has {base.shape[0]} frames but translations has {t.shape[0]}; they must match")
    if t.ndim == 3 and base.ndim == 2:
        base = np.broadcast_to(base, (t.shape[0], v, 3))
    if not t.any():  # nothing moves: the same bytes back (base + 0.0 would turn a -0.0 into +0.0)
        return base.copy()
    # (V, K) @ (K, 3) and (V, K) @ (F, K, 3) both broadcast to (..., V, 3).
    return base + weights @ t


def deform_matrices(vertices, skin: Skin, world) -> np.ndarray:
    """General linear blend skinning: v' = sum_i w_i (world_i @ bind_pre_i @ [v, 1])[:3].

    vertices: (V, 3) mm; world: (K, 4, 4) landmark world matrices. Returns (V, 3) float64."""
    vertices = np.asarray(vertices, dtype=np.float64)
    world = np.asarray(world, dtype=np.float64)
    k = len(skin.names)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.shape[0] != skin.weights.shape[0]:
        raise SkinError(f"vertices must be ({skin.weights.shape[0]}, 3), got shape {vertices.shape}")
    if world.shape != (k, 4, 4):
        raise SkinError(f"world must be ({k}, 4, 4), got shape {world.shape}")
    homogeneous = np.concatenate([vertices, np.ones((len(vertices), 1))], axis=1)  # (V, 4)
    full = world @ skin.bind_pre  # (K, 4, 4)
    out = np.zeros_like(vertices)
    for i in range(k):
        column = skin.weights[:, i]
        used = np.flatnonzero(column)
        if len(used):
            moved = homogeneous[used] @ full[i].T  # (n, 4)
            out[used] += column[used, None] * moved[:, :3]
    return out


def translations_to_world(skin: Skin, translations) -> np.ndarray:
    """(K, 3) translations relative to rest -> (K, 4, 4) world matrices: the rest matrix with the
    translation added to its translation column."""
    t = np.asarray(translations, dtype=np.float64)
    if t.shape != (len(skin.names), 3):
        raise SkinError(f"translations must be ({len(skin.names)}, 3), got shape {t.shape}")
    world = skin.rest_world.copy()
    world[:, :3, 3] += t
    return world
