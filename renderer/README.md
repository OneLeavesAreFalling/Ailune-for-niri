# Web renderer

The pet loads this directory from a random loopback HTTP server hosted by
`python/ailune/pet/http_server.py`. It is a plain ES-module app: there is no build
step and no npm dependency.

```text
renderer/
├── index.html          layout, bubble and context-menu styling
└── src/
    ├── app.js          bridge, layout, drag, menu, speech bubble, animation loop
    ├── bridge.js       WebKit script-message wrapper
    ├── placeholder.js  default Canvas2D character
    └── live2d/
        └── adapter.js  optional Cubism integration point
```

## Placeholder renderer

The default character is hand-drawn with Canvas2D. It supports:

- breathing, blinking, hair sway, pointer look-at;
- expressions: `neutral`, `happy`, `sad`, `surprised`, `thinking`;
- motions mapped to small reactions (`happy`, `sad`, `surprised`, `thinking`, idle);
- `setMouth(value)` for future TTS amplitude, and `setSpeaking(bool)`
  (an idle mouth animation is used until real audio is connected);
- click reactions and hearts;
- speech bubbles from the chat stream;
- drag by moving the character inside the fixed layer surface;
- a right-click menu localized to the current UI language.

To preview it in a normal browser, serve the parent directory, for example:

```bash
cd renderer && python3 -m http.server 8088
# open http://127.0.0.1:8088/
```

Without a native bridge, messages are logged to the console; everything else works.

## Adding the Live2D Cubism runtime

The Cubism SDK for Web is **not** included. Review its license before downloading
or redistributing it.

1. Obtain the Cubism SDK for Web and build/obtain the Cubism Web Framework files.
2. Place the runtime under `renderer/vendor/live2d/` (same origin; CSP allows
   `script-src 'self'`).
3. Load its bootstrap script from `index.html` before `src/app.js`, or import it
   dynamically from `src/live2d/adapter.js`.
4. Expose:

```js
window.AiluneLive2D = {
  async create({ canvas, modelUrl, modelEntry, name }) {
    // Load modelUrl relative to the local /model/ server.
    // Return an object with:
    //   setExpression(name), playMotion(group, index),
    //   setMouth(value), setSpeaking(value), setLook(x, y),
    //   draw(now, dt), destroy()
  }
};
```

`adapter.js` calls `create()` when the global exists. If it throws, the placeholder
stays visible and the error is logged. The pet shell is notified with a
`{type:"renderer", renderer:"live2d"|"placeholder"}` bridge message.

### Model URL

The pet shell serves `/model/<entry>` from the active model's root. A model entry at
`Aria/Aria.model3.json` is available as:

```text
http://127.0.0.1:<pet-port>/model/Aria.model3.json
```

Relative texture/motion paths in the manifest resolve correctly against that URL.
Paths are restricted to the model root and traversal is rejected.

### Lip sync

Call the bridge methods from the pet shell:

- `window.AiluneBridge.setSpeaking(true)` at playback start;
- `window.AiluneBridge.setMouth(amplitude)` from TTS/audio analysis (0..1);
- `window.AiluneBridge.setSpeaking(false)` at the end.

A future Live2D adapter can map amplitude to the model's `LipSync` parameter group
instead of using the placeholder mouth.

## Debugging

- `AILUNE_PET_DEV=1` enables WebKit developer extras.
- `AILUNE_DEBUG=1` logs renderer bridge messages, JS errors and a startup probe.
- The page can be opened in a normal browser for layout/interaction work; no native
  bridge is required for the placeholder.
- If the pet appears blank, check:
  - `/src/app.js` returns 200 (static routing bug);
  - JS errors in the pet log;
  - WebKit transparency settings;
  - `AILUNE_PET_DEV=1` plus WebKit inspector.

## Security notes

- The page has a strict CSP and only loads same-origin/loopback resources.
- Never pass API keys or provider configuration into the renderer.
- Model JSON is untrusted input. The runtime should bound sizes, validate paths and
  avoid executing arbitrary data.
- Live2D models and SDK files carry their own licenses; do not commit them unless
  you have permission.
