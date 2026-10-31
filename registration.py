"""
registration.py
MIMIR — Gesture-Guided Surgical Intelligence

Registers a second series (the "moving" image, typically MRI) onto the
loaded scan (the fixed CT): rigid, then affine, Mattes mutual information,
multi-resolution. The result is resampled onto the CT grid so render.py can
show it slice for slice. Runs on a background thread like segmentation;
progress goes onto `state`, which the page polls.
"""

from __future__ import annotations
import logging
import time

import numpy as np
import SimpleITK as sitk

from dicom_io import load_dicom_path
from state import state

log = logging.getLogger("mimir.registration")
_cancelled = False


def load_moving(path: str) -> dict:
    """Load the moving series. Raises RuntimeError with a user-facing message."""
    arr, img, meta = load_dicom_path(path)
    if arr.shape[0] < 2:
        raise RuntimeError("Registration needs a 3D series. Choose a DICOM folder.")
    state.reg_moving = sitk.Cast(img, sitk.sitkFloat32)
    state.reg_moving_meta = meta
    state.reg_mri_arr = None
    state.reg_metrics = {}
    state.reg_error = None
    state.view_mode = 0
    return {"meta": meta, "dims": list(arr.shape)}


def cancel():
    global _cancelled
    if state.reg_running:
        _cancelled = True


def _coarse(img, max_dim=128):
    """Shrink to at most ~max_dim voxels per axis; physical space is kept."""
    return sitk.Shrink(img, [max(1, s // max_dim) for s in img.GetSize()])


def _stage(name, fixed, moving, tx):
    R = sitk.ImageRegistrationMethod()
    R.SetMetricAsMattesMutualInformation(numberOfHistogramBins=50)
    R.SetMetricSamplingStrategy(R.RANDOM)
    R.SetMetricSamplingPercentage(min(1.0, 200_000 / fixed.GetNumberOfPixels()), seed=1)
    R.SetInterpolator(sitk.sitkLinear)
    R.SetOptimizerAsRegularStepGradientDescent(learningRate=2.0, minStep=1e-3, numberOfIterations=200)
    R.SetOptimizerScalesFromPhysicalShift()
    R.SetShrinkFactorsPerLevel([4, 2, 1])
    R.SetSmoothingSigmasPerLevel([2, 1, 0])
    R.SmoothingSigmasAreSpecifiedInPhysicalUnitsOff()
    R.SetInitialTransform(tx, inPlace=True)

    def on_iteration():
        if _cancelled:
            R.StopRegistration()
        state.reg_log[-1] = (f"{name}: level {R.GetCurrentLevel() + 1}/3, "
                             f"iteration {R.GetOptimizerIteration()}, metric {R.GetMetricValue():.4f}")

    R.AddCommand(sitk.sitkIterationEvent, on_iteration)
    state.reg_log.append(f"{name}: starting...")
    R.Execute(fixed, moving)
    return R


def run_registration():
    """Background-thread entry point. Writes state.reg_mri_arr / reg_metrics."""
    global _cancelled
    state.reg_running = True
    state.reg_error = None
    state.reg_log = []
    _cancelled = False
    t0 = time.time()
    try:
        fixed_full = sitk.Cast(state.sitk_image, sitk.sitkFloat32)
        fixed, moving = _coarse(fixed_full), _coarse(state.reg_moving)
        rigid = sitk.CenteredTransformInitializer(fixed, moving, sitk.Euler3DTransform(),
                                                  sitk.CenteredTransformInitializerFilter.GEOMETRY)
        r1 = _stage("Rigid", fixed, moving, rigid)
        if _cancelled:
            return
        affine = sitk.AffineTransform(3)
        affine.SetCenter(rigid.GetCenter())
        affine.SetMatrix(rigid.GetMatrix())
        affine.SetTranslation(rigid.GetTranslation())
        r2 = _stage("Affine", fixed, moving, affine)
        if _cancelled:
            return
        state.reg_log.append("Resampling onto the scan grid...")
        out = sitk.Resample(state.reg_moving, fixed_full, affine, sitk.sitkLinear,
                            float(sitk.GetArrayViewFromImage(moving).min()))
        arr = sitk.GetArrayFromImage(out).astype(np.float32)
        lo, hi = np.percentile(arr[::4, ::4, ::4], (1, 99))  # MRI has no fixed units
        state.reg_window = (float(lo), float(max(hi, lo + 1)))
        state.reg_mri_arr = arr
        state.view_mode = 2
        state.reg_metrics = {
            "metric": round(r2.GetMetricValue(), 4),
            "iterations": r1.GetOptimizerIteration() + r2.GetOptimizerIteration(),
            "elapsed_s": round(time.time() - t0, 1),
            "stop": r2.GetOptimizerStopConditionDescription()[:160],
        }
        state.reg_log.append(f"Done in {state.reg_metrics['elapsed_s']} s.")
    except Exception as e:
        log.exception("Registration crashed")
        state.reg_error = str(e).strip().split("\n")[0] or "Registration failed."
    finally:
        if _cancelled:
            state.reg_error = "Registration cancelled."
        state.reg_running = False
