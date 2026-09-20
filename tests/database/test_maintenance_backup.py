import json
import zipfile
from pathlib import Path

import pytest

from app.maintenance import BackupError, BackupManager, RestoreMode


def test_backup_verify_and_restore_preserves_data(tmp_path: Path):
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "data").mkdir()
    (source / "config" / "settings.env").write_text("privacy=offline_only")
    (source / "data" / "memory.db").write_text("memory")
    manager = BackupManager(source, tmp_path / "backups")
    archive = manager.create(source_commit="abc")
    manifest = manager.verify(archive)
    assert {entry.path for entry in manifest.entries} == {"config/settings.env", "data/memory.db"}
    target = tmp_path / "target"
    target.mkdir()
    restored = manager.restore(archive, target)
    assert set(restored) == {"config/settings.env", "data/memory.db"}
    assert (target / "data/memory.db").read_text() == "memory"


def test_corrupted_checksum_and_traversal_fail_closed(tmp_path: Path):
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "config" / "safe").write_text("safe")
    manager = BackupManager(source, tmp_path / "backups")
    archive = manager.create()
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(corrupt, "w") as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "config/safe":
                data = b"changed"
            output.writestr(item, data)
    with pytest.raises(BackupError, match="checksum"):
        manager.verify(corrupt)


def test_malformed_manifest_and_unsupported_component_are_rejected(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    manager = BackupManager(source, tmp_path / "backups")
    with pytest.raises(BackupError, match="component"):
        manager.create(components=("logs",))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("MANIFEST.json", json.dumps({"format_version": 1, "entries": [{"path": "../escape", "component": "config", "size": 0, "sha256": ""}]}))
    with pytest.raises(BackupError):
        manager.verify(bad)


def test_selective_restore_does_not_restore_unselected_components(tmp_path: Path):
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "data").mkdir()
    (source / "config" / "settings").write_text("config")
    (source / "data" / "memory").write_text("data")
    manager = BackupManager(source, tmp_path / "backups")
    archive = manager.create()
    target = tmp_path / "target"
    target.mkdir()
    manager.restore(archive, target, mode=RestoreMode.CONFIG_ONLY)
    assert (target / "config/settings").exists()
    assert not (target / "data/memory").exists()
