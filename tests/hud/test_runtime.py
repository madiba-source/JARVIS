import hashlib

from PySide6.QtCore import QSize

from app.hud.runtime import ASSET_PATH, ASSET_SHA256, ASSET_SIZE, HudRuntime, _HudWidget


def test_approved_asset_is_unchanged() -> None:
    assert HudRuntime.verify_asset()
    assert hashlib.sha256(ASSET_PATH.read_bytes()).hexdigest() == ASSET_SHA256


def test_hud_starts_with_locked_aspect_ratio_and_cleans_up(qapp) -> None:
    runtime = HudRuntime()

    assert runtime.start()
    assert runtime.available
    assert runtime.widget is not None
    runtime.widget.resize(QSize(1024, 1024))
    runtime.widget.repaint()
    assert runtime.widget.minimumSize().width() == ASSET_SIZE[0]
    assert runtime.widget.minimumSize().height() == ASSET_SIZE[1]
    runtime.disable()
    assert not runtime.enabled
    runtime.close()
    assert not runtime.available
    assert runtime.widget is None


def test_hud_animation_is_time_based_and_bounded(qapp) -> None:
    runtime = HudRuntime()
    assert runtime.start()
    widget = runtime.widget
    assert isinstance(widget, _HudWidget)
    first = widget._started
    widget._started = first + 2.2
    widget.repaint()
    assert widget._enabled
    runtime.close()


def test_hud_render_failure_is_graceful(qapp, tmp_path) -> None:
    runtime = HudRuntime(asset_path=tmp_path / "missing.png")

    assert runtime.start() is False
    assert runtime.available is False
    assert runtime.widget is None
    assert runtime.error == "ValueError"


import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
