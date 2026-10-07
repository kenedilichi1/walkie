import pytest

from walkie import config
from walkie.config import ConfigError

VALID_YAML = """
location:
  lat: 6.31625
  lon: 8.11691
  timezone: Africa/Lagos
weather:
  cache: "cache/weather_today.json"
  forecast_url: "https://api.open-meteo.com/v1/forecast"
ollama:
  host: "http://localhost:11434"
  model: "llama3.2:3b"
"""


def write_settings(tmp_path, text):
    path = tmp_path / "settings.yaml"
    path.write_text(text)
    return path


def test_load_settings_valid(tmp_path):
    settings = config.load_settings(write_settings(tmp_path, VALID_YAML))
    assert settings.lat == pytest.approx(6.31625)
    assert settings.lon == pytest.approx(8.11691)
    assert settings.timezone == "Africa/Lagos"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.weather_cache.is_absolute()
    assert str(settings.weather_cache).endswith("cache/weather_today.json")


def test_load_settings_rejects_null_island(tmp_path):
    path = write_settings(tmp_path, "location:\n  lat: 0.0\n  lon: 0.0\n")
    with pytest.raises(ConfigError, match="make region"):
        config.load_settings(path)


def test_load_settings_rejects_sub_mm_null_island(tmp_path):
    path = write_settings(tmp_path, "location:\n  lat: 1e-12\n  lon: 1e-12\n")
    with pytest.raises(ConfigError, match="make region"):
        config.load_settings(path)


def test_load_settings_accepts_near_zero_real_coordinates(tmp_path):
    # equator / prime-meridian adjacent is a real place, unlike the placeholders
    path = write_settings(tmp_path, "location:\n  lat: 0.0001\n  lon: 0.0\n")
    settings = config.load_settings(path)
    assert settings.lat == pytest.approx(0.0001)


def test_load_settings_rejects_out_of_range(tmp_path):
    path = write_settings(tmp_path, "location:\n  lat: 91.0\n  lon: 8.1\n")
    with pytest.raises(ConfigError, match="out of range"):
        config.load_settings(path)


def test_load_settings_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="make setup"):
        config.load_settings(tmp_path / "nope.yaml")


def test_load_settings_rejects_garbage_yaml(tmp_path):
    path = write_settings(tmp_path, "location: [unclosed")
    with pytest.raises(ConfigError, match="could not read"):
        config.load_settings(path)


def test_load_ollama_config_defaults_when_file_missing(tmp_path):
    host, model = config.load_ollama_config(tmp_path / "nope.yaml")
    assert host == config.DEFAULT_OLLAMA_HOST
    assert model == config.DEFAULT_OLLAMA_MODEL


def test_load_ollama_config_reads_settings(tmp_path):
    host, model = config.load_ollama_config(write_settings(tmp_path, VALID_YAML))
    assert host == "http://localhost:11434"
    assert model == "llama3.2:3b"


def test_load_quotes_skips_comments_and_blanks(tmp_path):
    path = tmp_path / "quotes.txt"
    path.write_text("# comment\n\nWalk on.\n  \nStand up.\n")
    assert config.load_quotes(path) == ["Walk on.", "Stand up."]


def test_load_quotes_falls_back_when_empty(tmp_path):
    missing = tmp_path / "quotes.txt"
    assert config.load_quotes(missing) == [config.DEFAULT_QUOTE]
    missing.write_text("# only comments\n")
    assert config.load_quotes(missing) == [config.DEFAULT_QUOTE]


def test_load_user_plan_missing(tmp_path):
    with pytest.raises(ConfigError, match="walkie wizard"):
        config.load_user_plan(tmp_path / "user_plan.json")


def test_voice_model_defaults_when_section_missing(tmp_path):
    settings = config.load_settings(write_settings(tmp_path, VALID_YAML))
    assert settings.voice_model.is_absolute()
    assert str(settings.voice_model).endswith("data/voices/en_US-lessac-medium.onnx")


def test_voice_model_reads_settings_override(tmp_path):
    text = VALID_YAML + 'voice:\n  model: "data/voices/custom.onnx"\n'
    settings = config.load_settings(write_settings(tmp_path, text))
    assert str(settings.voice_model).endswith("data/voices/custom.onnx")
