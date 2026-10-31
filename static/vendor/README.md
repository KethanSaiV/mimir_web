# Vendored frontend files

Bundled so the app works offline. Pinned; update deliberately.

| Path | Package / source | Version | Licence |
|---|---|---|---|
| `three.module.js`, `OrbitControls.js` | three.js | r160 | MIT |
| `gsap.min.js` | GSAP | 3.12.5 | GreenSock standard licence |
| `fonts/rajdhani-*`, `fonts/syncopate-*` | Fontsource (Google Fonts) | — | SIL OFL 1.1 |
| `mediapipe/vision_bundle.js` | `@mediapipe/tasks-vision` `vision_bundle.mjs` (renamed to `.js` so it is served as JavaScript) | 0.10.14 | Apache-2.0 |
| `mediapipe/vision_wasm_internal.js`, `.wasm` | `@mediapipe/tasks-vision` `wasm/` (SIMD build only; WebView2 supports SIMD) | 0.10.14 | Apache-2.0 |
| `mediapipe/hand_landmarker.task` | `storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/` | float16 v1 | Apache-2.0 (MediaPipe model card) |

The MediaPipe JS/wasm files come from `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/`.
