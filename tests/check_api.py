"""In-process API checks (no window, no Docker). Uses pydicom's bundled test files.

Run from mimir_web/:  ../venv/Scripts/python.exe tests/check_api.py
"""
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from fastapi.testclient import TestClient
from pydicom.data import get_testdata_file

import segmentation
import server
from state import state

JSON = {"Content-Type": "application/json"}
CT_SMALL = get_testdata_file("CT_small.dcm")  # RescaleIntercept -1024
c = TestClient(server.app, base_url="http://127.0.0.1", raise_server_exceptions=False)


def _open_ct_small():
    server._ask_path = lambda d: CT_SMALL
    r = c.post("/api/dicom/open-file", headers=JSON)
    assert r.status_code == 200, r.text


def check_single_file_is_hu():
    _open_ct_small()
    med = float(np.median(state.raw_volume))
    assert abs(med) < 100, f"median {med:.0f}: rescale intercept not applied (expect ~2 HU)"
    assert state.sitk_image.GetSpacing()[:2] != (1.0, 1.0), "PixelSpacing ignored"


def check_post_needs_json():
    r = c.post("/api/segment/run")
    assert r.status_code == 415, f"body-less POST accepted ({r.status_code}): CSRF-able"


def check_foreign_host_rejected():
    r = TestClient(server.app, base_url="http://evil.example").get("/api/status")
    assert r.status_code == 400, f"foreign Host accepted ({r.status_code}): DNS rebinding"


def check_window_validation():
    for ww in (0, -400):
        r = c.post("/api/dicom/window", headers=JSON, json={"ww": ww})
        assert r.status_code == 422, f"ww={ww} accepted"


def check_slice_params():
    _open_ct_small()
    r = c.get("/api/dicom/slice?i=99&wl=50&ww=300")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png", r.text
    assert (state.current_slice, state.wl, state.ww) == (0, 50, 300), "slice params not applied"
    for q in ("ww=0", "wl=nan"):
        r = c.get(f"/api/dicom/slice?{q}")
        assert r.status_code == 422, f"{q} accepted ({r.status_code})"


def check_mismatched_mask_does_not_crash():
    _open_ct_small()
    state.seg_mask = np.ones((1, 10, 10), np.int32)
    state.show_overlay = True
    r = c.get("/api/dicom/slice")
    state.seg_mask, state.show_overlay = None, False
    assert r.status_code == 200, f"slice with foreign mask -> {r.status_code}"


def check_single_slice_mesh_message():
    _open_ct_small()
    r = c.get("/api/dicom/mesh?iso=0")
    assert r.status_code == 400 and "at least 2 slices" in r.json()["detail"], r.text


def check_no_reload_or_double_run_while_segmenting():
    _open_ct_small()
    release = threading.Event()
    real = segmentation.run_segmentation

    def fake(path, modality):
        release.wait(5)
        state.seg_running = False

    segmentation.run_segmentation = fake
    try:
        assert c.post("/api/segment/run", headers=JSON).status_code == 200
        r2 = c.post("/api/segment/run", headers=JSON)
        r3 = c.post("/api/dicom/open-file", headers=JSON)
    finally:
        release.set()
        server._seg_thread.join(5)
        segmentation.run_segmentation = real
    assert r2.status_code == 409, f"second run -> {r2.status_code}"
    assert r3.status_code == 409, f"open during segmentation -> {r3.status_code}"


def check_cancel_kills_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    segmentation._proc, state.seg_running = proc, True
    try:
        segmentation.cancel()
        proc.wait(timeout=5)
    finally:
        segmentation._proc, state.seg_running = None, False
        if proc.poll() is None:
            proc.kill()


def _synthetic(vol, spacing=(1.0, 1.0, 1.0)):
    """Put a volume straight into state, as if a scan had been opened."""
    import SimpleITK as sitk
    img = sitk.GetImageFromArray(vol)
    img.SetSpacing(spacing)
    state.raw_volume, state.sitk_image = vol.astype(np.float32), img
    state.current_slice, state.measurements = 0, []


def check_measure_roi_known_spacing():
    vol = np.zeros((1, 100, 100), np.float32)
    vol[0, :, 50:] = 100  # right half bright
    _synthetic(vol, (0.5, 0.25, 1.0))
    assert c.get("/api/status").json()["spacing"] == [0.5, 0.25], "status lacks in-plane spacing"
    r = c.post("/api/measure/roi", headers=JSON, json={"slice": 0, "cx": 25, "cy": 50, "rx": 10, "ry": 10})
    s = r.json()
    assert r.status_code == 200 and s["mean"] == 0 and s["max"] == 0, r.text
    assert abs(s["area_mm2"] - s["pixels"] * 0.125) < 1e-6 and abs(s["area_mm2"] - np.pi * 100 * 0.125) < 2, s
    s = c.post("/api/measure/roi", headers=JSON, json={"slice": 0, "cx": 50, "cy": 50, "rx": 10, "ry": 5}).json()
    assert 40 < s["mean"] < 60 and s["min"] == 0 and s["max"] == 100, s
    r = c.post("/api/measure/roi", headers=JSON, json={"slice": 0, "cx": -500, "cy": 50, "rx": 3, "ry": 3})
    assert r.status_code == 400, f"ROI outside image -> {r.status_code}"


def check_review_summary_and_report():
    vol = np.zeros((4, 20, 20), np.float32)
    _synthetic(vol, (0.5, 0.5, 2.0))  # voxel = 0.5 mL / 1000
    state.seg_mask = np.zeros((4, 20, 20), np.int32)
    state.seg_mask[:2, :10, :10] = 5  # 200 voxels of liver = 0.1 mL
    state.measurements = [{"type": "ruler", "slice": 1, "text": "<b>12.0 mm"}]
    try:
        s = c.get("/api/review/summary").json()
        html = c.get("/api/review/report").text
        saved = Path(__file__).parent / "_report_check.html"
        server._ask_save_path = lambda name: str(saved)
        r = c.post("/api/review/export", headers=JSON)
        written = saved.read_text(encoding="utf-8")
        saved.unlink()
    finally:
        state.seg_mask = None
    assert s["structures"] == [{"id": 5, "name": "Liver", "volume_ml": 0.1}], s["structures"]
    assert s["dims"] == [4, 20, 20] and s["measurements"][0]["slice"] == 1, s
    assert "not for diagnostic use" in html and "data:image/png;base64," in html, "report lacks disclaimer/snapshot"
    assert "&lt;b&gt;12.0 mm" in html, "measurement text not escaped"
    assert r.json()["path"] == str(saved) and "Liver" in written and "0.1 mL" in written, r.text


def check_registration_recovers_shift():
    import SimpleITK as sitk
    from scipy.ndimage import center_of_mass
    import registration
    zz, yy, xx = np.mgrid[:40, :64, :64]
    def blobs(shift):  # three gaussian blobs, so rotation is constrained too
        dz, dy, dx = shift
        return sum(np.exp(-((zz - cz - dz) ** 2 + (yy - cy - dy) ** 2 + (xx - cx - dx) ** 2) / (2 * r * r))
                   for cz, cy, cx, r in ((20, 30, 30, 6), (14, 18, 44, 4), (26, 44, 20, 5))).astype(np.float32)
    fixed = blobs((0, 0, 0)) * 1000
    _synthetic(fixed, (1.0, 1.0, 1.0))
    moving = sitk.GetImageFromArray(50 + blobs((2, -3, 4)) * 300)  # shifted, different intensities
    state.reg_moving, state.reg_moving_meta = moving, {"Modality": "MR"}
    registration.run_registration()
    assert state.reg_error is None, state.reg_error
    reg = state.reg_mri_arr
    got = np.array(center_of_mass(np.clip(reg - 50, 0, None)))  # 50 = moving background
    want = np.array(center_of_mass(fixed))
    assert np.abs(got - want).max() < 1.0, f"registered blobs at {got}, expected {want}"
    state.view_mode = 2
    assert c.get("/api/dicom/slice?i=20").status_code == 200, "blend view does not render"
    r = c.post("/api/register/view", headers=JSON, json={"mode": 3})
    assert r.status_code == 422, f"view mode 3 accepted ({r.status_code})"
    state.reg_mri_arr = state.reg_moving = None
    state.view_mode = 0


def check_path_avoids_bone_wall():
    _, yy, xx = np.mgrid[:40, :80, :80]
    vol = np.where((yy - 40) ** 2 + (xx - 40) ** 2 < 30 ** 2, 40, -1000).astype(np.float32)  # body cylinder
    vol[:, 10:70, 22:26] = 1000  # bone wall on the left (low x) side of the target
    _synthetic(vol, (1.0, 1.0, 2.0))
    state.modality = "CT"
    r = c.post("/api/path/target", headers=JSON, json={"slice": 20, "x": 40, "y": 40})
    assert r.status_code == 200, r.text
    paths = r.json()["paths"]
    assert 1 <= len(paths) <= 5 and r.json()["selected"] == 0, paths
    for p in paths:  # no sampled point of any path lies in the wall
        (ex, ey, ez), (tx, ty, tz) = p["entry_xyz"], p["target_xyz"]
        s = np.linspace(0, 1, 200)
        xs, ys, zs = (np.round(a + (b - a) * s).astype(int) for a, b in ((tx, ex), (ty, ey), (tz, ez)))
        assert not (vol[np.clip(zs, 0, 39), np.clip(ys, 0, 79), np.clip(xs, 0, 79)] > 300).any(), p
    assert paths[0]["entry_xyz"][0] > 40 and paths[0]["length_mm"] < 35, paths[0]
    r = c.post("/api/path/target", headers=JSON, json={"slice": 20, "x": 23, "y": 40})
    assert r.status_code == 400 and "critical" in r.json()["detail"], r.text
    c.post("/api/path/clear", headers=JSON)


def run():
    checks = [v for k, v in globals().items() if k.startswith("check_")]
    failed = 0
    for fn in checks:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"{len(checks) - failed}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    run()
