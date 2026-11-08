# Architecture

Ailune is split into a small Go control core and three Python processes. The split
keeps the long-running desktop state independent from GUI toolkits while allowing
the pet to use GTK4 layer shell and the settings UI to use PyQt6.

```text
                        ┌──────────────────────────────┐
                        │          Niri / Wayland      │
                        └──────────────┬───────────────┘
                                       │ layer shell + input region
┌──────────────┐   HTTP + SSE   ┌──────▼───────┐   HTTP + SSE   ┌──────────────┐
│  PyQt6 UI    │◄──────────────►│  Go core     │◄──────────────►│  Pet shell   │
│  settings    │                │  :8766       │                │  GTK4/WebKit │
│  chat        │                │  state, SSE  │                │  :random     │
└──────┬───────┘                └──────┬───────┘                └──────┬───────┘
       │                               │ supervision                    │
       │ HTTP + SSE                    │ spawn/restart                  │ renderer bridge
       ▼                               ▼                                ▼
┌────────────────────────────────────────────────┐          ┌─────────────────────┐
│ Python AI service (:8765, FastAPI)             │          │ Web page (WebGL/    │
│ providers · secrets · SQLite · chat · memory   │          │ Canvas2D placeholder)│
└───────────────────────┬────────────────────────┘          └─────────────────────┘
                        │ HTTPS
                        ▼
              OpenAI-compatible / Ollama /
              LM Studio / custom endpoints
```

## Processes

| Process | Language | Responsibility | Port |
| --- | --- | --- | --- |
| `ailune core` / `ailune run` | Go | lifecycle, state snapshot, SSE, auth, supervisor, Niri diagnostics, UI spawning | `127.0.0.1:8766` |
| AI service (`python -m ailune.service`) | Python | provider adapters, secrets, SQLite, chat streaming, personalities, memory | `127.0.0.1:8765` |
| Settings/chat UI (`python -m ailune.ui`) | Python + PyQt6 | settings, model manager, chat, language switching | none |
| Pet shell (`python -m ailune.pet`) | Python + GTK4 + WebKitGTK | layer surface, input region, drag/menu, renderer host | random loopback |
| Renderer page | HTML/ES modules | character drawing, expressions, bridge, speech bubble | served by pet |

All processes are launched from the same checkout and receive `AILUNE_ROOT`,
`AILUNE_*` directories, the core/AI URLs and the shared token through the
environment.

## Startup sequence

1. `ailune run` resolves XDG paths, loads `config.json`, creates/loads `api-token`,
   and binds the control API before children start.
2. The supervisor starts the AI service and the pet shell with restart/backoff.
3. The UI can be opened from the pet menu, `ailune ui`, or the CLI action.
4. The UI reads the current state from the core and loads characters/providers
   from the AI service.
5. The pet loads state, subscribes to the SSE stream, serves the renderer, and
   presents its layer surface.

`ailune core` is the same core without the AI/pet children, useful for debugging
the UI or the API alone.

## State ownership

- **Core-owned:** active character, pet x/y/scale/visibility/output, interface
  language, service statuses. Persisted to `config.json`.
- **AI-service-owned:** character records, personalities, provider configurations,
  conversations, messages, memory notes. Persisted to SQLite.
- **UI-owned:** window geometry and language preference (`QSettings`). The
  interface language is mirrored to the core so the pet menu follows it.
- **Pet-owned:** renderer viewport, character canvas position during drag, input
  region rectangles. Position updates are written back to the core with debounce.

The duplicate active-character metadata is intentional: the pet must be able to
start without the AI service, and the core must persist enough to relaunch it.

## Desktop pet

The pet is **not** a normal floating XDG toplevel. It is a layer-shell surface on
the `overlay` layer, sized to the selected output:

- GTK window background is transparent through a CSS provider.
- WebKitGTK `WebView` background is transparent; the page itself has no background.
- The page draws a fixed 420×420 character canvas anywhere inside the full-output
  surface. The surface never moves, so dragging cannot fight Wayland's positioning
  rules.
- `Gdk.Surface.set_input_region()` is set to a rectangle around the character
  (plus the context menu while open). Everything outside passes clicks through to
  the desktop. An empty region makes the pet fully click-through.
- The right-click menu is DOM/CSS inside the same surface. Its rectangle is added
  to the input region so the buttons are clickable.
- Layer surfaces are per-output and not tied to a workspace, so the pet stays
  visible when switching workspaces on that output.

`gtk4-layer-shell` must be linked before `libwayland-client`. The pet entry point
re-executes itself with `LD_PRELOAD` pointing at `libgtk4-layer-shell.so`; see
`python/ailune/pet/bootstrap.py` and [NIRI.md](NIRI.md).

## Renderer bridge

The Web page exposes `window.AiluneBridge`:

| Direction | Message | Purpose |
| --- | --- | --- |
| Python → JS | `setLayout({x,y,scale,clickThrough,language})` | viewport state |
| Python → JS | `loadCharacter({name,model_url,model_entry})` | load model or placeholder |
| Python → JS | `setCaption(text, sticky)`, `setExpression(name)`, `playMotion(group,index)`, `setMouth(value)`, `setSpeaking(bool)` | chat/voice reactions |
| Python → JS | `setVisible(bool)`, `setLanguage(lang)`, `openMenuAt(x,y)` | UI state |
| JS → Python | `ready`, `position`, `input-region`, `action`, `interaction`, `js-error`, `renderer` | bridge events |

The platform bridge is WebKit's script message handler named `ailune`. The renderer
continues to work in a normal browser (messages are logged to the console).

## Model import

`python/ailune/models/manifest.py` parses `.model3.json`, resolves every reference
inside the model root, checks extensions/existence, and reports structured codes.
Path traversal and symlink escapes are rejected. `library.py` copies only the
referenced files, preserving relative paths. The UI displays the report, a
texture preview, counts and warnings before creating the character record in the
AI service.

The model entry is later served by the pet's local HTTP server under `/model/...`
so WebGL texture loads are not blocked by `file://` origin rules.

## Persistence and paths

| Data | Default location |
| --- | --- |
| config, token | `$XDG_CONFIG_HOME/ailune/` |
| SQLite, model library | `$XDG_DATA_HOME/ailune/` |
| runtime `core.json` | `$XDG_RUNTIME_DIR/ailune/` |
| cache, uv/go build caches | `$XDG_CACHE_HOME/ailune/` |

Secrets are stored in a `0600` JSON file by default, or in the Secret Service when
`AILUNE_SECRET_BACKEND=secret-service`.

The renderer reads the active character's model from the local HTTP server; it
never reads arbitrary user paths.

## Failure handling

- The supervisor restarts the AI service and pet with exponential backoff (1–30s).
- UI/pet HTTP clients use short timeouts and retry SSE connections with backoff.
- The pet keeps rendering its placeholder if the core or AI service is down.
- Chat errors are normalized to codes (`auth`, `rate_limit`, `timeout`, `network`,
  `server_error`, …) and surfaced as localized UI messages plus provider detail.
- Model and settings failures are reported without exposing API keys.
- `ailune doctor` checks Python/GTK/WebKit/Niri and prints paths and statuses.

## Extension points

- **Live2D:** implement `window.AiluneLive2D.create()` according to
  `renderer/src/live2d/adapter.js`; the placeholder remains the fallback.
- **Providers:** add an adapter in `python/ailune/ai/` plus a preset in `registry.py`.
- **Voice:** call the renderer's `setSpeaking` / `setMouth` bridge; add an ASR/TTS
  service similar to the AI service.
- **Niri features:** extend `internal/niri` and expose actions/info through the core
  API; the layer surface design does not depend on them.
