"""Offscreen smoke test for the serve window pieces (QR + file list)."""

from PyQt6.QtWidgets import QApplication

from walkie.ui.app import ensure_app
from walkie.ui.sync_window import SyncWindow, qr_pixmap


def test_qr_pixmap_is_non_empty():
    ensure_app()
    pixmap = qr_pixmap("http://192.168.1.20:8000/")
    assert not pixmap.isNull()
    assert pixmap.width() >= 100


def test_sync_window_lists_files(tmp_path):
    ensure_app()
    (tmp_path / "today_plan.json").write_bytes(b"x" * 1024)
    window = SyncWindow(
        "http://192.168.1.20:8000/",
        tmp_path,
        tmp_path / "routes" / "walk.gpx",
        tmp_path / "cache" / "streets.graphml",
        tmp_path / "cache" / "map-tiles",
    )
    window.refresh()

    rows = window._table.rowCount()
    assert rows >= 1
    # The present file shows a ready status with a size.
    status = window._table.item(0, 1).text()
    assert status.startswith("ready")
    assert "KB" in status
    window.close()


def test_sync_window_route_placeholder_when_no_gpx(tmp_path):
    ensure_app()
    missing = tmp_path / "routes" / "walk.gpx"
    window = SyncWindow(
        "http://192.168.1.20:8000/",
        tmp_path,
        missing,
        tmp_path / "cache" / "streets.graphml",
        tmp_path / "cache" / "map-tiles",
    )
    window._route.refresh()
    # Fewer than two points -> placeholder, no crash.
    assert len(window._route._points) < 2
    assert QApplication.instance() is not None
    window.close()
