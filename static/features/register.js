// Register: load a second (moving) series, register it onto the open scan on the
// server, then view CT / registered MRI / blend. Uses the page globals:
// api, applyLoadedState, refreshSliceImage, numSlices.
(() => {
  const $ = id => document.getElementById(id);
  const blend = $('regBlendSlider');
  let poll = null;

  function render(s) {
    $('regMoving').textContent = s.moving
      ? `Moving: ${s.moving.Modality} · ${s.moving.Patient} · ${s.moving['Study Date']}`
      : 'No moving series loaded. Choose the folder of a second 3D series of the same patient, for example an MRI.';
    $('btnRegLoad').disabled = s.running;
    $('btnRegRun').disabled = s.running || !s.moving;
    $('btnRegRun').textContent = s.running ? 'Registering…' : 'Run registration';
    $('btnRegCancel').style.display = s.running ? 'flex' : 'none';
    $('regLog').textContent = s.error || s.log[s.log.length - 1] || '';
    $('regLog').style.color = s.error ? 'var(--red)' : '';
    $('regResult').style.display = s.done ? 'block' : 'none';
    document.querySelectorAll('[data-regmode]').forEach(b =>
      b.setAttribute('aria-pressed', String(+b.dataset.regmode === s.view_mode)));
    const pct = Math.round(s.blend * 100);
    blend.value = pct; blend.style.setProperty('--val', pct + '%'); $('regBlendV').textContent = pct + '%';
    blend.disabled = s.view_mode !== 2;
    const m = s.metrics;
    $('regMetrics').textContent = s.done
      ? `Mattes MI ${m.metric} · ${m.iterations} iterations (final level of each stage) · ${m.elapsed_s} s`
      : '';
  }

  let wasRunning = false;
  async function refresh() {
    clearTimeout(poll);
    const s = await api('/api/register/status');
    render(s);
    if (s.running) { wasRunning = true; poll = setTimeout(refresh, 700); }
    else if (wasRunning) { wasRunning = false; if (numSlices > 0) refreshSliceImage(); }  // result opens in blend view
  }

  $('btnRegLoad').addEventListener('click', async () => {
    try { await api('/api/register/load-moving', { method: 'POST', body: '{}' }); } catch { return; }
    refresh();
    if (numSlices > 0) refreshSliceImage();
  });
  $('btnRegRun').addEventListener('click', async () => {
    try { await api('/api/register/run', { method: 'POST', body: '{}' }); } catch { return; }
    refresh();
  });
  $('btnRegCancel').addEventListener('click', () =>
    api('/api/register/cancel', { method: 'POST', body: '{}' }).catch(() => {}));

  async function setView(body) {
    await api('/api/register/view', { method: 'POST', body: JSON.stringify(body) });
    refresh();
    refreshSliceImage();
  }
  document.querySelectorAll('[data-regmode]').forEach(b =>
    b.addEventListener('click', () => setView({ mode: +b.dataset.regmode }).catch(() => {})));
  let debounce = null;
  blend.addEventListener('input', () => {
    $('regBlendV').textContent = blend.value + '%';
    blend.style.setProperty('--val', blend.value + '%');
    clearTimeout(debounce);
    debounce = setTimeout(() => setView({ blend: blend.value / 100 }).catch(() => {}), 100);
  });

  // A new scan drops the previous registration (server side); show that.
  const baseApplyLoadedState = applyLoadedState;
  applyLoadedState = function (data) {
    baseApplyLoadedState(data);
    refresh();
  };
})();
