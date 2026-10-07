from walkie.storage import read_json, write_json


def test_read_json_missing_file(tmp_path):
    assert read_json(tmp_path / "nope.json") is None


def test_read_json_corrupt_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert read_json(path) is None


def test_read_json_non_object_returns_none(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]")
    assert read_json(path) is None


def test_write_json_roundtrip_and_parents(tmp_path):
    path = tmp_path / "deep" / "nested" / "data.json"
    write_json(path, {"a": 1, "b": [1, 2]})
    assert read_json(path) == {"a": 1, "b": [1, 2]}
    assert not path.with_suffix(".json.tmp").exists()


def test_write_json_is_atomic_overwrites(tmp_path):
    path = tmp_path / "data.json"
    write_json(path, {"version": 1})
    write_json(path, {"version": 2})
    assert read_json(path) == {"version": 2}
