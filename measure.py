"""
measure.py
MIMIR — Gesture-Guided Surgical Intelligence

Slice measurements. Ruler and angle are pure geometry, so the page does
them itself with the spacing from /api/status; ROI statistics need the
raw voxel values and are computed here.
"""

from __future__ import annotations
import numpy as np

from state import state


def spacing_xy() -> tuple:
    """In-plane pixel size (mm) along image x (columns) and y (rows)."""
    if state.sitk_image is None:
        return (1.0, 1.0)
    sx, sy = state.sitk_image.GetSpacing()[:2]
    return (float(sx), float(sy))


def roi_stats(slice_idx: int, cx: float, cy: float, rx: float, ry: float) -> dict:
    """Mean/std/min/max of the raw values (HU for CT) inside an axis-aligned
    ellipse given in image pixel coordinates, plus its area in mm²."""
    img = state.raw_volume[slice_idx]
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    inside = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1
    vals = img[inside]
    if vals.size == 0:
        raise ValueError("The ROI does not cover any pixel of the image.")
    sx, sy = spacing_xy()
    return {
        "mean": float(vals.mean()), "std": float(vals.std()),
        "min": float(vals.min()), "max": float(vals.max()),
        "pixels": int(vals.size), "area_mm2": float(vals.size * sx * sy),
    }
