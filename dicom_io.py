"""
dicom_io.py
MIMIR — Gesture-Guided Surgical Intelligence

DICOM loading, ported directly from the desktop app's DicomLoader so
behavior (series discovery, HU handling, metadata extraction) stays
identical between the two versions.
"""

from __future__ import annotations
import os
import numpy as np
import pydicom
import SimpleITK as sitk


def _meta(ds) -> dict:
    def s(t, d="N/A"):
        return str(getattr(ds, t, d))
    return {
        "Patient": s("PatientName"),
        "Modality": s("Modality"),
        "Study Date": s("StudyDate"),
        "Rows": s("Rows"),
        "Columns": s("Columns"),
        "Institution": s("InstitutionName"),
    }


def load_dicom_path(path: str):
    """
    Load a single DICOM file or a DICOM series folder.
    Returns (volume: np.ndarray[Z,H,W] float32, sitk_image, meta: dict)
    Raises RuntimeError with a user-facing message on failure.
    """
    if os.path.isfile(path):
        ds = pydicom.dcmread(path)
        arr = ds.pixel_array.astype(np.float32)
        if arr.ndim == 2:
            arr = arr[np.newaxis, ...]
        return arr, sitk.GetImageFromArray(arr), _meta(ds)

    if os.path.isdir(path):
        reader = sitk.ImageSeriesReader()
        dicom_dir = path
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
            raise RuntimeError("No DICOM series found in that folder.")
        files = reader.GetGDCMSeriesFileNames(dicom_dir, ids[0])
        reader.SetFileNames(files)
        img = reader.Execute()
        arr = sitk.GetArrayFromImage(img).astype(np.float32)
        ds = pydicom.dcmread(files[0])
        return arr, img, _meta(ds)

    raise RuntimeError("Invalid path.")
