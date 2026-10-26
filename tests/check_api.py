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
