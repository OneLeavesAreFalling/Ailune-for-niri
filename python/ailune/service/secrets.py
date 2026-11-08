"""Secret storage for provider API keys.

The file backend is a 0600 JSON file. It protects against other local users and
accidental logging, but it is not encryption. The optional Secret Service
backend stores keys in the desktop keyring via ``secret-tool``.

Ailune never returns stored keys through the API and never logs them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path


class SecretError(RuntimeError):
    pass


class SecretStore:
    backend_name = "unknown"

    def get(self, ref: str) -> str | None:
        raise NotImplementedError

    def set(self, ref: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, ref: str) -> None:
        raise NotImplementedError


class FileSecretStore(SecretStore):
    backend_name = "file"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items() if isinstance(v, str)}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)

    def get(self, ref: str) -> str | None:
        with self._lock:
            return self._read().get(ref)

    def set(self, ref: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[ref] = value
            self._write(data)

    def delete(self, ref: str) -> None:
        with self._lock:
            data = self._read()
            if ref in data:
                del data[ref]
                self._write(data)


class SecretServiceStore(SecretStore):
    backend_name = "secret-service"

    def __init__(self) -> None:
        if not shutil.which("secret-tool"):
            raise SecretError("secret-tool is not installed")
        self._lock = threading.Lock()

    @staticmethod
    def _attrs(ref: str) -> list[str]:
        return ["service", "ailune", "ref", ref]

    def get(self, ref: str) -> str | None:
        with self._lock:
            proc = subprocess.run(
                ["secret-tool", "lookup", *self._attrs(ref)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        if proc.returncode != 0:
            return None
        value = proc.stdout.strip()
        return value or None

    def set(self, ref: str, value: str) -> None:
        with self._lock:
            proc = subprocess.run(
                ["secret-tool", "store", "--label", f"Ailune provider key ({ref})", *self._attrs(ref)],
                input=value,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        if proc.returncode != 0:
            raise SecretError("could not store the API key in the desktop keyring")

    def delete(self, ref: str) -> None:
        with self._lock:
            subprocess.run(
                ["secret-tool", "clear", *self._attrs(ref)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )


def make_secret_store(path: Path, backend: str) -> SecretStore:
    if backend == "secret-service":
        return SecretServiceStore()
    return FileSecretStore(path)
