"""WP-04 acceptance (TDD 12): a 90-second fixture produces raw.txt and
clean.md; re-running is a no-op; clean.md retains a self-correction
present in the fixture (golden test).

`ffmpeg` isn't installed in this dev/build environment (confirmed via
`ce doctor`), so `Preprocessor`/`Splitter`/`TranscriptionClient` are all
exercised here via fakes injected through the `capture.audio` Protocols —
same DI approach WP-02 established for `LLMClient`. The real
`FfmpegPreprocessor`/`FfmpegSilenceSplitter`/`OpenAITranscriptionClient`
are exercised manually on a machine that has `ffmpeg` installed.

The "self-correction" claim itself is a property of the real `raw_text`
content and the real `transcript_clean` prompt/model — this test verifies
the *plumbing* (raw text goes in, comes back out untouched in raw.txt; the
gateway's response is what lands in clean.md) rather than a real ASR/LLM
judgment call, which no automated test can make without a network call.
"""

from pathlib import Path

import pytest

from ce.capture.audio import transcribe
from ce.exit_codes import CaptureError
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import Capture, CaptureMoment, CaptureType

FIXTURE_WAV = Path(__file__).parent / "fixtures" / "audio" / "self-correction-90s.wav"

SELF_CORRECTION_RAW = (
    "So I pointed the streaming job at postgres -- wait, no, actually it "
    "was mysql, not postgres, my bad -- and the join kept spilling to disk."
)


class FakePreprocessor:
    def __init__(self, output_bytes: bytes = b"fake-preprocessed-audio"):
        self.output_bytes = output_bytes
        self.calls: list[tuple[Path, Path]] = []

    def run(self, input_path: Path, output_path: Path, config) -> None:
        self.calls.append((input_path, output_path))
        output_path.write_bytes(self.output_bytes)


class FakeTranscriptionClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def transcribe(self, path: Path, *, model: str, vocabulary: list[str]) -> str:
        self.calls.append({"path": path, "model": model, "vocabulary": vocabulary})
        return self._responses.pop(0)


class FakeSplitter:
    def __init__(self, chunks: list[tuple[Path, float]]):
        self.chunks = chunks
        self.calls: list[Path] = []

    def split(self, path: Path, out_dir: Path, config) -> list[tuple[Path, float]]:
        self.calls.append(path)
        return self.chunks


class FakeLLMClient:
    """Mirrors WP-02's fake `LLMClient` — echoes back a canned "cleaned"
    version so the test controls exactly what lands in clean.md."""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        return ProviderResponse(content=self.content, in_tokens=50, out_tokens=20)


def _sample_capture(**overrides) -> Capture:
    defaults = dict(
        id="cap-20260716-1423",
        project="test-proj",
        type=CaptureType.AUDIO,
        moment=CaptureMoment.IN_SITU,
        captured_at="2026-07-16T14:23:00Z",
        source_path=Path("captures/audio/raw/cap-20260716-1423.wav"),
    )
    defaults.update(overrides)
    return Capture(**defaults)


def _write_source(data_root: Path, capture: Capture) -> None:
    from ce import store

    source = store.project_dir(data_root, capture.project) / capture.source_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(FIXTURE_WAV.read_bytes())


def test_fixture_wav_is_a_real_90_second_file():
    import wave

    with wave.open(str(FIXTURE_WAV), "rb") as w:
        assert round(w.getnframes() / w.getframerate()) == 90


def test_transcribe_produces_raw_and_clean_files(tmp_path, make_engine_config):
    capture = _sample_capture()
    _write_source(tmp_path, capture)

    preprocessor = FakePreprocessor()
    transcription_client = FakeTranscriptionClient([SELF_CORRECTION_RAW])
    llm_client = FakeLLMClient(
        content=f"So I pointed the job at postgres.\n\n{SELF_CORRECTION_RAW}"
    )
    gateway = Gateway(make_engine_config(), data_root=tmp_path, client=llm_client)

    result = transcribe(
        tmp_path,
        capture,
        make_engine_config(),
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )

    assert result.derived is not None
    raw_path = tmp_path / "projects" / "test-proj" / result.derived.transcript_raw
    clean_path = tmp_path / "projects" / "test-proj" / result.derived.transcript_clean
    assert raw_path.exists()
    assert clean_path.exists()
    assert raw_path.read_text(encoding="utf-8") == SELF_CORRECTION_RAW


def test_clean_md_retains_the_self_correction_verbatim(tmp_path, make_engine_config):
    """The golden test named in TDD 12's WP-04 Done-when line."""
    capture = _sample_capture()
    _write_source(tmp_path, capture)

    correction_phrase = "wait, no, actually it was mysql, not postgres, my bad"
    preprocessor = FakePreprocessor()
    transcription_client = FakeTranscriptionClient([SELF_CORRECTION_RAW])
    llm_client = FakeLLMClient(content=f"Paragraph one.\n\n{SELF_CORRECTION_RAW}")
    gateway = Gateway(make_engine_config(), data_root=tmp_path, client=llm_client)

    result = transcribe(
        tmp_path,
        capture,
        make_engine_config(),
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )

    clean_path = tmp_path / "projects" / "test-proj" / result.derived.transcript_clean
    assert correction_phrase in clean_path.read_text(encoding="utf-8")
    # And the prompt actually received the raw self-correction as input --
    # the LLM can't preserve what it was never given.
    assert correction_phrase in llm_client.calls[0]["user"]


def test_rerunning_transcribe_is_a_no_op(tmp_path, make_engine_config):
    capture = _sample_capture()
    _write_source(tmp_path, capture)

    preprocessor = FakePreprocessor()
    transcription_client = FakeTranscriptionClient([SELF_CORRECTION_RAW])
    llm_client = FakeLLMClient(content="cleaned")
    config = make_engine_config()
    gateway = Gateway(config, data_root=tmp_path, client=llm_client)

    once = transcribe(
        tmp_path,
        capture,
        config,
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )
    twice = transcribe(
        tmp_path,
        once,
        config,
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )

    assert twice == once
    assert len(transcription_client.calls) == 1  # not called again
    assert len(llm_client.calls) == 1  # not called again


def test_force_reruns_even_when_already_done(tmp_path, make_engine_config):
    capture = _sample_capture()
    _write_source(tmp_path, capture)

    preprocessor = FakePreprocessor()
    transcription_client = FakeTranscriptionClient([SELF_CORRECTION_RAW, "second pass"])
    llm_client = FakeLLMClient(content="cleaned")
    config = make_engine_config()
    gateway = Gateway(config, data_root=tmp_path, client=llm_client)

    once = transcribe(
        tmp_path,
        capture,
        config,
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )
    transcribe(
        tmp_path,
        once,
        config,
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
        force=True,
    )

    assert len(transcription_client.calls) == 2


def test_transcribe_rejects_non_audio_capture(tmp_path, make_engine_config):
    capture = _sample_capture(type=CaptureType.SCREENSHOT)
    with pytest.raises(CaptureError, match="not an audio capture"):
        transcribe(
            tmp_path,
            capture,
            make_engine_config(),
            gateway=Gateway(make_engine_config(), data_root=tmp_path, client=FakeLLMClient("x")),
        )


def test_transcribe_raises_on_missing_source_file(tmp_path, make_engine_config):
    capture = _sample_capture()
    with pytest.raises(CaptureError, match="not found"):
        transcribe(
            tmp_path,
            capture,
            make_engine_config(),
            gateway=Gateway(make_engine_config(), data_root=tmp_path, client=FakeLLMClient("x")),
            preprocessor=FakePreprocessor(),
            transcription_client=FakeTranscriptionClient(["x"]),
        )


def test_transcribe_chunks_oversized_files(tmp_path, make_engine_config):
    from ce.capture.audio import MAX_UPLOAD_BYTES

    capture = _sample_capture()
    _write_source(tmp_path, capture)

    oversized = b"\0" * (MAX_UPLOAD_BYTES + 1)
    preprocessor = FakePreprocessor(output_bytes=oversized)
    chunk_a = tmp_path / "chunk-a.wav"
    chunk_b = tmp_path / "chunk-b.wav"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")
    splitter = FakeSplitter([(chunk_a, 0.0), (chunk_b, 90.0)])
    transcription_client = FakeTranscriptionClient(["first half", "second half"])
    llm_client = FakeLLMClient(content="cleaned")
    gateway = Gateway(make_engine_config(), data_root=tmp_path, client=llm_client)

    result = transcribe(
        tmp_path,
        capture,
        make_engine_config(),
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
        splitter=splitter,
    )

    assert len(transcription_client.calls) == 2
    assert len(splitter.calls) == 1
    raw_path = tmp_path / "projects" / "test-proj" / result.derived.transcript_raw
    raw_text = raw_path.read_text(encoding="utf-8")
    assert "[+00:00]" in raw_text
    assert "[+01:30]" in raw_text  # 90 seconds
    assert "first half" in raw_text
    assert "second half" in raw_text


def test_preprocessed_temp_file_is_cleaned_up(tmp_path, make_engine_config):
    capture = _sample_capture()
    _write_source(tmp_path, capture)

    preprocessor = FakePreprocessor()
    transcription_client = FakeTranscriptionClient([SELF_CORRECTION_RAW])
    llm_client = FakeLLMClient(content="cleaned")
    gateway = Gateway(make_engine_config(), data_root=tmp_path, client=llm_client)

    transcribe(
        tmp_path,
        capture,
        make_engine_config(),
        gateway=gateway,
        preprocessor=preprocessor,
        transcription_client=transcription_client,
    )

    input_path, output_path = preprocessor.calls[0]
    assert not output_path.exists()  # temp preprocessed file removed after use


# --- pure logic that doesn't need a real ffmpeg binary to test ---------------
#
# These are string/arithmetic helpers around ffmpeg's stderr output. Unlike
# the DI seams above, they don't need a fake *Protocol* -- monkeypatching
# `subprocess.run` (or calling the static parse methods directly) exercises
# the real implementation, not a stand-in for it.


def test_silence_filter_reflects_non_default_config(make_engine_config):
    from ce.capture.audio import _silence_filter

    config = make_engine_config(
        transcription={
            "provider": "openai",
            "model": "gpt-4o-mini-transcribe",
            "vocabulary": [],
            "preprocess": {"silence_threshold_db": -55, "silence_min_sec": 2.5, "loudnorm": False},
        }
    ).transcription.preprocess

    filter_string = _silence_filter(config)

    assert "stop_duration=2.5" in filter_string
    assert "stop_threshold=-55.0dB" in filter_string
    assert "loudnorm" not in filter_string  # disabled in this config


def test_silence_filter_appends_loudnorm_when_enabled(make_engine_config):
    from ce.capture.audio import _silence_filter

    config = make_engine_config().transcription.preprocess  # loudnorm: True by default
    assert _silence_filter(config).endswith(",loudnorm")


class TestFfmpegSilenceSplitterParsing:
    """Direct tests of the pure stderr-parsing methods."""

    def test_parse_duration(self):
        from ce.capture.audio import FfmpegSilenceSplitter

        stderr = "  Duration: 00:03:07.50, start: 0.000000, bitrate: 128 kb/s\n"
        assert FfmpegSilenceSplitter._parse_duration(stderr) == 187.5

    def test_parse_duration_missing_is_zero(self):
        from ce.capture.audio import FfmpegSilenceSplitter

        assert FfmpegSilenceSplitter._parse_duration("no duration line here") == 0.0

    def test_parse_silence_midpoints(self):
        from ce.capture.audio import FfmpegSilenceSplitter

        stderr = (
            "[silencedetect @ 0x1] silence_start: 60\n"
            "[silencedetect @ 0x1] silence_end: 62 | silence_duration: 2\n"
            "[silencedetect @ 0x1] silence_start: 120.5\n"
            "[silencedetect @ 0x1] silence_end: 121.5 | silence_duration: 1\n"
        )
        assert FfmpegSilenceSplitter._parse_silence_midpoints(stderr) == [61.0, 121.0]

    def test_parse_silence_midpoints_none_found(self):
        from ce.capture.audio import FfmpegSilenceSplitter

        assert FfmpegSilenceSplitter._parse_silence_midpoints("nothing here") == []


class _FakeCompletedProcess:
    def __init__(self, stderr: str = "", returncode: int = 0):
        self.stderr = stderr
        self.returncode = returncode


def test_ffmpeg_silence_splitter_cuts_on_detected_silence(
    tmp_path, monkeypatch, make_engine_config
):
    """Full `split()` orchestration, with `subprocess.run` faked -- proves
    the cut-point selection (never mid-word: only cuts at silence
    midpoints) and per-chunk ffmpeg invocation, without a real ffmpeg
    binary."""
    from ce.capture import audio as audio_module
    from ce.capture.audio import MAX_UPLOAD_BYTES, FfmpegSilenceSplitter

    # 3-minute file, silence at 60s and 120s -- sized so the byte budget
    # forces at least one cut, and the cut must land on a real silence
    # midpoint (61.0 or 120.75), never mid-word.
    analyze_stderr = (
        "Duration: 00:03:00.00, start: 0.000000, bitrate: 128 kb/s\n"
        "[silencedetect] silence_start: 60.0\n"
        "[silencedetect] silence_end: 62.0 | silence_duration: 2.0\n"
        "[silencedetect] silence_start: 120.5\n"
        "[silencedetect] silence_end: 121.0 | silence_duration: 0.5\n"
    )

    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        if "-af" in cmd and any("silencedetect" in part for part in cmd):
            return _FakeCompletedProcess(stderr=analyze_stderr, returncode=0)
        return _FakeCompletedProcess(returncode=0)  # chunk extraction "succeeds"

    monkeypatch.setattr(audio_module.subprocess, "run", fake_run)

    src = tmp_path / "big.wav"
    src.write_bytes(b"\0" * (MAX_UPLOAD_BYTES * 3))  # forces >=1 cut given the byte budget

    splitter = FfmpegSilenceSplitter()
    preprocess_config = make_engine_config().transcription.preprocess
    chunks = splitter.split(src, tmp_path / "chunks", preprocess_config)

    assert len(chunks) >= 2
    assert chunks[0][1] == 0.0  # first chunk always starts at 0
    cut_offsets = {offset for _, offset in chunks[1:]}
    assert cut_offsets <= {61.0, 120.75}  # only ever cuts at a silence midpoint
    # one analyze pass + one ffmpeg invocation per chunk
    assert len(run_calls) == 1 + len(chunks)
