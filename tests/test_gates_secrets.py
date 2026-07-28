"""G2 — secret scan (TDD 6.2, 12 WP-05).

`gitleaks` isn't installed in this dev environment (confirmed via
`ce doctor`), so `GitleaksScanner` itself is exercised manually on a machine
that has it. These tests cover the deny-list matcher, `list_scannable_files`
(a real `git ls-files` call — `git` is installed here), and `scan_repo`/
`write_redaction_report` against the `SecretScanner` Protocol via a fake.
"""

import json
import subprocess
from pathlib import Path

import pytest

from ce.gates.secrets import (
    SecretFinding,
    is_denied,
    list_scannable_files,
    scan_repo,
    write_redaction_report,
)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        "nested/dir/.env",
        "server.pem",
        "certs/server.pem",
        "id_rsa",
        "id_rsa.pub",
        "secrets/db.yml",
        "a/b/secrets/db.yml",
        "credentials.json",
        "prod.tfstate",
        ".npmrc",
        ".pypirc",
        "tests/fixtures/anything.py",
        "a/fixtures/b/c.py",
        "seed-data/x.sql",
        "a/seed_users/y.sql",
    ],
)
def test_denied_paths(path):
    assert is_denied(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "src/main.py",
        "README.md",
        "config/engine.yml",
        "docs/adr/0001.md",
        "environment.py",  # doesn't match ".env*" -- different filename entirely
    ],
)
def test_allowed_paths(path):
    assert is_denied(path) is False


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    return repo


def test_list_scannable_files_excludes_denied(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (repo / "secrets").mkdir()
    (repo / "secrets" / "db.yml").write_text("password: hunter2\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    files = list_scannable_files(repo)
    names = {f.relative_to(repo).as_posix() for f in files}

    assert names == {"main.py"}


class FakeScanner:
    def __init__(self, findings: list[SecretFinding]):
        self._findings = findings
        self.calls: list[tuple[Path, list[Path]]] = []

    def scan(self, repo_path: Path, files: list[Path]) -> list[SecretFinding]:
        self.calls.append((repo_path, files))
        return self._findings


def test_scan_repo_returns_findings_and_scanned_count(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    finding = SecretFinding(rule_id="generic-api-key", file="main.py", line=1, match="xxx")
    scanner = FakeScanner([finding])

    findings, scanned_count = scan_repo(repo, scanner)

    assert findings == [finding]
    assert scanned_count == 1  # .env excluded by the deny-list before scanning
    # The scanner never even receives the denied file's path.
    scanned_paths = {p.name for p in scanner.calls[0][1]}
    assert scanned_paths == {"main.py"}


def test_write_redaction_report(tmp_path):
    report_path = tmp_path / "redaction-report.json"
    findings = [
        SecretFinding(rule_id="aws-access-key-id", file="config.py", line=12, match="AKIA...")
    ]

    write_redaction_report(report_path, tmp_path / "repo", findings)

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["findings"][0]["rule_id"] == "aws-access-key-id"
    assert data["findings"][0]["file"] == "config.py"
