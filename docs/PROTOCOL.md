# Local HTTP and bridge protocol

The protocol is versioned informally for the prototype (`0.1`). All HTTP services
bind loopback only. Sensitive endpoints require:

```http
Authorization: Bearer <local-token>
```

`<local-token>` is created in `$XDG_CONFIG_HOME/ailune/api-token` with mode `0600`
and shared by the core, AI service, UI and pet through the environment or file.

Errors use one envelope:

```json
{"error": {"code": "auth", "message": "authentication failed", "retryable": false}}
```

`code` is stable and localizable; `message` is safe diagnostic text. API keys are
never included.

## Go core — `http://127.0.0.1:8766`

### `GET /api/v1/health`

Unauthenticated liveness and version. Used by the launcher and UI status check.

```json
{"ok": true, "version": "0.1.0-dev"}
```

### `GET /api/v1/state`

```json
{
  "version": 1,
  "started_at": "2026-11-08T02:35:01Z",
  "language": "en",
  "active_character": {
    "id": "char_...",
    "name": "Aria",
    "model_path": "/home/user/.local/share/ailune/characters/aria-...",
    "model_entry": "Aria.model3.json",
    "personality_id": "pers_...",
    "scale": 1.0,
    "reply_language": "auto"
  },
  "pet": {"visible": true, "x": 1239, "y": 599, "scale": 1.0, "output": "", "click_through": false},
  "services": {"core": "running", "ai": "running", "pet": "running"}
}
```

`active_character` may be `null`. `pet.x`/`pet.y` are monitor-local logical pixels;
`-1` means “choose a default”. `output` is a Gdk connector name; empty means primary.

### `PATCH /api/v1/state`

Partial update. Every field is optional.

```json
{
  "active_character": {"id": "...", "name": "...", "model_path": "/abs/path",
                       "model_entry": "Aria.model3.json", "scale": 1.0,
                       "reply_language": "auto", "personality_id": null},
  "pet": {"visible": true, "x": 40, "y": 60, "scale": 1.2, "click_through": false, "output": ""},
  "language": "zh_CN"
}
```

- `active_character: null` clears the active character.
- `model_path` must be absolute; `model_entry` must be relative, end in
  `.model3.json`, and must not escape the model directory.
- `pet.scale` is clamped to 0.25–4; the UI exposes 0.5–2.
- `language` is `en` or `zh_CN`.
- Persistence is atomic (`config.json`, `0600`); a successful response is the new
  snapshot.

### `GET /api/v1/events` (SSE)

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-store`.

On connect the server sends the current snapshot as `state.changed`, then:

```
id: 2
event: state.changed
data: {...snapshot...}

id: 3
event: service.status
data: {"service":"ai","status":"running","state":{...}}

id: 4
event: pet.command
data: {"type":"caption","text":"Hello","sticky":true}

id: 5
event: app.notice
data: {...}
```

A keep-alive comment (`: ping`) is sent every 15 seconds. Clients should reconnect
and discard local assumptions when the first snapshot arrives. Subscribers are
capped at a small buffer; slow consumers drop events intentionally.

### `GET /api/v1/info`

Version, paths, process/runtime info and Niri diagnostics:

```json
{
  "version": "0.1.0-dev",
  "paths": {"config_dir": "...", "data_dir": "...", "runtime_dir": "..."},
  "runtime": {"pid": 123, "go_version": "go1.27.3"},
  "niri": {"available": true, "version": "...", "outputs": {...}, "workspaces": [...]}
}
```

Niri data is best-effort with short timeouts.

### `POST /api/v1/pet/commands`

Publishes a `pet.command` SSE event for the pet shell. The request body is an
arbitrary JSON object with a `type`:

```json
{"type": "expression", "name": "happy"}
{"type": "motion", "group": "Happy", "index": 0}
{"type": "caption", "text": "Hello!", "sticky": true}
{"type": "speaking", "value": true}
{"type": "mouth", "value": 0.4}
{"type": "reload"}
{"type": "menu", "x": 1200, "y": 800}
```

Returns `202 {"event_id": 4}`.

### `POST /api/v1/actions/open-ui`

Spawns the PyQt6 UI using the configured Python environment. Returns `202`.

### `POST /api/v1/actions/quit`

Stops the core; the supervisor sends SIGTERM to children. Returns `202`, then
triggers shutdown asynchronously.

## Python AI service — `http://127.0.0.1:8765`

All `/api/v1/*` routes require the bearer token. `/healthz` is unauthenticated.

### Health and metadata

- `GET /api/v1/health` → `{ok, version, secret_backend, stats}`
- `GET /api/v1/meta` → provider presets, capabilities (`live2d_runtime: false`,
  `asr: false`, `tts: false`, `streaming_chat: true`), secret backend, stats.

### Personalities

- `GET /api/v1/personalities`
- `POST /api/v1/personalities` `{name, system_prompt}`
- `PATCH /api/v1/personalities/{id}` `{name?, system_prompt?}`
- `DELETE /api/v1/personalities/{id}` (the built-in personality is protected)

### Characters

- `GET /api/v1/characters`, `GET /api/v1/characters/{id}`
- `POST /api/v1/characters`

```json
{"name":"Aria","model_path":"/abs/path","model_entry":"Aria.model3.json",
 "personality_id":"pers_...","reply_language":"auto","scale":1.0}
```

- `PATCH /api/v1/characters/{id}` (same fields, all optional)
- `DELETE /api/v1/characters/{id}` (cascades conversations and memories)

### Providers

- `GET /api/v1/providers` — public records include `has_api_key`, never the key or
  secret reference.
- `POST /api/v1/providers`

```json
{"display_name":"DeepSeek","provider_type":"deepseek",
 "base_url":"https://api.deepseek.com/v1","model_name":"deepseek-chat",
 "api_key":"sk-...", "temperature":0.8, "max_tokens":2048,
 "timeout_seconds":60, "extra_params":{}, "is_default":true}
```

- `PATCH /api/v1/providers/{id}` — same fields; `api_key: ""` clears the stored key.
- `DELETE /api/v1/providers/{id}` — deletes the secret and record.
- `POST /api/v1/providers/test` — accepts a provider shape plus optional
  `provider_id`; returns `{ok, message, latency_ms, models}`. It uses the saved key
  when `api_key` is omitted and `provider_id` is supplied. It never mutates config.
- `GET /api/v1/providers/{id}/models` — provider `/models` or Ollama `/api/tags`.

Provider types: `openai`, `deepseek`, `zhipu`, `dashscope`, `moonshot`, `ollama`,
`lmstudio`, `custom`. Aliases include `openai-compatible`.

### Conversations, messages, memory

- `GET /api/v1/conversations?character_id=...`
- `POST /api/v1/conversations` `{character_id, title?}`
- `GET /api/v1/conversations/{id}/messages?limit=200`
- `DELETE /api/v1/conversations/{id}`
- `GET /api/v1/memories?character_id=...&limit=100`
- `POST /api/v1/memories` `{character_id, content}`
- `DELETE /api/v1/memories/{id}?character_id=...`

### `POST /api/v1/chat/stream`

Request:

```json
{"character_id":"char_...","message":"Hello",
 "conversation_id":null,"provider_id":null,"request_id":null}
```

Response is `text/event-stream`. Events:

| Event | Data |
| --- | --- |
| `start` | conversation id, persisted user message, provider metadata, request id |
| `delta` | `{"type":"delta","text":"...","request_id":"..."}` |
| `done` | `{"type":"done","message":{...assistant row...},"request_id":"..."}` |
| `error` | `{"type":"error","error":{code,message,retryable?},"request_id":"..."}` |
| `cancelled` | client or server cancelled the generation |

The assistant message is persisted only after a successful stream. The user
message is persisted immediately. History sent to the provider is capped at 24
messages; up to 20 memory notes are injected into the system prompt.

### `POST /api/v1/chat/cancel/{request_id}`

Cooperative cancellation. The registry cancels the streaming task and closes the
provider request; the stream may end with a `cancelled` event or a closed
connection. Unknown IDs return `404`.

## Pet bridge (WebKit script messages)

Page → Python (`window.webkit.messageHandlers.ailune.postMessage(...)`):

```json
{"type":"ready","native":true}
{"type":"input-region","rects":[[x,y,w,h], ...]}
{"type":"position","x":1239,"y":599,"scale":1.0}
{"type":"action","action":"open-ui" | "hide" | "reload" | "quit"}
{"type":"interaction","action":"headpat","x":...,"y":...}
{"type":"renderer","renderer":"placeholder" | "live2d","name":"..."}
{"type":"js-error","message":"...","filename":"...","line":12}
```

Python → page (via `evaluate_javascript`):

```js
window.AiluneBridge.setLayout({x, y, scale, clickThrough, language});
window.AiluneBridge.loadCharacter({name, model_entry, model_url});
window.AiluneBridge.setCaption(text, sticky);
window.AiluneBridge.setExpression("happy");
window.AiluneBridge.playMotion("Happy", 0);
window.AiluneBridge.setSpeaking(true);
window.AiluneBridge.setMouth(0.4);
window.AiluneBridge.setVisible(true);
window.AiluneBridge.setLanguage("zh_CN");
window.AiluneBridge.openMenuAt(x, y);
```

The bridge is optional outside the pet: a browser logs messages instead.

## Pet renderer server

Bound to a random `127.0.0.1` port:

- `/index.html`, `/src/*`, `/assets/*` — renderer files from the checkout.
- `/model/*` — files inside the active model directory only.
- `/favicon.ico` — 204.

Only GET/HEAD are served; paths are resolved and checked against their root.
The server has no authentication (loopback-only, random port, no secrets). Model
assets are already local user data.

## Compatibility notes

- `heartbeat`/`retry:` fields in SSE are ignored by clients; reconnect with
  exponential backoff.
- Event IDs are monotonic but not replayed. Reconnect always re-sends state.
- The protocol is local-only; do not expose either port to a network.
