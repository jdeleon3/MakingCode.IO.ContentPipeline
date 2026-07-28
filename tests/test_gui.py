"""WP-17 acceptance: `ce gui` serves on 127.0.0.1 only; `/doctor` streams a
real `ce doctor` subprocess line-by-line via SSE and shows the correct exit
code; reloading `/doctor?run=<id>` resumes from the tailed log; stopping the
GUI leaves no orphaned child process.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from ce.gui import runner
from ce.gui.app import create_app

pytest.importorskip("fastapi")


@pytest.fixture(autouse=True)
def _clean_run_registry():
    """`runner._runs` is a module-level dict shared across the whole `ce
    gui` process's lifetime by design (ADR-009: not a daemon, no cross-run
    persistence needed) -- reset it between tests so one test's runs can't
    leak into another's."""
    runner._runs.clear()
    yield
    runner._runs.clear()


def test_run_command_and_stream_real_doctor_subprocess(tmp_path):
    """Exercises `runner.py` directly (no HTTP layer): a real `ce doctor`
    subprocess is launched, its log is tailed from the file (not piped
    stdout), and the final event carries the process's real exit code."""
    handle = runner.run_command(["doctor"], cwd=tmp_path, data_root=tmp_path / "data")

    lines: list[str] = []
    exit_code = None
    for event in runner.stream_run(handle.run_id):
        if "line" in event:
            lines.append(event["line"])
        if event.get("done"):
            exit_code = event["exit_code"]

    assert exit_code in (0, 1)  # this dev machine may or may not pass doctor
    assert any("environment check" in line.lower() for line in lines)
    assert handle.log_path.exists()


def test_terminate_all_stops_still_running_processes():
    """Unit-level proof of the orphan-prevention mechanism WP-17's Done-when
    line requires, using a fake process handle rather than a real long-lived
    subprocess (nothing in this pipeline's own commands run indefinitely, so
    there's no real command to race against a shutdown deterministically)."""

    class _FakeProcess:
        def __init__(self) -> None:
            self.terminated = False
            self._alive = True

        def poll(self) -> int | None:
            return None if self._alive else 0

        def terminate(self) -> None:
            self.terminated = True
            self._alive = False

    fake = _FakeProcess()
    handle = runner.RunHandle(
        run_id="fake-run", args=["doctor"], log_path=Path("unused.log"), process=fake
    )
    runner._runs["fake-run"] = handle

    runner.terminate_all()

    assert fake.terminated


def test_gui_serves_on_127_0_0_1_and_doctor_screen_streams_and_resumes(tmp_path, monkeypatch):
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
        assert server.started, "uvicorn server did not start in time"

        port = server.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"

        page = httpx.get(f"{base}/doctor", timeout=10)
        assert page.status_code == 200
        assert "Run ce doctor" in page.text

        started = httpx.post(f"{base}/doctor/run", timeout=10)
        assert started.status_code == 200
        run_id = started.json()["run_id"]

        exit_code = None
        lines: list[str] = []
        with httpx.stream("GET", f"{base}/doctor/stream/{run_id}", timeout=60) as stream:
            for raw in stream.iter_lines():
                if not raw.startswith("data: "):
                    continue
                event = json.loads(raw[len("data: ") :])
                if "line" in event:
                    lines.append(event["line"])
                if event.get("done"):
                    exit_code = event["exit_code"]
                    break

        assert exit_code in (0, 1)
        assert any("environment check" in line.lower() for line in lines)

        # Reloading /doctor?run=<id> after the run finished still renders
        # (the page's inline script reconnects and replays from the log
        # file rather than needing the run to still be in-flight).
        reload_resp = httpx.get(f"{base}/doctor?run={run_id}", timeout=10)
        assert reload_resp.status_code == 200
        assert run_id in reload_resp.text
    finally:
        server.should_exit = True
        thread.join(timeout=10)
