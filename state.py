"""
state.py
MIMIR — Gesture-Guided Surgical Intelligence

Server-side session state. Since this runs as a single-user local server
(one instance per machine, launched by server.py), a single in-memory state
object is sufficient — no per-session/multi-tenant complexity needed.
"""

from __future__ import annotations
from typing import Optional
import numpy as np


class WorkstationState:
    def __init__(self):
        self.raw_volume: Optional[np.ndarray] = None      # (Z,H,W) float32
        self.seg_mask: Optional[np.ndarray] = None         # (Z,H,W) int32
        self.sitk_image = None                             # geometry reference
        self.dicom_path: Optional[str] = None
        self.modality: str = "CT"
        self.metadata: dict = {}

        self.current_slice: int = 0
        self.wl: float = 40.0
        self.ww: float = 400.0
        self.zoom: float = 1.0
        self.pan_x: int = 0
        self.pan_y: int = 0

        self.active_filter: str = "None (Original)"
        self.filter_strength: float = 1.0

        self.show_overlay: bool = False
        self.opacity: float = 0.45

        # Segmentation run tracking (background thread updates these;
        # the frontend polls /api/segment/status to follow along)
        self.seg_running: bool = False
        self.seg_log: list = []
        self.seg_error: Optional[str] = None
        self.seg_active_labels: list = []   # organ ids present in the last result

        # Measurements drawn by the page, mirrored here for the report
        self.measurements: list = []

        # Registration
        self.reg_ct_arr: Optional[np.ndarray] = None
        self.reg_mri_arr: Optional[np.ndarray] = None
        self.reg_metrics: dict = {}
        self.view_mode: int = 0   # 0=CT, 1=MRI Registered, 2=Overlay
        self.reg_moving = None                 # moving series (sitk image), before registration
        self.reg_moving_meta: dict = {}
        self.reg_window = (0.0, 1.0)           # display range of reg_mri_arr (percentiles)
        self.reg_blend: float = 0.5            # MRI weight in view_mode 2
        self.reg_running: bool = False
        self.reg_log: list = []
        self.reg_error: Optional[str] = None

        # Path planning
        self.tumor_point_mm = None
        self.tumor_voxel = None
        self.path_ranked: list = []
        self.selected_path_idx: Optional[int] = None
        self.mesh_center = None   # xyz mm subtracted from the last 3D mesh

    @property
    def has_volume(self) -> bool:
        return self.raw_volume is not None

    @property
    def has_segmentation(self) -> bool:
        return self.seg_mask is not None

    @property
    def num_slices(self) -> int:
        return 0 if self.raw_volume is None else self.raw_volume.shape[0]

    @property
    def current_mask_slice(self):
        """The seg_mask slice aligned to the current raw_volume slice.
        Defensive about Z-dimension mismatches between the two volumes
        (shouldn't normally happen since both come from the same DICOM
        series, but TotalSegmentator's NIfTI round-trip could in theory
        produce a slightly different Z count). A different in-plane size
        means the mask isn't for this scan, so no overlay is drawn."""
        if self.seg_mask is None or self.raw_volume is None:
            return None
        if self.seg_mask.shape[1:] != self.raw_volume.shape[1:]:
            return None
        mz = self.seg_mask.shape[0]
        vz = self.raw_volume.shape[0]
        idx = min(int(self.current_slice * mz / vz), mz - 1)
        return self.seg_mask[idx]


state = WorkstationState()