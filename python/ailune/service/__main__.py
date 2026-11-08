"""Run the Ailune AI service with uvicorn."""

from __future__ import annotations

import logging
import sys

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("ailune.service")
    try:
        settings = Settings.from_env()
    except Exception as exc:
        log.error("cannot start AI service: %s", exc)
        return 1
    app = create_app(settings)
    log.info("AI service listening on http://%s:%d", settings.host, settings.port)
    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            access_log=False,
            server_header=False,
            proxy_headers=False,
        )
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception("AI service crashed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
