# Vendored frontend libraries

The app runs offline, so every frontend dependency is a pinned copy here. Update deliberately.

| Path | Package / source | Version | Licence | Notes |
|---|---|---|---|---|
| `webawesome/` | Web Awesome | 3.14.0 | MIT | `dist-cdn` loader, chunks, components, styles, `translations/en.js`. Components autoload from the `data-webawesome` base path. |
| `lucide/` | lucide-static | 1.58.0 | ISC | Only the icons the page uses. Add one by copying `icons/<name>.svg` from the same version. Used through `<wa-icon library="lucide" name="…">`. |
| `three.module.js`, `OrbitControls.js` | three.js | r160 | MIT | 3D view. |
| `gsap.min.js` | GSAP | 3.12.5 | GreenSock standard licence | View fades. |
| `fonts/syncopate-*` | Fontsource (Google Fonts) | — | SIL OFL 1.1 | Wordmark only. UI text uses the Windows system font (Segoe UI Variable). |
| `mediapipe/vision_bundle.js` | `@mediapipe/tasks-vision` `vision_bundle.mjs` (renamed to `.js` so it is served as JavaScript) | 0.10.14 | Apache-2.0 | Gesture camera. |
| `mediapipe/vision_wasm_internal.js`, `.wasm` | `@mediapipe/tasks-vision` `wasm/` (SIMD build only; WebView2 supports SIMD) | 0.10.14 | Apache-2.0 | |
| `mediapipe/hand_landmarker.task` | `storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/` | float16 v1 | Apache-2.0 (MediaPipe model card) | |

The MediaPipe JS/wasm files come from `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/`.
