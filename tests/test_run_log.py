"""WP-17 acceptance: every invocation gets a plain-text `data/runs/<run-id>-
<command>.log` (TDD §14), which `gui/runner.py` depends on tailing."""

import io
import sys

import pytest

from ce import run_log


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["doctor"], "doctor"),
        (["brief", "select", "br-01"], "brief-select"),
        (["gui", "--port", "8420"], "gui"),
        (["produce", "pc-0001", "--force"], "produce-pc-0001"),
        ([], "ce"),
    ],
)
def test_command_name(argv, expected):
    assert run_log.command_name(argv) == expected


def test_new_run_id_has_no_colons_and_sorts_chronologically():
    a = run_log.new_run_id()
    b = run_log.new_run_id()
    assert ":" not in a
    assert a <= b


def test_tee_writes_plain_text_log_and_strips_ansi_but_not_the_real_stream(tmp_path, monkeypatch):
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    with run_log.tee(tmp_path, ["doctor"]) as log_path:
        print("\x1b[32mhello\x1b[0m")

    assert "\x1b[32m" in fake_stdout.getvalue()
    logged = log_path.read_text(encoding="utf-8")
    assert "hello" in logged
    assert "\x1b[" not in logged
    assert sys.stdout is fake_stdout  # restored after the block


def test_tee_uses_ce_run_id_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv(run_log.RUN_ID_ENV_VAR, "20260101T000000000000")
    with run_log.tee(tmp_path, ["doctor"]) as log_path:
        pass
    assert log_path.name == "20260101T000000000000-doctor.log"


def test_tee_generates_a_run_id_when_env_var_absent(tmp_path, monkeypatch):
    monkeypatch.delenv(run_log.RUN_ID_ENV_VAR, raising=False)
    with run_log.tee(tmp_path, ["doctor"]) as log_path:
        pass
    assert log_path.exists()
    assert log_path.parent == tmp_path / "runs"
