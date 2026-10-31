"""
server.py
MIMIR — Gesture-Guided Surgical Intelligence

Local FastAPI server shown in a native window (pywebview). Runs entirely
on the user's own machine — nothing is uploaded anywhere. The window is
just the UI; all DICOM/AI work happens in this process.

Implemented: DICOM open, slice rendering (windowing, filters, overlay),
3D mesh, segmentation. Registration / Path Planning / Gesture camera
are planned.
"""

from __future__ import annotations
import logging
import os
import socket
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import webview

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from state import state
from dicom_io import load_dicom_path
from render import render_current_slice_png
from mesh3d import extract_mesh, suggest_iso_defaults, serialize_mesh
from measure import spacing_xy, roi_stats
import report

__version__ = "0.1.0"  # bump before tagging a release: git tag v<this>

# Resolves to the bundle dir when frozen by PyInstaller, so cwd doesn't matter.
STATIC = Path(__file__).parent / "static"
# Window icon when run from source; a frozen build isn't given installer/ and
# pywebview then falls back to the exe's own (MIMIR) icon.
ICON = Path(__file__).parent / "installer" / "mimir.ico"

LOG_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MIMIR" / "mimir.log"
log = logging.getLogger("mimir")

app = FastAPI(title="MIMIR", version=__version__)
# Blocks DNS rebinding: a page on another domain resolving to 127.0.0.1 sends its own Host.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def _json_posts_only(request: Request, call_next):
    # Other websites can send body-less "simple" POSTs to localhost; a JSON
    # content type forces a CORS preflight, which this server never answers.
    if request.method == "POST" and not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"detail": "POST requests must be application/json."}, 415)
    return await call_next(request)


# ══════════════════════════════════════════════════════════════
#  Native OS file/folder dialogs (via the app window)
# ══════════════════════════════════════════════════════════════

window = None  # the pywebview window, set in __main__


def _ask_path(dialog) -> str | None:
    """dialog: webview.FileDialog.OPEN or .FOLDER. Safe to call from
    request threads; pywebview marshals it onto the GUI thread."""
    paths = window.create_file_dialog(dialog)
    return paths[0] if paths else None


def _ask_save_path(filename: str) -> str | None:
    paths = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename,
                                      file_types=("HTML report (*.html)",))
    return paths[0] if paths else None


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
    state.seg_log = []
    state.seg_error = None
    state.seg_active_labels = []
    state.reg_ct_arr = state.reg_mri_arr = None
    state.view_mode = 0
    state.tumor_point_mm = state.tumor_voxel = None
    state.path_ranked = []
    state.selected_path_idx = None
    state.measurements = []
    return {
        "meta": meta,
        "num_slices": int(volume.shape[0]),
        "current_slice": int(state.current_slice),
        "wl": state.wl, "ww": state.ww,
    }


def _open(dialog) -> dict:
    # A running segmentation would write its result onto the newly opened scan.
    if state.seg_running:
        raise HTTPException(409, "Segmentation is running. Cancel it before opening another scan.")
    path = _ask_path(dialog)
    if not path:
        return {"cancelled": True}
    try:
        return _load_and_reset(path)
    except Exception as e:
        log.warning("Could not open %s: %s", path, e)
        raise HTTPException(400, str(e))


@app.post("/api/dicom/open-file")
def open_file():
    return _open(webview.FileDialog.OPEN)


@app.post("/api/dicom/open-folder")
def open_folder():
    return _open(webview.FileDialog.FOLDER)


@app.get("/api/dicom/slice")
def get_slice(
    i: int | None = None,
    wl: float | None = Query(None, allow_inf_nan=False),
    ww: float | None = Query(None, gt=0, allow_inf_nan=False),
):
    # The page sends the whole view with each request; storing it keeps
    # /api/status (page-refresh resume) in step.
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    if i is not None:
        state.current_slice = max(0, min(state.num_slices - 1, i))
    if wl is not None:
        state.wl = wl
    if ww is not None:
        state.ww = ww
    png = render_current_slice_png()
    return Response(content=png, media_type="image/png")


class WindowUpdate(BaseModel):
    wl: float | None = Field(None, allow_inf_nan=False)
    ww: float | None = Field(None, gt=0, allow_inf_nan=False)


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
        "spacing": spacing_xy(),
    }


# ══════════════════════════════════════════════════════════════
#  Measurements
# ══════════════════════════════════════════════════════════════

class RoiRequest(BaseModel):
    slice: int
    cx: float = Field(allow_inf_nan=False)
    cy: float = Field(allow_inf_nan=False)
    rx: float = Field(gt=0, allow_inf_nan=False)
    ry: float = Field(gt=0, allow_inf_nan=False)


@app.post("/api/measure/roi")
def measure_roi(body: RoiRequest):
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    if not 0 <= body.slice < state.num_slices:
        raise HTTPException(400, "Slice index out of range.")
    try:
        return roi_stats(body.slice, body.cx, body.cy, body.rx, body.ry)
    except ValueError as e:
        raise HTTPException(400, str(e))


class MeasurementList(BaseModel):
    items: list[dict]


@app.get("/api/measure/list")
def get_measurements():
    return {"items": state.measurements}


@app.post("/api/measure/list")
def set_measurements(body: MeasurementList):
    state.measurements = body.items
    return {"count": len(state.measurements)}


# ══════════════════════════════════════════════════════════════
#  Review / report
# ══════════════════════════════════════════════════════════════

def _report_html() -> str:
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    return report.report_html(report.summary(), render_current_slice_png())


@app.get("/api/review/summary")
def review_summary():
    if state.raw_volume is None:
        raise HTTPException(404, "No volume loaded.")
    return report.summary()


@app.get("/api/review/report")
def review_report():
    return Response(content=_report_html(), media_type="text/html")


@app.post("/api/review/export")
def review_export():
    html = _report_html()
    path = _ask_save_path("mimir-report.html")
    if not path:
        return {"cancelled": True}
    Path(path).write_text(html, encoding="utf-8")
    return {"path": path}


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

_seg_lock = threading.Lock()
_seg_thread: threading.Thread | None = None


@app.post("/api/segment/run")
def run_segment():
    global _seg_thread
    if state.raw_volume is None or not state.dicom_path:
        raise HTTPException(400, "Open a DICOM file or folder first.")
    from segmentation import run_segmentation
    with _seg_lock:
        if state.seg_running:
            raise HTTPException(409, "Segmentation is already running.")
        state.seg_running = True  # set before start() so a second request can't slip in
        _seg_thread = threading.Thread(
            target=run_segmentation, args=(state.dicom_path, state.modality), daemon=True)
        _seg_thread.start()
    return {"started": True}


@app.post("/api/segment/cancel")
def cancel_segment():
    from segmentation import cancel
    cancel()
    return {"cancelling": state.seg_running}


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
app.mount("/features", StaticFiles(directory=STATIC / "features"), name="features")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Root logger also catches uvicorn's "Exception in ASGI application" tracebacks.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                                      encoding="utf-8")])
    log.info("MIMIR %s starting", __version__)
    # Free port, already listening, so the window's first request just
    # queues until uvicorn is up (no race, no clash with a second instance).
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    # log_config=None: a --noconsole build has no stdout for uvicorn's handlers.
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()

    window = webview.create_window(f"MIMIR {__version__}", f"http://127.0.0.1:{port}",
                                   width=1600, height=1000, min_size=(1100, 700))
    if sys.platform == "win32":
        try:
            import ctypes
            # Own taskbar group + icon instead of python.exe's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MIMIR.Workstation")
        except Exception as e:
            log.warning("Could not set AppUserModelID: %s", e)
    webview.start(icon=str(ICON) if ICON.exists() else None)  # blocks until the window is closed; daemon thread dies with it

    # Don't leave a TotalSegmentator container/process running after the window closes;
    # the join lets the worker's finally-block delete its temp folder.
    if _seg_thread is not None and _seg_thread.is_alive():
        from segmentation import cancel
        cancel()
        _seg_thread.join(timeout=15)
    log.info("MIMIR stopped")