from walkie import cli


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
    assert args.lat == 1.5
    assert args.name == "X"


def test_parser_requires_command():
    import pytest

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])
