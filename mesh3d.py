"""
mesh3d.py
MIMIR — Gesture-Guided Surgical Intelligence

Extracts an iso-surface mesh from the loaded volume (marching cubes) for
3D rendering in the browser via Three.js/WebGL — the actual triangle
mesh is computed here (CPU, once per iso-value change), but all the
rendering (rotation, lighting, zoom) happens client-side on the user's
own GPU via WebGL.

Binary wire format (little-endian):
    uint32  n_vertices
    uint32  n_faces
    float32[n_vertices * 3]   vertex xyz  (mm, patient space)
    float32[n_vertices * 3]   normal xyz
    uint32[n_faces * 3]       triangle indices
"""

from __future__ import annotations
import struct
import numpy as np
from skimage.measure import marching_cubes
from scipy.ndimage import zoom


def _downsample_for_speed(volume: np.ndarray, spacing_zyx: tuple, max_dim: int = 220):
    """Cap the largest volume dimension so marching cubes stays fast.
    Adjusts spacing to compensate so real-world proportions are kept."""
    z, y, x = volume.shape
    largest = max(z, y, x)
    if largest <= max_dim:
        return volume, spacing_zyx
    factor = max_dim / largest
    small = zoom(volume, factor, order=1)
    new_spacing = tuple(s / factor for s in spacing_zyx)
    return small.astype(np.float32), new_spacing


def extract_mesh(volume: np.ndarray, spacing_zyx: tuple, iso_value: float,
                  step_size: int = 1, max_dim: int = 220):
    """
    volume: (Z,H,W) array (HU for CT, raw intensity for MRI)
    spacing_zyx: (z_spacing, y_spacing, x_spacing) in mm
    iso_value: surface threshold
    step_size: marching-cubes stride — higher = coarser/faster mesh
    Returns (vertices Nx3 float32 mm, faces Mx3 uint32, normals Nx3 float32,
             center xyz mm that was subtracted from the vertices)
    """
    if min(volume.shape) < 2:
        raise ValueError("3D view needs a series with at least 2 slices. Open a DICOM folder.")
    vol, spacing = _downsample_for_speed(volume, spacing_zyx, max_dim=max_dim)

    vmin, vmax = float(vol.min()), float(vol.max())
    if not (vmin < iso_value < vmax):
        raise ValueError(
            f"iso_value {iso_value} is outside the volume's data range "
            f"[{vmin:.1f}, {vmax:.1f}] — nothing to render at this threshold.")

    verts, faces, normals, _ = marching_cubes(
        vol, level=iso_value, spacing=spacing, step_size=step_size,
        allow_degenerate=False,
    )
    # marching_cubes returns verts in (z,y,x) order matching array axes —
    # reorder to (x,y,z) for a conventional right-handed 3D scene.
    verts = verts[:, [2, 1, 0]].astype(np.float32)
    normals = normals[:, [2, 1, 0]].astype(np.float32)

    # Center the mesh at the origin so orbit controls rotate around the
    # object instead of some far-off corner.
    center = verts.mean(axis=0)
    verts -= center

    return verts, faces.astype(np.uint32), normals, center


def suggest_iso_defaults(volume: np.ndarray, modality: str) -> dict:
    """Suggest a sensible default iso-value + slider range for the given
    modality, mirroring 3D Slicer's built-in volume-rendering presets."""
    vmin, vmax = float(volume.min()), float(volume.max())
    modality = (modality or "CT").upper()

    if modality == "CT":
        # HU-based: bone is roughly 300+ HU, soft tissue ~40, air ~-1000
        return {
            "min": max(vmin, -200), "max": min(vmax, 2000),
            "default": 300, "label": "Bone (CT)",
        }
    else:
        # MRI has no standard units — use percentiles of the actual data
        p50, p85 = float(np.percentile(volume, 50)), float(np.percentile(volume, 85))
        return {
            "min": vmin, "max": vmax,
            "default": p85, "label": "Body Surface (MRI)",
        }


def serialize_mesh(vertices: np.ndarray, faces: np.ndarray, normals: np.ndarray) -> bytes:
    header = struct.pack("<II", len(vertices), len(faces))
    return header + vertices.tobytes() + normals.tobytes() + faces.tobytes()
