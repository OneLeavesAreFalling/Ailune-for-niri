# Lessons learned

These are the practical lessons from the first Ailune vertical slice. They are
written for the next contributor (and for future me).

## 1. Validate Wayland windowing before anything else

The plan was right: window positioning/stacking was the highest technical risk.
Niri does not let an XDG toplevel choose its position; X11 patterns do not transfer.
The working solution was a GTK4 layer-shell overlay, not a floating Qt window. Spend
the first day on the smallest possible window experiment before building UI around
assumptions.

## 2. Link order matters for gtk4-layer-shell with PyGObject

PyGObject loads `libwayland-client` early, so `gtk4-layer-shell` initialized too
late and printed “GtkWindow is not a layer surface.” Setting
`LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` fixed it. The pet launcher now detects
the library and re-execs automatically. If you see “Failed to initialize layer
surface”, check this before debugging compositor support.

## 3. Transparency needs three separate things

Transparency only worked when all of these were true:

1. GTK window CSS is transparent.
2. `WebKit.WebView.set_background_color(transparent)`.
3. The HTML page's `html, body` background is transparent.

Missing any one leaves a dark or white rectangle. Do not trust a single
`set_opacity(0)` call; it affects input and children too.

## 4. Full-output overlay + input region beats moving a small surface

The better pattern is a fixed full-output layer surface, a moving canvas inside it,
and `Gdk.Surface.set_input_region` for click-through. Moving a layer surface while
dragging causes feedback between pointer position and surface position. The surface
should stay still; only the character's DOM/canvas position changes.

## 5. A clipped input region is not optional

A full-screen overlay that captures the whole output makes the desktop unusable.
Input regions were the difference between a demo and a usable pet. The region must
be updated for drag, menu, scale and click-through. Test wallpaper clicks explicitly.

## 6. Keep the renderer bridge small and JSON-only

The WebKit script-message bridge is easy to get wrong. Using JSON messages in both
directions and a single handler name kept it debuggable. Always escape Python→JS
arguments with `json.dumps`; never interpolate free text into JavaScript. Add a
trailing `; true` to evaluated scripts because WebKit reports “Unsupported result
type” when a script returns `undefined`.

## 7. Static file routing is a classic bug

The first WebKit page loaded, but `/src/app.js` returned 404 because the server
stripped `/src/` and joined it to the renderer root instead of `renderer/src/`.
The page silently showed no character. Check every asset path and MIME type; use the
browser's network log or a `curl` probe. A 404 in a module import can look like a JS
error with no window error event.

## 8. Collect JavaScript errors explicitly

`window.onerror` does not catch all module-loading failures. During debugging, inject
a start-time error listener and evaluate a small diagnostic object
(`typeof window.AiluneBridge`, `document.readyState`, resource errors). A one-line
probe saved far more time than guessing.

## 9. Do not block the Qt main thread on HTTP

Service calls in the UI must run in worker threads. Even a “local” call can hang for
seconds if the service is down. `run_async` + QThread signals works well. Use
`GLib.idle_add` for GTK, and a bounded executor/dedicated thread for pet I/O.

## 10. Provider adapters need explicit failure semantics

OpenAI-compatible services differ (models endpoint shape, max token fields, SSE
details, error JSON). The adapter must normalize errors (`auth`, `rate_limit`,
`timeout`, `network`, `bad_response`) and never log or echo keys. Redirects should be
disabled so Authorization is not forwarded. Test with `httpx.MockTransport` rather
than real keys.

## 11. i18n from day one is cheap; retrofitting is not

Every UI string went through `tr()`, and a catalog parity test caught missing keys
immediately. Dynamic strings need special care (status pills, empty states, backend
error codes). Store translation keys, not already-translated text, when a widget may
need to refresh after a language switch.

## 12. Use fixtures for models and providers

Live2D models and cloud keys are bad test dependencies. A generated `.model3.json`
tree with dummy files tests the validator, path traversal, copy logic, and HTTP
server without distributing assets. A tiny mock OpenAI server tests the full
streaming path and lets the UI be exercised offline. Keep these in tests, not the
product.

## 13. Sandboxes hide devices; state what you could not test

The test environment had no `/dev/dri`, so WebGL could not be verified, and no
`/dev/uinput`, so clicks could not be injected. Do not claim those passed. The
correct output is “implemented, call verified, manual test required” with a
reproduction checklist. This is better than a false green check.

## 14. Prefer local, reviewable dependencies

The Go core uses only the standard library, making it easy to build and audit.
Python uses FastAPI/httpx/PyQt6 but avoids vendor SDKs. The only heavy native
dependency is the GTK/WebKit stack, which is unavoidable for the validated pet
window. Every new dependency should earn its place.

## 15. Protect user data by construction

API keys are write-only from the API's perspective, stored 0600, never logged, and
deleted with the provider. The renderer server only exposes the active model
directory. The token is shared through a 0600 file, and both services refuse
non-loopback binds. Document the limits of the file secret store honestly; a 0600
file is not encryption.

## 16. Keep a clean separation between dev state and the user's desktop

Using `.local/` for the dev launcher avoids polluting `~/.config` and makes
screenshots/tests reproducible. The same environment variables (`AILUNE_*`) are
honored by Go, UI, AI service and pet, so all components agree on paths.

## 17. The placeholder is a feature, not a cheat

Shipping a complete Canvas2D placeholder meant the whole chat → caption → pet loop,
menu, drag math and i18n could be validated without the Cubism SDK. It also gives
users something to see immediately. The key is to be explicit in the README and
provide a clean adapter boundary for the real renderer.
