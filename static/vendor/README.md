# Vendored frontend libraries

The app runs offline, so every frontend dependency is a pinned copy here.

| Library | Version | Licence | Notes |
|---|---|---|---|
| Web Awesome (`webawesome/`) | 3.14.0 | MIT | `dist-cdn` loader, chunks, components, styles, `translations/en.js`. Components autoload from `data-webawesome` base path. |
| Lucide (`lucide/`) | lucide-static 1.58.0 | ISC | Only the icons the page uses. Add an icon: copy `icons/<name>.svg` from the same version. Used through `<wa-icon library="lucide" name="…">`. |
| Three.js (`three.module.js`, `OrbitControls.js`) | — | MIT | 3D view. |
| GSAP (`gsap.min.js`) | — | GreenSock standard licence | View fades. |
| Syncopate (`fonts/`) | — | OFL | Wordmark only. UI text uses the Windows system font (Segoe UI Variable). |
