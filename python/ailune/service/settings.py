"""Service configuration resolved from the environment and the core config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ailune.common.paths import Paths, is_loopback, load_app_config, load_token, resolve_paths, split_host_port


@dataclass(frozen=True)
class Settings:
    paths: Paths
    token: str
    host: str
    port: int
    database_path: Path
    secrets_path: Path
    secret_backend: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        paths = resolve_paths()
        paths.ensure()

        listen = os.environ.get("AILUNE_AI_LISTEN")
        if not listen:
            config = load_app_config()
            listen = config.get("ai_service_listen") or "127.0.0.1:8765"
        host, port = split_host_port(listen)
        if not is_loopback(host):
            raise RuntimeError(f"refusing to bind the AI service to non-loopback address {host!r}")

        backend = os.environ.get("AILUNE_SECRET_BACKEND", "file").strip().lower()
        if backend not in {"file", "secret-service"}:
            raise RuntimeError("AILUNE_SECRET_BACKEND must be 'file' or 'secret-service'")

        return cls(
            paths=paths,
            token=load_token(create=True),
            host=host,
            port=port,
            database_path=paths.db_file,
            secrets_path=paths.config_dir / "secrets.json",
            secret_backend=backend,
            log_level=os.environ.get("AILUNE_LOG_LEVEL", "info").lower(),
        )


def settings_for_tests(tmp_path: Path) -> Settings:
    """Deterministic settings used by tests; no user directories are touched."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    runtime_dir = tmp_path / "runtime"
    cache_dir = tmp_path / "cache"
    for directory in (config_dir, data_dir, runtime_dir, cache_dir):
        directory.mkdir(parents=True, exist_ok=True)
    paths = Paths(
        config_dir=config_dir,
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        config_file=config_dir / "config.json",
        token_file=config_dir / "api-token",
        core_file=runtime_dir / "core.json",
        db_file=data_dir / "ailune.db",
    )
    return Settings(
        paths=paths,
        token="test-token-" + "0" * 40,
        host="127.0.0.1",
        port=0,
        database_path=data_dir / "ailune.db",
        secrets_path=config_dir / "secrets.json",
        secret_backend="file",
        log_level="debug",
    )
