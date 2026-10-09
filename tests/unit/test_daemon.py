"""Tests for the background daemon: config invalidation and the run loop."""

from pathlib import Path

from walkie import daemon


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    import os

    os.utime(path, (mtime, mtime))


def test_config_stamp_reports_change_only_when_file_moves(tmp_path):
    settings = tmp_path / "settings.yaml"
    plan = tmp_path / "user_plan.json"
    _touch(settings, 1000.0)
    _touch(plan, 1000.0)

    stamp = daemon.ConfigStamp((settings, plan))
    assert stamp.changed() is False  # nothing moved yet

    _touch(settings, 2000.0)
    assert stamp.changed() is True  # settings.yaml was rewritten
    assert stamp.changed() is False  # re-armed: not reported twice

    _touch(plan, 3000.0)
    assert stamp.changed() is True  # user_plan.json was rewritten


def test_config_stamp_treats_missing_file_as_zero(tmp_path):
    settings = tmp_path / "settings.yaml"
    plan = tmp_path / "user_plan.json"

    stamp = daemon.ConfigStamp((settings, plan))
    assert stamp.changed() is False

    # Creating the file for the first time counts as a change.
    _touch(plan, 1000.0)
    assert stamp.changed() is True


def test_run_daemon_reloads_config_when_it_changes(tmp_path, monkeypatch):
    """A schedule change in another process must be picked up, not ignored."""
    settings = tmp_path / "settings.yaml"
    plan = tmp_path / "user_plan.json"
    _touch(settings, 1000.0)
    _touch(plan, 1000.0)

    loads: list[int] = []
    passes: list[int] = []

    def fake_load():
        loads.append(1)
        return object(), object()

    def fake_run(**_kwargs):
        passes.append(1)
        if len(passes) == 1:
            _touch(settings, 2000.0)  # another process rewrote settings
        if len(passes) >= 2:
            raise KeyboardInterrupt  # stop after the reload is observed
        return ["did work"]

    monkeypatch.setattr(daemon, "_load_config", fake_load)
    daemon.run_daemon(
        check_interval=0.0,
        run_fn=fake_run,
        sleep_fn=lambda _s: None,
        pid_path=tmp_path / "daemon.pid",
        config_paths=(settings, plan),
    )

    # Loaded once at start, once again after settings.yaml changed.
    assert len(loads) == 2
    assert len(passes) >= 2


def test_run_daemon_survives_a_failing_pass(tmp_path, monkeypatch):
    """One bad pass must not kill the background service."""
    calls: list[int] = []

    def flaky_run(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient failure")
        raise KeyboardInterrupt

    monkeypatch.setattr(daemon, "_load_config", lambda: (object(), object()))
    daemon.run_daemon(
        check_interval=0.0,
        run_fn=flaky_run,
        sleep_fn=lambda _s: None,
        pid_path=tmp_path / "daemon.pid",
        config_paths=(),
    )

    assert len(calls) == 2  # kept going past the failure


def test_run_daemon_refuses_second_instance(tmp_path, monkeypatch):
    """A second daemon must not start (it would double-fire reminders)."""
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(str(_foreign_live_pid()))

    ran: list[int] = []

    def fake_run(**_kwargs):
        ran.append(1)
        raise KeyboardInterrupt

    monkeypatch.setattr(daemon, "_load_config", lambda: (object(), object()))
    daemon.run_daemon(
        check_interval=0.0,
        run_fn=fake_run,
        sleep_fn=lambda _s: None,
        pid_path=pid_path,
        config_paths=(),
    )
    assert ran == []  # never entered the loop


def test_run_daemon_writes_and_clears_pid_file(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"

    def stop_after_one(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(daemon, "_load_config", lambda: (object(), object()))
    daemon.run_daemon(
        check_interval=0.0,
        run_fn=stop_after_one,
        sleep_fn=lambda _s: None,
        pid_path=pid_path,
        config_paths=(),
    )
    # Clean shutdown removed the pid file.
    assert not pid_path.exists()


def test_stop_daemon_without_pid_file_returns_false(tmp_path):
    assert daemon.stop_daemon(pid_path=tmp_path / "daemon.pid") is False


def _foreign_live_pid() -> int:
    """A pid that is alive but is not this process (init/pid 1)."""
    return 1


def test_plist_content_fills_in_real_paths():
    content = daemon._plist_content(
        python=Path("/venv/bin/python"),
        repo_root=Path("/repo"),
        interval=45.0,
        log_path=Path("/logs/walkie.log"),
    )
    assert "<string>/venv/bin/python</string>" in content
    assert "<string>-m</string>" in content
    assert "<string>walkie</string>" in content
    assert "<string>daemon</string>" in content
    assert "<string>45.0</string>" in content
    assert "<string>/repo</string>" in content
    assert "<string>/logs/walkie.log</string>" in content
    assert "<key>KeepAlive</key>" in content
    assert "<key>RunAtLoad</key>" in content


def test_install_daemon_writes_plist_and_registers(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_launchctl(*args: str) -> bool:
        calls.append(list(args))
        return True

    plist = tmp_path / "com.walkie.daemon.plist"
    log_path = tmp_path / "logs" / "walkie.log"
    monkeypatch.setattr(daemon.os, "getuid", lambda: 501)

    ok = daemon.install_daemon(
        interval=30.0,
        python=Path("/venv/bin/python"),
        repo_root=Path("/repo"),
        plist_path=plist,
        log_path=log_path,
        launchctl=fake_launchctl,
    )
    assert ok is True
    # Plist written with real paths.
    text = plist.read_text()
    assert "<string>/venv/bin/python</string>" in text
    assert "<string>/repo</string>" in text
    # Registered and started.
    assert ["bootstrap", "gui/501", str(plist)] in calls
    assert ["kickstart", "gui/501/com.walkie.daemon"] in calls
    # Reload attempted first (idempotent), even though it may fail.
    assert calls[0][0] == "bootout"


def test_install_daemon_is_idempotent_overwrites_plist(tmp_path, monkeypatch):
    plist = tmp_path / "com.walkie.daemon.plist"
    plist.write_text("old contents")
    monkeypatch.setattr(daemon.os, "getuid", lambda: 501)

    ok = daemon.install_daemon(
        interval=30.0,
        python=Path("/venv/bin/python"),
        repo_root=Path("/repo"),
        plist_path=plist,
        log_path=tmp_path / "logs" / "walkie.log",
        launchctl=lambda *_args: True,
    )
    assert ok is True
    assert "old contents" not in plist.read_text()
    assert "<string>/venv/bin/python</string>" in plist.read_text()


def test_install_daemon_fails_when_bootstrap_fails(tmp_path, monkeypatch):
    def fake_launchctl(*args: str) -> bool:
        return args[0] != "bootstrap"  # only bootstrap fails

    monkeypatch.setattr(daemon.os, "getuid", lambda: 501)
    ok = daemon.install_daemon(
        python=Path("/venv/bin/python"),
        repo_root=Path("/repo"),
        plist_path=tmp_path / "com.walkie.daemon.plist",
        log_path=tmp_path / "logs" / "walkie.log",
        launchctl=fake_launchctl,
    )
    assert ok is False


def test_uninstall_daemon_removes_plist_and_pid(tmp_path, monkeypatch):
    plist = tmp_path / "com.walkie.daemon.plist"
    plist.write_text("x")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123")
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.os, "getuid", lambda: 501)

    ok = daemon.uninstall_daemon(
        plist_path=plist,
        pid_path=pid_path,
        launchctl=lambda *args: calls.append(list(args)) or True,
    )
    assert ok is True
    assert not plist.exists()
    assert not pid_path.exists()
    assert ["bootout", "gui/501/com.walkie.daemon"] in calls


def test_uninstall_daemon_without_agent_is_calm(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon.os, "getuid", lambda: 501)
    ok = daemon.uninstall_daemon(
        plist_path=tmp_path / "com.walkie.daemon.plist",
        pid_path=tmp_path / "daemon.pid",
        launchctl=lambda *_args: False,
    )
    # Nothing installed: no exception, reports failure but stays calm.
    assert ok is False
