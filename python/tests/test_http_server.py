from __future__ import annotations

from pathlib import Path

import httpx

from ailune.pet.http_server import RendererServer

RENDERER = Path(__file__).resolve().parents[2] / "renderer"


def test_renderer_and_model_serving(sample_model: Path):
    server = RendererServer(RENDERER)
    base = server.start()
    server.set_model_root(sample_model)
    try:
        with httpx.Client(timeout=5) as client:
            index = client.get(base)
            assert index.status_code == 200
            assert "Ailune" in index.text
            assert "text/html" in index.headers["content-type"]

            app_js = client.get(base.rsplit("/index.html", 1)[0] + "/src/app.js")
            assert app_js.status_code == 200
            assert "AiluneBridge" in app_js.text

            model = client.get(base.rsplit("/index.html", 1)[0] + "/model/Aria.model3.json")
            assert model.status_code == 200
            assert "FileReferences" in model.text
            assert "application/json" in model.headers["content-type"]

            forged = client.get(base.rsplit("/index.html", 1)[0] + "/model/%2e%2e/secret")
            assert forged.status_code == 404

            favicon = client.get(base.rsplit("/index.html", 1)[0] + "/favicon.ico")
            assert favicon.status_code == 204
    finally:
        server.stop()


def test_missing_model_root_is_404(sample_model: Path):
    server = RendererServer(RENDERER)
    base = server.start()
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(base.rsplit("/index.html", 1)[0] + "/model/Aria.model3.json")
            assert response.status_code == 404
    finally:
        server.stop()
