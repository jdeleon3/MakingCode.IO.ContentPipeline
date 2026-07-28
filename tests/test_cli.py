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

# Which work package implements each stub. Empty now that WP-16 (the last
# one) is built -- every command in EXPECTED_COMMANDS resolves for real.
EXPECTED_WP: dict[tuple[str, ...], str] = {}


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
    required = {}
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
analytics:
  umami: {{api_url: "https://umami.example.com", website_id: "site-1"}}
sweep:
  topics: [DuckDB]
  rss_feeds: []
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
analytics:
  umami: {api_url: "https://umami.example.com", website_id: "site-1"}
sweep:
  topics: [DuckDB]
  rss_feeds: []
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


# --- capture --dir batch mode -------------------------------------------------


def test_capture_audio_and_screen_reject_both_file_and_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    audio_file = tmp_path / "memo.wav"
    audio_file.write_bytes(b"fake")

    both = runner.invoke(
        cli.app,
        ["capture", "audio", str(audio_file), "--dir", str(tmp_path), "--project", "test-proj"],
    )
    assert both.exit_code != Exit.OK
    assert isinstance(both.exception, CEError)

    neither = runner.invoke(cli.app, ["capture", "audio", "--project", "test-proj"])
    assert neither.exit_code != Exit.OK
    assert isinstance(neither.exception, CEError)


def test_capture_screen_dir_batches_a_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    folder = tmp_path / "screenshots"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"fake-png")
    (folder / "b.png").write_bytes(b"fake-png")
    (folder / "notes.txt").write_bytes(b"not a screenshot")  # skipped by extension

    result = runner.invoke(
        cli.app, ["capture", "screen", "--dir", str(folder), "--project", "test-proj"]
    )

    assert result.exit_code == Exit.OK, result.output
    assert "2 succeeded, 0 failed" in result.output

    from ce.capture import ingest as capture_ingest

    captures = capture_ingest.list_captures(tmp_path / "data", "test-proj")
    assert len(captures) == 2


def test_capture_screen_dir_skip_and_continue_reports_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    folder = tmp_path / "screenshots"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"fake-png")
    (folder / "b.bogus").write_bytes(b"fake")  # not a screen extension -- silently skipped

    result = runner.invoke(
        cli.app, ["capture", "screen", "--dir", str(folder), "--project", "test-proj"]
    )
    assert result.exit_code == Exit.OK, result.output
    assert "1 succeeded, 0 failed" in result.output


def test_capture_screen_dir_empty_folder_reports_no_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    folder = tmp_path / "empty"
    folder.mkdir()

    result = runner.invoke(
        cli.app, ["capture", "screen", "--dir", str(folder), "--project", "test-proj"]
    )
    assert result.exit_code == Exit.OK
    assert "no matching files" in result.output.lower()


def test_capture_audio_dir_batches_a_folder(tmp_path, monkeypatch):
    import shutil

    from ce.capture import audio as audio_module
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse

    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])
    _write_minimal_engine_config(tmp_path)
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")

    folder = tmp_path / "recordings"
    folder.mkdir()
    (folder / "a.wav").write_bytes(b"fake-audio")
    (folder / "b.wav").write_bytes(b"fake-audio")

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
        cli.app, ["capture", "audio", "--dir", str(folder), "--project", "test-proj"]
    )

    assert result.exit_code == Exit.OK, result.output
    assert "2 succeeded, 0 failed" in result.output

    from ce import store

    captures = store.list_captures(tmp_path / "data", "test-proj")
    assert len(captures) == 2
    assert all(c.derived is not None and c.derived.transcript_clean is not None for c in captures)


# --- harvest / brief list (WP-08, TDD 12 "Done when") -----------------------


def test_harvest_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce harvest` used to raise `NotImplementedYet("harvest", "WP-08")`;
    now it should reach real logic (and fail on a missing project, not on
    "not implemented yet"). A full fake-every-external-client run is
    already covered at the module level by `test_harvest_git.py`,
    `test_harvest_research.py`, and `test_harvest_inventory.py` — this is
    just the wiring smoke test."""
    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)

    result = runner.invoke(cli.app, ["harvest", "does-not-exist"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_brief_list_empty_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["project", "new", "test-proj"])

    result = runner.invoke(cli.app, ["brief", "list", "test-proj"])

    assert result.exit_code == Exit.OK, result.output
    assert "no briefs" in result.output.lower()


def test_brief_list_prints_briefs_and_filters_by_status(tmp_path, monkeypatch):
    from datetime import date

    from ce import store
    from ce.models import (
        Brief,
        BriefDemand,
        BriefStatus,
        GroundingStrength,
        Project,
    )

    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.scaffold_project_tree(data_root, "test-proj")
    briefs = [
        Brief(
            id="br-01",
            project="test-proj",
            archetype="why_this_project",
            title="Why this project",
            angle="origin",
            demand=BriefDemand(recurrence=1, signals=[]),
            grounding_strength=GroundingStrength.STRONG,
            dedupe_max_similarity=0.1,
            weakest_point="n=1",
            status=BriefStatus.CANDIDATE,
        ),
        Brief(
            id="br-02",
            project="test-proj",
            archetype="specific_gotcha",
            title="A weak one",
            angle="gotcha",
            demand=BriefDemand(recurrence=0, signals=[]),
            grounding_strength=GroundingStrength.WEAK,
            dedupe_max_similarity=0.0,
            weakest_point="thin",
            status=BriefStatus.DROPPED,
        ),
    ]
    store.write_briefs(data_root, "test-proj", briefs)

    all_result = runner.invoke(cli.app, ["brief", "list", "test-proj"])
    assert all_result.exit_code == Exit.OK, all_result.output
    assert "br-01" in all_result.output
    assert "br-02" in all_result.output

    dropped_result = runner.invoke(cli.app, ["brief", "list", "test-proj", "--status", "dropped"])
    assert dropped_result.exit_code == Exit.OK
    assert "br-02" in dropped_result.output
    assert "br-01" not in dropped_result.output

    bad_status_result = runner.invoke(cli.app, ["brief", "list", "test-proj", "--status", "bogus"])
    assert bad_status_result.exit_code != Exit.OK
    assert isinstance(bad_status_result.exception, CEError)


# --- brief select / produce (WP-09, TDD 12 "Done when") ---------------------


def test_brief_select_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce brief select` used to raise `NotImplementedYet("brief select",
    "WP-09")`; now it should reach real logic (and fail on an unknown
    brief, not on "not implemented yet")."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["brief", "select", "br-99"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_produce_is_wired_not_a_stub(tmp_path, monkeypatch):
    """Same wiring check as `test_brief_select_is_wired_not_a_stub`, for
    `ce produce`."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["produce", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_brief_select_promotes_a_brief_to_a_piece(tmp_path, monkeypatch):
    from datetime import date

    from ce import store
    from ce.models import Brief, BriefDemand, BriefStatus, GroundingStrength, Project

    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
                status=BriefStatus.CANDIDATE,
            )
        ],
    )

    result = runner.invoke(cli.app, ["brief", "select", "br-01"])

    assert result.exit_code == Exit.OK, result.output
    assert "pc-0001" in result.output

    [reloaded] = store.read_briefs(data_root, "test-proj")
    assert reloaded.status == BriefStatus.SELECTED
    piece = store.read_piece(data_root, "test-proj", "pc-0001")
    assert piece.brief_id == "br-01"


def test_produce_end_to_end_drafts_grades_and_writes_article(tmp_path, monkeypatch):
    """Wires select -> produce through the real CLI commands, with
    Anthropic/OpenAI (article draft/grade/revise + voice-RAG embeddings)
    faked -- same shape as `test_capture_audio_end_to_end`."""
    import json
    import shutil
    from datetime import date

    from ce import index as index_module
    from ce import store
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse
    from ce.models import Brief, BriefDemand, BriefStatus, GroundingStrength, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
                status=BriefStatus.CANDIDATE,
            )
        ],
    )
    select_result = runner.invoke(cli.app, ["brief", "select", "br-01"])
    assert select_result.exit_code == Exit.OK, select_result.output

    grade_json = json.dumps(
        {
            "scores": {"hook": 9, "evidence": 9, "specificity": 9, "voice": 9, "cta": 9},
            "top_fixes": [],
        }
    )

    class FakeAnthropicClient:
        def __init__(self):
            self._responses = iter(["# Drafted article\n\nBody.", grade_json])

        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content=next(self._responses), in_tokens=10, out_tokens=5)

    class FakeEmbeddingsClient:
        def embed(self, text, *, model):
            return [1.0, 0.0, 0.0]

    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)
    monkeypatch.setattr(index_module, "OpenAIEmbeddingsClient", FakeEmbeddingsClient)

    result = runner.invoke(cli.app, ["produce", "pc-0001"])

    assert result.exit_code == Exit.OK, result.output
    assert "ce verify pc-0001" in result.output

    piece = store.read_piece(data_root, "test-proj", "pc-0001")
    assert piece.generated_at is not None
    assert len(piece.grades) == 1
    article = (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").read_text(
        encoding="utf-8"
    )
    assert article == "# Drafted article\n\nBody."


# --- verify (WP-10, TDD 12 "Done when") --------------------------------------


def test_verify_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce verify` used to raise `NotImplementedYet("verify", "WP-10")`; now
    it should reach real logic (and fail on an unknown piece, not on "not
    implemented yet")."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["verify", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_verify_blocks_on_a_planted_unverifiable_claim_and_writes_verification_json(
    tmp_path, monkeypatch
):
    """WP-10 Done-when: a fixture article with one planted unverifiable
    claim exits 2 naming that claim; verification.json is still written."""
    import json
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse
    from ce.models import Piece, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    piece = Piece(
        id="pc-0001",
        brief_id="br-01",
        project="test-proj",
        slug="a-piece",
        created_at=datetime.now(UTC),
        article_path=Path("article.md"),
    )
    store.write_piece(data_root, "test-proj", piece)
    from ce.models import Brief, BriefDemand, GroundingStrength

    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )
    (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").write_text(
        "This change saved us exactly $2M a year.", encoding="utf-8"
    )

    claims_json = json.dumps(
        {
            "claims": [
                {
                    "text": "This change saved us exactly $2M a year.",
                    "class": "unverifiable",
                    "ref": None,
                }
            ]
        }
    )

    class FakeAnthropicClient:
        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content=claims_json, in_tokens=10, out_tokens=5)

    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)

    result = runner.invoke(cli.app, ["verify", "pc-0001"])

    # `CliRunner.invoke(cli.app, ...)` calls the Typer app directly, not
    # `cli.main()` -- the CEError -> process-exit-code translation (TDD 9's
    # exit 2 for a gate block) only happens in `main()` (see
    # `test_main_maps_ce_error_to_exit_code`), so this asserts the
    # exception itself carries `Exit.GATE_BLOCKED`, same as every other
    # CEError-raising CLI test here.
    assert result.exit_code != Exit.OK, result.output
    assert isinstance(result.exception, GateBlocked)
    assert result.exception.exit_code == Exit.GATE_BLOCKED
    assert "This change saved us exactly $2M a year." in result.exception.message

    verification_path = store.verification_json_path(data_root, "test-proj", "pc-0001")
    assert verification_path.exists()
    data = json.loads(verification_path.read_text(encoding="utf-8"))
    assert len(data["claims"]) == 1
    assert data["claims"][0]["passed"] is False


def test_verify_passes_and_marks_piece_verified(tmp_path, monkeypatch):
    import json
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse
    from ce.models import Brief, BriefDemand, GroundingStrength, Piece, PieceStatus, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )
    (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").write_text(
        "I think this project went well.", encoding="utf-8"
    )

    claims_json = json.dumps(
        {"claims": [{"text": "I think this project went well.", "class": "opinion", "ref": None}]}
    )

    class FakeAnthropicClient:
        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content=claims_json, in_tokens=10, out_tokens=5)

    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)

    result = runner.invoke(cli.app, ["verify", "pc-0001"])

    assert result.exit_code == Exit.OK, result.output

    reloaded = store.read_piece(data_root, "test-proj", "pc-0001")
    assert reloaded.status == PieceStatus.VERIFIED
    assert reloaded.verification is not None
    assert reloaded.verification.claims_checked == 1
    assert reloaded.verification.claims_failed == 0


def test_verify_force_proceeds_despite_a_failed_claim(tmp_path, monkeypatch):
    """`--force` (TDD 6.4: G4 is "blocking, bypassable with --force", unlike
    G1/G2) lets `ce verify` proceed past a failed claim instead of raising
    -- verification.json and piece.yml still record the failure."""
    import json
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse
    from ce.models import Brief, BriefDemand, GroundingStrength, Piece, PieceStatus, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    repo_prompts_dir = Path(__file__).parent.parent / "prompts"
    shutil.copytree(repo_prompts_dir, tmp_path / "prompts")

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )
    (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").write_text(
        "This change saved us exactly $2M a year.", encoding="utf-8"
    )

    claims_json = json.dumps(
        {
            "claims": [
                {
                    "text": "This change saved us exactly $2M a year.",
                    "class": "unverifiable",
                    "ref": None,
                }
            ]
        }
    )

    class FakeAnthropicClient:
        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content=claims_json, in_tokens=10, out_tokens=5)

    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)

    result = runner.invoke(cli.app, ["verify", "pc-0001", "--force"])

    assert result.exit_code == Exit.OK, result.output

    verification_path = store.verification_json_path(data_root, "test-proj", "pc-0001")
    data = json.loads(verification_path.read_text(encoding="utf-8"))
    assert data["claims"][0]["passed"] is False

    reloaded = store.read_piece(data_root, "test-proj", "pc-0001")
    assert reloaded.status == PieceStatus.VERIFIED
    assert reloaded.verification.claims_failed == 1


# --- assets (WP-11, TDD 12 "Done when") --------------------------------------


def test_assets_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce assets` used to raise `NotImplementedYet("assets", "WP-11")`; now
    it should reach real logic (and fail on an unknown piece, not on "not
    implemented yet")."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["assets", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_assets_only_diagram_end_to_end(tmp_path, monkeypatch):
    """Wires `ce assets --only diagram` through the real CLI command, with
    `mermaid-cli` faked (this dev environment has none installed -- see
    test_assets.py)."""
    from datetime import UTC, date, datetime

    from ce import store
    from ce.assets import diagram as diagram_module
    from ce.models import Brief, BriefDemand, GroundingStrength, Piece, Project

    monkeypatch.chdir(tmp_path)
    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )
    diagrams_dir = store.piece_dir(data_root, "test-proj", "pc-0001") / "assets" / "diagrams"
    diagrams_dir.mkdir(parents=True)
    (diagrams_dir / "flow.mmd").write_text("graph TD; A-->B;", encoding="utf-8")

    class FakeMermaidCliRenderer:
        def render(self, mermaid_source, output_path, *, width):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-png")

    monkeypatch.setattr(diagram_module, "MermaidCliRenderer", FakeMermaidCliRenderer)

    result = runner.invoke(cli.app, ["assets", "pc-0001", "--only", "diagram"])

    assert result.exit_code == Exit.OK, result.output
    assert (store.piece_dir(data_root, "test-proj", "pc-0001") / "assets" / "flow.png").exists()


# --- render (WP-12, TDD 12 "Done when") --------------------------------------


def test_render_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce render` used to raise `NotImplementedYet("render", "WP-12")`; now
    it should reach real logic (and fail on an unknown piece, not on "not
    implemented yet")."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["render", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_render_linkedin_end_to_end(tmp_path, monkeypatch):
    """Wires `ce render --platform linkedin` through the real CLI command,
    with the Anthropic client faked. Mechanical-validation edge cases
    (over-length, URL leaking into the body, markdown surviving, etc.) are
    covered directly against `produce/renditions.py` in
    test_produce_renditions.py -- this only proves the CLI plumbing:
    config loading, the canonical/UTM URL, and the written renditions/*.yml.
    """
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.llm import gateway as gateway_module
    from ce.llm.gateway import ProviderResponse
    from ce.models import Piece, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    (tmp_path / "config" / "platforms").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parent.parent / "config" / "platforms" / "linkedin.yml",
        tmp_path / "config" / "platforms" / "linkedin.yml",
    )
    # Gateway resolves prompts/ relative to cwd (like data/ and config/) --
    # give this isolated tmp_path its own copy, same as the verify/assets
    # end-to-end tests.
    shutil.copytree(Path(__file__).parent.parent / "prompts", tmp_path / "prompts")

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").write_text(
        "# A piece\n\nSome article body.", encoding="utf-8"
    )

    body = "A" * 50 + "."  # ends on a sentence boundary within hook_chars=200, no URL
    utm_url = "https://example.com/blog/a-piece?utm_source=linkedin&utm_medium=social&utm_campaign=a-piece"
    linkedin_content = f"{body}\n---\nLink in the comments: {utm_url}"

    class FakeAnthropicClient:
        def complete(self, *, model, system, user, max_tokens):
            return ProviderResponse(content=linkedin_content, in_tokens=10, out_tokens=5)

    monkeypatch.setattr(gateway_module, "AnthropicClient", FakeAnthropicClient)

    result = runner.invoke(cli.app, ["render", "pc-0001", "--platform", "linkedin"])

    assert result.exit_code == Exit.OK, result.output
    rendition = store.read_rendition(data_root, "test-proj", "pc-0001", "linkedin")
    assert rendition.body == body
    assert utm_url in rendition.first_comment


# --- package (WP-13, TDD 12 "Done when") -------------------------------------


def test_package_is_wired_not_a_stub(tmp_path, monkeypatch):
    """`ce package` used to raise `NotImplementedYet("package", "WP-13")`;
    now it should reach real logic (and fail on an unknown piece, not on
    "not implemented yet")."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["package", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def test_package_requires_a_rendition_first(tmp_path, monkeypatch):
    """A piece with `ce render` never run has nothing to review -- refused
    with a hint, not an empty REVIEW.html."""
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.models import Brief, BriefDemand, GroundingStrength, Piece, Project

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    (tmp_path / "config" / "platforms").mkdir(parents=True, exist_ok=True)
    for name in ("linkedin", "facebook", "youtube"):
        shutil.copy(
            Path(__file__).parent.parent / "config" / "platforms" / f"{name}.yml",
            tmp_path / "config" / "platforms" / f"{name}.yml",
        )
    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )

    result = runner.invoke(cli.app, ["package", "pc-0001"])

    assert result.exit_code == Exit.ERROR
    assert "render" in str(result.exception)


def test_package_end_to_end(tmp_path, monkeypatch):
    """Wires `ce package` through the real CLI command: a piece with a
    LinkedIn rendition and a staged hero image produces
    `outbox/<id>/REVIEW.html` embedding the rendition's copy and
    referencing the copied image -- and never copies the staged
    `hero-source.*` *input* alongside the rendered `hero.*` *output*.
    """
    import shutil
    from datetime import UTC, date, datetime

    from ce import store
    from ce.models import (
        Brief,
        BriefDemand,
        GroundingStrength,
        Piece,
        PostPlatform,
        Project,
        Rendition,
    )

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    (tmp_path / "config" / "platforms").mkdir(parents=True, exist_ok=True)
    for name in ("linkedin", "facebook", "youtube"):
        shutil.copy(
            Path(__file__).parent.parent / "config" / "platforms" / f"{name}.yml",
            tmp_path / "config" / "platforms" / f"{name}.yml",
        )

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_piece(
        data_root,
        "test-proj",
        Piece(
            id="pc-0001",
            brief_id="br-01",
            project="test-proj",
            slug="a-piece",
            created_at=datetime.now(UTC),
            article_path=Path("article.md"),
        ),
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )

    utm_url = (
        "https://example.com/blog/a-piece"
        "?utm_source=linkedin&utm_medium=social&utm_campaign=a-piece"
    )
    linkedin_body = "A" * 50 + "."
    store.write_rendition(
        data_root,
        "test-proj",
        "pc-0001",
        Rendition(
            platform=PostPlatform.LINKEDIN,
            body=linkedin_body,
            first_comment=f"Link in the comments: {utm_url}",
            prompt_version=1,
            generated_at=datetime.now(UTC),
        ),
    )

    assets_dir = store.piece_dir(data_root, "test-proj", "pc-0001") / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "hero.jpg").write_bytes(b"fake-jpeg-bytes")
    (assets_dir / "hero-source.jpg").write_bytes(b"fake-jpeg-bytes")

    result = runner.invoke(cli.app, ["package", "pc-0001"])

    assert result.exit_code == Exit.OK, result.output

    outbox_dir = tmp_path / "outbox" / "pc-0001"
    review_html = (outbox_dir / "REVIEW.html").read_text(encoding="utf-8")
    assert "Why this project" in review_html
    assert linkedin_body in review_html
    # Jinja2 autoescape turns "&" into "&amp;" inside the <textarea> --
    # correct HTML (browsers decode it back on `.value` read); compare
    # against the escaped form rather than the raw URL.
    assert utm_url.replace("&", "&amp;") in review_html
    assert "assets/hero.jpg" in review_html
    assert "hero-source" not in review_html

    assert (outbox_dir / "assets" / "hero.jpg").exists()
    assert not (outbox_dir / "assets" / "hero-source.jpg").exists()


# --- publish site (WP-14, TDD 12 "Done when") -------------------------------
#
# Module-level coverage (frontmatter/file-plan shape, the edit/verify
# preconditions, OG tag assertion, poll timeout) lives in
# tests/test_publish_site.py, same split WP-13 used for package/review_html.
# These wire the real CLI command and check its dry-run/exit-code contract.


def test_publish_site_is_wired_not_a_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli.app, ["publish", "site", "pc-9999"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert isinstance(result.exception, CEError)


def _write_publishable_piece(tmp_path, *, generated_at):
    from datetime import UTC, date, datetime

    from ce import store
    from ce.models import Brief, BriefDemand, GroundingStrength, Piece, Project

    data_root = tmp_path / "data"
    store.write_project(
        data_root, Project(slug="test-proj", title="Test", started_at=date(2026, 7, 1))
    )
    store.write_briefs(
        data_root,
        "test-proj",
        [
            Brief(
                id="br-01",
                project="test-proj",
                archetype="why_this_project",
                title="Why this project",
                angle="origin",
                demand=BriefDemand(recurrence=1, signals=[]),
                grounding_strength=GroundingStrength.STRONG,
                dedupe_max_similarity=0.1,
                weakest_point="n=1",
            )
        ],
    )
    piece = Piece(
        id="pc-0001",
        brief_id="br-01",
        project="test-proj",
        slug="a-piece",
        created_at=datetime.now(UTC),
        article_path=Path("article.md"),
        generated_at=generated_at,
    )
    store.write_piece(data_root, "test-proj", piece)
    (store.piece_dir(data_root, "test-proj", "pc-0001") / "article.md").write_text(
        "# Why this project\n\nBody text here.\n", encoding="utf-8"
    )
    return data_root


def test_publish_site_dry_run_prints_frontmatter_and_file_plan_without_writing(
    tmp_path, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)  # identity.site_repo: ~/code/site -- never touched
    _write_publishable_piece(tmp_path, generated_at=datetime.now(UTC) - timedelta(days=1))

    result = runner.invoke(cli.app, ["publish", "site", "pc-0001", "--dry-run"])

    assert result.exit_code == Exit.OK, result.output
    assert "would write" in result.output
    assert "src/content/blog/a-piece.md" in result.output.replace("\\", "/")
    assert "title: Why this project" in result.output
    assert "pubDate:" in result.output


def test_publish_site_blocks_an_unedited_article_with_exit_4(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from ce.exit_codes import PreconditionUnmet

    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    _write_publishable_piece(tmp_path, generated_at=datetime.now(UTC) + timedelta(days=1))

    result = runner.invoke(cli.app, ["publish", "site", "pc-0001"])

    assert isinstance(result.exception, PreconditionUnmet)
    assert result.exception.exit_code == Exit.PRECONDITION


# --- posted / metrics pull (WP-15, TDD 12 "Done when") -----------------------
#
# Module-level coverage of the actual metrics logic (UTM click resolution,
# LinkedIn manual-entry-only, per-date idempotency) lives in
# tests/test_metrics_pull.py, same split WP-14 used for publish/site.py.
# These wire the real CLI commands and cover `ce posted`'s pure store I/O
# end to end (no external network involved, unlike `metrics pull`).


def test_posted_appends_to_posted_yml(tmp_path, monkeypatch):
    from ce import store

    monkeypatch.chdir(tmp_path)
    _write_publishable_piece(tmp_path, generated_at=None)

    result = runner.invoke(
        cli.app,
        ["posted", "pc-0001", "--platform", "linkedin", "--url", "https://linkedin.test/posts/1"],
    )

    assert result.exit_code == Exit.OK, result.output
    records = store.read_posted(tmp_path / "data")
    assert len(records) == 1
    assert records[0].piece_id == "pc-0001"
    assert records[0].platform.value == "linkedin"
    assert records[0].url == "https://linkedin.test/posts/1"


def test_posted_a_second_post_does_not_clobber_the_first(tmp_path, monkeypatch):
    from ce import store

    monkeypatch.chdir(tmp_path)
    _write_publishable_piece(tmp_path, generated_at=None)

    runner.invoke(
        cli.app,
        ["posted", "pc-0001", "--platform", "linkedin", "--url", "https://linkedin.test/posts/1"],
    )
    result = runner.invoke(
        cli.app,
        ["posted", "pc-0001", "--platform", "youtube", "--url", "https://youtu.be/dQw4w9WgXcQ"],
    )

    assert result.exit_code == Exit.OK, result.output
    records = store.read_posted(tmp_path / "data")
    assert len(records) == 2
    assert {r.platform.value for r in records} == {"linkedin", "youtube"}


def test_posted_unknown_piece_is_a_readable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        cli.app, ["posted", "pc-9999", "--platform", "linkedin", "--url", "https://x.test/1"]
    )

    assert isinstance(result.exception, CEError)
    assert not isinstance(result.exception, NotImplementedYet)


def test_posted_rejects_an_unknown_platform(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_publishable_piece(tmp_path, generated_at=None)

    result = runner.invoke(
        cli.app, ["posted", "pc-0001", "--platform", "tiktok", "--url", "https://x.test/1"]
    )

    assert isinstance(result.exception, CEError)
    assert "tiktok" in str(result.exception)


def test_metrics_pull_is_wired_not_a_stub(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)

    result = runner.invoke(cli.app, ["metrics", "pull"])

    assert not isinstance(result.exception, NotImplementedYet)
    assert result.exit_code == Exit.OK, result.output


def test_metrics_pull_with_no_posted_records_writes_performance_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)

    result = runner.invoke(cli.app, ["metrics", "pull"])

    assert result.exit_code == Exit.OK, result.output
    performance_md = (tmp_path / "data" / "performance.md").read_text(encoding="utf-8")
    assert "No posts recorded yet" in performance_md


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


def test_main_maps_ce_error_to_exit_code(tmp_path, monkeypatch):
    """cli.main translates a CEError into its process exit code."""

    def boom():
        raise GateBlocked("G1", "repo not in allowlist")

    # `main()` loads `.env` from cwd (TDD 14) -- chdir away from the repo
    # root so this doesn't pick up whatever real `.env` a developer has
    # sitting there and leak real keys into this (and later) tests' env.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == Exit.GATE_BLOCKED


def test_main_lets_unexpected_errors_surface(tmp_path, monkeypatch):
    """Only CEError is translated; genuine bugs keep their traceback."""

    def boom():
        raise ValueError("a real bug")

    monkeypatch.chdir(tmp_path)  # see test_main_maps_ce_error_to_exit_code
    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(ValueError):
        cli.main()


def test_ce_error_hint_is_optional():
    exc = CEError("bare message")
    assert exc.hint is None


def test_main_loads_dotenv_from_cwd(tmp_path, monkeypatch):
    """`ce`'s entry point loads `.env` from the current directory before
    running any command, so API keys can live in a gitignored file
    instead of requiring `setx`/persistent env vars (existing env vars
    still win, per `load_dotenv`'s `override=False` default)."""
    import os

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CE_TEST_DOTENV_VAR", raising=False)
    (tmp_path / ".env").write_text("CE_TEST_DOTENV_VAR=hello\n", encoding="utf-8")
    monkeypatch.setattr(cli, "app", lambda: None)

    try:
        cli.main()
        assert os.environ.get("CE_TEST_DOTENV_VAR") == "hello"
    finally:
        # dotenv writes straight to os.environ; monkeypatch only auto-undoes
        # its own setenv/delenv calls, so this needs an explicit cleanup.
        os.environ.pop("CE_TEST_DOTENV_VAR", None)
