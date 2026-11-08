"""Parse and validate Live2D Cubism ``.model3.json`` manifests.

The validator is deliberately strict about referenced files escaping the model
directory. Rendering itself is provided by the Web renderer; this module only
inspects the model so a broken import is caught before it reaches the pet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODEL_SUFFIX = ".model3.json"
TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB safety limit for copying


@dataclass
class Issue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path, "severity": self.severity}


@dataclass
class ModelManifest:
    root: Path
    entry: Path
    name: str
    version: int | None
    moc: str | None = None
    textures: list[Path] = field(default_factory=list)
    physics: Path | None = None
    pose: Path | None = None
    expressions: list[dict[str, str]] = field(default_factory=list)
    motions: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    groups: list[dict[str, str]] = field(default_factory=list)
    hit_areas: list[dict[str, str]] = field(default_factory=list)
    referenced_files: list[Path] = field(default_factory=list)
    total_bytes: int = 0
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def thumbnail(self) -> Path | None:
        return self.textures[0] if self.textures else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "root": str(self.root),
            "entry": str(self.entry),
            "entry_relative": self.entry.relative_to(self.root).as_posix(),
            "version": self.version,
            "moc": self.moc,
            "textures": [str(p) for p in self.textures],
            "thumbnail": str(self.thumbnail) if self.thumbnail else None,
            "physics": str(self.physics) if self.physics else None,
            "pose": str(self.pose) if self.pose else None,
            "expressions": self.expressions,
            "motions": self.motions,
            "groups": self.groups,
            "hit_areas": self.hit_areas,
            "total_bytes": self.total_bytes,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "counts": {
                "textures": len(self.textures),
                "expressions": len(self.expressions),
                "motion_groups": len(self.motions),
                "motions": sum(len(v) for v in self.motions.values()),
            },
        }


def discover_entries(directory: Path, max_depth: int = 3) -> list[Path]:
    """Find model entry files under a directory, shallowest first."""
    directory = directory.expanduser()
    if not directory.is_dir():
        return []
    found: list[Path] = []
    base_depth = len(directory.parts)
    for path in sorted(directory.rglob("*" + MODEL_SUFFIX)):
        if len(path.parts) - base_depth > max_depth:
            continue
        found.append(path)
    found.sort(key=lambda p: (len(p.relative_to(directory).parts), str(p)))
    return found


def validate_model(model_path: str | Path, entry: str | Path | None = None) -> ModelManifest:
    """Validate a model directory/entry and return a report.

    ``model_path`` may point at the model directory or directly at an entry
    file. When ``entry`` is omitted, exactly one entry under ``model_path`` is
    selected automatically.
    """
    raw = Path(model_path).expanduser()
    if raw.is_file() and raw.name.endswith(MODEL_SUFFIX):
        root = raw.parent
        entry_path = raw
    else:
        root = raw
        entry_path = Path(entry).expanduser() if entry else None
        if entry_path is not None and not entry_path.is_absolute():
            entry_path = root / entry_path
        if entry_path is None:
            candidates = discover_entries(root)
            if len(candidates) == 1:
                entry_path = candidates[0]
            elif not candidates:
                entry_path = root / f"{root.name}{MODEL_SUFFIX}"
            else:
                entry_path = candidates[0]

    try:
        root = root.resolve(strict=False)
    except OSError:
        pass
    try:
        entry_path = entry_path.resolve(strict=False)
    except OSError:
        pass

    manifest = ModelManifest(
        root=root,
        entry=entry_path,
        name=_model_name(entry_path),
        version=None,
    )

    if not _inside(root, entry_path):
        manifest.errors.append(
            Issue("entry_outside_root", "the model entry must be inside the model directory", str(entry_path))
        )
        return manifest
    if not entry_path.is_file():
        manifest.errors.append(
            Issue("entry_missing", "the model entry file was not found", str(entry_path))
        )
        return manifest
    if not entry_path.name.endswith(MODEL_SUFFIX):
        manifest.errors.append(
            Issue("entry_extension", "the model entry must end with .model3.json", str(entry_path))
        )
        return manifest

    try:
        payload = json.loads(entry_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        manifest.errors.append(Issue("entry_encoding", "the model entry is not valid UTF-8", str(entry_path)))
        return manifest
    except json.JSONDecodeError as exc:
        manifest.errors.append(
            Issue("entry_json", f"the model entry is not valid JSON (line {exc.lineno})", str(entry_path))
        )
        return manifest

    if not isinstance(payload, dict):
        manifest.errors.append(Issue("entry_shape", "the model entry must contain a JSON object", str(entry_path)))
        return manifest

    version = payload.get("Version")
    if isinstance(version, int):
        manifest.version = version
    else:
        manifest.warnings.append(
            Issue("version_missing", "the model entry has no integer Version field", str(entry_path), "warning")
        )

    refs = payload.get("FileReferences")
    if not isinstance(refs, dict):
        manifest.errors.append(
            Issue("references_missing", "FileReferences is missing or invalid", str(entry_path))
        )
        return _finish(manifest)

    _check_moc(manifest, refs.get("Moc"))
    _check_textures(manifest, refs.get("Textures"))
    _check_optional_file(manifest, refs.get("Physics"), "physics", ".physics3.json")
    _check_optional_file(manifest, refs.get("Pose"), "pose", ".pose3.json")
    _check_expressions(manifest, refs.get("Expressions"))
    _check_motions(manifest, refs.get("Motions"))
    _collect_groups(manifest, payload.get("Groups"))
    _collect_hit_areas(manifest, payload.get("HitAreas"))
    _check_user_data(manifest, refs.get("UserData"))
    _check_display_info(manifest, refs.get("DisplayInfo"))

    if not manifest.expressions:
        manifest.warnings.append(Issue("no_expressions", "the model does not define expressions", severity="warning"))
    if not manifest.motions:
        manifest.warnings.append(Issue("no_motions", "the model does not define motions", severity="warning"))
    if not any(group.get("name") == "EyeBlink" for group in manifest.groups):
        manifest.warnings.append(
            Issue("no_eyeblink", "the model has no EyeBlink parameter group", severity="warning")
        )
    if not any(group.get("name") == "LipSync" for group in manifest.groups):
        manifest.warnings.append(
            Issue("no_lipsync", "the model has no LipSync parameter group", severity="warning")
        )
    return _finish(manifest)


def _finish(manifest: ModelManifest) -> ModelManifest:
    seen: set[Path] = set()
    total = 0
    for path in manifest.referenced_files:
        if path in seen:
            continue
        seen.add(path)
        try:
            total += path.stat().st_size
        except OSError:
            continue
    manifest.total_bytes = total
    if total > MAX_MODEL_BYTES:
        manifest.errors.append(
            Issue(
                "model_too_large",
                f"the model is larger than the {MAX_MODEL_BYTES // (1024**3)} GiB safety limit",
                str(manifest.root),
            )
        )
    return manifest


def _resolve_ref(manifest: ModelManifest, value: Any, *, required: bool, kind: str, suffix: str = "") -> Path | None:
    if not isinstance(value, str) or not value.strip():
        if required:
            manifest.errors.append(
                Issue(f"{kind}_missing", f"the {kind} reference is missing", str(manifest.entry))
            )
        return None
    candidate = (manifest.root / value).resolve(strict=False)
    if not _inside(manifest.root, candidate):
        manifest.errors.append(
            Issue(f"{kind}_outside_root", f"the {kind} reference escapes the model directory", value)
        )
        return None
    if suffix and not candidate.name.endswith(suffix):
        manifest.errors.append(
            Issue(f"{kind}_extension", f"the {kind} file must end with {suffix}", value)
        )
        return None
    if not candidate.is_file():
        manifest.errors.append(
            Issue(f"{kind}_file_missing", f"the referenced {kind} file does not exist", value)
        )
        return None
    manifest.referenced_files.append(candidate)
    return candidate


def _check_moc(manifest: ModelManifest, value: Any) -> None:
    path = _resolve_ref(manifest, value, required=True, kind="moc", suffix=".moc3")
    if path:
        manifest.moc = path.relative_to(manifest.root).as_posix()


def _check_textures(manifest: ModelManifest, value: Any) -> None:
    if not isinstance(value, list) or not value:
        manifest.errors.append(Issue("textures_missing", "the model defines no textures", str(manifest.entry)))
        return
    for item in value:
        path = _resolve_ref(manifest, item, required=True, kind="texture")
        if path is None:
            continue
        if path.suffix.lower() not in TEXTURE_SUFFIXES:
            manifest.warnings.append(
                Issue("texture_format", f"unusual texture format: {path.suffix}", str(path), "warning")
            )
        manifest.textures.append(path)


def _check_optional_file(manifest: ModelManifest, value: Any, kind: str, suffix: str) -> None:
    if value is None:
        return
    path = _resolve_ref(manifest, value, required=False, kind=kind, suffix=suffix)
    if path is not None:
        setattr(manifest, kind, path)


def _check_expressions(manifest: ModelManifest, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        manifest.errors.append(Issue("expressions_shape", "Expressions must be a list", str(manifest.entry)))
        return
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("Name"), str):
            manifest.errors.append(Issue("expression_shape", "an expression is missing its Name", str(manifest.entry)))
            continue
        path = _resolve_ref(manifest, item.get("File"), required=True, kind="expression", suffix=".exp3.json")
        if path is not None:
            manifest.expressions.append(
                {"name": item["Name"], "file": path.relative_to(manifest.root).as_posix()}
            )


def _check_motions(manifest: ModelManifest, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        manifest.errors.append(Issue("motions_shape", "Motions must be an object", str(manifest.entry)))
        return
    for group, items in value.items():
        if not isinstance(group, str) or not isinstance(items, list):
            manifest.errors.append(
                Issue("motion_group_shape", f"invalid motion group: {group!r}", str(manifest.entry))
            )
            continue
        collected: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                manifest.errors.append(
                    Issue("motion_shape", f"a motion in group {group} is not an object", str(manifest.entry))
                )
                continue
            path = _resolve_ref(manifest, item.get("File"), required=True, kind="motion", suffix=".motion3.json")
            if path is None:
                continue
            entry = {"file": path.relative_to(manifest.root).as_posix()}
            if isinstance(item.get("Sound"), str) and item["Sound"]:
                sound = _resolve_ref(manifest, item["Sound"], required=False, kind="sound")
                if sound is not None:
                    entry["sound"] = sound.relative_to(manifest.root).as_posix()
            collected.append(entry)
        if collected:
            manifest.motions[group] = collected


def _collect_groups(manifest: ModelManifest, value: Any) -> None:
    if not isinstance(value, list):
        return
    for group in value:
        if not isinstance(group, dict) or not isinstance(group.get("Name"), str):
            continue
        target = group.get("Target")
        manifest.groups.append(
            {
                "name": group["Name"],
                "target": target if isinstance(target, str) else "",
                "ids": ",".join(item for item in group.get("Ids", []) if isinstance(item, str)),
            }
        )


def _collect_hit_areas(manifest: ModelManifest, value: Any) -> None:
    if not isinstance(value, list):
        return
    for area in value:
        if isinstance(area, dict) and isinstance(area.get("Name"), str):
            manifest.hit_areas.append(
                {
                    "name": area["Name"],
                    "id": area.get("Id") if isinstance(area.get("Id"), str) else "",
                }
            )


def _check_user_data(manifest: ModelManifest, value: Any) -> None:
    if isinstance(value, str) and value:
        _resolve_ref(manifest, value, required=False, kind="user_data", suffix=".userdata3.json")
    elif isinstance(value, dict):
        pass


def _check_display_info(manifest: ModelManifest, value: Any) -> None:
    if isinstance(value, str) and value:
        _resolve_ref(manifest, value, required=False, kind="display_info", suffix=".cdi3.json")


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _model_name(entry: Path) -> str:
    name = entry.name
    if name.endswith(MODEL_SUFFIX):
        name = name[: -len(MODEL_SUFFIX)]
    elif name.endswith(".json"):
        name = name[:-5]
    name = re.sub(r"[_-]+", " ", name).strip()
    return name or entry.parent.name
