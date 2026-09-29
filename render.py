"""
render.py
MIMIR — Gesture-Guided Surgical Intelligence

Renders the current slice (windowing + optional filter + optional
segmentation overlay) to PNG bytes for the browser to display in an
<img>. Mirrors the desktop app's render_slice pipeline so behavior
matches exactly.
"""

from __future__ import annotations
import numpy as np
import cv2
from preprocessing_engine import PreprocessingEngine
from state import state

_engine = PreprocessingEngine()


def render_current_slice_png() -> bytes:
    if state.raw_volume is None:
        raise RuntimeError("No volume loaded.")

    raw = state.raw_volume[state.current_slice]
    lo = state.wl - state.ww / 2
    hi = state.wl + state.ww / 2
    img = ((np.clip(raw, lo, hi) - lo) / (hi - lo) * 255).astype(np.uint8)

    _engine.active_filter = state.active_filter
    _engine.strength = state.filter_strength
    img = _engine.apply(img)

    if state.show_overlay and state.seg_mask is not None:
        from segmentation import apply_overlay
        mask_slice = state.current_mask_slice
        if mask_slice is not None:
            disp = apply_overlay(img, mask_slice, state.opacity)
            ok, buf = cv2.imencode(".png", disp)
            if not ok:
                raise RuntimeError("Failed to encode slice image.")
            return buf.tobytes()

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Failed to encode slice image.")
    return buf.tobytes()