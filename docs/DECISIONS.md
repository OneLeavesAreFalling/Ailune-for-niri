# Decision records

## ADR-001 — Pet window: GTK4 layer shell + WebKitGTK

**Status:** accepted (validated on Niri 26.04).

**Context.** The plan proposed Go + PyQt6 + Qt WebEngine, but Wayland compositors
do not let ordinary clients position top-level windows or place them above tiled
windows. Niri is no exception. The pet needs transparent, borderless, always-on-top,
positionable, click-through-capable behaviour. Qt on Wayland has no first-class
layer-shell API, and `layer-shell-qt` would require a C++ shim and a second toolkit
integration.

**Decision.** Implement the pet shell in Python with GTK4 + `gtk4-layer-shell` and
WebKitGTK, hosting the same Web renderer the plan envisioned. Keep PyQt6 for the
settings/chat UI as required. The pet is an overlay layer surface; the renderer page
draws the character inside a full-output surface.

**Consequences.**
- Two GUI toolkits (Qt for settings, GTK for the pet) increase dependencies.
- The Web renderer is portable across the Live2D SDK and the placeholder.
- The windowing path works with Niri today and does not need user window rules.
- The UI cannot embed a Qt layer surface; previews are handled by the pet itself.

## ADR-002 — Full-output surface with a clipped input region

**Status:** accepted.

**Context.** A small surface cannot be moved by the client on Wayland. A full-output
surface can host the character and receive pointer events, but would otherwise block
the entire desktop.

**Decision.** Use a full-output layer surface, draw the character at an internal
position, and set `Gdk.Surface.set_input_region()` to the character/menu rectangles.
Dragging moves the character inside the surface, not the surface itself.

**Consequences.**
- Stable dragging without compositor feedback loops.
- Click-through is possible without compositor-specific protocols.
- The surface still composites at output size; high-resolution performance needs
  profiling.
- Input is rectangular, not per-pixel.

## ADR-003 — Go core + Python services

**Status:** accepted.

**Context.** The plan calls for a Go core coordinating lifecycle/state and a Python
side handling UI/AI. The biggest practical question is process count and ownership.

**Decision.** Keep the Go core small and dependency-free (stdlib only). It owns
lifecycle, state, auth, SSE, supervision and Niri diagnostics. The Python AI service
owns providers/DB/chat. PyQt6 is a separate process. The pet is a separate process.
The UI and pet talk to the two HTTP services directly.

**Consequences.**
- Clear failure isolation: the UI or pet can crash without taking down chat history.
- More processes and a shared protocol to maintain.
- The core persists the minimum active-character data so the pet can start without
  the AI service.

## ADR-004 — HTTP + SSE instead of WebSocket

**Status:** accepted for the prototype.

**Context.** Chat and state updates are unidirectional streams. WebSocket adds a
dependency, framing and reconnect logic for both ends.

**Decision.** Use plain HTTP for commands and Server-Sent Events for state and
streaming chat. Use authenticated loopback HTTP. Cancellation is a separate POST.

**Consequences.**
- The Go side needs no external module.
- SSE is easy to inspect with `curl`.
- Bidirectional real-time features (voice duplex, tool calls) may eventually favor
  WebSocket; the event envelope is designed so a transport swap is possible.

## ADR-005 — Provider adapters over vendor SDKs

**Status:** accepted.

**Context.** OpenAI-compatible APIs differ subtly; Ollama and LM Studio are local;
users may point at arbitrary compatible endpoints.

**Decision.** Implement a small `AIProvider` interface and use `httpx` directly.
`OpenAICompatibleProvider` covers cloud/custom/LM Studio; `OllamaProvider` uses the
native NDJSON API. Presets carry default base URLs/models. Connection tests use
`/models` and `/api/tags`, not generated tokens.

**Consequences.**
- Full control over timeouts, redirects, cancellation and error mapping.
- No vendor SDK logs can leak keys.
- Provider-specific behavior must be tested deliberately; presets are starting
  points, not guarantees.

## ADR-006 — JSON i18n catalogs instead of Qt .qm

**Status:** accepted for the prototype; revisit before packaging.

**Context.** Qt's `QTranslator`/`.qm` pipeline is conventional but requires
`lrelease` at build time and makes live catalog edits less transparent. The UI is
built from Python widgets with runtime retranslation.

**Decision.** Use JSON catalogs (`en.json`, `zh_CN.json`) and a small `Translator`
with a `language_changed` signal. Pages implement `retranslate()`. A pytest test
checks catalog parity and that literal keys used in the UI exist in both catalogs.

**Consequences.**
- Easy review/diff and runtime switching.
- Not the standard Qt tooling; pluralization/context support is minimal.
- If Qt Linguist tooling is needed later, catalogs can be converted.

## ADR-007 — Secrets: file by default, Secret Service optional

**Status:** accepted.

**Context.** The plan asks for API-key safety and suggests the system keyring. A
keyring dependency can fail in minimal sessions, and `secret-tool` behavior varies.

**Decision.** Default to a 0600 JSON file under the config directory. Offer
`AILUNE_SECRET_BACKEND=secret-service` via `secret-tool`. The API never returns keys;
the UI shows only `has_api_key`. Keys are never logged.

**Consequences.**
- Works out of the box on any Linux desktop.
- The file is not encryption; it protects against other users, not root or same-user
  malware. Documented in SECURITY.md.
- Keyring integration is an opt-in, not silently assumed.

## ADR-008 — Placeholder renderer; SDK/model assets not bundled

**Status:** accepted; Live2D integration is the next milestone.

**Context.** Live2D Cubism SDK and models have separate licenses. Automatically
fetching or vendoring them would be a licensing risk and would bloat the prototype.

**Decision.** Ship a hand-drawn Canvas2D character that exercises the entire bridge
(expressions, motions, mouth, captions, interactions). Model import/validation is
complete and real. Provide `renderer/src/live2d/adapter.js` as the drop-in point for
a Cubism-based implementation.

**Consequences.**
- The whole app is visually demonstrable without external assets.
- Users may expect real model rendering; the limitation is prominent in the README.
- The Cubism integration must be added before the project can claim Live2D support.

## ADR-009 — XDG paths and explicit development isolation

**Status:** accepted.

**Decision.** Use standard XDG directories in production. The dev launcher
(`scripts/dev.sh`) overrides them to `.local/`, which is gitignored. The token is a
shared file rather than a per-process secret, so components can start independently.

**Consequences.**
- No root/user config pollution in development.
- Users can run the UI/pet manually as long as they share the same environment.
- Config migration/versioning is minimal at this stage (version 1).
