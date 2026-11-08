"""A loopback HTTP server that serves the renderer and the active model.

WebKitGTK refuses cross-origin file:// fetches for textures and moc3 data, so
the pet shell serves both the renderer and the model from a random loopback
port. Only files below the selected model directory are exposed.
"""

from __future__ import annotations

import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXTRA_TYPES = {
    ".moc3": "application/octet-stream",
    ".model3.json": "application/json",
    ".motion3.json": "application/json",
    ".exp3.json": "application/json",
    ".physics3.json": "application/json",
    ".pose3.json": "application/json",
    ".userdata3.json": "application/json",
    ".cdi3.json": "application/json",
}


class RendererServer:
    def __init__(self, renderer_dir: Path, host: str = "127.0.0.1") -> None:
        self.renderer_dir = renderer_dir.resolve()
        if not (self.renderer_dir / "index.html").is_file():
            raise FileNotFoundError(f"renderer/index.html not found under {self.renderer_dir}")
        self.host = host
        self._model_root: Path | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def model_root(self) -> Path | None:
        return self._model_root

    def set_model_root(self, root: Path | None) -> None:
        if root is None:
            self._model_root = None
            return
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            resolved = root.expanduser().absolute()
        self._model_root = resolved if resolved.is_dir() else None

    def start(self) -> str:
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AilunePet/0.1"

            def do_GET(self) -> None:  # noqa: N802
                server._handle(self)

            def do_HEAD(self) -> None:  # noqa: N802
                server._handle(self, head_only=True)

            def log_message(self, fmt: str, *args: object) -> None:
                # Per-request logging is noisy and may expose local paths.
                return

        self._httpd = ThreadingHTTPServer((self.host, 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="ailune-renderer")
        self._thread.start()
        port = self._httpd.server_address[1]
        return f"http://{self.host}:{port}/index.html"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def _handle(self, request: BaseHTTPRequestHandler, head_only: bool = False) -> None:
        parsed = urlsplit(request.path)
        path = unquote(parsed.path)
        if path == "/" or path == "/index.html":
            file_path = self.renderer_dir / "index.html"
        elif path.startswith("/src/"):
            file_path = self._safe_join(self.renderer_dir / "src", path[len("/src/") :])
        elif path.startswith("/assets/"):
            file_path = self._safe_join(self.renderer_dir / "assets", path[len("/assets/") :])
        elif path.startswith("/model/"):
            root = self._model_root
            file_path = self._safe_join(root, path[len("/model/") :]) if root else None
        elif path == "/favicon.ico":
            request.send_response(HTTPStatus.NO_CONTENT)
            request.end_headers()
            return
        else:
            self._not_found(request, head_only)
            return

        if file_path is None or not file_path.is_file():
            self._not_found(request, head_only)
            return
        try:
            data = file_path.read_bytes()
        except OSError:
            self._not_found(request, head_only)
            return
        content_type = EXTRA_TYPES.get(file_path.name if file_path.name.endswith(".json") else file_path.suffix.lower())
        if content_type is None:
            content_type, _ = mimetypes.guess_type(file_path.name)
        if content_type is None:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/json", "application/javascript"):
            content_type += "; charset=utf-8"
        request.send_response(HTTPStatus.OK)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("X-Content-Type-Options", "nosniff")
        request.end_headers()
        if not head_only:
            try:
                request.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    @staticmethod
    def _safe_join(root: Path, relative: str) -> Path | None:
        relative = relative.replace("\\", "/")
        if not relative or "\x00" in relative:
            return None
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _not_found(request: BaseHTTPRequestHandler, head_only: bool) -> None:
        body = b"not found\n"
        request.send_response(HTTPStatus.NOT_FOUND)
        request.send_header("Content-Type", "text/plain; charset=utf-8")
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        if not head_only:
            try:
                request.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass


__all__ = ["RendererServer"]
