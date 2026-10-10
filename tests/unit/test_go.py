"""Tests for `walkie go` — the one-command bootstrap (setup gaps -> build)."""

from __future__ import annotations

from pathlib import Path

import pytest

from walkie import cli, config, go
from walkie.models import UserPlan

READY_SETTINGS = """\
region:
  name: "lagos"
  pbf: "{pbf}"

location:
  lat: 6.5244
  lon: 3.3792
  timezone: "Africa/Lagos"
"""


def write_settings(path: Path, pbf: Path) -> None:
    path.write_text(READY_SETTINGS.format(pbf=pbf))


def write_example(path: Path) -> None:
    path.write_text('location:\n  lat: 0.0\n  lon: 0.0\n')


def test_ensure_settings_file_copies_example(tmp_path):
    example = tmp_path / "settings.example.yaml"
    example.write_text("region:\n  name: x\n")
    settings = tmp_path / "settings.yaml"

    assert go.ensure_settings_file(settings, example) is True
    assert settings.read_text() == example.read_text()
    assert go.ensure_settings_file(settings, example) is False  # second run


def test_ensure_settings_file_without_example_raises(tmp_path):
    with pytest.raises(config.ConfigError):
        go.ensure_settings_file(tmp_path / "settings.yaml", tmp_path / "nope.yaml")


def test_needs_region_when_settings_missing(tmp_path):
    assert go.needs_region(tmp_path / "settings.yaml") is True


def test_needs_region_for_placeholder_coords(tmp_path):
    example = tmp_path / "settings.example.yaml"
    write_example(example)
    settings = tmp_path / "settings.yaml"
    go.ensure_settings_file(settings, example)
    assert go.needs_region(settings) is True


def test_needs_region_false_when_ready(tmp_path):
    pbf = tmp_path / "lagos.osm.pbf"
    pbf.write_bytes(b"x")
    settings = tmp_path / "settings.yaml"
    write_settings(settings, pbf)
    assert go.needs_region(settings) is False


def test_needs_region_when_pbf_file_missing(tmp_path):
    settings = tmp_path / "settings.yaml"
    write_settings(settings, tmp_path / "gone.osm.pbf")
    assert go.needs_region(settings) is True


def test_ensure_region_skips_when_ready(tmp_path, monkeypatch):
    pbf = tmp_path / "lagos.osm.pbf"
    pbf.write_bytes(b"x")
    settings = tmp_path / "settings.yaml"
    write_settings(settings, pbf)
    called = []
    monkeypatch.setattr(
        go.region, "execute", lambda args: called.append(args)
    )

    go.ensure_region(settings)
    assert called == []


def test_ensure_region_runs_execute_when_missing(tmp_path, monkeypatch):
    example = tmp_path / "settings.example.yaml"
    write_example(example)
    settings = tmp_path / "settings.yaml"
    go.ensure_settings_file(settings, example)
    called = []
    monkeypatch.setattr(
        go.region, "execute", lambda args: called.append(args)
    )

    go.ensure_region(settings)
    assert len(called) == 1
    assert called[0].dry_run is False
    assert called[0].lat is None


def test_ensure_user_plan_noop_when_saved(tmp_path):
    plan_path = tmp_path / "user_plan.json"
    config.save_user_plan(UserPlan(), plan_path)

    def boom():
        raise AssertionError("wizard must not open")

    go.ensure_user_plan(run_wizard=boom, plan_path=plan_path)


def test_ensure_user_plan_opens_wizard_when_missing(tmp_path):
    plan_path = tmp_path / "user_plan.json"

    def wizard():
        config.save_user_plan(UserPlan(), plan_path)

    go.ensure_user_plan(run_wizard=wizard, plan_path=plan_path)
    assert plan_path.exists()


def test_ensure_user_plan_cancelled_aborts(tmp_path):
    with pytest.raises(config.ConfigError, match="setup not finished"):
        go.ensure_user_plan(
            run_wizard=lambda: None,
            plan_path=tmp_path / "user_plan.json",
        )


def test_ensure_user_plan_wizard_import_error(tmp_path):
    def no_qt():
        raise ImportError("PyQt6")

    with pytest.raises(config.ConfigError, match="make wizard"):
        go.ensure_user_plan(run_wizard=no_qt, plan_path=tmp_path / "x.json")


def test_prepare_runs_steps_in_order(tmp_path, monkeypatch):
    example = tmp_path / "settings.example.yaml"
    write_example(example)
    settings = tmp_path / "settings.yaml"
    plan_path = tmp_path / "user_plan.json"
    steps = []

    monkeypatch.setattr(
        go, "ensure_region", lambda path: steps.append("region")
    )

    def wizard():
        steps.append("wizard")
        config.save_user_plan(UserPlan(), plan_path)

    go.prepare(settings_path=settings, plan_path=plan_path, run_wizard=wizard)
    assert steps == ["region", "wizard"]


def test_parser_go_flags():
    args = cli.build_parser().parse_args(
        ["go", "--build-only", "--force", "--no-window", "--port", "9000"]
    )
    assert args.command == "go"
    assert args.build_only is True
    assert args.force is True
    assert args.no_window is True
    assert args.port == 9000


def test_main_defaults_to_go(monkeypatch):
    seen = []
    monkeypatch.setitem(cli.HANDLERS, "go", lambda args: seen.append(args.command))
    assert cli.main([]) == 0
    assert seen == ["go"]


def test_cmd_go_build_only_skips_serve(monkeypatch):
    import argparse

    from walkie import go as go_mod

    events = []
    monkeypatch.setattr(go_mod, "prepare", lambda: events.append("prepare"))
    monkeypatch.setattr(
        "walkie.pipeline.run", lambda force=False: events.append("run") or []
    )
    monkeypatch.setattr(
        cli, "_serve_files", lambda port, no_window: events.append("serve")
    )
    args = argparse.Namespace(force=False, build_only=True, no_window=False, port=8000)
    cli.cmd_go(args)
    assert events == ["prepare", "run"]


def test_cmd_go_serves_by_default(monkeypatch):
    import argparse

    from walkie import go as go_mod

    events = []
    monkeypatch.setattr(go_mod, "prepare", lambda: events.append("prepare"))
    monkeypatch.setattr(
        "walkie.pipeline.run", lambda force=False: events.append("run") or []
    )
    monkeypatch.setattr(
        cli, "_serve_files", lambda port, no_window: events.append((port, no_window))
    )
    args = argparse.Namespace(force=False, build_only=False, no_window=True, port=8123)
    cli.cmd_go(args)
    assert events == ["prepare", "run", (8123, True)]
