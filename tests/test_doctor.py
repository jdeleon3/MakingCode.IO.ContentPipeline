"""WP-00 acceptance: doctor reports every dependency and exits 1 on a missing required one."""

import pytest

from ce import doctor
from ce.doctor import Check, CheckResult
from ce.exit_codes import Exit


def _fake_check(name="thing", ok=True, required=True):
    return Check(
        name=name,
        probe=lambda: CheckResult(ok, "detail"),
        required=required,
        needed_for="WP-00",
        install="install it",
    )


def test_all_present_returns_ok(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [_fake_check(ok=True)])
    assert doctor.run() == Exit.OK


def test_missing_required_returns_error(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [_fake_check(ok=False, required=True)])
    assert doctor.run() == Exit.ERROR


def test_missing_optional_still_ok(monkeypatch):
    """A dependency for a future WP must not fail the check."""
    monkeypatch.setattr(doctor, "CHECKS", [_fake_check(ok=False, required=False)])
    assert doctor.run() == Exit.OK


def test_strict_promotes_optional_to_required(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [_fake_check(ok=False, required=False)])
    assert doctor.run(strict=True) == Exit.ERROR


def test_probe_exception_is_contained(monkeypatch):
    """A probe that raises must be reported as a failure, not crash the CLI."""

    def exploding():
        raise RuntimeError("probe blew up")

    check = Check(
        name="explodes",
        probe=exploding,
        required=False,
        needed_for="WP-00",
        install="n/a",
    )
    monkeypatch.setattr(doctor, "CHECKS", [check])
    assert doctor.run() == Exit.OK  # optional, so still OK overall


def test_real_checks_are_wellformed():
    """Every registered check has the metadata the report needs."""
    assert doctor.CHECKS, "no checks registered"
    for check in doctor.CHECKS:
        assert check.name
        assert check.install, f"{check.name} has no install hint"
        assert check.needed_for.startswith("WP-"), f"{check.name} needed_for is not a WP id"
        assert callable(check.probe)


def test_python_check_reflects_running_interpreter():
    result = doctor.check_python()
    assert isinstance(result, CheckResult)
    assert result.detail


def test_missing_binary_is_not_an_exception():
    result = doctor._run_version(["definitely-not-a-real-binary-xyz", "--version"])
    assert result.ok is False
    assert "not on PATH" in result.detail


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
def test_env_probe_never_prints_secret(monkeypatch, var):
    monkeypatch.setenv(var, "sk-super-secret-value")
    probe = doctor._check_env(var)
    result = probe()
    assert result.ok
    assert "sk-super-secret-value" not in result.detail
    assert "chars" in result.detail


def test_env_probe_treats_blank_as_missing(monkeypatch):
    monkeypatch.setenv("CE_TEST_VAR", "   ")
    assert doctor._check_env("CE_TEST_VAR")().ok is False
