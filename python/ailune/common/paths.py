"""Shared filesystem, configuration and token helpers.

The Go core and every Python process resolve the same paths. Environment
variables are honoured for development and for the launcher's child processes.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "ailune"


def _env_dir(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def project_root() -> Path:
    """Locate the checkout containing ``python/pyproject.toml`` and ``renderer``."""
    override = os.environ.get("AILUNE_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if (root / "python" / "pyproject.toml").is_file():
            return root
        raise RuntimeError(f"AILUNE_ROOT={override!r} is not an Ailune checkout")
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "python" / "pyproject.toml").is_file() and (parent / "renderer").is_dir():
            return parent
    raise RuntimeError("cannot locate the Ailune checkout; set AILUNE_ROOT")


@dataclass(frozen=True)
class Paths:
    config_dir: Path
    data_dir: Path
    runtime_dir: Path
    cache_dir: Path
    config_file: Path
    token_file: Path
    core_file: Path
    db_file: Path

    def ensure(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.runtime_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def resolve_paths() -> Paths:
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    runtime_base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"

    config_dir = _env_dir("AILUNE_CONFIG_DIR", config_home / APP_NAME)
    data_dir = _env_dir("AILUNE_DATA_DIR", data_home / APP_NAME)
    runtime_dir = _env_dir(
        "AILUNE_RUNTIME_DIR", Path(runtime_base) / f"{APP_NAME}-{os.getuid()}"
    )
    cache_dir = _env_dir("AILUNE_CACHE_DIR", cache_home / APP_NAME)
    config_file = Path(
        os.environ.get("AILUNE_CONFIG_FILE", str(config_dir / "config.json"))
    ).expanduser()

    return Paths(
        config_dir=config_dir,
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        cache_dir=cache_dir,
        config_file=config_file,
        token_file=config_dir / "api-token",
        core_file=runtime_dir / "core.json",
        db_file=data_dir / "ailune.db",
    )


def load_token(create: bool = True) -> str:
    """Return the shared local API token, creating it if requested."""
    token_env = os.environ.get("AILUNE_TOKEN")
    if token_env:
        return token_env.strip()
    paths = resolve_paths()
    try:
        token = paths.token_file.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except FileNotFoundError:
        pass
    if not create:
        return ""
    paths.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_hex(32)
    paths.token_file.write_text(token + "\n", encoding="utf-8")
    os.chmod(paths.token_file, 0o600)
    return token


def load_app_config() -> dict:
    """Read the core's JSON config without creating it."""
    paths = resolve_paths()
    try:
        return json.loads(paths.config_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def core_url() -> str:
    override = os.environ.get("AILUNE_CORE_URL")
    if override:
        return override.rstrip("/")
    config = load_app_config()
    listen = config.get("listen") or "127.0.0.1:8766"
    return f"http://{listen}"


def ai_url() -> str:
    override = os.environ.get("AILUNE_AI_URL")
    if override:
        return override.rstrip("/")
    config = load_app_config()
    listen = config.get("ai_service_listen") or "127.0.0.1:8765"
    return f"http://{listen}"


def split_host_port(listen: str) -> tuple[str, int]:
    host, _, port = listen.rpartition(":")
    if not host:
        raise ValueError(f"invalid listen address: {listen!r}")
    return host.strip("[]"), int(port)


def is_loopback(host: str) -> bool:
    import ipaddress

    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
