# Work log

## 2026-11-08 — Chinese README

- Added [`README_CN.md`](README_CN.md): a complete Simplified Chinese translation
  of the project README.
- Added language links between `README.md` and `README_CN.md`.
- No source, configuration or documentation structure was changed beyond the new
  top-level README file.

## 2026-11-08 — first vertical slice

**Goal:** start the project and implement a working, testable foundation for the
Ailune Linux desktop companion.

### What was created

1. **Project skeleton**
   - Go module `github.com/ailune/ailune` (stdlib only).
   - Python package `ailune` under `python/`, with `pyproject.toml`, tests, and
     separate `ai`, `service`, `ui`, `pet`, `models`, `common` modules.
   - `renderer/` ES-module Web page, `docs/`, `scripts/`, `assets/`, `configs/`.
   - `README.md`, `WORKLOG.md`, `LESSONS.md`, `docs/ARCHITECTURE.md`,
     `docs/PROTOCOL.md`, `docs/NIRI.md`, `docs/DECISIONS.md`, `docs/SECURITY.md`.

2. **Go core** (`cmd/ailune`, `internal/...`)
   - XDG path resolution, 0600 shared token, JSON config with atomic writes and
     validation.
   - Thread-safe state manager and SSE event bus.
   - Authenticated loopback HTTP API (`/state`, `/events`, `/info`, `/pet/commands`,
     `/actions/open-ui`, `/actions/quit`).
   - Process supervisor with restart/backoff and process-group shutdown.
   - Niri diagnostics wrapper (`niri msg --json`).
   - CLI: `run`, `core`, `ui`, `service`, `pet`, `open`, `state`, `doctor`, `version`.
   - Unit tests for config, state, events, API/SSE, auth, pet commands, Niri wrappers.

3. **Python AI service** (`python/ailune/service`, `ai`)
   - FastAPI app with bearer auth and structured errors.
   - SQLite schema: personalities, characters, providers, conversations, messages,
     memories; default personality seed; WAL and foreign keys.
   - Provider adapters: OpenAI-compatible (SSE) and native Ollama (NDJSON), plus
     presets for OpenAI, DeepSeek, Zhipu, DashScope, Moonshot, Ollama, LM Studio and
     custom endpoints. Connection tests, model listing, cancellation, timeouts.
   - Secret store: 0600 file by default; optional Secret Service via `secret-tool`.
   - Chat engine: personality + memory injection, history window, streaming events,
     persistence, request cancellation, provider error codes.
   - 38 pytest tests covering providers, manifest validation, SQLite, API, chat,
     i18n and the renderer HTTP server.

4. **Live2D model tooling**
   - `.model3.json` discovery/parsing.
   - Validates moc3, textures, physics, pose, expressions, motions, sounds, groups
     and hit areas; reports structured errors/warnings.
   - Blocks path traversal and references outside the model root.
   - Imports a validated model with a copy option that copies only referenced files.
   - UI thumbnail/check report and model library integration.

5. **PyQt6 interface**
   - Sidebar navigation: Chat, Characters, AI Providers, Personality, Memory,
     Settings.
   - Chat with streaming Markdown bubbles, conversation history, stop button, pet
     caption/expression forwarding.
   - Character import dialog, validation report, personality/language/size editing,
     desktop activation/deletion.
   - Provider CRUD, preset auto-fill, masked write-only key field, test connection,
     default provider, extra JSON parameters.
   - Personality CRUD; memory CRUD per character.
   - Settings: live interface language, pet visibility/scale/click-through/reset,
     service health, Niri summary, data/token paths, About/licenses.
   - English + Simplified Chinese JSON catalogs with a key-parity test.

6. **Desktop pet**
   - Python GTK4 layer-shell overlay with transparent WebKitGTK page.
   - Full-output surface with `Gdk.Surface.set_input_region` clipping; empty region
     for click-through/hidden.
   - Character canvas positioning and drag; right-click menu (Chat/Settings/Hide/
     Reload/Quit); automatic language-aware labels.
   - Local renderer/model HTTP server with path traversal protection.
   - WebKit ↔ Python script-message bridge; SSE client from the core; debounced
     position persistence.
   - Automatic `LD_PRELOAD` re-exec so gtk4-layer-shell initializes correctly.
   - Hand-drawn Canvas2D placeholder character with breathing, blinking, looking,
     expressions, mouth sync hooks, click reactions and captions.

7. **Launcher/tooling**
   - `scripts/setup.sh`, `scripts/dev.sh`, `Makefile`.
   - Development mode uses `.local/` for config/data/runtime/XDG so it does not
     touch the user's real Ailune state.

### Verification performed

Environment: Arch Linux, Niri 26.04, Wayland, eDP-1 2560×1600 @ scale 1.5,
GTK 4.24.1, gtk4-layer-shell 1.3.0, WebKitGTK 2.54.2, PyQt6 6.12.0.

- **Go tests:** `go test ./...` — all packages passed (`config`, `state`,
  `eventbus`, `httpapi`, `niri`).
- **Python tests:** `38 passed` (providers, API, chat, store, manifest, copy,
  renderer server, i18n).
- **Layer-shell experiment:** a live layer surface appeared in
  `niri msg layers` as `ailune-pet`/`Overlay`; transparency and full-output
  rendering were confirmed with screenshots; the pet remained visible across a
  workspace switch (3 → 5 → 3).
- **Renderer:** WebKit loaded the page from the local server and rendered the
  Canvas2D character; speech bubble and context menu were screenshot-verified.
- **Full stack:** `ailune run` started the core, AI service and pet under the Go
  supervisor; all three reported `running`, the AI database survived restart, and the
  pet layer was present.
- **Live UI:** the PyQt6 window opened on the real Niri/Wayland session
  (`app_id=dev.ailune.Ailune`) and rendered populated chat history.
- **End-to-end chat:** created a fixture model + character, a mock OpenAI-compatible
  streaming server, and a provider via the API. Chat streamed `start`/`delta`/
  `done`, persisted messages, and the UI rendered the conversation. The pet loaded
  the active character name ("Aria") and displayed a greeting bubble.
- **UI:** all six pages rendered offscreen at 1220×800; populated chat, character
  library, provider form, and live EN→ZH switching were screenshot-verified.
- **Not verified in this session:** real pointer drag/click-through (sandbox has no
  `/dev/uinput`), WebGL/Live2D rendering (sandbox has no `/dev/dri`), real cloud
  provider credentials, ASR/TTS.

### Structure changes (user was notified in the final response)

- Added `cmd/`, `internal/`, `python/`, `renderer/`, `docs/`, `scripts/`, `assets/`,
  `configs/`, `models/` and `data/` placeholders.
- Root docs: `README.md`, `WORKLOG.md`, `LESSONS.md`.
- State/data defaults follow XDG; dev uses `.local/`.

### Known gaps / next steps

1. Integrate Live2D Cubism SDK for Web into `renderer/src/live2d/` (license review,
   SDK drop-in, motions/expressions/lip sync).
2. Real pointer testing on the target Niri session: drag, click, click-through,
   multi-monitor output switching, 1.5× fractional scaling.
3. Add TTS/ASR and wire `setMouth` to audio amplitude; reserve phoneme hooks.
4. Add memory editing/export and automatic memory extraction; conversation export.
5. Harden provider discovery/streaming for more vendors; add recorded-fixture tests.
6. Package (systemd user service, desktop entry, tray integration, installer) and
   finish license review.
7. Add Niri output selector to the UI (state already carries `output`).
8. Performance profile the full-output layer surface on high-resolution displays.

### Useful commands

```bash
./scripts/setup.sh
make test
make doctor
make run
# Development paths only:
AILUNE_DEBUG=1 ./scripts/dev.sh
# Head-on pet debugging:
AILUNE_DEBUG=1 LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so \
  PYTHONPATH=python .venv/bin/python -m ailune.pet
```

No Live2D SDK, model assets, or API keys are included in the repository.
