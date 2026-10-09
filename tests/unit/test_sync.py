"""Step 7: quote-flavoured notifications + LAN download server."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from walkie import config
from walkie.storage import write_json
from walkie.suggest import reminders
from walkie.sync import SyncError, notify, server


def test_with_quote_prefixes_given_quote():
    body = notify.with_quote("30 min at 16:30.", quote="Shoes on. Phone down. Go.")
    assert body == "Shoes on. Phone down. Go.\n30 min at 16:30."


def test_with_quote_uses_config_picker(monkeypatch):
    monkeypatch.setattr(config, "pick_quote", lambda: "Walk on.")
    assert notify.with_quote("detail").startswith("Walk on.")


def test_with_quote_caps_body_length():
    body = notify.with_quote("x" * 1000, quote="q")
    assert len(body) <= notify.MAX_BODY


def _proposal(when: str = "16:30", for_date: str = "2026-10-07") -> dict:
    return {
        "suggested_time": when,
        "duration_minutes": 30,
        "location_type": "shade",
        "reason": "test",
        "approve_by": f"{for_date}T{when}",
        "for_date": for_date,
        "weather_fingerprint": "unavailable",
    }


def test_reminder_notification_carries_quote(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "pick_quote", lambda: "Stand up from your computer.")
    proposal_path = tmp_path / "proposal.json"
    write_json(proposal_path, _proposal("16:30"))
    notified: list[tuple[str, str]] = []
    actions = reminders.check_reminders(
        datetime.fromisoformat("2026-10-07T16:00"),
        lambda title, message: notified.append((title, message)),
        proposal_path=proposal_path,
        today_path=tmp_path / "today_plan.json",
        state_path=tmp_path / "state.json",
    )
    assert actions == ["reminder-30"]
    title, message = notified[0]
    assert "walk at 16:30" in title
    assert message.startswith("Stand up from your computer.")
    assert "30 min at 16:30" in message  # proposal detail survives the quote


def _served_output(tmp_path):
    directory = tmp_path / "output"
    (directory / "routes").mkdir(parents=True)
    (directory / "today_plan.json").write_text('{"approved_by": "test"}')
    (directory / "routes" / "walk.gpx").write_text("<gpx version='1.1'/>")
    return directory


def _running(directory):
    httpd = server.start_server(directory, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def test_landing_page_lists_files_and_serves_gpx(tmp_path):
    directory = _served_output(tmp_path)
    httpd, thread = _running(directory)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base}/", timeout=5) as resp:
            page = resp.read().decode()
        assert "routes/walk.gpx" in page
        assert "today_plan.json" in page
        assert "walk_audio.mp3" in page
        assert "missing" in page  # voice not built in this fixture

        with urllib.request.urlopen(f"{base}/?v=1", timeout=5) as resp:
            assert resp.status == 200  # a query string still hits the page

        with urllib.request.urlopen(f"{base}/routes/walk.gpx", timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == b"<gpx version='1.1'/>"

        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{base}/audio/walk_audio.mp3", timeout=5)
        assert err.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_refuses_path_traversal(tmp_path):
    served = tmp_path / "output"
    served.mkdir()
    (tmp_path / "secret.txt").write_text("top secret")
    httpd, thread = _running(served)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{base}/../secret.txt", timeout=5)
        assert err.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_start_server_port_in_use_raises(tmp_path):
    first = server.start_server(tmp_path, host="127.0.0.1", port=0)
    try:
        with pytest.raises(SyncError, match="cannot listen"):
            server.start_server(
                tmp_path, host="127.0.0.1", port=first.server_address[1]
            )
    finally:
        first.server_close()


def test_start_server_missing_directory(tmp_path):
    with pytest.raises(SyncError, match="not found"):
        server.start_server(tmp_path / "nope")


def test_lan_ip_is_an_ip():
    ip = server.lan_ip()
    assert ip.count(".") == 3  # never raises; falls back to 127.0.0.1


def test_serve_prints_qr_for_the_landing_url(tmp_path, monkeypatch):
    """serve() renders a QR encoding http://<ip>:<port>/ so the phone can scan it."""
    directory = _served_output(tmp_path)
    seen: list[str] = []

    def _capture(url: str) -> str:
        seen.append(url)
        return "QR"

    monkeypatch.setattr(server, "qr_blocks", _capture)
    # serve_forever would block; raise so serve() unwinds after logging
    monkeypatch.setattr(
        "http.server.ThreadingHTTPServer.serve_forever",
        lambda self: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    server.serve(directory, host="127.0.0.1", port=0)
    assert seen and seen[0].startswith("http://127.0.0.1:")
    assert seen[0].endswith("/")
