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
_PNG_FAST = [cv2.IMWRITE_PNG_COMPRESSION, 0]  # localhost only: skip compression, ~2x faster encode


def render_current_slice_png() -> bytes:
    if state.raw_volume is None:
        raise RuntimeError("No volume loaded.")

    raw = state.raw_volume[state.current_slice]
    lo = state.wl - state.ww / 2
    hi = state.wl + state.ww / 2
    img = ((np.clip(raw, lo, hi) - lo) / (hi - lo) * 255).astype(np.uint8)

    mri = state.reg_mri_arr
    if state.view_mode and mri is not None and mri.shape == state.raw_volume.shape:
        mlo, mhi = state.reg_window
        m8 = ((np.clip(mri[state.current_slice], mlo, mhi) - mlo) / (mhi - mlo) * 255).astype(np.uint8)
        img = m8 if state.view_mode == 1 else cv2.addWeighted(m8, state.reg_blend, img, 1 - state.reg_blend, 0)

    _engine.active_filter = state.active_filter
    _engine.strength = state.filter_strength
    img = _engine.apply(img)

    if state.show_overlay and state.seg_mask is not None:
        from segmentation import apply_overlay
        mask_slice = state.current_mask_slice
        if mask_slice is not None:
            disp = apply_overlay(img, mask_slice, state.opacity)
            ok, buf = cv2.imencode(".png", disp, _PNG_FAST)
            if not ok:
                raise RuntimeError("Failed to encode slice image.")
            return buf.tobytes()

    ok, buf = cv2.imencode(".png", img, _PNG_FAST)
    if not ok:
        raise RuntimeError("Failed to encode slice image.")
    return buf.tobytes()