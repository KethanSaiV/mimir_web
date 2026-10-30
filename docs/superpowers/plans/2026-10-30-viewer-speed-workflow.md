# Viewer speed and workflow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fast slice scrolling and W/L, plus PACS-style zoom, pan, drag-W/L and a slice scrubber.
Spec: `docs/superpowers/specs/2026-10-30-viewer-speed-workflow-design.md`.

**Constraints:** keep the rules from the 2026-10-13 plan (tokens only, no hex outside `:root`, ≥12px fonts,
no `alert()`, reduced motion). Commits: no AI/Claude trailers.

Run checks from `mimir_web/`: `../venv/Scripts/python.exe tests/check_api.py` and `tests/check_ui.py`.

### Task 1: Stateless slice endpoint + fast PNG

- [x] Add `check_slice_params` to `tests/check_api.py`: open CT_small, `GET /api/dicom/slice?i=99&wl=50&ww=300`
      → 200, `image/png`, `state.current_slice == 0`, `state.wl == 50`, `state.ww == 300`; `ww=0` → 422; `wl=nan` → 422.
      Run: FAIL (wl not stored).
- [x] `server.py`: `get_slice(i: int | None = None, wl: float | None = Query(None, allow_inf_nan=False),
      ww: float | None = Query(None, gt=0, allow_inf_nan=False))`; clamp `i` into `state.current_slice`, store wl/ww.
- [x] `render.py`: pass `[cv2.IMWRITE_PNG_COMPRESSION, 0]` to both `imencode` calls.
- [x] Run check_api: all pass. Commit.

### Task 2: Latest-wins rendering in the page

- [x] Add `check_viewer_controls` to `tests/check_ui.py`: `/api/dicom/nav` and `/api/dicom/window` absent from the
      page, `id="sliceSlider"` and `id="viewerHint"` present. Run: FAIL.
- [x] `refreshSliceImage()`: build `/api/dicom/slice?i=&wl=&ww=` from JS state; one in flight, one pending; load via
      `new Image()` then swap `sliceImg.src`; error toast from the loader.
- [x] `navSlice` clamps locally (no `/nav`); `onWindowInput` renders directly (no `/window`, no debounce);
      `applyPreset` tweens the sliders with `onUpdate: onWindowInput`.
- [x] Slice scrubber `#sliceSlider` between Prev/Next, synced in `refreshSliceImage`, max set on load.

### Task 3: PACS mouse + zoom/pan + reset

- [x] `zoom`, `panX`, `panY`, initial wl/ww stored on load; `applyTransform()` sets `sliceImg.style.transform`.
- [x] Wheel: Ctrl → zoom about cursor (1×–8×), else slice. Pointer drag: button 0 → W/L, button 2 → pan,
      pointer capture; `contextmenu` suppressed on the canvas; `dblclick` and `R` → `resetView()`.
- [x] `resetView()` in 2D resets zoom/pan/W/L; `syncViewerChrome` enables Reset when a scan is loaded or in 3D,
      hides hint and scrubber in 3D.
- [x] `#viewerHint` line; hidden after the first drag. Zoom shown in `ovBR` when > 1×.
- [x] Run both check scripts: all pass. Commit.

### Task 4: Manual verification

- [x] Run the app, open a series: wheel and scrubber are smooth, drag-W/L follows the mouse, Ctrl+wheel zooms at the
      cursor, right-drag pans, double-click resets, presets animate, filter and overlay still apply, 3D still works.

**Verified 2026-10-30** in headless Edge over CDP with real input events, against a 120-slice 512² CT phantom
(19/19): 30-event wheel burst → 2 requests, never overlapping; one step ≈ 5–10 ms; Ctrl+wheel zooms the image
(not the page) and keeps the point under the cursor fixed; drag W/L, pan, double-click reset, presets, scrubber,
filter and 3D chrome all behave. Not covered: the real pywebview window and the segmentation overlay (needs Docker).
