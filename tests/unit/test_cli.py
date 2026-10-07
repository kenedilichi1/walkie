import pytest

from walkie import cli, config


def test_parser_suggest_flags():
    args = cli.build_parser().parse_args(["suggest", "--edit"])
    assert args.command == "suggest"
    assert args.edit is True
    assert args.force_new is False


def test_parser_region_flags():
    args = cli.build_parser().parse_args(
        ["region", "--dry-run", "--lat", "1.5", "--lon", "2.5", "--name", "X"]
    )
    assert args.command == "region"
    assert args.dry_run is True
    assert args.lat == pytest.approx(1.5)
    assert args.name == "X"


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_parser_plan_flags():
    args = cli.build_parser().parse_args(["plan", "--force-new"])
    assert args.command == "plan"
    assert args.force_new is True


def test_parser_voice_defaults_to_walk_gpx(tmp_path):
    args = cli.build_parser().parse_args(["voice"])
    assert args.command == "voice"
    assert args.gpx == config.DEFAULT_WALK_GPX
    args = cli.build_parser().parse_args(["voice", "--gpx", str(tmp_path / "a.gpx")])
    assert args.gpx == tmp_path / "a.gpx"


def test_main_exit_codes(monkeypatch):
    from walkie import config, region

    # success
    monkeypatch.setitem(cli.HANDLERS, "remind", lambda args: None)
    assert cli.main(["remind"]) == 0

    # user/config error -> 1
    def bad_config(args):
        raise config.ConfigError("bad settings")

    monkeypatch.setitem(cli.HANDLERS, "suggest", bad_config)
    assert cli.main(["suggest"]) == 1

    # region failure -> 1
    def bad_region(args):
        raise region.RegionError("no extract")

    monkeypatch.setitem(cli.HANDLERS, "region", bad_region)
    assert cli.main(["region"]) == 1

    # Ctrl-C -> 130
    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.HANDLERS, "daemon", interrupted)
    assert cli.main(["daemon"]) == 130
