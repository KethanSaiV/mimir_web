// Measure tools: Ruler, Angle and Ellipse ROI on an SVG layer over the 2D slice.
// Image pixel coordinates are the source of truth; screen positions are derived
// from #sliceImg's on-screen box, so pan/zoom/resize need no extra wiring.
// Uses the page globals: api, toast, applyLoadedState, sliceImg, currentSlice,
// refreshSliceImage, in2D.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const canvas = document.querySelector('.canvas');
  const card = document.getElementById('cardMeasure');
  const list = document.getElementById('measureList');
  const hint = document.getElementById('measureHint');
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'measure-layer');
  svg.setAttribute('aria-hidden', 'true');
  canvas.appendChild(svg);

  const HINTS = {
    ruler: 'Drag across the image to measure a distance.',
    angle: 'Click three points: one end, the vertex, the other end.',
    ellipse: 'Drag a box to place an elliptical ROI.',
  };
  const NAMES = { ruler: 'Ruler', angle: 'Angle', ellipse: 'ROI' };
  let tool = null, draft = null, items = [], spacing = [1, 1], unit = ' HU';

  function toImage(e) {
    const r = sliceImg.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width * sliceImg.naturalWidth,
            (e.clientY - r.top) / r.height * sliceImg.naturalHeight];
  }
  function toScreen([x, y]) {
    const r = sliceImg.getBoundingClientRect(), c = svg.getBoundingClientRect();
    return [r.left - c.left + x / sliceImg.naturalWidth * r.width,
            r.top - c.top + y / sliceImg.naturalHeight * r.height];
  }
  const vec = (a, b) => [(b[0] - a[0]) * spacing[0], (b[1] - a[1]) * spacing[1]];  // mm
  const lengthMm = (a, b) => Math.hypot(...vec(a, b));
  function angleDeg(a, b, c) {
    const u = vec(b, a), v = vec(b, c);
    const cos = (u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v));
    return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
  }

  function el(tag, attrs, text) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text) n.textContent = text;
    return svg.appendChild(n);
  }

  function draw() {
    svg.replaceChildren();
    if (!in2D() || !sliceImg.naturalWidth) return;
    const shown = items.filter(m => m.slice === currentSlice);
    if (draft) shown.push(draft);
    for (const m of shown) {
      const p = m.pts.map(toScreen);
      if (m.type === 'ellipse') {
        const [a, b] = p;
        el('ellipse', { cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2,
                        rx: Math.abs(b[0] - a[0]) / 2, ry: Math.abs(b[1] - a[1]) / 2 });
      } else {
        el('polyline', { points: p.map(q => q.join(',')).join(' ') });
        p.forEach(q => el('circle', { cx: q[0], cy: q[1], r: 3 }));
      }
      const label = m.text || liveText(m);
      const q = p[p.length - 1];
      if (label) el('text', { x: q[0] + 8, y: q[1] - 8 }, label);
    }
  }

  function liveText(m) {
    if (m.type === 'ruler') return lengthMm(...m.pts).toFixed(1) + ' mm';
    if (m.type === 'angle' && m.pts.length === 3) return angleDeg(...m.pts).toFixed(1) + '°';
    return '';
  }

  // Redraw when anything that moves the image changes (pan, zoom, slice, view, resize).
  let lastKey = '';
  (function tick() {
    requestAnimationFrame(tick);
    if (tool && card.style.display === 'none') setTool(null);  // left the Measure tab
    if (draft && draft.slice !== currentSlice) draft = null;
    const r = sliceImg.getBoundingClientRect();
    const key = [currentSlice, r.left, r.top, r.width, r.height, in2D(), sliceImg.naturalWidth].join();
    if (key !== lastKey) { lastKey = key; draw(); }
  })();

  function setTool(t) {
    tool = t; draft = null;
    card.querySelectorAll('[data-tool]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tool === t)));
    canvas.classList.toggle('measuring', !!t);
    hint.textContent = t ? HINTS[t] + ' Esc returns to window/level.' : 'Pick a tool, then draw on the image.';
    draw();
  }
  card.querySelectorAll('[data-tool]').forEach(b =>
    b.addEventListener('click', () => setTool(tool === b.dataset.tool ? null : b.dataset.tool)));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && tool) setTool(null); });

  // Capture phase: while a tool is active, left-drag draws instead of window/level.
  canvas.addEventListener('pointerdown', e => {
    if (!tool || e.button !== 0 || !in2D()) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    const p = toImage(e);
    if (tool !== 'angle') {
      draft = { type: tool, slice: currentSlice, pts: [p, p] };
      canvas.setPointerCapture(e.pointerId);
    } else if (!draft) {
      draft = { type: 'angle', slice: currentSlice, pts: [p, p] };
    } else {
      draft.pts[draft.pts.length - 1] = p;
      if (draft.pts.length === 3) finish(); else draft.pts.push(p);
    }
    draw();
  }, true);
  canvas.addEventListener('pointermove', e => {
    if (!draft) return;
    draft.pts[draft.pts.length - 1] = toImage(e);
    draw();
  });
  canvas.addEventListener('pointerup', () => {
    if (draft && draft.type !== 'angle') finish();
  });
  // Quick angle clicks must not trigger the double-click view reset.
  canvas.addEventListener('dblclick', e => { if (tool) e.stopImmediatePropagation(); }, true);

  async function finish() {
    const m = draft;
    draft = null;
    const [a, b] = m.pts;
    if (m.type !== 'angle' && Math.hypot(b[0] - a[0], b[1] - a[1]) < 2) { draw(); return; }  // a click, not a drag
    if (m.type === 'ellipse') {
      try {
        m.stats = await api('/api/measure/roi', { method: 'POST', body: JSON.stringify({
          slice: m.slice, cx: (a[0] + b[0]) / 2, cy: (a[1] + b[1]) / 2,
          rx: Math.max(0.5, Math.abs(b[0] - a[0]) / 2), ry: Math.max(0.5, Math.abs(b[1] - a[1]) / 2) }) });
      } catch { draw(); return; }
      const s = m.stats;
      m.text = `${s.mean.toFixed(0)} ± ${s.std.toFixed(0)}${unit} · ${s.area_mm2.toFixed(0)} mm²`;
    } else {
      m.text = liveText(m);
    }
    items.push(m);
    save();
  }

  function save() {
    api('/api/measure/list', { method: 'POST', body: JSON.stringify({ items }) }).catch(() => {});
    renderList();
    draw();
  }

  function renderList() {
    list.replaceChildren(...items.map((m, i) => {
      const row = document.createElement('div');
      row.className = 'feature-row';
      const go = document.createElement('button');
      go.className = 'feature-row-main';
      go.textContent = `Slice ${m.slice + 1} · ${NAMES[m.type]} · ${m.text}`;
      go.title = m.stats ? `min ${m.stats.min.toFixed(0)} · max ${m.stats.max.toFixed(0)} · ${m.stats.pixels} px` : 'Go to slice';
      go.addEventListener('click', () => { currentSlice = m.slice; refreshSliceImage(); });
      const del = document.createElement('button');
      del.className = 'btn sm';
      del.textContent = 'Delete';
      del.setAttribute('aria-label', `Delete ${NAMES[m.type]} on slice ${m.slice + 1}`);
      del.addEventListener('click', () => { items.splice(i, 1); save(); });
      row.append(go, del);
      return row;
    }));
    if (!items.length) list.textContent = '';
  }

  // A newly opened (or resumed) scan brings its own spacing and measurements.
  const baseApplyLoadedState = applyLoadedState;
  applyLoadedState = function (data) {
    baseApplyLoadedState(data);
    setTool(null);
    Promise.all([api('/api/status'), api('/api/measure/list')]).then(([s, l]) => {
      spacing = s.spacing;
      unit = (s.modality || '').toUpperCase() === 'CT' ? ' HU' : '';
      items = l.items;
      renderList();
      draw();
    });
  };
})();
