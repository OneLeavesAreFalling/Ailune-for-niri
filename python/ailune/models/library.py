"""Copy a validated model into Ailune's managed library."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .manifest import ModelManifest, validate_model


@dataclass
class ImportResult:
    entry: Path
    report: object

    def to_dict(self) -> dict:
        return {"entry": str(self.entry), "report": self.report.to_dict()}


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "-", value, flags=re.UNICODE).strip("-_").lower()
    return value[:60] or "model"


def destination_for(manifest: ModelManifest, library_dir: Path) -> Path:
    digest = hashlib.sha1(str(manifest.entry).encode("utf-8")).hexdigest()[:8]
    base = library_dir / f"{slugify(manifest.name)}-{digest}"
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = library_dir / f"{base.name}-{counter}"
        counter += 1
    return candidate


def copy_into_library(manifest: ModelManifest, library_dir: Path) -> ImportResult:
    """Copy only the files referenced by the manifest, preserving structure."""
    if not manifest.ok:
        raise ValueError("cannot import a model with validation errors")
    library_dir = library_dir.expanduser().resolve()
    library_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = destination_for(manifest, library_dir)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        files = {manifest.entry, *manifest.referenced_files}
        for source in files:
            relative = source.relative_to(manifest.root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        entry_relative = manifest.entry.relative_to(manifest.root)
        new_entry = destination / entry_relative
        report = validate_model(destination, new_entry)
        if not report.ok:
            raise ValueError("the copied model failed validation")
        return ImportResult(entry=new_entry, report=report)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
