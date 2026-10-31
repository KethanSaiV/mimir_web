// Review: on the Review tab the main area shows the report preview (the same
// server-rendered HTML that "Export report" saves). Uses the page globals:
// api, toast, syncTabCards, numSlices.
(() => {
  const canvas = document.querySelector('.canvas');
  const panel = document.createElement('iframe');
  panel.className = 'review-panel';
  panel.title = 'Report preview';
  panel.hidden = true;
  canvas.appendChild(panel);

  const refresh = () => { panel.src = '/api/review/report?t=' + Date.now(); };

  const baseSyncTabCards = syncTabCards;
  syncTabCards = function (activeBtnId) {
    baseSyncTabCards(activeBtnId);
    panel.hidden = activeBtnId !== 'tabReview' || numSlices === 0;
    if (!panel.hidden) refresh();
  };

  document.getElementById('btnRefreshReport').addEventListener('click', refresh);
  document.getElementById('btnExportReport').addEventListener('click', async e => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const r = await api('/api/review/export', { method: 'POST', body: '{}' });
      if (!r.cancelled) toast('Report saved to ' + r.path);
    } catch { /* api() already showed the error */ }
    finally { btn.disabled = false; }
  });
})();
