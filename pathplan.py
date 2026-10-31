"""
pathplan.py
MIMIR — Gesture-Guided Surgical Intelligence

Straight needle trajectories from the skin to a clicked target. Rays are cast
from the target in ~600 directions over a ~2 mm grid; each ray's entry point
is where it leaves the body. Rays that cross a critical structure or are
longer than the limit are dropped; the rest are scored by clearance and length.

Critical structures: bone/dense contrast (HU > 300), plus every segmented
structure except the one containing the target and the muscles.
Research prototype — a geometric sketch, not a surgical plan.
"""

from __future__ import annotations
import numpy as np
from scipy import ndimage

from state import state

MUSCLE_LABELS = list(range(33, 43))  # gluteus, iliopsoas, autochthon: needles pass through muscle
GRID_MM = 2.0
_cache: dict = {}


def _spacing_zyx() -> np.ndarray:
    sx, sy, sz = state.sitk_image.GetSpacing() if state.sitk_image is not None else (1.0, 1.0, 1.0)
    return np.array([sz, sy, sx])


def _body_mask(small: np.ndarray) -> np.ndarray:
    """Largest connected HU > -300 region, holes (gas, lungs) filled slice by slice."""
    lab, n = ndimage.label(small > -300)
    if n == 0:
        return np.zeros(small.shape, bool)
    body = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
    return np.stack([ndimage.binary_fill_holes(s) for s in body])


def _fields(step, target_label):
    """Body mask and clearance field (mm to the nearest critical voxel) on the search grid."""
    key = (id(state.raw_volume), id(state.seg_mask), target_label)
    if key not in _cache:
        _cache.clear()
        small = state.raw_volume[::step[0], ::step[1], ::step[2]]
        crit = small > 300
        seg = state.seg_mask
        if seg is not None and seg.shape == state.raw_volume.shape:
            s = seg[::step[0], ::step[1], ::step[2]]
            crit |= (s > 0) & (s != target_label) & ~np.isin(s, MUSCLE_LABELS)
        clear = ndimage.distance_transform_edt(~crit, sampling=_spacing_zyx() * step)
        _cache[key] = (_body_mask(small), clear)
    return _cache[key]


def _directions(n: int) -> np.ndarray:
    """n roughly uniform unit vectors (Fibonacci sphere), (z, y, x)."""
    i = np.arange(n) + 0.5
    z = 1 - 2 * i / n
    r = np.sqrt(1 - z * z)
    a = np.pi * (1 + 5 ** 0.5) * i
    return np.stack([z, r * np.sin(a), r * np.cos(a)], 1)


def plan(target_zyx, max_len_mm: float = 150.0, n_dirs: int = 600, top: int = 5) -> list:
    """Ranked paths (best first). Raises ValueError with a user-facing message."""
    sp = _spacing_zyx()
    step = np.maximum(1, np.round(GRID_MM / sp)).astype(int)
    tz, ty, tx = (int(v) for v in target_zyx)
    target_label = int(state.seg_mask[tz, ty, tx]) if (
        state.seg_mask is not None and state.seg_mask.shape == state.raw_volume.shape) else 0
    body, clear = _fields(step, target_label)
    gsp = sp * step
    shape = np.array(body.shape)

    # Note: ~2 mm search grid, so entry points are accurate to about one grid step;
    # resample the winners at full resolution if that ever matters.
    t = np.arange(0, max_len_mm + gsp.min(), gsp.min())          # (M,) mm along the ray
    dirs = _directions(n_dirs)                                    # (N, 3)
    pts = np.array(target_zyx) * sp + dirs[:, None] * t[None, :, None]
    idx = np.round(pts / gsp).astype(int)
    inb = ((idx >= 0) & (idx < shape)).all(-1)
    idx = np.clip(idx, 0, shape - 1)
    inside = body[idx[..., 0], idx[..., 1], idx[..., 2]] & inb   # (N, M)
    c = clear[idx[..., 0], idx[..., 1], idx[..., 2]]
    if not inside[0, 0]:
        raise ValueError("The target must be inside the body.")
    if c[0, 0] == 0:
        raise ValueError("The target lies in a critical structure (bone or a segmented organ).")

    exits = (~inside).any(1)
    k = (~inside).argmax(1)                                       # first sample outside the body
    before = np.arange(len(t))[None, :] < k[:, None]
    cmin = np.where(before, c, np.inf).min(1)
    length = t[k]
    # Leaving through the top/bottom of the scanned range is not a skin entry.
    ok = exits & (cmin > 0) & inb[np.arange(n_dirs), k]
    if not ok.any():
        raise ValueError(f"No straight path under {max_len_mm:.0f} mm avoids the critical structures.")
    score = 0.6 * np.minimum(cmin, 20) / 20 + 0.4 * (1 - length / max_len_mm)

    picked = []
    for i in np.argsort(-np.where(ok, score, -np.inf)):
        if not ok[i] or len(picked) == top:
            break
        if all(dirs[i] @ dirs[j] < np.cos(np.radians(15)) for j in picked):  # keep the 5 distinct
            picked.append(i)
    out = []
    for i in picked:
        entry_mm = pts[i, k[i]]
        entry = entry_mm / sp
        out.append({
            "entry_xyz": [round(float(entry[2]), 1), round(float(entry[1]), 1), round(float(entry[0]), 1)],
            "target_xyz": [tx, ty, tz],
            "entry_mm": [float(entry_mm[2]), float(entry_mm[1]), float(entry_mm[0])],
            "target_mm": [tx * float(sp[2]), ty * float(sp[1]), tz * float(sp[0])],
            "length_mm": round(float(length[i]), 1),
            "clearance_mm": round(float(cmin[i]), 1),
            "score": round(float(score[i]), 3),
        })
    return out
