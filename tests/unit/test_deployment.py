from pathlib import Path

from app.deployment import APPROVED_HUD_SHA256, InstallPaths, release_metadata, verify_approved_asset


def test_install_paths_are_home_relative_and_separated(tmp_path: Path):
    paths = InstallPaths.for_home(tmp_path)
    assert paths.application == tmp_path / "JARVIS"
    assert paths.config != paths.data != paths.logs


def test_release_metadata_has_single_version_source():
    metadata = release_metadata(commit="abc123")
    assert metadata["version"] == "0.22.0"
    assert metadata["commit"] == "abc123"


def test_approved_asset_hash_is_verified_without_replacement():
    asset = Path(__file__).parents[2] / "assets/hud/approved-ui.png"
    assert APPROVED_HUD_SHA256
    assert verify_approved_asset(asset)
