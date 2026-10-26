"""
segmentation.py
MIMIR — Gesture-Guided Surgical Intelligence

AI organ segmentation via TotalSegmentator, ported from the desktop app's
SegmentationWorker (originally a QThread). Runs as a plain function meant
to be called from a background thread — all progress/results are written
onto the shared `state` object, which the frontend polls.

Uses the CPU "--fast" TotalSegmentator preset by default. This still
takes real time (roughly a minute or few per volume on typical hardware)
since it's a genuine deep-learning inference pass, not a shortcut.
"""

from __future__ import annotations
import logging
import os
import sys
import shutil
import subprocess
import tempfile
import uuid
import numpy as np
import SimpleITK as sitk

from state import state

RIBS_LABEL = 51

ORGAN_COLOURS = {
    1:  ("Spleen",              (0,   255,  80)),
    2:  ("Kidney Right",        (0,   120, 255)),
    3:  ("Kidney Left",         (0,   200, 255)),
    4:  ("Gallbladder",         (0,   255, 220)),
    5:  ("Liver",               (30,  105, 210)),   # BGR: brown, distinct from aorta red
    6:  ("Stomach",             (255, 180,   0)),
    7:  ("Pancreas",            (0,   255, 255)),
    8:  ("Adrenal Right",       (255, 255,   0)),
    9:  ("Adrenal Left",        (200, 255,   0)),
    10: ("Aorta",               (0,     0, 255)),
    11: ("Inferior Vena Cava",  (180,   0, 255)),
    12: ("Portal/Splenic Vein", (255,   0, 180)),
    13: ("Iliac Artery Right",  (0,    80, 200)),
    14: ("Iliac Artery Left",   (0,   100, 180)),
    15: ("Iliac Vein Right",    (140,   0, 200)),
    16: ("Iliac Vein Left",     (120,   0, 180)),
    17: ("Lung Right",          (100, 180, 255)),
    18: ("Lung Left",           (60,  140, 255)),
    19: ("Heart",               (147,  20, 255)),   # BGR: deep pink
    20: ("Esophagus",           (255, 160, 100)),
    21: ("Urinary Bladder",     (255, 100, 100)),
    22: ("Prostate/Uterus",     (255, 150, 200)),
    23: ("Colon",               (140, 200,  80)),
    24: ("Duodenum",            (255, 200, 100)),
    25: ("Small Bowel",         (120, 180,  60)),
    26: ("Sacrum",              (255, 240, 180)),
    27: ("Femur Right",         (200, 150, 255)),
    28: ("Femur Left",          (150, 100, 255)),
    29: ("Hip Right",           (220, 170, 255)),
    30: ("Hip Left",            (170, 120, 255)),
    31: ("Vertebrae",           (255, 220, 150)),
    32: ("Intervertebral Discs",(200, 200, 140)),
    33: ("Gluteus Max Right",   (180, 255, 180)),
    34: ("Gluteus Max Left",    (140, 220, 140)),
    35: ("Gluteus Med Right",   (160, 240, 160)),
    36: ("Gluteus Med Left",    (120, 200, 120)),
    37: ("Gluteus Min Right",   (140, 220, 100)),
    38: ("Gluteus Min Left",    (100, 180,  80)),
    39: ("Iliopsoas Right",     (255, 180, 140)),
    40: ("Iliopsoas Left",      (220, 140, 100)),
    41: ("Autochthon Right",    (200, 255, 220)),
    42: ("Autochthon Left",     (160, 220, 180)),
    43: ("Spinal Cord",         (240, 240, 100)),
    44: ("Scapula Right",       (230, 210, 255)),
    45: ("Scapula Left",        (200, 180, 255)),
    46: ("Clavicula Right",     (210, 200, 255)),
    47: ("Clavicula Left",      (180, 170, 255)),
    48: ("Humerus Right",       (255, 210, 210)),
    49: ("Humerus Left",        (220, 180, 180)),
    50: ("Brain",               (200, 220, 255)),
    RIBS_LABEL: ("Ribs",        (180, 180, 255)),
}

_RIB_NAMES = {f"rib_left_{i}": RIBS_LABEL for i in range(1, 13)}
_RIB_NAMES.update({f"rib_right_{i}": RIBS_LABEL for i in range(1, 13)})

_NAME_TO_ID = {
    "spleen": 1, "kidney_right": 2, "kidney_left": 3,
    "gallbladder": 4, "liver": 5, "stomach": 6, "pancreas": 7,
    "adrenal_gland_right": 8, "adrenal_gland_left": 9,
    "aorta": 10, "inferior_vena_cava": 11,
    "portal_vein_and_splenic_vein": 12,
    "iliac_artery_right": 13, "iliac_artery_left": 14,
    "iliac_vena_right": 15, "iliac_vena_left": 16,
    "iliac_vein_right": 15, "iliac_vein_left": 16,
    "lung_right": 17, "lung_upper_lobe_right": 17,
    "lung_lower_lobe_right": 17, "lung_middle_lobe_right": 17,
    "lung_left": 18, "lung_upper_lobe_left": 18,
    "lung_lower_lobe_left": 18,
    "heart": 19, "esophagus": 20, "urinary_bladder": 21,
    "prostate": 22, "uterus": 22, "colon": 23,
    "duodenum": 24, "small_bowel": 25, "sacrum": 26,
    "femur_right": 27, "femur_left": 28,
    "hip_right": 29, "hip_left": 30,
    "vertebrae": 31, "intervertebral_discs": 32,
    "gluteus_maximus_right": 33, "gluteus_maximus_left": 34,
    "gluteus_medius_right": 35, "gluteus_medius_left": 36,
    "gluteus_minimus_right": 37, "gluteus_minimus_left": 38,
    "iliopsoas_right": 39, "iliopsoas_left": 40,
    "autochthon_right": 41, "autochthon_left": 42,
    "spinal_cord": 43, "scapula_right": 44, "scapula_left": 45,
    "clavicula_right": 46, "clavicula_left": 47,
    "humerus_right": 48, "humerus_left": 49, "brain": 50,
}
_NAME_TO_ID.update(_RIB_NAMES)


def _pick_task(modality: str) -> str:
    return "total_mr" if modality.upper() in ("MR", "MRI") else "total"


DOCKER_IMAGE = "wasserth/totalsegmentator:2.18.0"

# A --noconsole build would otherwise flash a console window per subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

log = logging.getLogger("mimir.segmentation")

# The current run, so cancel() can stop it. Killing the `docker run` client
# alone leaves the container running, hence the container name.
_proc: subprocess.Popen | None = None
_container: str | None = None
_cancelled = False


def cancel():
    global _cancelled
    if not state.seg_running:
        return
    _cancelled = True
    if _container:
        subprocess.run(["docker", "kill", _container], capture_output=True, creationflags=_NO_WINDOW)
    if _proc is not None and _proc.poll() is None:
        # ponytail: kills only the direct child; the source-only pip fallback may leave
        # nnU-Net worker processes behind. Use `taskkill /T` if that shows up in practice.
        _proc.kill()


def _seg_command(tmp_dir: str, nii_in: str, out_dir: str) -> list | None:
    """TotalSegmentator command line up to (not incl.) task/device flags.
    Docker first; local Python install only when running from source.
    Sets state.seg_error and returns None if neither is usable."""
    if shutil.which("docker"):
        if subprocess.run(["docker", "info"], capture_output=True,
                          creationflags=_NO_WINDOW).returncode != 0:
            state.seg_error = "Docker is installed but not running. Start Docker Desktop and try again."
            return None
        if subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True,
                          creationflags=_NO_WINDOW).returncode != 0:
            _log("Downloading segmentation image (~15 GB, first time only)...")
        global _container
        _container = f"mimir-seg-{uuid.uuid4().hex[:8]}"
        # Named volume keeps model weights across --rm runs.
        return ["docker", "run", "--rm", "--ipc=host", "--name", _container,
                "-v", f"{tmp_dir}:/data", "-v", "mimir-totalseg:/root/.totalsegmentator",
                DOCKER_IMAGE, "TotalSegmentator",
                "-i", "/data/input.nii.gz", "-o", "/data/segs"]
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "totalsegmentator.bin.TotalSegmentator",
                "-i", nii_in, "-o", out_dir]
    state.seg_error = "Segmentation needs Docker. Install Docker Desktop, start it, and try again."
    return None


def _log(msg: str):
    state.seg_log.append(msg)
    # Keep the log from growing unbounded across repeated runs.
    if len(state.seg_log) > 400:
        state.seg_log = state.seg_log[-400:]


def run_segmentation(dicom_path: str, modality: str):
    """
    Runs TotalSegmentator on the given DICOM path and writes the merged
    label volume into state.seg_mask. Meant to be called on a background
    thread — updates state.seg_running / state.seg_log / state.seg_error
    as it goes so the frontend can poll for progress.

    This mirrors the desktop app's SegmentationWorker.run() logic exactly,
    with Qt signals replaced by writes to the shared state object.
    """
    global _proc, _container, _cancelled
    state.seg_running = True
    state.seg_log = []
    state.seg_error = None
    _proc, _container, _cancelled = None, None, False
    tmp_dir = None
    try:
        task = _pick_task(modality)
        tmp_dir = tempfile.mkdtemp(prefix="totalseg_")
        nii_in = os.path.join(tmp_dir, "input.nii.gz")
        out_dir = os.path.join(tmp_dir, "segs")
        os.makedirs(out_dir, exist_ok=True)

        _log(f"Converting DICOM -> NIfTI ({task})...")
        reader = sitk.ImageSeriesReader()
        dicom_dir = dicom_path
        if os.path.isdir(dicom_path):
            ids = reader.GetGDCMSeriesIDs(dicom_dir)
            if not ids:
                for sub in sorted(os.listdir(dicom_dir)):
                    sp = os.path.join(dicom_dir, sub)
                    if os.path.isdir(sp):
                        ids = reader.GetGDCMSeriesIDs(sp)
                        if ids:
                            dicom_dir = sp
                            break
            if not ids:
                state.seg_error = "No DICOM series found."
                return
            files = reader.GetGDCMSeriesFileNames(dicom_dir, ids[0])
        else:
            files = [dicom_path]
        reader.SetFileNames(files)
        sitk.WriteImage(reader.Execute(), nii_in)

        cmd = _seg_command(tmp_dir, nii_in, out_dir)
        if cmd is None or _cancelled:
            return

        _log(f"Running TotalSegmentator ({task}, CPU fast)...")
        proc = _proc = subprocess.Popen(
            cmd + ["-ta", task, "-d", "cpu", "--fast"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=_NO_WINDOW,
        )
        if _cancelled:
            cancel()  # cancel() ran between the check above and Popen; stop what just started
        for line in proc.stdout:
            line = line.strip()
            if line and not line.startswith(("W0", "E0", "===")):
                _log(line[:150])
        proc.wait()
        if _cancelled:
            return
        if proc.returncode != 0:
            state.seg_error = f"TotalSegmentator failed (exit code {proc.returncode})."
            return

        _log("Merging masks...")
        seg_files = [f for f in os.listdir(out_dir)
                     if f.endswith(".nii.gz") or f.endswith(".nii")]
        if not seg_files:
            state.seg_error = "No output files from TotalSegmentator."
            return

        label_vol = None
        merged = 0
        active_labels = set()
        for fname in sorted(seg_files):
            stem = fname.replace(".nii.gz", "").replace(".nii", "").lower()
            # CT task writes each vertebra separately (vertebrae_L1, ...).
            lid = _NAME_TO_ID.get(stem, 31 if stem.startswith("vertebrae_") else None)
            if lid is None:
                continue
            arr = sitk.GetArrayFromImage(
                sitk.ReadImage(os.path.join(out_dir, fname))
            ).astype(np.uint8)
            if label_vol is None:
                label_vol = np.zeros_like(arr, dtype=np.int32)
            label_vol[arr > 0] = lid
            active_labels.add(lid)
            merged += 1

        if label_vol is None or label_vol.max() == 0:
            state.seg_error = "Mask empty - no organs matched."
            return

        state.seg_mask = label_vol
        state.seg_active_labels = sorted(active_labels)
        state.show_overlay = True
        _log(f"Done - {merged} structures merged.")

    except Exception as e:
        import traceback
        log.exception("Segmentation crashed")
        state.seg_error = f"{e}\n{traceback.format_exc()}"
    finally:
        if _cancelled:
            state.seg_error = "Segmentation cancelled."
        if state.seg_error:
            log.warning("Segmentation ended: %s", state.seg_error.split("\n")[0])
        state.seg_running = False
        _proc = _container = None
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def apply_overlay(scan_slice_bgr_or_gray, mask_slice, opacity):
    """Composite the colored organ-label overlay onto a uint8 grayscale
    slice. Returns a BGR uint8 image (for cv2 PNG encoding)."""
    import cv2
    if scan_slice_bgr_or_gray.ndim == 2:
        bgr = cv2.cvtColor(scan_slice_bgr_or_gray, cv2.COLOR_GRAY2BGR)
    else:
        bgr = scan_slice_bgr_or_gray
    ov = bgr.copy()
    for label, (_, colour) in ORGAN_COLOURS.items():
        m = (mask_slice == label)
        if m.any():
            ov[m] = colour
    return cv2.addWeighted(ov, opacity, bgr, 1 - opacity, 0)
