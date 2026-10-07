"""Voice cues: GPX turns -> timed cues -> voice-only MP3.

Fixture: tests/fixtures/square_loop.gpx — 100 m square near the equator,
5 points, timestamps 75 s per side => 3 "Turn right" corners at 75/150/225 s,
loop = 300 s, total = 400 m.
"""

import re
import subprocess
from pathlib import Path

import pytest

from walkie import config
from walkie.media.voice import (
    AudioSpec,
    VoiceError,
    build_walk_audio,
    encode_mp3,
    ensure_voice_model,
    parse_walk,
    plan_cues,
    render_cues,
    write_wav,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "square_loop.gpx"
SPEC = AudioSpec(sample_rate=22050, sample_width=2, channels=1)


def stub_synth(text: str) -> tuple[AudioSpec, bytes]:
    return SPEC, b"\x01\x00" * (SPEC.sample_rate // 10)  # 0.1 s of int16 value 1


def probe_duration(path: Path) -> float:
    import imageio_ffmpeg

    proc = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)],
        capture_output=True, text=True,
    )
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    assert match, proc.stderr[-400:]
    h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
    return h * 3600 + m * 60 + s


def test_parse_walk_turns_match_gpx_corners():
    walk = parse_walk(FIXTURE)
    assert len(walk.turns) == 3
    assert walk.loop_seconds == pytest.approx(300, abs=0.5)
    assert walk.total_meters == pytest.approx(400, abs=8)
    assert [t.at_seconds for t in walk.turns] == pytest.approx([75, 150, 225], abs=1)
    assert [t.at_meters for t in walk.turns] == pytest.approx([100, 200, 300], abs=8)


def test_instructions_match_gpx_turns():
    walk = parse_walk(FIXTURE)
    assert [t.instruction for t in walk.turns] == ["Turn right", "Turn right", "Turn right"]


def test_left_turn_detected(tmp_path):
    # go north, then turn west: a left turn
    gpx = tmp_path / "left.gpx"
    gpx.write_text(
        '<?xml version="1.0"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="6.0" lon="8.0"></trkpt>'
        '<trkpt lat="6.001" lon="8.0"></trkpt>'
        '<trkpt lat="6.001" lon="7.999"></trkpt>'
        "</trkseg></trk></gpx>"
    )
    walk = parse_walk(gpx)
    assert [t.instruction for t in walk.turns] == ["Turn left"]


def test_plan_cues_cover_start_turns_and_finish():
    walk = parse_walk(FIXTURE)
    cues = plan_cues(walk)
    assert len(cues) == 5
    assert cues[0].at_seconds == 0.0 and "Start" in cues[0].text
    assert [c.text for c in cues[1:-1]] == ["Turn right"] * 3
    assert cues[-1].at_seconds == walk.loop_seconds
    assert "arrived" in cues[-1].text


def test_render_covers_loop_time_and_places_cues():
    walk = parse_walk(FIXTURE)
    cues = plan_cues(walk)
    spec, pcm = render_cues(cues, walk.loop_seconds, stub_synth)
    duration = len(pcm) / (spec.sample_rate * spec.sample_width * spec.channels)
    assert duration >= walk.loop_seconds
    # each cue's non-silence audio starts exactly at its timestamp
    for cue in cues:
        offset = int(cue.at_seconds * spec.sample_rate) * spec.sample_width * spec.channels
        assert pcm[offset : offset + 4] == b"\x01\x00\x01\x00", cue


def test_render_rejects_format_change_mid_walk():
    def flaky(text):
        if text != cues[0].text:
            return AudioSpec(16000, 2, 1), b"\x00"
        return SPEC, b"\x01\x00"

    cues = plan_cues(parse_walk(FIXTURE))
    with pytest.raises(VoiceError, match="format changed"):
        render_cues(cues, 300.0, flaky)


def test_render_rejects_empty_cues():
    with pytest.raises(VoiceError, match="no cues"):
        render_cues([], 300.0, stub_synth)


def test_parse_walk_missing_file(tmp_path):
    with pytest.raises(VoiceError, match="not found"):
        parse_walk(tmp_path / "nope.gpx")


def test_parse_walk_too_few_points(tmp_path):
    gpx = tmp_path / "short.gpx"
    gpx.write_text(
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="6.0" lon="8.0"></trkpt><trkpt lat="6.001" lon="8.0"></trkpt>'
        "</trkseg></trk></gpx>"
    )
    with pytest.raises(VoiceError, match="at least 3"):
        parse_walk(gpx)


def test_build_walk_audio_end_to_end_stub(tmp_path):
    out = tmp_path / "walk_audio.mp3"
    result = build_walk_audio(FIXTURE, out_path=out, synth=stub_synth)
    assert out.exists() and out.stat().st_size > 0
    assert result.cues == 5
    assert result.loop_seconds == pytest.approx(300, abs=0.5)
    assert not out.with_suffix(".wav").exists()  # intermediate cleaned up
    # spec test: playback covers loop time — probed from the real mp3
    assert probe_duration(out) == pytest.approx(300, abs=2)


def test_encode_mp3_failure_is_user_facing(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    with pytest.raises(VoiceError, match="ffmpeg failed"):
        encode_mp3(bad, tmp_path / "out.mp3")


def test_write_wav_roundtrip(tmp_path):
    path = tmp_path / "x.wav"
    write_wav(path, SPEC, b"\x01\x00" * 100)
    assert path.stat().st_size > 100


def test_ensure_voice_model_existing_file(tmp_path):
    model = tmp_path / "en_US-lessac-medium.onnx"
    model.write_bytes(b"stub")
    assert ensure_voice_model(model) == model


def test_ensure_voice_model_bad_name(tmp_path):
    with pytest.raises(VoiceError, match="not a"):
        ensure_voice_model(tmp_path / "my-voice.onnx")


def test_ensure_voice_model_downloads_once(tmp_path, monkeypatch):
    downloads = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, size):
            yield b"data"

    monkeypatch.setattr(
        "walkie.media.voice.requests.get", lambda url, **kw: downloads.append(url) or FakeResp()
    )
    model = tmp_path / "voices" / "en_US-lessac-medium.onnx"
    ensure_voice_model(model)
    assert model.exists()
    assert model.with_suffix(".json").exists() or Path(str(model) + ".json").exists()
    assert len(downloads) == 2
    assert all("piper-voices" in url for url in downloads)
    # second call: no more downloads
    ensure_voice_model(model)
    assert len(downloads) == 2


def test_build_walk_audio_requires_model_when_no_synth(tmp_path):
    with pytest.raises(VoiceError, match="voice_model"):
        build_walk_audio(FIXTURE, out_path=tmp_path / "x.mp3")


@pytest.mark.skipif(
    not (config.ROOT / "data/voices/en_US-lessac-medium.onnx").exists(),
    reason="piper voice model not downloaded yet (run: walkie voice once)",
)
def test_live_piper_covers_loop_time(tmp_path):
    """Real Piper synthesis: mp3 duration covers the 300 s loop."""
    out = tmp_path / "live.mp3"
    model = config.ROOT / "data/voices/en_US-lessac-medium.onnx"
    result = build_walk_audio(FIXTURE, out_path=out, voice_model=model)
    assert result.cues == 5
    assert probe_duration(out) == pytest.approx(300, abs=3)
