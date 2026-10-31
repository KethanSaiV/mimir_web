// Path Plan: click a target on the 2D slice, the server ranks straight needle
// paths from the skin; the selected one is drawn on the slice (projection) and
// in the 3D view. Uses the page globals: api, toast, applyLoadedState,
// sliceImg, currentSlice, in2D, and the 'mimir:mesh' event from the 3D module.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const $ = id => document.getElementById(id);
  const canvas = document.querySelector('.canvas');
  const card = $('cardPath');
  const pick = $('btnPathPick');
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'measure-layer path-layer');
  svg.setAttribute('aria-hidden', 'true');
  canvas.appendChild(svg);
  let st = { paths: [], selected: null, target: null, mesh_center: null };
  let picking = false, mesh = null, three = null, line = null;

  const selected = () => st.selected == null ? null : st.paths[st.selected];

  function toScreen(x, y) {
    const r = sliceImg.getBoundingClientRect(), c = svg.getBoundingClientRect();
    return [r.left - c.left + x / sliceImg.naturalWidth * r.width, r.top - c.top + y / sliceImg.naturalHeight * r.height];
  }
  function el(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    return svg.appendChild(n);
  }

  function draw() {
    svg.replaceChildren();
    const p = selected();
    if (!p || !in2D() || !sliceImg.naturalWidth) return;
    const [ex, ey, ez] = p.entry_xyz, [tx, ty, tz] = p.target_xyz;
    const e = toScreen(ex, ey), t = toScreen(tx, ty);
    el('line', { x1: e[0], y1: e[1], x2: t[0], y2: t[1], class: 'proj' });  // projection onto this slice
    el('rect', { x: t[0] - 5, y: t[1] - 5, width: 10, height: 10, class: tz === currentSlice ? 'here' : '' });
    el('circle', { cx: e[0], cy: e[1], r: 4, class: Math.round(ez) === currentSlice ? 'here' : '' });
    const s = (currentSlice - tz) / (ez - tz);  // where the needle crosses the displayed slice
    if (ez !== tz && s > 0 && s < 1) {
      const q = toScreen(tx + s * (ex - tx), ty + s * (ey - ty));
      el('circle', { cx: q[0], cy: q[1], r: 5, class: 'here' });
    }
  }

  let lastKey = '';
  (function tick() {
    requestAnimationFrame(tick);
    if (picking && card.style.display === 'none') setPicking(false);  // left the Path tab
    const r = sliceImg.getBoundingClientRect();
    const key = [currentSlice, r.left, r.top, r.width, r.height, in2D(), sliceImg.naturalWidth, st.selected].join();
    if (key !== lastKey) { lastKey = key; draw(); }
  })();

  function draw3D() {
    if (line) { line.parent?.remove(line); line.geometry.dispose(); line = null; }
    const p = selected();
    if (!p || !mesh || !st.mesh_center) return;
    const c = st.mesh_center, pts = [p.entry_mm, p.target_mm].map(v => new three.Vector3(v[0] - c[0], v[1] - c[1], v[2] - c[2]));
    const colour = getComputedStyle(document.documentElement).getPropertyValue('--amber').trim();
    line = new three.Line(new three.BufferGeometry().setFromPoints(pts),
                          new three.LineBasicMaterial({ color: colour, depthTest: false, transparent: true }));
    line.renderOrder = 10;  // drawn after the (transparent) mesh, so it shows through the surface
    mesh.add(line);         // inherits the mesh's centring rotation and scale
  }
  window.addEventListener('mimir:mesh', async e => {
    ({ mesh, THREE: three } = e.detail);
    st = await api('/api/path/status');
    draw3D();
  });

  function render(s) {
    st = s;
    $('pathList').replaceChildren(...s.paths.map((p, i) => {
      const b = document.createElement('button');
      b.className = 'feature-row-main';
      b.setAttribute('aria-pressed', String(i === s.selected));
      b.textContent = `#${i + 1} · ${p.length_mm} mm · clearance ${p.clearance_mm} mm`;
      b.addEventListener('click', async () => render(await api('/api/path/select',
        { method: 'POST', body: JSON.stringify({ index: i }) })));
      return b;
    }));
    $('pathNote').textContent = s.target
      ? `Target at x ${s.target[0]}, y ${s.target[1]}, slice ${s.target[2] + 1}. Square: target, dot: skin entry, ring: where the needle crosses this slice.`
      : 'Pick target, then click the lesion on the image. Paths avoid bone and, after segmentation, organs other than the target one.';
    $('btnPathClear').disabled = !s.target;
    draw();
    draw3D();
  }

  function setPicking(on) {
    picking = on;
    pick.setAttribute('aria-pressed', String(on));
    canvas.classList.toggle('measuring', on);
  }
  pick.addEventListener('click', () => setPicking(!picking));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && picking) setPicking(false); });
  $('btnPathClear').addEventListener('click', async () => render(await api('/api/path/clear', { method: 'POST', body: '{}' })));

  // Capture phase: while picking, a left click sets the target instead of window/level.
  canvas.addEventListener('pointerdown', async e => {
    if (!picking || e.button !== 0 || !in2D()) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    const r = sliceImg.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * sliceImg.naturalWidth, y = (e.clientY - r.top) / r.height * sliceImg.naturalHeight;
    setPicking(false);
    $('pathNote').textContent = 'Planning…';
    try {
      render(await api('/api/path/target', { method: 'POST', body: JSON.stringify({ slice: currentSlice, x, y }) }));
    } catch { render(st); }
  }, true);

  const baseApplyLoadedState = applyLoadedState;
  applyLoadedState = function (data) {
    baseApplyLoadedState(data);
    setPicking(false);
    api('/api/path/status').then(render);
  };
})();
