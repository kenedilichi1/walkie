"""Turn cues from walk.gpx rendered into one voice-only MP3 (Piper TTS).

The MP3 carries spoken cues only — start, turns, arrival. It deliberately
contains no music and no beat/BPM matching: play your own local music in
your own player alongside it while walkie narrates the route.

Pipeline: parse GPX -> timed turn cues -> Piper synthesis -> silence-padded
timeline (so playback covers the whole loop) -> output/audio/walk_audio.mp3.
"""

from __future__ import annotations

import math
import re
import subprocess
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gpxpy
import requests
from gpxpy.gpx import GPXException

from walkie import config
from walkie.geo import haversine_m
from walkie.log import get_logger

log = get_logger("voice")

WALKING_SPEED_MPS = config.WALKING_SPEED_MPS
TURN_THRESHOLD_DEG = 40.0
MIN_TURN_SPACING_M = 15.0
START_TEXT = "Start of your walk. Follow the route."
FINISH_TEXT = "You have arrived. Walk complete."
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICE_NAME_RE = re.compile(
    r"^(?P<lang>[a-z]{2,3})_(?P<country>[A-Z]{2})"
    r"-(?P<style>[a-z0-9_]+)-(?P<quality>x_low|low|medium|high)$"
)


class VoiceError(Exception):
    """Voice generation failed; the message is user-facing."""


@dataclass(frozen=True)
class Turn:
    instruction: str
    at_seconds: float
    at_meters: float


@dataclass(frozen=True)
class Walk:
    turns: tuple[Turn, ...]
    loop_seconds: float
    total_meters: float


@dataclass(frozen=True)
class Cue:
    at_seconds: float
    text: str


@dataclass(frozen=True)
class AudioSpec:
    sample_rate: int
    sample_width: int
    channels: int


@dataclass(frozen=True)
class BuildResult:
    path: Path
    cues: int
    loop_seconds: float


Synth = Callable[[str], tuple[AudioSpec, bytes]]


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angle_delta(old_deg: float, new_deg: float) -> float:
    delta = (new_deg - old_deg + 180.0) % 360.0 - 180.0
    return delta + 360.0 if delta == -180.0 else delta


def _instruction_for(delta_deg: float) -> str | None:
    if abs(delta_deg) < TURN_THRESHOLD_DEG:
        return None
    return "Turn right" if delta_deg > 0 else "Turn left"


def _load_points(gpx_path: Path) -> list[tuple[float, float, datetime | None]]:
    if not gpx_path.exists():
        raise VoiceError(f"{gpx_path} not found — build the route first (step 5)")
    try:
        with open(gpx_path, encoding="utf-8") as handle:
            gpx = gpxpy.parse(handle)
    except (OSError, GPXException) as exc:
        raise VoiceError(f"could not read {gpx_path}: {exc}") from exc
    points = [
        (p.latitude, p.longitude, p.time)
        for track in gpx.tracks
        for segment in track.segments
        for p in segment.points
    ]
    if len(points) < 3:
        raise VoiceError(f"{gpx_path} needs at least 3 track points, got {len(points)}")
    return points


def _cumulative_m(
    points: Sequence[tuple[float, float, datetime | None]],
) -> list[float]:
    cumulative = [0.0]
    for prev, curr in zip(points, points[1:], strict=False):
        cumulative.append(
            cumulative[-1] + haversine_m(prev[0], prev[1], curr[0], curr[1])
        )
    return cumulative


def _loop_seconds(
    points: Sequence[tuple[float, float, datetime | None]], total_m: float
) -> tuple[float, bool]:
    """(loop_seconds, has_times) — GPX timestamps win, walking speed estimates."""
    times = [p[2] for p in points]
    first, last = times[0], times[-1]
    if first is not None and last is not None and all(t is not None for t in times):
        span = (last - first).total_seconds()
        if span > 0:
            return span, True
    return total_m / WALKING_SPEED_MPS, False


def _turn_candidates(
    points: Sequence[tuple[float, float, datetime | None]],
    cumulative: Sequence[float],
    has_times: bool,
) -> list[Turn]:
    turns: list[Turn] = []
    for i in range(1, len(points) - 1):
        prev, curr, nxt = points[i - 1], points[i], points[i + 1]
        old = _bearing_deg(prev[0], prev[1], curr[0], curr[1])
        new = _bearing_deg(curr[0], curr[1], nxt[0], nxt[1])
        delta = _angle_delta(old, new)
        instruction = _instruction_for(delta)
        if instruction is None:
            continue
        at_m = cumulative[i]
        at_s = _time_at(points, i, at_m, has_times)
        turns.append(Turn(instruction, at_s, at_m))
    return turns


def _time_at(
    points: Sequence[tuple[float, float, datetime | None]],
    index: int,
    at_m: float,
    has_times: bool,
) -> float:
    start, here = points[0][2], points[index][2]
    if has_times and start is not None and here is not None:
        return (here - start).total_seconds()
    return at_m / WALKING_SPEED_MPS


def _select_turns(candidates: Sequence[Turn]) -> list[Turn]:
    """Keep the sharpest turn per corner; drop repeats within spacing."""
    accepted: list[Turn] = []
    for turn in sorted(candidates, key=lambda t: -abs(t.at_meters)):
        if any(abs(turn.at_meters - a.at_meters) < MIN_TURN_SPACING_M for a in accepted):
            continue
        accepted.append(turn)
    return sorted(accepted, key=lambda t: t.at_meters)


def parse_walk(gpx_path: Path) -> Walk:
    """GPX track -> timed turns, loop length, total distance."""
    points = _load_points(gpx_path)
    cumulative = _cumulative_m(points)
    total_m = cumulative[-1]
    loop_s, has_times = _loop_seconds(points, total_m)
    turns = tuple(_select_turns(_turn_candidates(points, cumulative, has_times)))
    if not has_times:
        loop_s = max(loop_s, turns[-1].at_seconds if turns else 0.0)
    return Walk(turns, loop_s, total_m)


def plan_cues(walk: Walk) -> list[Cue]:
    """Turn list -> timed spoken cues (start, turns, arrival)."""
    cues = [Cue(0.0, START_TEXT)]
    cues.extend(Cue(t.at_seconds, t.instruction) for t in walk.turns)
    cues.append(Cue(float(walk.loop_seconds), FINISH_TEXT))
    return cues


def ensure_voice_model(model_path: Path) -> Path:
    """Download the Piper voice model (once) into data/voices/."""
    if model_path.exists():
        return model_path
    match = VOICE_NAME_RE.match(model_path.stem)
    if match is None:
        raise VoiceError(
            f"voice model missing at {model_path} and its name is not a "
            "standard Piper voice (e.g. en_US-lessac-medium)"
        )
    parts = match.groupdict()
    voice_dir = f"{parts['lang']}/{parts['lang']}_{parts['country']}"
    stem = model_path.stem
    for suffix in (".onnx", ".onnx.json"):
        url = f"{HF_BASE}/{voice_dir}/{parts['style']}/{parts['quality']}/{stem}{suffix}"
        _download(url, Path(f"{model_path}{suffix.removeprefix('.onnx')}"))
    return model_path


def _download(url: str, dest: Path) -> None:
    log.info(f"Downloading voice model part: {dest.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            part = dest.with_suffix(dest.suffix + ".part")
            with open(part, "wb") as handle:
                for chunk in resp.iter_content(1 << 16):
                    handle.write(chunk)
            part.replace(dest)
    except (requests.RequestException, OSError) as exc:
        raise VoiceError(
            f"could not download {url}: {exc} — place the file at {dest} manually "
            "(network needed once; works offline afterwards)"
        ) from exc


def piper_synth(model_path: Path) -> Synth:
    """Load the Piper voice; each call renders one cue to 16-bit PCM."""
    from piper import PiperVoice

    try:
        voice = PiperVoice.load(str(model_path))
    except Exception as exc:  # noqa: BLE001 — onnxruntime raises non-standard errors
        raise VoiceError(f"could not load voice model {model_path}: {exc}") from exc

    def synth(text: str) -> tuple[AudioSpec, bytes]:
        chunks = list(voice.synthesize(text))
        if not chunks:
            raise VoiceError(f"no audio synthesized for: {text!r}")
        first = chunks[0]
        spec = AudioSpec(first.sample_rate, first.sample_width, first.sample_channels)
        return spec, b"".join(c.audio_int16_bytes for c in chunks)

    return synth


def render_cues(
    cues: Sequence[Cue], loop_seconds: float, synth: Synth
) -> tuple[AudioSpec, bytes]:
    """Place every cue at its timestamp over a silence buffer covering the loop."""
    if not cues:
        raise VoiceError("no cues to render")
    spec: AudioSpec | None = None
    placed: list[tuple[float, bytes]] = []
    for cue in cues:
        cue_spec, pcm = synth(cue.text)
        if spec is None:
            spec = cue_spec
        elif cue_spec != spec:
            raise VoiceError("cue audio format changed mid-walk")
        placed.append((cue.at_seconds, pcm))
    if spec is None:
        raise VoiceError("no cues to render")
    end_s = max([loop_seconds] + [t + _pcm_seconds(p, spec) for t, p in placed])
    buf = bytearray(_seconds_to_bytes(end_s, spec))
    for at_s, pcm in placed:
        _place(buf, pcm, at_s, spec)
    return spec, bytes(buf)


def _pcm_seconds(pcm: bytes, spec: AudioSpec) -> float:
    return len(pcm) / (spec.sample_rate * spec.sample_width * spec.channels)


def _seconds_to_bytes(seconds: float, spec: AudioSpec) -> int:
    samples = int(math.ceil(seconds * spec.sample_rate))
    return samples * spec.sample_width * spec.channels


def _place(buf: bytearray, pcm: bytes, at_s: float, spec: AudioSpec) -> None:
    offset = _seconds_to_bytes(at_s, spec)
    end = min(offset + len(pcm), len(buf))
    if offset < len(buf):
        buf[offset:end] = pcm[: end - offset]


def write_wav(path: Path, spec: AudioSpec, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(spec.channels)
        handle.setsampwidth(spec.sample_width)
        handle.setframerate(spec.sample_rate)
        handle.writeframes(pcm)


def encode_mp3(wav_path: Path, mp3_path: Path) -> None:
    import imageio_ffmpeg

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", str(wav_path),
             "-codec:a", "libmp3lame", "-q:a", "4", str(mp3_path)],
            capture_output=True, text=True,
        )
    except OSError as exc:
        raise VoiceError(f"ffmpeg could not run: {exc}") from exc
    if proc.returncode != 0:
        raise VoiceError(f"ffmpeg failed: {proc.stderr[-400:]}")


def build_walk_audio(
    gpx_path: Path,
    out_path: Path = config.WALK_AUDIO_PATH,
    voice_model: Path | None = None,
    synth: Synth | None = None,
) -> BuildResult:
    """walk.gpx -> output/audio/walk_audio.mp3 (spoken cues, no music)."""
    walk = parse_walk(gpx_path)
    cues = plan_cues(walk)
    if synth is None:
        if voice_model is None:
            raise VoiceError("voice_model path required to synthesize cues")
        synth = piper_synth(ensure_voice_model(voice_model))
    spec, pcm = render_cues(cues, walk.loop_seconds, synth)
    wav_path = out_path.with_suffix(".wav")
    write_wav(wav_path, spec, pcm)
    encode_mp3(wav_path, out_path)
    wav_path.unlink(missing_ok=True)
    log.info(
        f"Voice track: {len(cues)} cues covering {walk.loop_seconds:.0f}s "
        f"({walk.total_meters:.0f} m) — play your own music alongside it"
    )
    return BuildResult(out_path, len(cues), walk.loop_seconds)
