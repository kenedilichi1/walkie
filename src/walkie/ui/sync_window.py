"""PyQt face on the LAN file server: route preview, QR, URL, live file list.

The HTTP server runs in a background thread; this window is only a view onto
its state. Cron keeps building the files — this just serves them and shows
what is ready.
"""

from __future__ import annotations

import threading
from pathlib import Path

import segno
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from walkie import config
from walkie.log import get_logger
from walkie.sync.preview import (
    TILE_PX,
    MapFrame,
    fetch_tile,
    file_status,
    fit_map_frame,
    fit_projection,
    load_street_segments,
    parse_points,
)
from walkie.sync.server import start_server

log = get_logger("sync")

REFRESH_MS = 2500
QR_TARGET_PX = 200
QUIET_ZONE = 4  # QR modules of white border


def qr_pixmap(url: str, target_px: int = QR_TARGET_PX) -> QPixmap:
    """Render a QR for `url` onto a QPixmap (segno matrix + QPainter, no image libs)."""
    qr = segno.make(url, error="m")
    matrix = [list(row) for row in qr.matrix]
    modules = len(matrix) + 2 * QUIET_ZONE
    scale = max(1, target_px // modules)
    px = modules * scale
    image = QImage(px, px, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                x = (c + QUIET_ZONE) * scale
                y = (r + QUIET_ZONE) * scale
                painter.drawRect(x, y, scale, scale)
    painter.end()
    return QPixmap.fromImage(image)


class RouteWidget(QWidget):
    """Draws today's planned loop over a real OpenStreetMap view.

    The map is genuine raster tiles (cached on disk, so it stays offline after
    the first fetch) placed with web-mercator maths, so the route sits on real
    streets. If no tiles are available it falls back to the local street-graph
    lines, then to a plain route.
    """

    def __init__(
        self,
        gpx_path: Path,
        graphml_path: Path,
        tile_cache: Path,
    ) -> None:
        super().__init__()
        self._gpx_path = gpx_path
        self._graphml_path = graphml_path
        self._tile_cache = tile_cache
        self._points: list[tuple[float, float]] = []
        self._streets: list[
            tuple[tuple[float, float], tuple[float, float]]
        ] = []
        self._frame: MapFrame | None = None
        self._tile_images: list[tuple[int, int, QImage]] = []
        self.setMinimumSize(220, 220)

    def refresh(self) -> None:
        self._points = parse_points(self._gpx_path)
        self._streets = load_street_segments(self._graphml_path)
        self._load_map()
        self.update()

    def _load_map(self) -> None:
        """Fetch the tiles for the current route and viewport size."""
        self._tile_images = []
        self._frame = fit_map_frame(
            self._points, self.width(), self.height()
        )
        if self._frame is None:
            return
        for z, x, y in self._frame.tiles():
            data = fetch_tile(self._tile_cache, z, x, y)
            if not data:
                continue
            image = QImage()
            if image.loadFromData(data):
                self._tile_images.append((x, y, image))

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if len(self._points) < 2:
            painter.setPen(QColor("#8b949e"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No route yet"
            )
            painter.end()
            return

        w, h = self.width(), self.height()

        if self._frame is not None and self._tile_images:
            # A real map: blit the tiles, then the route on top.
            for x, y, image in self._tile_images:
                px = int(x * TILE_PX - self._frame.origin_wx)
                py = int(y * TILE_PX - self._frame.origin_wy)
                painter.drawImage(px, py, image)
            path = [self._frame.screen(lat, lon) for lat, lon in self._points]
        else:
            # No tiles (offline / first run): fall back to street-graph lines.
            proj = fit_projection(self._points, w, h, expand=1.35)
            if self._streets:
                painter.setPen(QPen(QColor("#c9d1d9"), 1))
                for a, b in self._streets:
                    ax, ay = proj.point(*a)
                    bx, by = proj.point(*b)
                    painter.drawLine(int(ax), int(ay), int(bx), int(by))
            path = [proj.point(lat, lon) for lat, lon in self._points]

        # The planned walk, bold on top of whatever background we have.
        pen = QPen(QColor("#1a73e8"), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for i in range(len(path) - 1):
            painter.drawLine(
                int(path[i][0]), int(path[i][1]),
                int(path[i + 1][0]), int(path[i + 1][1]),
            )
        painter.setPen(QPen(QColor("white"), 1))
        painter.setBrush(QColor("#3fb950"))  # start
        painter.drawEllipse(int(path[0][0]) - 6, int(path[0][1]) - 6, 12, 12)
        painter.setBrush(QColor("#f85149"))  # end
        painter.drawEllipse(int(path[-1][0]) - 6, int(path[-1][1]) - 6, 12, 12)
        painter.end()

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802 - Qt API
        # The viewport size picks the zoom, so refetch tiles when it changes.
        super().resizeEvent(event)
        self._load_map()


class SyncWindow(QWidget):
    """The window: status line, route preview + QR/URL, and a live file list."""

    def __init__(
        self,
        url: str,
        directory: Path,
        gpx_path: Path,
        graphml_path: Path,
        tile_cache: Path,
    ) -> None:
        super().__init__()
        self.setWindowTitle("walkie")
        self._directory = directory
        self._route = RouteWidget(gpx_path, graphml_path, tile_cache)

        status = QLabel(f"Serving on {url} — scan or open this URL")
        status.setWordWrap(True)

        self._url_label = QLabel(url)
        self._url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._url_label.setStyleSheet("font-weight: bold;")
        qr_label = QLabel()
        qr_label.setPixmap(qr_pixmap(url))
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        right = QVBoxLayout()
        right.addWidget(qr_label)
        right.addWidget(self._url_label)
        hint = QLabel("Scan with your phone camera (same Wi-Fi).")
        hint.setStyleSheet("color: #8b949e;")
        hint.setWordWrap(True)
        right.addWidget(hint)
        right.addStretch(1)

        mid = QHBoxLayout()
        mid.addWidget(self._route, stretch=1)
        mid.addLayout(right)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["File", "Status", "Note"])
        header = self._table.horizontalHeader()
        if header is not None:
            header.setStretchLastSection(True)
        vheader = self._table.verticalHeader()
        if vheader is not None:
            vheader.setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(status)
        layout.addLayout(mid)
        layout.addWidget(self._table)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        self._route.refresh()
        statuses = file_status(self._directory)
        self._table.setRowCount(len(statuses))
        for row, fs in enumerate(statuses):
            self._table.setItem(row, 0, QTableWidgetItem(fs.rel))
            ready = fs.present
            text = f"ready · {fs.size_kb:.0f} KB" if ready else "missing"
            item = QTableWidgetItem(text)
            item.setForeground(QColor("#3fb950") if ready else QColor("#8b949e"))
            self._table.setItem(row, 1, item)
            self._table.setItem(row, 2, QTableWidgetItem(fs.note))
        self._table.resizeColumnsToContents()


def run_serve_window(
    directory: Path = config.OUTPUT_DIR,
    host: str | None = None,
    port: int = 8000,
) -> None:
    """Start the file server in a thread and show the window until it is closed."""
    from walkie.ui.app import ensure_app

    httpd = start_server(directory, host, port)
    bound_port = int(httpd.server_address[1])
    ip = str(httpd.server_address[0])
    url = f"http://{ip}:{bound_port}/"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    log.info(f"Serving {directory} at {url}")

    app = ensure_app()
    app.setApplicationName("walkie-serve")
    gpx_path = directory / str(
        config.DEFAULT_WALK_GPX.relative_to(config.OUTPUT_DIR)
    )
    window = SyncWindow(
        url, directory, gpx_path, config.STREET_GRAPH_PATH, config.MAP_TILE_CACHE
    )
    window.resize(760, 560)
    window.show()
    try:
        app.exec()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        log.info("Server stopped.")
