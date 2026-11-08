from __future__ import annotations

import json
from pathlib import Path

from ailune.models.library import copy_into_library
from ailune.models.manifest import discover_entries, validate_model


def test_valid_model(sample_model: Path):
    report = validate_model(sample_model)
    assert report.ok
    assert report.entry.name == "Aria.model3.json"
    assert len(report.textures) == 1
    assert sum(len(v) for v in report.motions.values()) == 2
    assert len(report.expressions) == 1
    assert report.total_bytes > 0
    data = report.to_dict()
    assert data["counts"]["motion_groups"] == 2
    assert data["errors"] == []


def test_missing_texture_is_reported(sample_model: Path):
    (sample_model / "textures" / "texture_00.png").unlink()
    report = validate_model(sample_model)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "texture_file_missing" in codes


def test_path_traversal_is_rejected(sample_model: Path):
    outside = sample_model.parent / "outside.moc3"
    outside.write_bytes(b"MOC3")
    manifest = json.loads((sample_model / "Aria.model3.json").read_text(encoding="utf-8"))
    manifest["FileReferences"]["Moc"] = "../outside.moc3"
    (sample_model / "Aria.model3.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_model(sample_model)
    assert not report.ok
    assert any(issue.code == "moc_outside_root" for issue in report.errors)


def test_bad_json(sample_model: Path):
    (sample_model / "Aria.model3.json").write_text("{not json", encoding="utf-8")
    report = validate_model(sample_model)
    assert not report.ok
    assert report.errors[0].code == "entry_json"


def test_entry_discovery(sample_model: Path):
    entries = discover_entries(sample_model.parent)
    assert sample_model / "Aria.model3.json" in entries


def test_copy_into_library_only_copies_references(sample_model: Path, tmp_path: Path):
    (sample_model / "notes.txt").write_text("not part of the model", encoding="utf-8")
    report = validate_model(sample_model)
    library = tmp_path / "library"
    result = copy_into_library(report, library)
    assert result.report.ok
    assert result.entry.is_file()
    assert not (result.entry.parent / "notes.txt").exists()
    assert (result.entry.parent / "textures" / "texture_00.png").is_file()
    assert str(library) in str(result.entry)


def test_invalid_copy_is_refused(sample_model: Path, tmp_path: Path):
    (sample_model / "textures" / "texture_00.png").unlink()
    report = validate_model(sample_model)
    assert not report.ok
    try:
        copy_into_library(report, tmp_path / "library")
    except ValueError:
        pass
    else:
        raise AssertionError("expected copy to be refused")
