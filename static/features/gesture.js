// Gesture camera: MediaPipe HandLandmarker on the webcam (all local, vendored),
// driving the existing 2D viewer: navSlice, zoom/panX/panY + applyTransform.
//   open palm, held 1 s  -> arm / disarm
//   fist, held 1 s       -> lock / unlock (input ignored while locked)
//   index finger up      -> move vertically to scroll slices
//   pinch (one hand)     -> move to pan
//   pinch (both hands)   -> spread / close to zoom
// Camera is off until the user enables it; the stream stops when disabled or hidden.
const $ = id => document.getElementById(id);
const MP = '/vendor/mediapipe/';
const HOLD_MS = 1000, STABLE = 4, SMOOTH = 0.4, SLICE_STEP = 0.03;

const video = $('camVideo'), overlay = $('camOverlay'), btn = $('btnCamera');
let landmarker = null, connections = [], stream = null, running = false, lastTime = -1;
let armed = false, locked = false;
let stable = { name: 'none', count: 0, since: 0, fired: false };
let prev = null;  // smoothed positions from the previous frame, per gesture

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

// One hand's 21 landmarks -> 'pinch' | 'palm' | 'fist' | 'point' | 'other'.
export function classify(h) {
  const size = dist(h[0], h[9]);  // wrist to middle-finger knuckle
  const up = [[8, 6], [12, 10], [16, 14], [20, 18]].map(([tip, pip]) => dist(h[tip], h[0]) > dist(h[pip], h[0]) * 1.15);
  if (dist(h[4], h[8]) < 0.3 * size) return 'pinch';
  if (up.every(Boolean)) return 'palm';
  if (!up.some(Boolean)) return 'fist';
  if (up[0] && !up[1] && !up[2] && !up[3]) return 'point';
  return 'other';
}

// Gesture of the whole frame, plus the point(s) that drive it.
export function frameGesture(hands) {
  const kinds = hands.map(classify);
  if (hands.length === 2 && kinds.every(k => k === 'pinch'))
    return { name: 'zoom', a: mid(hands[0][4], hands[0][8]), b: mid(hands[1][4], hands[1][8]) };
  if (!hands.length) return { name: 'none' };
  const h = hands[0], k = kinds[0];
  if (k === 'pinch') return { name: 'pan', a: mid(h[4], h[8]) };
  if (k === 'point') return { name: 'scroll', a: h[8] };
  return { name: k };
}

const LABELS = { none: 'No hand', other: 'Hand seen', palm: 'Open palm', fist: 'Fist',
                 scroll: 'Point: scroll slices', pan: 'Pinch: pan', zoom: 'Two-hand pinch: zoom' };

export function act(g, now) {
  // Debounce: a gesture counts once seen on STABLE consecutive frames.
  if (g.name === stable.name) stable.count++;
  else stable = { name: g.name, count: 1, since: now, fired: false };
  if (stable.count < STABLE) { prev = null; return; }

  if ((g.name === 'palm' || g.name === 'fist') && !stable.fired && now - stable.since > HOLD_MS) {
    stable.fired = true;  // one toggle per hold
    if (g.name === 'palm') { armed = !armed; locked = false; } else if (armed) locked = !locked;
  }
  const live = armed && !locked && in2D() && ['scroll', 'pan', 'zoom'].includes(g.name);
  if (!live) { prev = null; return; }

  // Exponential smoothing of the driving point(s).
  const s = { name: g.name, a: g.a, b: g.b };
  if (prev && prev.name === g.name) {
    s.a = { x: prev.a.x + SMOOTH * (g.a.x - prev.a.x), y: prev.a.y + SMOOTH * (g.a.y - prev.a.y) };
    if (g.b) s.b = { x: prev.b.x + SMOOTH * (g.b.x - prev.b.x), y: prev.b.y + SMOOTH * (g.b.y - prev.b.y) };
    s.acc = prev.acc;
  } else { prev = { ...s, acc: 0 }; return; }

  const canvas = document.querySelector('.canvas').getBoundingClientRect();
  if (g.name === 'scroll') {
    s.acc += s.a.y - prev.a.y;
    while (Math.abs(s.acc) >= SLICE_STEP) { navSlice(Math.sign(s.acc)); s.acc -= Math.sign(s.acc) * SLICE_STEP; }
  } else if (g.name === 'pan') {
    panX -= (s.a.x - prev.a.x) * canvas.width;   // camera image is mirrored on screen
    panY += (s.a.y - prev.a.y) * canvas.height;
    applyTransform();
  } else if (g.name === 'zoom') {
    const z = Math.max(1, Math.min(8, zoom * dist(s.a, s.b) / Math.max(1e-3, dist(prev.a, prev.b))));
    if (z === 1) panX = panY = 0;
    zoom = z;
    applyTransform();
  }
  prev = s;
}

function drawHands(hands) {
  const ctx = overlay.getContext('2d');
  overlay.width = video.videoWidth; overlay.height = video.videoHeight;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  const css = getComputedStyle(document.documentElement);
  ctx.strokeStyle = css.getPropertyValue('--teal-glow').trim();
  ctx.fillStyle = css.getPropertyValue('--amber').trim();
  ctx.lineWidth = 2;
  for (const h of hands) {
    for (const { start, end } of connections) {
      ctx.beginPath();
      ctx.moveTo(h[start].x * overlay.width, h[start].y * overlay.height);
      ctx.lineTo(h[end].x * overlay.width, h[end].y * overlay.height);
      ctx.stroke();
    }
    for (const p of h) { ctx.beginPath(); ctx.arc(p.x * overlay.width, p.y * overlay.height, 3, 0, 7); ctx.fill(); }
  }
}

function showStatus(gestureName) {
  const on = !!stream;
  $('camStatus').dataset.state = on ? 'active' : 'off';
  $('camStatusText').textContent = on ? 'Camera: on' : 'Camera: off';
  $('gestureStatus').textContent = on ? LABELS[gestureName] || 'Hand seen' : 'Gestures off';
  $('gestureHint').textContent = !on ? 'Using mouse and keyboard'
    : !armed ? 'Disarmed: hold an open palm to arm'
    : locked ? 'Locked: hold a fist to unlock' : 'Armed: point, pinch or two-hand pinch';
  $('lockIndicator').textContent = 'Gestures: ' + (!on ? 'off' : !armed ? 'disarmed' : locked ? 'locked' : 'armed');
  btn.textContent = on ? 'Disable camera' : 'Enable camera';
  btn.setAttribute('aria-pressed', String(on));
}

function loop() {
  if (!running) return;
  requestAnimationFrame(loop);
  if (video.readyState < 2 || video.currentTime === lastTime) return;
  lastTime = video.currentTime;
  const hands = landmarker.detectForVideo(video, performance.now()).landmarks;
  drawHands(hands);
  const g = frameGesture(hands);
  act(g, performance.now());
  showStatus(g.name);
}

async function start() {
  btn.disabled = true;
  try {
    if (!landmarker) {
      $('camPlaceholder').textContent = 'Loading hand tracking…';
      const { HandLandmarker } = await import(MP + 'vision_bundle.js');
      connections = HandLandmarker.HAND_CONNECTIONS;
      const files = { wasmLoaderPath: MP + 'vision_wasm_internal.js', wasmBinaryPath: MP + 'vision_wasm_internal.wasm' };
      const opts = d => ({ baseOptions: { modelAssetPath: MP + 'hand_landmarker.task', delegate: d },
                           runningMode: 'VIDEO', numHands: 2 });
      landmarker = await HandLandmarker.createFromOptions(files, opts('GPU'))
        .catch(() => HandLandmarker.createFromOptions(files, opts('CPU')));
    }
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    video.srcObject = stream;
    await video.play();
    video.hidden = overlay.hidden = false;
    $('camPlaceholder').hidden = true;
    armed = locked = false;
    running = true;
    loop();
  } catch (e) {
    stop();
    $('camPlaceholder').textContent = 'Camera unavailable: ' + (e.message || e.name);
    toast('Could not start the camera: ' + (e.message || e.name), 'error');
  } finally {
    btn.disabled = false;
    showStatus('none');
  }
}

function stop() {
  running = false;
  stream?.getTracks().forEach(t => t.stop());
  stream = null;
  video.srcObject = null;
  video.hidden = overlay.hidden = true;
  $('camPlaceholder').hidden = false;
  $('camPlaceholder').textContent = 'Camera off.';
  armed = locked = false;
  showStatus('none');
}

btn.addEventListener('click', () => (stream ? stop() : start()));
document.addEventListener('visibilitychange', () => { if (document.hidden && stream) stop(); });
