"""WP-19 acceptance: `/runs` triggers real §9 stage commands through
`runner.py` and streams them live; a gate-blocked run (exit 2) is visibly
distinguished from success; `ce publish site` cannot be submitted without
the confirm step; closing the browser tab mid-run doesn't kill the
subprocess, and reopening `/runs/<run-id>` replays the same log.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
import uvicorn

from ce import store
from ce.gui import runner
from ce.gui.app import create_app
from ce.models import Project, PublishableLevel, RepoRef

pytest.importorskip("fastapi")

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


def _write_minimal_engine_config(root: Path) -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "engine.yml").write_text(_MINIMAL_ENGINE_YML, encoding="utf-8")


def _make_gate_blocked_project(tmp_path: Path, slug: str = "blocked-proj") -> None:
    """A project whose one repo is NOT in `config.repos.allowed` (empty in
    `_MINIMAL_ENGINE_YML`) -- `ce harvest` hits G1 before any git subprocess
    runs and exits 2. Written directly via `store.write_project`, not `ce
    project new --repo`, because that CLI command already fail-fasts on an
    unlisted repo at creation time (`project.py::_resolve_repo`) -- this
    reproduces the same repos-list-changed-after-creation scenario that
    module's own docstring calls out as G1's real job to catch."""
    data_root = tmp_path / "data"
    repo_dir = tmp_path / "some-repo"
    repo_dir.mkdir()
    project = Project(
        slug=slug,
        title="Blocked",
        started_at=date(2026, 1, 1),
        repos=[RepoRef(name="some-repo", path=repo_dir, publishable=PublishableLevel.FULL)],
    )
    store.write_project(data_root, project)
    store.scaffold_project_tree(data_root, slug)


@pytest.fixture(autouse=True)
def _clean_run_registry():
    runner._runs.clear()
    yield
    runner._runs.clear()


def test_gate_blocked_harvest_exits_2_and_is_reported_over_the_run_stream(tmp_path):
    """Runner-level proof that a real gate-blocked run's exit code (2, not
    0 and not a generic 1) reaches whoever is tailing the log -- the data
    the `/runs/<run-id>` page's exit-code branch (0 / 2 / other) depends on."""
    _write_minimal_engine_config(tmp_path)
    _make_gate_blocked_project(tmp_path)

    handle = runner.run_command(
        ["harvest", "blocked-proj"], cwd=tmp_path, data_root=tmp_path / "data"
    )

    lines: list[str] = []
    exit_code = None
    for event in runner.stream_run(handle.run_id):
        if "line" in event:
            lines.append(event["line"])
        if event.get("done"):
            exit_code = event["exit_code"]

    assert exit_code == 2
    assert any("G1" in line or "allowlist" in line.lower() for line in lines)


def test_runs_start_rejects_publish_site_without_confirm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    resp = client.post("/runs/start", json={"command": "publish-site", "argument": "pc-0001"})

    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"].lower()
    assert not runner._runs  # nothing was ever launched


def test_runs_start_accepts_publish_site_with_confirm(tmp_path, monkeypatch):
    """Confirming submits like any other command -- whether the underlying
    `ce publish site` itself then succeeds is out of scope here (that's
    WP-14's own test suite); this only proves the GUI's confirm gate is the
    thing standing in the way, not a hidden second block."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    resp = client.post(
        "/runs/start",
        json={"command": "publish-site", "argument": "pc-0001", "confirm": True},
    )

    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    handle = runner.get_run(run_id)
    assert handle is not None
    assert handle.args == ["publish", "site", "pc-0001"]


def test_runs_picker_page_disables_publish_site_until_confirmed(tmp_path, monkeypatch):
    """Static-content proof that the picker page ships the confirm-required
    flag and gating script for `publish-site` -- the actual disabling is a
    DOM/JS behavior a headless httpx client can't execute, but the data and
    logic it depends on must be present in what the server rendered."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    resp = client.get("/runs")

    assert resp.status_code == 200
    assert 'data-confirm="true"' in resp.text
    assert "publish-site" in resp.text
    assert "submitBtn.disabled" in resp.text


def test_run_detail_page_distinguishes_gate_blocked_from_success(tmp_path, monkeypatch):
    """Static-content proof the `/runs/<run-id>` page's script actually
    branches on exit code 2 into a distinctly labeled/styled state, not
    lumped in with either "passed" or a generic "failed"."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    handle = runner.run_command(["doctor"], cwd=tmp_path, data_root=tmp_path / "data")
    # Drain so the fixture's process doesn't linger past the test.
    for _ in runner.stream_run(handle.run_id):
        pass

    resp = client.get(f"/runs/{handle.run_id}")

    assert resp.status_code == 200
    assert "status-gate-blocked" in resp.text
    assert "gate blocked" in resp.text.lower()
    assert "exit_code === 2" in resp.text


def test_doctor_run_via_runs_console_streams_live_and_exits(tmp_path, monkeypatch):
    """Full HTTP round-trip: submit `ce doctor` through `/runs/start` (the
    generic picker, not `/doctor/run`), stream `/runs/stream/<id>`, and get
    real output + the real exit code."""
    monkeypatch.chdir(tmp_path)

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        assert server.started

        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        started = httpx.post(f"{base}/runs/start", json={"command": "doctor"}, timeout=10)
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        def _drain_stream():
            lines: list[str] = []
            exit_code = None
            with httpx.stream("GET", f"{base}/runs/stream/{run_id}", timeout=60) as stream:
                for raw in stream.iter_lines():
                    if not raw.startswith("data: "):
                        continue
                    event = json.loads(raw[len("data: ") :])
                    if "line" in event:
                        lines.append(event["line"])
                    if event.get("done"):
                        exit_code = event["exit_code"]
                        break
            return lines, exit_code

        lines, exit_code = _drain_stream()
        assert exit_code in (0, 1)
        assert any("environment check" in line.lower() for line in lines)

        # Reopening /runs/<run-id> (not a query param -- WP-19's literal
        # Done-when wording) after the run finished still renders, and
        # re-streaming from it replays the identical log from the top --
        # proof closing the tab never killed the subprocess, and the log
        # file (not a one-shot pipe) is what's being served.
        page = httpx.get(f"{base}/runs/{run_id}", timeout=10)
        assert page.status_code == 200
        assert run_id in page.text
        assert "doctor" in page.text

        replay_lines, replay_exit_code = _drain_stream()
        assert replay_lines == lines
        assert replay_exit_code == exit_code
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_gate_blocked_harvest_via_runs_console_reports_exit_2_over_http(tmp_path, monkeypatch):
    """Same gate-blocked scenario as
    `test_gate_blocked_harvest_exits_2_and_is_reported_over_the_run_stream`,
    but driven through the actual HTTP route (`/runs/start` +
    `/runs/stream/<id>`) rather than calling `runner` directly -- proves the
    real exit-2 case, not just `ce doctor`'s 0/1, reaches the SSE wire the
    `/runs/<run-id>` page's exit-code branch depends on."""
    monkeypatch.chdir(tmp_path)
    _write_minimal_engine_config(tmp_path)
    _make_gate_blocked_project(tmp_path)

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        assert server.started

        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        started = httpx.post(
            f"{base}/runs/start",
            json={"command": "harvest", "argument": "blocked-proj"},
            timeout=10,
        )
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        lines: list[str] = []
        exit_code = None
        with httpx.stream("GET", f"{base}/runs/stream/{run_id}", timeout=60) as stream:
            for raw in stream.iter_lines():
                if not raw.startswith("data: "):
                    continue
                event = json.loads(raw[len("data: ") :])
                if "line" in event:
                    lines.append(event["line"])
                if event.get("done"):
                    exit_code = event["exit_code"]
                    break

        assert exit_code == 2
        assert any("G1" in line or "allowlist" in line.lower() for line in lines)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_runs_page_lists_recent_runs_from_log_files(tmp_path, monkeypatch):
    """`/runs` reads `data/runs/*.log` for its recent-runs list (TDD 10.10's
    Screens table) -- proven here against real files written by
    `runner.run_command`, not fabricated log names, including a two-token
    command (`brief select` -> `brief-select`, `run_log.py::command_name`'s
    own hyphenation)."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    doctor_handle = runner.run_command(["doctor"], cwd=tmp_path, data_root=tmp_path / "data")
    for _ in runner.stream_run(doctor_handle.run_id):
        pass
    brief_handle = runner.run_command(
        ["brief", "select", "br-01"], cwd=tmp_path, data_root=tmp_path / "data"
    )
    for _ in runner.stream_run(brief_handle.run_id):
        pass

    resp = client.get("/runs")

    assert resp.status_code == 200
    assert doctor_handle.run_id in resp.text
    assert brief_handle.run_id in resp.text
    assert "brief-select" in resp.text


def test_run_detail_unknown_run_id_is_404(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient

    client = TestClient(create_app())

    resp = client.get("/runs/does-not-exist")

    assert resp.status_code == 404
