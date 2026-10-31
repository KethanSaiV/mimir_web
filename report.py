"""
report.py
MIMIR — Gesture-Guided Surgical Intelligence

Review summary of the loaded scan (metadata, geometry, segmented structure
volumes, measurements, selected needle path) and a self-contained HTML
report built from it, with the current slice embedded as a PNG.
"""

from __future__ import annotations
import base64
import datetime
from html import escape

import numpy as np

from state import state

TYPE_NAMES = {"ruler": "Distance", "angle": "Angle", "ellipse": "ROI"}


def summary() -> dict:
    sx, sy, sz = state.sitk_image.GetSpacing() if state.sitk_image is not None else (1.0, 1.0, 1.0)
    structures = []
    if state.seg_mask is not None:
        from segmentation import ORGAN_COLOURS
        counts = np.bincount(state.seg_mask.ravel())
        voxel_ml = sx * sy * sz / 1000.0
        for lid in np.nonzero(counts[1:])[0] + 1:  # 0 is background
            name = ORGAN_COLOURS.get(int(lid), (f"Label {lid}",))[0]
            structures.append({"id": int(lid), "name": name, "volume_ml": round(float(counts[lid] * voxel_ml), 1)})
    path = None
    if state.selected_path_idx is not None and state.selected_path_idx < len(state.path_ranked):
        path = state.path_ranked[state.selected_path_idx]
    return {
        "meta": state.metadata,
        "modality": state.modality,
        "dims": list(state.raw_volume.shape),  # slices, rows, columns
        "spacing": [sx, sy, sz],              # mm, x/y/z
        "structures": structures,
        "measurements": state.measurements,
        "path": path,
    }


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in pairs)


def report_html(s: dict, slice_png: bytes) -> str:
    """One self-contained HTML file (inline CSS, base64 image)."""
    m = s["meta"]
    z, h, w = s["dims"]
    study = _rows([("Patient", m.get("Patient", "N/A")), ("Modality", s["modality"]),
                   ("Study date", m.get("Study Date", "N/A")), ("Institution", m.get("Institution", "N/A")),
                   ("Dimensions", f"{w} × {h} × {z} voxels"),
                   ("Voxel size", " × ".join(f"{v:.3g}" for v in s["spacing"]) + " mm")])
    structures = (_rows((x["name"], f'{x["volume_ml"]} mL') for x in s["structures"])
                  or "<tr><td>No segmentation run.</td></tr>")
    meas = (_rows((f'Slice {x.get("slice", 0) + 1} · {TYPE_NAMES.get(x.get("type"), x.get("type"))}', x.get("text", ""))
                  for x in s["measurements"]) or "<tr><td>No measurements.</td></tr>")
    p = s["path"]
    at = lambda v: f"x {v[0]:.0f}, y {v[1]:.0f}, slice {v[2] + 1:.0f}"
    path = (_rows([("Entry", at(p["entry_xyz"])), ("Target", at(p["target_xyz"])),
                   ("Length", f'{p["length_mm"]} mm'), ("Clearance", f'{p["clearance_mm"]} mm')])
            if p else "<tr><td>No path selected.</td></tr>")
    img = base64.b64encode(slice_png).decode()
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>MIMIR report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;color:#1d2420;background:#ffffff;max-width:860px;margin:24px auto;padding:0 20px;}}
.warn{{border:2px solid #b3261e;color:#b3261e;padding:10px 14px;font-weight:700;margin:12px 0 20px;}}
h1{{margin:0;font-size:24px;}} h2{{font-size:16px;margin:24px 0 8px;border-bottom:1px solid #c9d1cc;padding-bottom:4px;}}
table{{border-collapse:collapse;width:100%;font-size:14px;}} th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid #e3e8e5;}}
th{{width:45%;font-weight:600;}} img{{max-width:100%;background:#000000;}} small{{color:#5c6660;}}
</style></head><body>
<h1>MIMIR scan report</h1><small>Generated {when}</small>
<div class="warn">Research prototype — not for diagnostic use.</div>
<h2>Study</h2><table>{study}</table>
<h2>Current slice</h2><img alt="Current slice" src="data:image/png;base64,{img}">
<h2>Segmented structures</h2><table>{structures}</table>
<h2>Measurements</h2><table>{meas}</table>
<h2>Needle path</h2><table>{path}</table>
</body></html>"""
