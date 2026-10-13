"""
server.py
MIMIR — Gesture-Guided Surgical Intelligence

Local FastAPI server. Runs entirely on the user's own machine — nothing
is uploaded anywhere. The browser tab is just the UI; all DICOM/AI work
happens in this process using the user's own CPU/GPU.

Step 1 scope (this file): DICOM open (file/folder via native OS dialog),
slice rendering with windowing + filters, slice navigation.
Segmentation / Registration / Path Planning / Gesture camera are wired
in subsequent steps.
"""

from __future__ import annotations
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from state import state
from dicom_io import load_dicom_path
from render import render_current_slice_png
from mesh3d import extract_mesh, suggest_iso_defaults, serialize_mesh

__version__ = "0.1.0"  # bump before tagging a release: git tag v<this>

# Resolves to the bundle dir when frozen by PyInstaller, so cwd doesn't matter.
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="MIMIR", version=__version__)


# ══════════════════════════════════════════════════════════════
#  Native OS file/folder dialogs
# ══════════════════════════════════════════════════════════════

def _native_open_file() -> str | None:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(title="Open DICOM File")
    root.destroy()
    return path or None


def _native_open_folder() -> str | None:
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(title="Open DICOM Folder")
    root.destroy()
    return path or None


# ══════════════════════════════════════════════════════════════
#  DICOM endpoints
# ══════════════════════════════════════════════════════════════

def _load_and_reset(path: str) -> dict:
    volume, sitk_image, meta = load_dicom_path(path)
    state.raw_volume = volume
    state.sitk_image = sitk_image
    state.dicom_path = path
    state.modality = meta.get("Modality", "CT")
    state.metadata = meta
    state.current_slice = volume.shape[0] // 2
    state.wl, state.ww = 40.0, 400.0
    state.active_filter = "None (Original)"
    state.filter_strength = 1.0
    state.zoom, state.pan_x, state.pan_y = 1.0, 0, 0
    state.seg_mask = None
    state.show_overlay = False
    state.seg_running = False
    state.seg_log = []
    state.seg_error = None
    state.seg_active_labels = []
    state.reg_ct_arr = state.reg_mri_arr = None
    state.view_mode = 0
    state.tumor_point_mm = state.tumor_voxel = None
    state.path_ranked = []
    state.selected_path_idx = None
    return {
        "meta": meta,
        "num_slices": int(volume.shape[0]),
        "current_slice": int(state.current_slice),
        "wl": state.wl, "ww": state.ww,
    }


@app.post("/api/dicom/open-file")
def open_file():
    path = _native_open_file()
    if not path:
        return {"cancelled": True}
    try:
        return _load_and_reset(path)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/dicom/open-folder")
def open_folder():
    path = _native_open_folder()
    if not path:
        return {"cancelled": True}
    try:
        return _load_and_reset(path)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/dicom/slice")
def get_slice():
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    png = render_current_slice_png()
    return Response(content=png, media_type="image/png")


class WindowUpdate(BaseModel):
    wl: float | None = None
    ww: float | None = None


@app.post("/api/dicom/window")
def set_window(body: WindowUpdate):
    if body.wl is not None:
        state.wl = body.wl
    if body.ww is not None:
        state.ww = body.ww
    return {"wl": state.wl, "ww": state.ww}


class FilterUpdate(BaseModel):
    name: str | None = None
    strength: float | None = None


@app.get("/api/dicom/filters")
def list_filters():
    from preprocessing_engine import PreprocessingEngine
    return {
        "filters": PreprocessingEngine.FILTERS,
        "active": state.active_filter,
        "strength": state.filter_strength,
    }


@app.post("/api/dicom/filter")
def set_filter(body: FilterUpdate):
    from preprocessing_engine import PreprocessingEngine
    if body.name is not None:
        if body.name not in PreprocessingEngine.FILTERS:
            raise HTTPException(400, f"Unknown filter: {body.name}")
        state.active_filter = body.name
    if body.strength is not None:
        state.filter_strength = max(0.1, min(2.0, body.strength))
    return {"active": state.active_filter, "strength": state.filter_strength}


class SliceNav(BaseModel):
    delta: int = 0
    index: int | None = None


@app.post("/api/dicom/nav")
def nav_slice(body: SliceNav):
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    if body.index is not None:
        state.current_slice = max(0, min(state.num_slices - 1, body.index))
    else:
        state.current_slice = max(0, min(state.num_slices - 1, state.current_slice + body.delta))
    return {"current_slice": int(state.current_slice), "num_slices": state.num_slices}


@app.get("/api/status")
def status():
    return {
        "version": __version__,
        "has_volume": state.has_volume,
        "num_slices": state.num_slices,
        "current_slice": state.current_slice,
        "wl": state.wl, "ww": state.ww,
        "modality": state.modality,
        "meta": state.metadata,
        "active_filter": state.active_filter,
        "filter_strength": state.filter_strength,
    }


# ══════════════════════════════════════════════════════════════
#  3D volume rendering (marching cubes -> mesh -> browser WebGL)
# ══════════════════════════════════════════════════════════════

def _spacing_zyx() -> tuple:
    """SimpleITK spacing is (x,y,z); our volume array is indexed (z,y,x)."""
    if state.sitk_image is not None:
        sx, sy, sz = state.sitk_image.GetSpacing()
        return (sz, sy, sx)
    return (1.0, 1.0, 1.0)


@app.get("/api/dicom/mesh-defaults")
def mesh_defaults():
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    return suggest_iso_defaults(state.raw_volume, state.modality)


@app.get("/api/dicom/mesh")
def get_mesh(iso: float, step: int = 1):
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    try:
        verts, faces, normals = extract_mesh(
            state.raw_volume, _spacing_zyx(), iso_value=iso, step_size=max(1, step))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(faces) == 0:
        raise HTTPException(400, "No surface found at this threshold — try a different value.")
    blob = serialize_mesh(verts, faces, normals)
    return Response(content=blob, media_type="application/octet-stream")


# ══════════════════════════════════════════════════════════════
#  Segmentation (TotalSegmentator)
# ══════════════════════════════════════════════════════════════

@app.post("/api/segment/run")
def run_segment():
    if state.raw_volume is None or not state.dicom_path:
        raise HTTPException(400, "Open a DICOM file or folder first.")
    if state.seg_running:
        raise HTTPException(409, "Segmentation is already running.")

    from segmentation import run_segmentation
    thread = threading.Thread(
        target=run_segmentation, args=(state.dicom_path, state.modality), daemon=True)
    thread.start()
    return {"started": True}


@app.get("/api/segment/status")
def segment_status():
    return {
        "running": state.seg_running,
        "log": state.seg_log,
        "error": state.seg_error,
        "done": state.has_segmentation,
        "active_labels": state.seg_active_labels,
        "show_overlay": state.show_overlay,
        "opacity": state.opacity,
    }


@app.get("/api/segment/legend")
def segment_legend():
    from segmentation import ORGAN_COLOURS
    items = []
    for lid in state.seg_active_labels:
        name, bgr = ORGAN_COLOURS.get(lid, (f"Label {lid}", (128, 128, 128)))
        b, g, r = bgr
        items.append({"id": lid, "name": name, "color": f"#{r:02x}{g:02x}{b:02x}"})
    return {"items": items}


class OverlayUpdate(BaseModel):
    show: bool | None = None
    opacity: float | None = None


@app.post("/api/segment/overlay")
def set_overlay(body: OverlayUpdate):
    if body.show is not None:
        if body.show and not state.has_segmentation:
            raise HTTPException(400, "Run segmentation first.")
        state.show_overlay = body.show
    if body.opacity is not None:
        state.opacity = max(0.0, min(1.0, body.opacity))
    return {"show_overlay": state.show_overlay, "opacity": state.opacity}


# ══════════════════════════════════════════════════════════════
#  Static frontend
# ══════════════════════════════════════════════════════════════

app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
app.mount("/vendor", StaticFiles(directory=STATIC / "vendor"), name="vendor")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def _open_browser():
    webbrowser.open("http://127.0.0.1:8731")


if __name__ == "__main__":
    import uvicorn
    threading.Timer(1.0, _open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8731, log_level="warning")