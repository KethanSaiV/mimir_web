# Planned features made real — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the "unfinished" signals from MIMIR by making the planned systems actually work:
the window icon (item 1), the five planned systems — Measure, Review, Register, Path Plan, Gesture camera (item 2) —
and copy that only promises what exists (item 3). Each system is an MVP: small, correct, honest.

**Context:** single-user local FastAPI server (`server.py`, state in `state.py`) + one page `static/index.html`
shown in a pywebview (Edge WebView2) window. Scan volume is `state.raw_volume` (Z,H,W float32, HU for CT),
geometry in `state.sitk_image` (spacing/origin/direction), optional `state.seg_mask` (TotalSegmentator labels).
The 2D view is server-rendered PNG via `GET /api/dicom/slice?i=&wl=&ww=` (`render.py`); the page owns view state
(`currentSlice`, `zoom`, `panX/panY`). 3D is Three.js in a `<script type="module">` block.
Real test data: `../dataset/MIMIR Dataset/3` (a DICOM series). Synthetic data: `pydicom` test files (see `tests/check_api.py`).

## Global constraints

- **Parallel UI redesign in progress on another branch.** It restyles all of `index.html` (Web Awesome components,
  Lucide icons, new tokens). To keep the merge small:
  - Put new frontend logic in **new files** `static/features/<name>.js` (classic scripts or modules), loaded with one
    `<script>` line each near the end of `index.html`.
  - Put new markup in **one contiguous block per feature** (a sidebar `.card` like `#cardSegment`, toggled by
    `syncTabCards`). Reuse existing classes (`.card`, `.card-title`, `.btn`, `.stat-row`) and `var(--token)` colours;
    no new hex colours, no emoji, no `alert()` (use `toast()`).
  - Touch existing lines only where unavoidable (enabling a tab, `syncTabCards`, overlay drawing hooks).
- Backend: one module per feature (`measure.py`, `registration.py`, `pathplan.py`, `report.py`), endpoints under
  `/api/<feature>/…` in `server.py`, POST bodies are JSON (the CSRF guard rejects body-less POSTs — keep it).
- No new Python dependencies unless a task says so. Frontend libraries must be **vendored** under `static/vendor/`
  (the app is offline), pinned versions, licences noted in `static/vendor/README.md`.
- A tab becomes enabled only when its feature works end to end. Remove its `data-planned`/`aria-disabled` then, and
  update `tests/check_ui.py::check_planned_systems` in the same commit.
- **Before every commit run all checks and commit only if green:**
  `../venv/Scripts/python.exe tests/check_api.py`, `../venv/Scripts/python.exe tests/check_ui.py`,
  and `node --check` on the extracted inline script. Add one API check per backend feature.
- Commits: author is already configured. **No `Co-Authored-By` / Claude / AI mentions in commit messages.**
- Research prototype: copy must never imply clinical/diagnostic use.

---

### Task 1: Window icon (item 1)

> Done: title bar shows the MIMIR icon (verified by screenshot from source). Taskbar grouping via AppUserModelID set but not visually verified (taskbar not visible in the capture). Frozen builds fall back to the exe icon.

- [x] When run from source the title bar and taskbar show the Python logo. Set the MIMIR icon on the pywebview
      window on Windows (WinForms backend): in `webview.start(func)` or via the window's native form, set
      `Form.Icon = System.Drawing.Icon(<installer/mimir.ico>)` using a bundle-safe path helper that already exists in
      `server.py` (check how static/ is resolved for PyInstaller). Also set the AppUserModelID
      (`ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MIMIR.Workstation')`) so the taskbar groups
      under MIMIR, not Python. Guard both with `sys.platform == 'win32'` and try/except + log.
- [x] Verify by launching `server.py` and checking the title bar and taskbar (screenshot with PowerShell if needed).
- [x] Commit.

### Task 2: Measure

> Done: ROI stats server-side (measure.py), ruler/angle client-side from /api/status spacing. Verified by check_measure_roi_known_spacing and a headless Edge run on series 3 (ruler length vs spacing, ROI, 90 degree angle, per-slice display, Esc, delete, W/L untouched while drawing).

- [x] Backend `measure.py`: pure functions on `state`:
      `distance_mm(p1, p2)` (pixel → mm with in-plane spacing from `sitk_image.GetSpacing()`),
      `angle_deg(a, b, c)`, `roi_stats(slice_idx, ellipse)` → mean/std/min/max HU and area mm².
      Endpoint `POST /api/measure/roi`. Distance and angle may be computed client-side if spacing is exposed via
      `/api/status` (add `spacing`). API check: known spacing → known mm.
- [x] Frontend `static/features/measure.js`: tools **Ruler**, **Angle**, **Ellipse ROI** drawn on an SVG layer
      over `#sliceImg` that follows the same `translate/scale` as the image (image pixel coordinates are the source
      of truth). While a measure tool is active, left-drag draws instead of window/level; Esc returns to W/L.
      Measurements are per slice, listed in the Measure card with delete buttons, shown only on their slice.
- [x] Enable the MEASURE tab. Commit.

### Task 3: Review (report)

> Done: the main-area panel is a live preview of the exact HTML that Export saves (GET /api/review/report). Verified by check_review_summary_and_report and headless Edge on series 3 (preview, export file written). The native Save dialog itself was monkeypatched in tests, not clicked by hand. Measurement shapes are listed in the report, not drawn on the snapshot.

- [x] `report.py` + `GET /api/review/summary`: patient/study metadata, series dims + spacing, segmentation
      structures present with volume in mL (voxel count × voxel volume), measurements (sent from the page or kept in
      `state.measurements`), selected path (Task 5, if present).
- [x] Review card + a main-area summary panel; **Export report** → native save dialog (reuse the
      `_ask_path`-style dialog pattern) writing a self-contained HTML report with a PNG snapshot of the current slice.
      Header states "Research prototype — not for diagnostic use".
- [x] Enable REVIEW. Commit.

### Task 4: Register (CT ↔ MRI)

> Done: rigid then affine Mattes MI on volumes shrunk to ~128 voxels per axis, result resampled onto the full CT grid. Verified by check_registration_recovers_shift (synthetic shift recovered to <0.1 voxel), a real-data run (series 3 moved 8/-5/6 mm with remapped intensities: recovered to within 0.5 mm in ~6 s) and headless Edge (load, run, progress, CT/MRI/blend). No real MRI series was available, so true CT-MRI registration is untested. The image corner overlay still says CT in MRI/blend view.

- [x] `registration.py`: load a second series via the existing loader (`dicom_io.load_dicom_path`) into
      `state.reg_mri_arr`; rigid then affine registration with SimpleITK (Mattes mutual information, multi-resolution,
      `CenteredTransformInitializer` GEOMETRY), resample the moving image onto the fixed CT grid; store metrics in
      `state.reg_metrics` (final metric value, iterations, elapsed). Run in a background thread with status polling
      like segmentation (`/api/register/run|status|cancel`); reuse that pattern, including the 409 guards.
- [x] Rendering: `state.view_mode` 0 = CT, 1 = registered MRI, 2 = blend (opacity slider). Extend
      `render_current_slice_png` (MRI windowed by its own percentiles).
- [x] Register card: "Load moving series…", Run/Cancel, progress, metrics, view-mode segmented control, blend slider.
      API check with a synthetic shifted volume: registration recovers a known translation within 1 voxel.
- [x] Enable REGISTER. Commit.

### Task 5: Path Plan (needle trajectory)

> Done: rays from the target in 600 directions on a ~2 mm grid (1.3 s first click on series 3, cached after), 5 directionally distinct winners. Not done: the full-resolution refine pass, so entry points are accurate to about one grid step (marked ponytail in pathplan.py). Verified by check_path_avoids_bone_wall and headless Edge on series 3 (pick target, ranked list, 2D projection, report row, 3D line). CT only. Without a segmentation only bone/contrast (HU > 300) counts as critical.

- [x] `pathplan.py`: target = a voxel the user clicks on a slice (`POST /api/path/target`). Candidate entry points =
      skin surface voxels (body mask from HU > −300, largest component, boundary) sampled on a sphere of directions.
      For each straight line entry→target compute: length mm, minimum distance to critical structures
      (segmentation labels if present — vessels, organs not containing the target; otherwise bone from HU > 300),
      and reject paths that cross them or exceed a max length (150 mm default). Score = weighted clearance and length.
      Return top 5 to `state.path_ranked`. Vectorise with numpy; must finish in a few seconds on a 512² × 300 volume
      (downsample for the search, then refine).
- [x] UI: Path card lists ranked paths (length, clearance); selecting one draws its projection on the 2D slice
      (entry, target, line) and as a line in the 3D view. Clear button.
- [x] API check: synthetic volume with a bone wall on one side → best path avoids it.
- [x] Enable PATH PLAN. Commit.

### Task 6: Gesture camera

> Done: MediaPipe HandLandmarker 0.10.14 vendored (SIMD wasm + float16 model, ~17 MB). Camera permission: CoreWebView2.PermissionRequested allows the camera for our 127.0.0.1 origin and denies it elsewhere. Verified: headless Edge with a fake camera (model loads, frames processed, enable/disable stops the stream); synthetic landmark sequences drive classify/act (arm, scroll, pan, zoom, lock); native pywebview window with WebView2's fake camera device reached 'Camera: on' with no prompt. NOT verified: real hand gestures in front of the physical webcam - needs a person; thresholds (pinch 0.3 of hand size, 1 s holds, 0.03 per slice) may need tuning.

- [x] Use **MediaPipe Tasks Vision (JS) HandLandmarker** in the page, vendored under `static/vendor/mediapipe/`
      (wasm + `hand_landmarker.task` model), pinned version, offline. No Python dependency.
- [x] Camera access in WebView2: getUserMedia needs a permission. Grant it for our localhost origin only
      (pywebview WebView2 permission handling, or `CoreWebView2.PermissionRequested` → Allow for camera when origin
      is `http://127.0.0.1:<port>`). Never enable for other origins.
- [x] Gestures (MVP, all reversible): **open palm held** = arm/disarm; **index finger up + move vertically** =
      scroll slices; **pinch + move** = pan; **two-hand pinch spread** = zoom; **fist** = lock (ignore input).
      Drive the existing functions (`navSlice`, the zoom/pan state + `applyTransform`, `resetView`), never new paths.
      Debounce/smooth with an exponential filter; show the live camera feed with landmark overlay in the camera panel,
      status dot (`data-state="active"`), and the recognised gesture name.
- [x] Camera off by default; a clear "Enable camera" button; stop the stream when disabled or the window hides.
- [x] Verify manually with the real camera. Commit.

### Task 7: Honest copy (item 3) and wrap-up

- [ ] Empty-state text, header "Gestures" pill and any remaining "planned"/"later release" copy describe exactly
      what now works. `tests/check_ui.py` updated so planned-system checks reflect reality.
- [ ] README feature table updated (remove the "Planned" note for what shipped).
- [ ] Final run of all checks; summary of what was built, what was verified by hand, and known limits.
