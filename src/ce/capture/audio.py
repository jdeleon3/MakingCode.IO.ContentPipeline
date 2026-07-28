"""Audio capture and transcription (TDD 10.2, WP-04).

`ingest()` copies a source recording into `captures/audio/raw/` and records
a `Capture`. `transcribe()` preprocesses it with ffmpeg, sends it to a
transcription API, and runs the `transcript_clean` LLM pass — producing
`raw.txt` (verbatim) and `clean.md` (readable, but preserving every
self-correction, tangent, and hedge verbatim; see prompts/transcript_clean.md).

ffmpeg and the transcription API are both reached through small Protocols
(`Preprocessor`, `TranscriptionClient`, `Splitter`) with real, subprocess/
httpx-based default implementations — same shape as WP-02's `LLMClient`.
This isn't optional here the way it was mostly-a-style-choice in WP-02: this
dev environment has no `ffmpeg` binary at all, so real subprocess calls
can't be exercised by the automated test suite regardless of preference.
Tests inject fakes; the real implementations are exercised manually on a
machine that has `ffmpeg` installed (which `ce doctor` verifies).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from ce import store
from ce.config import EngineConfig, PreprocessConfig
from ce.exit_codes import CaptureError
from ce.llm.gateway import Gateway
from ce.models import Capture, CaptureDerived, CaptureMoment, CaptureType

# OpenAI's audio transcription endpoint rejects files over 25MB; TDD 10.2
# chunks anything over 24MB to leave headroom.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


# ---------------------------------------------------------------------------
# Preprocessing (ffmpeg) — TDD 10.2
# ---------------------------------------------------------------------------


class Preprocessor(Protocol):
    def run(self, input_path: Path, output_path: Path, config: PreprocessConfig) -> None: ...


def _silence_filter(config: PreprocessConfig) -> str:
    filters = [
        "silenceremove=stop_periods=-1:"
        f"stop_duration={config.silence_min_sec}:"
        f"stop_threshold={config.silence_threshold_db}dB"
    ]
    if config.loudnorm:
        filters.append("loudnorm")
    return ",".join(filters)


class FfmpegPreprocessor:
    """Silence removal + loudness normalization + downmix to 16kHz mono —
    mitigates the silence-hallucination ASR failure mode (TDD 10.2)."""

    def run(self, input_path: Path, output_path: Path, config: PreprocessConfig) -> None:
        if shutil.which("ffmpeg") is None:
            raise CaptureError("ffmpeg is not on PATH", hint="ce doctor")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            _silence_filter(config),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        if proc.returncode != 0:
            raise CaptureError(f"ffmpeg preprocessing failed: {proc.stderr[-2000:]}")


# ---------------------------------------------------------------------------
# Chunking (TDD 10.2: "files > 24MB are split on silence boundaries")
# ---------------------------------------------------------------------------


class Splitter(Protocol):
    def split(
        self, path: Path, out_dir: Path, config: PreprocessConfig
    ) -> list[tuple[Path, float]]:
        """Returns `(chunk_path, start_offset_seconds)` pairs, in order."""
        ...


class FfmpegSilenceSplitter:
    """Splits an oversized file on silence boundaries (never mid-word),
    sized to keep each chunk under `MAX_UPLOAD_BYTES`. One ffmpeg pass
    (`silencedetect` + the `Duration:` line ffmpeg always prints) supplies
    both the silence timestamps and the total duration needed to size
    chunks, so no separate `ffprobe` call is needed.
    """

    def split(
        self, path: Path, out_dir: Path, config: PreprocessConfig
    ) -> list[tuple[Path, float]]:
        stderr = self._analyze(path, config)
        duration = self._parse_duration(stderr)
        silence_midpoints = self._parse_silence_midpoints(stderr)

        total_size = path.stat().st_size
        bytes_per_sec = total_size / duration if duration else 0
        target_sec = (MAX_UPLOAD_BYTES * 0.9) / bytes_per_sec if bytes_per_sec else duration

        cut_points = [0.0]
        next_target = target_sec
        for midpoint in silence_midpoints:
            if midpoint >= next_target:
                cut_points.append(midpoint)
                next_target = midpoint + target_sec
        if not cut_points or cut_points[-1] != duration:
            cut_points.append(duration)

        out_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[tuple[Path, float]] = []
        for i in range(len(cut_points) - 1):
            start, end = cut_points[i], cut_points[i + 1]
            chunk_path = out_dir / f"chunk-{i:03d}{path.suffix}"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-ss",
                str(start),
                "-to",
                str(end),
                "-c",
                "copy",
                str(chunk_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
            if proc.returncode != 0:
                raise CaptureError(f"ffmpeg chunking failed: {proc.stderr[-2000:]}")
            chunks.append((chunk_path, start))
        return chunks

    def _analyze(self, path: Path, config: PreprocessConfig) -> str:
        cmd = [
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={config.silence_threshold_db}dB:d={config.silence_min_sec}",
            "-f",
            "null",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        return proc.stderr

    @staticmethod
    def _parse_duration(stderr: str) -> float:
        match = _DURATION_RE.search(stderr)
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    @staticmethod
    def _parse_silence_midpoints(stderr: str) -> list[float]:
        starts = [float(m) for m in _SILENCE_START_RE.findall(stderr)]
        ends = [float(m) for m in _SILENCE_END_RE.findall(stderr)]
        return [(s + e) / 2 for s, e in zip(starts, ends, strict=False)]


def _format_offset(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Transcription (OpenAI) — TDD 10.2
# ---------------------------------------------------------------------------


class TranscriptionClient(Protocol):
    def transcribe(self, path: Path, *, model: str, vocabulary: list[str]) -> str: ...


class OpenAITranscriptionClient:
    """httpx-based client for OpenAI's audio transcription endpoint — same
    no-SDK rationale as WP-02's `AnthropicClient`: one multipart POST
    doesn't justify an SDK dependency.
    """

    _URL = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(self, *, api_key: str | None = None, timeout: float = 120.0) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._timeout = timeout

    def transcribe(self, path: Path, *, model: str, vocabulary: list[str]) -> str:
        if not self._api_key:
            raise CaptureError("OPENAI_API_KEY is not set", hint="ce doctor")
        data = {"model": model}
        if vocabulary:
            data["prompt"] = ", ".join(vocabulary)
        with path.open("rb") as handle:
            response = httpx.post(
                self._URL,
                files={"file": (path.name, handle)},
                data=data,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        response.raise_for_status()
        return response.json()["text"]


# ---------------------------------------------------------------------------
# ingest() / transcribe() — TDD 10.2 public interface
# ---------------------------------------------------------------------------


def ingest(
    data_root: Path,
    path: Path,
    project: str,
    *,
    moment: CaptureMoment = CaptureMoment.IN_SITU,
    context: str | None = None,
    captured_at: datetime | None = None,
) -> Capture:
    """Copy `path` into `captures/audio/raw/` and record a `Capture`. Does
    not transcribe — call `transcribe()` next."""
    if not path.exists():
        raise CaptureError(f"audio file not found: {path}")

    captured_at = captured_at or datetime.now(UTC)
    capture_id = store.generate_capture_id(data_root, project, captured_at)

    project_root = store.project_dir(data_root, project)
    raw_dir = project_root / "captures" / "audio" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{capture_id}{path.suffix}"
    shutil.copy2(path, dest)

    capture = Capture(
        id=capture_id,
        project=project,
        type=CaptureType.AUDIO,
        moment=moment,
        captured_at=captured_at,
        source_path=dest.relative_to(project_root),
        context=context,
    )
    store.write_capture(data_root, capture)
    return capture


def transcribe(
    data_root: Path,
    capture: Capture,
    config: EngineConfig,
    *,
    gateway: Gateway,
    preprocessor: Preprocessor | None = None,
    transcription_client: TranscriptionClient | None = None,
    splitter: Splitter | None = None,
    force: bool = False,
) -> Capture:
    """Idempotent: if `raw.txt`/`clean.md` already exist for this capture,
    re-running is a no-op unless `force=True` (TDD 12 WP-04 Done-when).

    Idempotency is a direct existing-output check rather than
    `store.py`'s `hash_inputs`/manifest primitives — those are one
    `_manifest.json` per *directory*, but `captures/audio/transcript/`
    holds outputs for every capture in the project, so a shared manifest
    there would collide across captures. Checking `capture.derived` plus
    file existence is simpler and sufficient for a single capture whose
    source audio never changes after ingest.
    """
    if capture.type != CaptureType.AUDIO:
        raise CaptureError(f"capture {capture.id!r} is not an audio capture")

    project_root = store.project_dir(data_root, capture.project)
    transcript_dir = project_root / "captures" / "audio" / "transcript"
    raw_txt_path = transcript_dir / f"{capture.id}.raw.txt"
    clean_md_path = transcript_dir / f"{capture.id}.clean.md"

    already_done = (
        not force
        and capture.derived is not None
        and capture.derived.transcript_raw is not None
        and capture.derived.transcript_clean is not None
        and (project_root / capture.derived.transcript_raw).exists()
        and (project_root / capture.derived.transcript_clean).exists()
    )
    if already_done:
        return capture

    source_path = project_root / capture.source_path
    if not source_path.exists():
        raise CaptureError(f"capture source file not found: {source_path}")

    preprocessor = preprocessor or FfmpegPreprocessor()
    transcription_client = transcription_client or OpenAITranscriptionClient()
    splitter = splitter or FfmpegSilenceSplitter()

    transcript_dir.mkdir(parents=True, exist_ok=True)
    preprocessed_path = transcript_dir / f"{capture.id}.preprocessed.wav"
    preprocessor.run(source_path, preprocessed_path, config.transcription.preprocess)

    try:
        if preprocessed_path.stat().st_size > MAX_UPLOAD_BYTES:
            chunk_dir = transcript_dir / f"{capture.id}.chunks"
            chunks = splitter.split(preprocessed_path, chunk_dir, config.transcription.preprocess)
            segments = []
            for chunk_path, offset in chunks:
                text = transcription_client.transcribe(
                    chunk_path,
                    model=config.transcription.model,
                    vocabulary=config.transcription.vocabulary,
                )
                segments.append(f"[+{_format_offset(offset)}]\n{text}")
            raw_text = "\n\n".join(segments)
            shutil.rmtree(chunk_dir, ignore_errors=True)
        else:
            raw_text = transcription_client.transcribe(
                preprocessed_path,
                model=config.transcription.model,
                vocabulary=config.transcription.vocabulary,
            )
    finally:
        preprocessed_path.unlink(missing_ok=True)

    raw_txt_path.write_text(raw_text, encoding="utf-8")

    clean_result = gateway.complete(
        "transcript_clean",
        {"raw_text": raw_text, "vocabulary": ", ".join(config.transcription.vocabulary)},
        tier="cheap",
    )
    clean_md_path.write_text(clean_result.content, encoding="utf-8")

    updated = capture.model_copy(
        update={
            "derived": CaptureDerived(
                transcript_raw=raw_txt_path.relative_to(project_root),
                transcript_clean=clean_md_path.relative_to(project_root),
                duration_sec=capture.derived.duration_sec if capture.derived else None,
            )
        }
    )
    store.write_capture(data_root, updated)
    return updated
