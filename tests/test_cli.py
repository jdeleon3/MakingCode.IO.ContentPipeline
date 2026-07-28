"""WP-00 acceptance: the CLI contract from TDD 9 is complete and stubs are honest."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ce import cli
from ce.exit_codes import CEError, Exit, GateBlocked, NotImplementedYet

runner = CliRunner()

# The complete contract from TDD 9. This list is the acceptance criterion for
# WP-00 and a regression guard thereafter: removing or renaming a command
# without updating the TDD will fail here.
EXPECTED_COMMANDS = [
    ("project", "new"),
    ("project", "list"),
    ("project", "show"),
    ("project", "close"),
    ("capture", "audio"),
    ("capture", "screen"),
    ("capture", "friction"),
    ("capture", "list"),
    ("harvest",),
    ("brief", "list"),
    ("brief", "select"),
    ("produce",),
    ("verify",),
    ("assets",),
    ("render",),
    ("package",),
    ("publish", "site"),
    ("posted",),
    ("metrics", "pull"),
    ("sweep",),
    ("index", "rebuild"),
    ("cost",),
    ("doctor",),
]

# Which work package implements each stub.
EXPECTED_WP = {
    ("harvest",): "WP-08",
    ("brief", "select"): "WP-09",
    ("produce",): "WP-09",
    ("verify",): "WP-10",
    ("assets",): "WP-11",
    ("render",): "WP-12",
    ("package",): "WP-13",
    ("publish", "site"): "WP-14",
    ("posted",): "WP-15",
    ("sweep",): "WP-16",
}


def test_help_runs():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "Content Engine" in result.output


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().startswith("ce ")


@pytest.mark.parametrize("command", EXPECTED_COMMANDS, ids=lambda c: " ".join(c))
def test_command_is_registered(command):
    """Every command in the TDD 9 contract resolves and has help text."""
    result = runner.invoke(cli.app, [*command, "--help"])
    assert result.exit_code == 0, f"`ce {' '.join(command)}` did not resolve"


@pytest.mark.parametrize("group", ["project", "capture", "brief", "publish", "metrics", "index"])
def test_group_help_runs(group):
    result = runner.invoke(cli.app, [group, "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("command,wp", list(EXPECTED_WP.items()), ids=lambda x: str(x))
def test_stub_names_its_work_package(command, wp):
    """An unimplemented command must say which WP builds it, not dump a traceback."""
    if not isinstance(command, tuple):  # pytest passes the wp string through too
        return
    args = list(command) + _dummy_args_for(command)
    result = runner.invoke(cli.app, args)
    assert isinstance(result.exception, NotImplementedYet), (
        f"`ce {' '.join(command)}` raised {result.exception!r}"
    )
    assert result.exception.wp == wp


def _dummy_args_for(command):
    """Minimum arguments to get past Typer parsing and reach the stub body."""
    required = {
        ("harvest",): ["some-slug"],
        ("brief", "select"): ["br-01"],
        ("produce",): ["pc-0001"],
        ("verify",): ["pc-0001"],
        ("assets",): ["pc-0001"],
        ("render",): ["pc-0001"],
        ("package",): ["pc-0001"],
        ("publish", "site"): ["pc-0001"],
        ("posted",): ["pc-0001", "--platform", "linkedin", "--url", "https://x.test/1"],
    }
    return required.get(command, [])


def test_doctor_exits_cleanly():
    """doctor is the one command implemented in WP-00; it must return 0 or 1, never crash."""
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code in (Exit.OK, Exit.ERROR)
    assert "environment check" in result.output.lower()


def test_cost_runs_with_no_ledger(tmp_path, monkeypatch):
    """WP-02: `ce cost` on a project with no LLM spend yet must not crash."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == Exit.OK
    assert "no calls recorded" in result.output.lower()


def test_cost_prints_per_prompt_breakdown(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from ce.llm import ledger as ledger_mod

    monkeypatch.chdir(tmp_path)
    now = datetime.now(UTC)
    ledger_mod.append(
        tmp_path / "data" / "ledger.jsonl",
        ledger_mod.LedgerRecord(
            ts=now,
            prompt="_wp02_echo",
            version=1,
            model="claude-haiku-4-5",
            in_tokens=100,
            out_tokens=50,
            usd=0.0003,
            cache_hit=False,
        ),
    )
    result = runner.invoke(cli.app, ["cost"])
    assert result.exit_code == Exit.OK
    assert "_wp02_echo" in result.output
    assert "1 calls" in result.output


# --- project lifecycle (WP-03, TDD 12 "Done when") --------------------------


def test_project_new_creates_the_full_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["project", "new", "test-proj"])
    assert result.exit_code == Exit.OK, result.output

    base = tmp_path / "data" / "projects" / "test-proj"
    assert (base / "project.yml").exists()
    assert (base / "captures" / "audio" / "raw").is_dir()
    assert (base / "captures" / "audio" / "transcript").is_dir()
    assert (base / "captures" / "screens").is_dir()
    assert (base / "captures" / "screencast").is_dir()
    assert (base / "captures" / "friction.md").exists()
    assert (base / "harvest").is_dir()
    assert (base / "pieces").is_dir()


def test_project_new_with_allowlisted_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_dir = tmp_path / "code" / "x"
    repo_dir.mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "engine.yml").write_text(
        f"""
identity:
  name: John
  site_url: https://example.com
  site_repo: ~/code/site
  timezone: America/New_York
repos:
  allowed:
    - name: x
      path: {repo_dir}
      publishable: full
llm:
  provider: anthropic
  models: {{reasoning: claude-opus-5, default: claude-sonnet-5, cheap: claude-haiku-4-5}}
  budget: {{monthly_usd: 20, per_run_usd: 2.0, on_exceed: halt}}
  retry: {{max_attempts: 4, backoff_base_sec: 2}}
transcription:
  provider: openai
  model: gpt-4o-mini-transcribe
  vocabulary: []
  preprocess: {{silence_threshold_db: -40, silence_min_sec: 1.5, loudnorm: true}}
embeddings: {{provider: openai, model: text-embedding-3-small}}
gates:
  allowlist: hard_fail
  secrets: hard_fail
  dedupe: {{threshold: 0.88, scope_days: 365}}
  claims: {{enabled: true, block_on_unverifiable: true}}
produce:
  min_grade: 8.0
  max_attempts: 3
  grade_weights: {{hook: 0.3, evidence: 0.3, specificity: 0.2, voice: 0.1, cta: 0.1}}
harvest:
  git: {{lookback_days: 60, min_significance: 2}}
  research: {{max_sources: 8}}
  inventory: {{min_briefs: 6, max_briefs: 8}}
utm:
  template: "?utm_source={{platform}}&utm_medium=social&utm_campaign={{slug}}"
""",
        encoding="utf-8",
    )

    result = runner.invoke(cli.app, ["project", "new", "test-proj", "--repo", str(repo_dir)])
    assert result.exit_code == Exit.OK, result.output


def test_project_new_duplicate_slug_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(cli.app, ["project", "new", "test-proj"])
    assert first.exit_code == Exit.OK

    second = runner.invoke(cli.app, ["project", "new", "test-proj"])
    assert second.exit_code != Exit.OK
    assert isinstance(second.exception, CEError)
    assert "already exists" in second.exception.message


def test_project_close_nonexistent_project_is_a_readable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["project", "close", "does-not-exist"])
    assert result.exit_code != Exit.OK
    assert isinstance(result.exception, CEError)


def test_project_close_abandoned_sets_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    result = runner.invoke(cli.app, ["project", "close", "test-proj", "--abandoned"])
    assert result.exit_code == Exit.OK, result.output
    assert "abandoned" in result.output.lower()

    from ce import store

    reloaded = store.read_project(tmp_path / "data", "test-proj")
    assert reloaded.status.value == "abandoned"


def test_project_close_without_abandoned_sets_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    result = runner.invoke(cli.app, ["project", "close", "test-proj"])
    assert result.exit_code == Exit.OK, result.output

    from ce import store

    reloaded = store.read_project(tmp_path / "data", "test-proj")
    assert reloaded.status.value == "complete"


def test_project_list_and_show(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj", "--title", "Test Project"])

    listed = runner.invoke(cli.app, ["project", "list"])
    assert listed.exit_code == Exit.OK
    assert "test-proj" in listed.output

    shown = runner.invoke(cli.app, ["project", "show", "test-proj"])
    assert shown.exit_code == Exit.OK
    assert "Test Project" in shown.output


# --- capture (WP-04, TDD 12 "Done when") -------------------------------------

_MINIMAL_ENGINE_YML = """
identity:
  name: John
  site_url: https://example.com
  site_repo: ~/code/site
  timezone: America/New_York
repos:
  allowed: []
llm:
  provider: anthropic
  models: {reasoning: claude-opus-5, default: claude-sonnet-5, cheap: claude-haiku-4-5}
  budget: {monthly_usd: 20, per_run_usd: 2.0, on_exceed: halt}
  retry: {max_attempts: 4, backoff_base_sec: 2}
transcription:
  provider: openai
  model: gpt-4o-mini-transcribe
  vocabulary: []
  preprocess: {silence_threshold_db: -40, silence_min_sec: 1.5, loudnorm: true}
embeddings: {provider: openai, model: text-embedding-3-small}
gates:
  allowlist: hard_fail
  secrets: hard_fail
  dedupe: {threshold: 0.88, scope_days: 365}
  claims: {enabled: true, block_on_unverifiable: true}
produce:
  min_grade: 8.0
  max_attempts: 3
  grade_weights: {hook: 0.3, evidence: 0.3, specificity: 0.2, voice: 0.1, cta: 0.1}
harvest:
  git: {lookback_days: 60, min_significance: 2}
  research: {max_sources: 8}
  inventory: {min_briefs: 6, max_briefs: 8}
utm:
  template: "?utm_source={platform}&utm_medium=social&utm_campaign={slug}"
"""


def _write_minimal_engine_config(root):
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "engine.yml").write_text(_MINIMAL_ENGINE_YML, encoding="utf-8")


def test_capture_audio_end_to_end(tmp_path, monkeypatch):
    """Wires ingest -> ffmpeg preprocess -> transcribe -> transcript_clean
    end to end through the real CLI command, with ffmpeg/OpenAI/Anthropic
    all faked (this dev environment has no ffmpeg — see test_capture_audio.py)."""
    import shutil

    from ce import store
    from ce.capture import audio as audio_module
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse

    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    _write_minimal_engine_config(tmp_path)
    # Gateway resolves prompts/ relative to cwd (like data/ and config/) --
    # give this isolated tmp_path its own copy so transcript_clean.md
    # resolves the same way it would from the repo root.
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")
    audio_file = tmp_path / "memo.wav"
    audio_file.write_bytes(b"fake-audio-bytes")

    class FakePreprocessor:
        def run(self, input_path, output_path, config):
            output_path.write_bytes(b"fake-preprocessed")

    class FakeTranscriptionClient:
        def transcribe(self, path, *, model, vocabulary):
            return "raw transcript text"

    class FakeAnthropicClient:
        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content="cleaned transcript", in_tokens=10, out_tokens=5)

    monkeypatch.setattr(audio_module, "FfmpegPreprocessor", FakePreprocessor)
    monkeypatch.setattr(audio_module, "OpenAITranscriptionClient", FakeTranscriptionClient)
    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)

    result = runner.invoke(
        cli.app,
        ["capture", "audio", str(audio_file), "--project", "test-proj", "--context", "a note"],
    )

    assert result.exit_code == Exit.OK, result.output
    captures = store.list_captures(tmp_path / "data", "test-proj")
    assert len(captures) == 1
    assert captures[0].derived is not None
    assert captures[0].derived.transcript_clean is not None
    clean_path = tmp_path / "data" / "projects" / "test-proj" / captures[0].derived.transcript_clean
    assert clean_path.read_text(encoding="utf-8") == "cleaned transcript"


def test_capture_audio_rejects_unknown_moment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    audio_file = tmp_path / "memo.wav"
    audio_file.write_bytes(b"fake")

    result = runner.invoke(
        cli.app,
        ["capture", "audio", str(audio_file), "--project", "test-proj", "--moment", "bogus"],
    )
    assert result.exit_code != Exit.OK
    assert isinstance(result.exception, CEError)


def test_capture_screen_and_friction_and_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    screenshot = tmp_path / "shot.png"
    screenshot.write_bytes(b"fake-png")
    screen_result = runner.invoke(
        cli.app, ["capture", "screen", str(screenshot), "--project", "test-proj"]
    )
    assert screen_result.exit_code == Exit.OK, screen_result.output

    friction_result = runner.invoke(
        cli.app, ["capture", "friction", "the OOM hit at 40GB", "--project", "test-proj"]
    )
    assert friction_result.exit_code == Exit.OK, friction_result.output

    list_result = runner.invoke(cli.app, ["capture", "list", "test-proj"])
    assert list_result.exit_code == Exit.OK
    assert "screenshot" in list_result.output
    assert "friction" in list_result.output


def test_capture_screen_unrecognized_extension_is_a_readable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    bogus = tmp_path / "notes.txt"
    bogus.write_bytes(b"not a screenshot")

    result = runner.invoke(cli.app, ["capture", "screen", str(bogus), "--project", "test-proj"])
    assert result.exit_code != Exit.OK
    assert isinstance(result.exception, CEError)


def test_capture_list_empty_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    result = runner.invoke(cli.app, ["capture", "list", "test-proj"])
    assert result.exit_code == Exit.OK
    assert "no captures" in result.output.lower()


# --- index rebuild (WP-06, TDD 12 "Done when") ------------------------------


def test_index_rebuild_end_to_end(tmp_path, monkeypatch):
    """Wires `store.list_pieces` -> embed -> `index.db` end to end through
    the real CLI command, with the embeddings API faked (this dev
    environment has no network access to it in tests — see test_index.py).
    """
    from datetime import UTC, datetime

    from ce import index as index_module
    from ce import store
    from ce.models import Piece, PieceStatus

    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    _write_minimal_engine_config(tmp_path)

    piece = Piece(
        id="pc-0001",
        brief_id="br-01",
        project="test-proj",
        slug="pc-0001",
        status=PieceStatus.DRAFTED,
        created_at=datetime.now(UTC),
        article_path="article.md",
    )
    store.write_piece(tmp_path / "data", "test-proj", piece)
    (store.piece_dir(tmp_path / "data", "test-proj", "pc-0001") / "article.md").write_text(
        "Some drafted article content about DuckDB.", encoding="utf-8"
    )

    class FakeEmbeddingsClient:
        def embed(self, text, *, model):
            return [1.0, 0.0, 0.0]

    monkeypatch.setattr(index_module, "OpenAIEmbeddingsClient", FakeEmbeddingsClient)

    result = runner.invoke(cli.app, ["index", "rebuild"])

    assert result.exit_code == Exit.OK, result.output
    assert "indexed 1" in result.output.lower()
    assert (tmp_path / "data" / "index.db").exists()


def test_index_rebuild_with_no_pieces_indexes_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)

    result = runner.invoke(cli.app, ["index", "rebuild"])

    assert result.exit_code == Exit.OK, result.output
    assert "indexed 0" in result.output.lower()


# --- exit code contract (TDD 9) --------------------------------------------


def test_exit_code_values():
    assert (Exit.OK, Exit.ERROR, Exit.GATE_BLOCKED, Exit.BUDGET_EXCEEDED, Exit.PRECONDITION) == (
        0,
        1,
        2,
        3,
        4,
    )


def test_gate_blocked_carries_gate_name():
    exc = GateBlocked("G2", "planted key found")
    assert exc.exit_code == Exit.GATE_BLOCKED
    assert "[G2]" in exc.message


def test_main_maps_ce_error_to_exit_code(monkeypatch):
    """cli.main translates a CEError into its process exit code."""

    def boom():
        raise GateBlocked("G1", "repo not in allowlist")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == Exit.GATE_BLOCKED


def test_main_lets_unexpected_errors_surface(monkeypatch):
    """Only CEError is translated; genuine bugs keep their traceback."""

    def boom():
        raise ValueError("a real bug")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(ValueError):
        cli.main()


def test_ce_error_hint_is_optional():
    exc = CEError("bare message")
    assert exc.hint is None
