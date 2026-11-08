# Security notes

Ailune is a single-user local desktop application. The threat model is “another
local process or a malicious web page tries to read keys/chat data or make Ailune
talk to an attacker.” It is not a sandbox against a compromised user account.

## Local API

- The Go core binds `127.0.0.1` (validated; it refuses non-loopback addresses).
- The AI service also refuses non-loopback listen addresses.
- Every sensitive endpoint requires `Authorization: Bearer <token>`.
- The token is 32 random bytes hex, stored in `$XDG_CONFIG_HOME/ailune/api-token`
  with mode `0600`, created by either the core or the Python side.
- Token comparison is constant-time on the Go side and `hmac.compare_digest` on the
  Python side.
- The core's `GET /api/v1/health` and the AI service's `GET /healthz` are
  unauthenticated by design; they expose only a version/ok status. The AI service's
  `GET /api/v1/health` requires the token.
- Both services set `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`
  and reject oversized request bodies.
- The core refuses cross-origin redirects for providers (httpx `follow_redirects=False`).

The token is passed to children in the environment and stored in a file. Any process
running as the same user can read it; that is equivalent to the trust boundary of a
desktop session.

## API keys

- Keys are write-only through the HTTP API. Public provider records expose only
  `has_api_key`.
- The default store is `$XDG_CONFIG_HOME/ailune/secrets.json`, mode `0600`, written
  atomically.
- `AILUNE_SECRET_BACKEND=secret-service` uses the desktop keyring via `secret-tool`.
- Provider adapters never include the key in error messages. Tests assert that a
  401 response does not leak the key.
- The UI never renders a stored key; the field is cleared when a provider is loaded.
- Deleting a provider deletes its secret.

The file backend is **not encryption**. It protects against accidental disclosure
and other local users; it does not protect against root or same-user malware. This
is documented in the UI and README.

## Provider traffic

- HTTPS is expected for remote providers; users can choose HTTP for local servers.
- Custom base URLs are validated to be http(s), have a host, and contain no embedded
  credentials/query/fragment.
- Redirects are disabled so an Authorization header is not forwarded to another host.
- API calls are made by the AI service, not the Web renderer. Keys never enter
  WebKit, the UI process, or the renderer page.

## Renderer and WebKit

- The pet serves the renderer and model files from a random loopback port. Only
  files under the selected model directory are exposed; path traversal/symlink
  escapes are rejected.
- The renderer's Content-Security-Policy is `default-src 'self'` with same-origin
  scripts/styles, images from self/data/blob/loopback, and connections to
  self/loopback. Remote content is not allowed.
- There is no authentication on the renderer server. It exposes only local model
  assets and public renderer code; it holds no secrets. A local process could fetch
  the active character's textures (already readable by that user).
- WebKitGTK may use a sandbox; in restricted/sandboxed environments it can fail to
  create its runtime directories. Users should run Ailune in a normal desktop
  session. WebKit developer extras are disabled unless `AILUNE_PET_DEV=1`.
- The page cannot call arbitrary Python; only the enumerated script-message handlers
  are processed, and all Python→JS arguments are JSON-encoded.

## Data at rest

| Data | Location | Protection |
| --- | --- | --- |
| config/token | config dir | dir/file 0600 |
| provider keys | secrets file or keyring | 0600 / keyring |
| SQLite | data dir | user file permissions |
| model assets | user-chosen paths or data dir | user file permissions |

Chat history and memories are not encrypted. Avoid storing sensitive personal
information in memory notes; they are injected into every relevant prompt.

## Prompt and content risks

- Personalities and memories are user-authored text; a malicious memory could
  influence model behaviour. There is no model/tool execution in this prototype, so
  the blast radius is limited to the reply text.
- Cloud providers receive the chosen provider configuration and chat messages.
  The UI shows provider names; the privacy note is in Settings.
- Model manifests are treated as untrusted input and parsed with strict path checks.
  They are not executed locally; the placeholder renderer ignores them. A future
  Cubism runtime must treat model JSON/moc3 as untrusted.

## Licenses

- Live2D Cubism SDK and Live2D models have their own licenses; they are not bundled.
- PyQt6 is GPL/commercial; the project uses GPL-3.0-or-later and must be reviewed
  before distribution.
- Do not redistribute third-party model assets without permission.

## Reporting

This is a prototype without a security contact yet. For now, open an issue in the
project repository with reproduction steps and avoid including API keys in reports.
