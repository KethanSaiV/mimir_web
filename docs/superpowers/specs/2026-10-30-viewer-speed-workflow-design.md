# Viewer speed and workflow — design

Sub-project 1 of the UI/UX pass (then: long-task feedback, polish, first run).

## Problem

Every slice step costs two round trips (`POST /api/dicom/nav`, then `GET /api/dicom/slice`), and nothing throttles them:
a wheel spin queues dozens of server renders. W/L changes do the same via `POST /api/dicom/window`. There is no
2D zoom or pan, no drag-to-window, and no way to jump to a slice.

## Decision

Keep server-side rendering (one render path, filters and overlay unchanged) and stop the waste (approach A).
Client-side windowing (approach B) is the upgrade if drag-W/L still feels slow after this.

## Server

- `GET /api/dicom/slice?i=&wl=&ww=` renders exactly that view. All params optional; `i` is clamped to the volume,
  `ww` must be > 0, non-finite values give 422. Given values are written to `state` so `/api/status` (page refresh
  resume) stays correct.
- `render.py` encodes PNG with `IMWRITE_PNG_COMPRESSION=1` (lossless, much faster than the default 3).
- `/api/dicom/nav` and `/api/dicom/window` stay; the frontend stops using them.

## Frontend

- The browser owns the view: `currentSlice`, the WL/WW sliders, `zoom`, `panX/panY`.
- `refreshSliceImage()` becomes latest-wins: at most one request in flight; anything asked for meanwhile collapses
  into one follow-up request for the newest view. The image loads off-screen and swaps in when ready (no blank flash).
  Corner annotations and sliders update immediately.
- PACS mouse mapping on the 2D image: wheel = slice, Ctrl+wheel = zoom about the cursor (1×–8×), left-drag = W/L
  (horizontal = width, vertical = level), right-drag = pan (no context menu), double-click or `R` = reset zoom, pan
  and W/L to the scan's initial values. Reset View works in 2D too.
- Zoom/pan is a CSS `transform` on the image: no server calls.
- A slice scrubber (range input) sits between Prev and Next. ↑/↓/PgUp/PgDn keep working.
- One hint line lists the mouse controls; it hides after the first drag.
- Bottom-right annotation shows the zoom when above 1×. Window presets animate through the same render path.

## Testing

- `tests/check_api.py`: slice params return a PNG, clamp `i`, store wl/ww; `ww=0` and `wl=nan` give 422.
- `tests/check_ui.py`: scrubber and hint exist; the page no longer calls `/api/dicom/nav` or `/api/dicom/window`.
- By hand in the app: wheel speed, drag-W/L smoothness, zoom/pan/reset, filters and overlay still render.

## Out of scope

Client-side caching, measurement tools, the other three sub-projects.
