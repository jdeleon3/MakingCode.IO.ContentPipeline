"""WP-05 acceptance (TDD 12): git harvest + safety gates.

`git` is installed in this dev environment (unlike `gitleaks`; see
`gates/secrets.py`), so every test here builds a real, throwaway git repo
under `tmp_path` and runs the real `git log`/`git ls-files` subprocess calls
against it — only the secret *scanner* is a fake, since gitleaks itself
isn't on PATH here (confirmed via `ce doctor`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ce.exit_codes import GateBlocked
from ce.gates.secrets import SecretFinding
from ce.harvest import git as git_harvest
from ce.harvest.git import ParsedCommit, RedactionSummary, _commit_prompt_vars
from ce.llm.gateway import Gateway, ProviderResponse
from ce.models import Project, PublishableLevel, RepoRef

GOLDEN_PATH = Path(__file__).parent / "golden" / "significance-scoring.json"
BASE = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return proc.stdout


def _init_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    return repo


def _commit(repo: Path, subject: str, body: str, files: dict[str, str], when: datetime) -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git("add", "-A", cwd=repo)

    date_str = when.isoformat()
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": date_str,
        "GIT_COMMITTER_DATE": date_str,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    args = ["commit", "-q", "-m", subject]
    if body:
        args += ["-m", body]
    _git(*args, cwd=repo, env=env)
    return _git("rev-parse", "HEAD", cwd=repo).strip()


class FakeScanner:
    """No findings, ever -- used by tests exercising everything *except*
    G2's blocking path."""

    def scan(self, repo_path: Path, files: list[Path]) -> list[SecretFinding]:
        return []


class FakeAwsKeyScanner:
    """Stand-in for `GitleaksScanner` (gitleaks isn't installed in this dev
    environment) that does *real* regex detection against real file
    content, rather than a scripted response -- so the mandatory
    planted-secret test (TDD 12 WP-05, TDD 13 #2) proves actual detection
    against a real fixture repo.
    """

    _AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")

    def scan(self, repo_path: Path, files: list[Path]) -> list[SecretFinding]:
        findings = []
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for match in self._AWS_KEY_RE.finditer(text):
                findings.append(
                    SecretFinding(
                        rule_id="aws-access-key-id",
                        file=str(f.relative_to(repo_path)),
                        match=match.group()[:8] + "...",
                    )
                )
        return findings


class FakeLLMClient:
    def __init__(self, content: str = "summary"):
        self.content = content
        self.calls: list[dict] = []

    def complete(self, *, model, system, user, max_tokens):
        self.calls.append({"model": model, "system": system, "user": user})
        return ProviderResponse(content=self.content, in_tokens=10, out_tokens=5)


def _repo_ref(path: Path, name: str = "thing", publishable=PublishableLevel.FULL) -> RepoRef:
    return RepoRef(name=name, path=path, publishable=publishable)


def _allowed_config(make_engine_config, repo_path: Path, **repo_ref_kwargs):
    """An `EngineConfig` whose allowlist contains exactly `repo_path`."""
    return make_engine_config(
        repos={"allowed": [_repo_ref(repo_path, **repo_ref_kwargs).model_dump(mode="json")]}
    )


def _project_with_repo(repo_path: Path, publishable=PublishableLevel.FULL, name: str = "thing"):
    return Project(
        slug="test-proj",
        title="Test",
        started_at="2026-01-01",
        repos=[_repo_ref(repo_path, name=name, publishable=publishable)],
    )


def _gateway(tmp_path: Path, config, client=None) -> Gateway:
    return Gateway(
        config,
        data_root=tmp_path / "data",
        prompts_dir=Path("prompts"),
        client=client or FakeLLMClient(),
    )


# ---------------------------------------------------------------------------
# G1 — raises before any git subprocess runs
# ---------------------------------------------------------------------------


def test_repo_outside_allowlist_raises_before_any_git_subprocess(
    tmp_path, make_engine_config, monkeypatch
):
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "x\n"}, BASE)

    project = _project_with_repo(repo_path)
    config = make_engine_config(repos={"allowed": []})  # repo NOT in the allowlist
    gateway = _gateway(tmp_path, config)

    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)

    with pytest.raises(GateBlocked, match="G1"):
        git_harvest.extract(
            project,
            lookback_days=60,
            gateway=gateway,
            harvest_dir=tmp_path / "harvest",
            min_significance=2,
            secret_scanner=FakeScanner(),
        )

    assert calls == []  # not one git subprocess was invoked


# ---------------------------------------------------------------------------
# G2 — mandatory planted-secret test (TDD 12 WP-05, TDD 13 #2)
# ---------------------------------------------------------------------------


def test_planted_aws_key_blocks_and_writes_redaction_report(tmp_path, make_engine_config):
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)
    _commit(
        repo_path,
        "Add deploy script with a hardcoded key",
        "",
        {"deploy.sh": "export AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n"},
        BASE + timedelta(days=1),
    )

    project = _project_with_repo(repo_path)
    config = _allowed_config(make_engine_config, repo_path)
    gateway = _gateway(tmp_path, config)
    harvest_dir = tmp_path / "harvest"

    with pytest.raises(GateBlocked, match="G2") as exc_info:
        git_harvest.extract(
            project,
            lookback_days=60,
            gateway=gateway,
            harvest_dir=harvest_dir,
            min_significance=2,
            secret_scanner=FakeAwsKeyScanner(),
            now=BASE + timedelta(days=2),
        )
    assert exc_info.value.exit_code == 2

    report_path = harvest_dir / "redaction-report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["findings"][0]["rule_id"] == "aws-access-key-id"
    assert report["findings"][0]["file"] == "deploy.sh"

    # git.json is never written on a G2 block -- a blocked run must not
    # look like a completed harvest.
    assert not (harvest_dir / "git.json").exists()


def test_denied_path_secret_is_never_reachable_by_the_scanner(tmp_path, make_engine_config):
    """A key sitting in a `.env` file -- denied before any content is read
    -- must never even reach the scanner, real or fake."""
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)
    _commit(
        repo_path,
        "Add local env file",
        "",
        {".env": "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n"},
        BASE + timedelta(days=1),
    )

    project = _project_with_repo(repo_path)
    config = _allowed_config(make_engine_config, repo_path)
    gateway = _gateway(tmp_path, config)

    harvest = git_harvest.extract(
        project,
        lookback_days=60,
        gateway=gateway,
        harvest_dir=tmp_path / "harvest",
        min_significance=2,
        secret_scanner=FakeAwsKeyScanner(),
        now=BASE + timedelta(days=2),
    )

    assert harvest.repos[0].redaction.findings == 0
    assert harvest.repos[0].redaction.scanned == 1  # README.md only; .env excluded


# ---------------------------------------------------------------------------
# No diff content ever reaches gateway.complete (TDD 6.2, 13 #3)
# ---------------------------------------------------------------------------


def test_git_log_never_requests_patch_content(tmp_path, make_engine_config, monkeypatch):
    """Code-inspection half of the mandatory check: the only git subprocess
    this module's `_run_git_log` ever constructs asks for `--numstat`, never
    a patch, a diff, or a `git show`. (Checked against just that function's
    source, not the whole module, so this doesn't trip over the word "diff"
    appearing in an unrelated docstring elsewhere in the file.)
    """
    import inspect

    cmd_source = inspect.getsource(git_harvest._run_git_log)
    assert "--patch" not in cmd_source
    assert "show" not in cmd_source
    assert "diff" not in cmd_source

    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)

    logged_cmds: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(cmd, *args, **kwargs):
        logged_cmds.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)

    project = _project_with_repo(repo_path)
    config = _allowed_config(make_engine_config, repo_path)
    gateway = _gateway(tmp_path, config)

    git_harvest.extract(
        project,
        lookback_days=60,
        gateway=gateway,
        harvest_dir=tmp_path / "harvest",
        min_significance=2,
        secret_scanner=FakeScanner(),
        now=BASE + timedelta(days=1),
    )

    git_log_cmds = [c for c in logged_cmds if c[:2] == ["git", "log"]]
    assert len(git_log_cmds) == 1
    joined = " ".join(git_log_cmds[0])
    assert "--patch" not in joined
    assert "-p" not in git_log_cmds[0]
    assert "--numstat" in joined


def test_commit_summarize_vars_hold_no_diff_content(tmp_path, make_engine_config):
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)
    _commit(
        repo_path,
        "feat: add a fairly long explanatory message describing exactly what changed and why it mattered here today",
        "",
        {"src/a.py": "x = 1\n"},
        BASE + timedelta(days=1),
    )

    project = _project_with_repo(repo_path)
    config = _allowed_config(make_engine_config, repo_path)
    llm_client = FakeLLMClient()
    gateway = _gateway(tmp_path, config, client=llm_client)

    git_harvest.extract(
        project,
        lookback_days=60,
        gateway=gateway,
        harvest_dir=tmp_path / "harvest",
        min_significance=2,
        secret_scanner=FakeScanner(),
        now=BASE + timedelta(days=2),
    )

    assert len(llm_client.calls) == 1  # only the one kept ("explained") commit
    prompt_text = llm_client.calls[0]["user"] + llm_client.calls[0]["system"]
    assert "x = 1" not in prompt_text  # the file's actual content never appears
    assert "+++" not in prompt_text
    assert "@@" not in prompt_text  # no unified-diff markers


# ---------------------------------------------------------------------------
# lessons-only propagation (TDD 6.1, 12 WP-05)
# ---------------------------------------------------------------------------


def test_lessons_only_repo_omits_repo_name_and_paths_from_prompt_vars(tmp_path, make_engine_config):
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)
    _commit(
        repo_path,
        "feat: add a fairly long explanatory message describing exactly what changed and why it mattered here today",
        "",
        {"src/secret_shaped_path.py": "x = 1\n"},
        BASE + timedelta(days=1),
    )

    project = _project_with_repo(
        repo_path, publishable=PublishableLevel.LESSONS_ONLY, name="client-thing"
    )
    config = _allowed_config(
        make_engine_config,
        repo_path,
        name="client-thing",
        publishable=PublishableLevel.LESSONS_ONLY,
    )
    llm_client = FakeLLMClient()
    gateway = _gateway(tmp_path, config, client=llm_client)

    git_harvest.extract(
        project,
        lookback_days=60,
        gateway=gateway,
        harvest_dir=tmp_path / "harvest",
        min_significance=2,
        secret_scanner=FakeScanner(),
        now=BASE + timedelta(days=2),
    )

    prompt_text = llm_client.calls[0]["user"] + llm_client.calls[0]["system"]
    assert "client-thing" not in prompt_text
    assert "secret_shaped_path.py" not in prompt_text


def test_full_repo_prompt_vars_include_repo_name_and_paths():
    commit = ParsedCommit(
        sha="a" * 40,
        at=BASE,
        author="Test",
        subject="feat: x",
        body="",
        files=("src/a.py",),
        insertions=1,
        deletions=0,
    )
    full_repo = _repo_ref(Path("/tmp/x"), name="content-engine", publishable=PublishableLevel.FULL)
    vars_ = _commit_prompt_vars(commit, full_repo)
    assert vars_["repo_name"] == "content-engine"
    assert vars_["file_paths"] == ["src/a.py"]
    assert vars_["lessons_only"] is False

    lessons_repo = _repo_ref(
        Path("/tmp/x"), name="content-engine", publishable=PublishableLevel.LESSONS_ONLY
    )
    vars_lessons = _commit_prompt_vars(commit, lessons_repo)
    assert vars_lessons["repo_name"] is None
    assert vars_lessons["file_paths"] == []
    assert vars_lessons["lessons_only"] is True


# ---------------------------------------------------------------------------
# extract() end-to-end: git.json shape, kept/dropped counts, redaction summary
# ---------------------------------------------------------------------------


def test_extract_writes_git_json_with_expected_shape(tmp_path, make_engine_config):
    repo_path = _init_repo(tmp_path)
    _commit(repo_path, "Initial commit", "", {"README.md": "hello\n"}, BASE)
    _commit(
        repo_path, "wip: checkpoint", "", {"README.md": "hello again\n"}, BASE + timedelta(days=1)
    )
    _commit(
        repo_path,
        "feat: add a fairly long explanatory message describing exactly what changed and why it mattered here today",
        "",
        {"src/a.py": "x = 1\n"},
        BASE + timedelta(days=2),
    )

    project = _project_with_repo(repo_path)
    config = _allowed_config(make_engine_config, repo_path)
    gateway = _gateway(tmp_path, config)
    harvest_dir = tmp_path / "harvest"

    harvest = git_harvest.extract(
        project,
        lookback_days=60,
        gateway=gateway,
        harvest_dir=harvest_dir,
        min_significance=2,
        secret_scanner=FakeScanner(),
        now=BASE + timedelta(days=3),
    )

    assert (harvest_dir / "git.json").exists()
    data = json.loads((harvest_dir / "git.json").read_text(encoding="utf-8"))
    assert list(data["repos"][0].keys()) == [
        "repo",
        "range",
        "total_commits",
        "kept",
        "dropped",
        "commits",
        "redaction",
    ]

    repo_harvest = harvest.repos[0]
    assert repo_harvest.total_commits == 3
    assert repo_harvest.kept == 1  # only the long "feat:" commit clears min_significance=2
    assert repo_harvest.dropped == 2
    assert repo_harvest.redaction == RedactionSummary(scanned=2, findings=0)
    [record] = repo_harvest.commits
    assert record.score == 2
    assert record.reasons == ["explained"]
    assert record.summary == "summary"  # FakeLLMClient's canned content


# ---------------------------------------------------------------------------
# Significance scoring golden fixture (TDD 12 WP-05, TDD 13 golden files)
# ---------------------------------------------------------------------------


def _build_significance_fixture(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path, "significance-repo")
    shas: dict[int, str] = {}

    def c(idx: int, day: int, subject: str, body: str, files: dict[str, str]) -> None:
        shas[idx] = _commit(repo, subject, body, files, BASE + timedelta(days=day))

    c(0, 0, "Initial commit", "", {"README.md": "# Project\n"})
    c(
        1,
        1,
        "feat: scaffold the ingestion pipeline module with an initial in-memory queue and basic "
        "structure for early local testing purposes",
        "",
        {"src/pipeline.py": "def run():\n    pass\n"},
    )
    c(2, 2, "wip: checkpoint", "", {"src/pipeline.py": "def run():\n    pass\n# note\n"})
    c(3, 3, "chore: bump dependency versions", "", {"package.json": '{"a": 1}\n'})
    c(
        4,
        4,
        "fix: correct queue overflow check",
        "",
        {"src/pipeline.py": "def run():\n    pass\n# fixed\n"},
    )
    c(
        5,
        8,
        "fix: resolve the OOM when the join spills to disk",
        "",
        {"src/join.py": "def join():\n    pass\n"},
    )
    c(6, 9, "docs: explain the spill-to-disk workaround", "", {"docs/architecture.md": "notes\n"})
    c(
        7,
        10,
        'Revert "feat: add risky caching layer"',
        f"This reverts commit {shas[6][:7]}.",
        {"src/cache.py": "# reverted\n"},
    )
    c(
        8,
        24,
        "style: reformat with prettier",
        "",
        {"src/pipeline.py": "def run():\n    pass  # fmt\n"},
    )
    c(9, 25, "typo: fix README typo", "", {"README.md": "# Project (fixed typo)\n"})
    c(10, 26, "bump: patch version number", "", {"VERSION": "0.1.1\n"})
    c(
        11,
        27,
        "fmt: run gofmt across the repo",
        "",
        {"src/join.py": "def join():\n    pass  # fmt\n"},
    )
    c(12, 28, "lint: fix eslint warnings", "", {"src/cache.py": "# reverted\n# lint\n"})
    c(
        13,
        29,
        "Add generated fixture data dump for local testing",
        "",
        {"data/big.txt": "\n".join(f"line{i:03d}" for i in range(1, 151)) + "\n"},
    )
    c(
        14,
        30,
        "Trim the generated fixture data down to essentials",
        "",
        {"data/big.txt": "\n".join(f"line{i:03d}" for i in range(1, 31)) + "\n"},
    )
    c(15, 31, "Add a go module for the sidecar", "", {"go.mod": "module sidecar\n"})
    c(
        16,
        32,
        "Update the lockfile after a dependency bump",
        "",
        {"pnpm-lock.yaml": "lockfile v1\n"},
    )
    c(
        17,
        33,
        "Write an ADR about the storage engine choice",
        "",
        {"adr/0002-storage-engine.md": "decision\n"},
    )
    c(
        18,
        40,
        "fix: patch the sidecar panic on empty batches and add a regression test covering the "
        "failure, plus update the on-call runbook",
        "",
        {"src/sidecar.py": "def handle():\n    pass\n"},
    )
    c(
        19,
        41,
        "Simplify sidecar batching logic",
        "",
        {"src/sidecar.py": "def handle():\n    return\n"},
    )
    c(20, 42, "Update README badges", "", {"README.md": "# Project (fixed typo) [badge]\n"})
    c(
        21,
        43,
        "Add docstring to join module",
        "",
        {"src/join.py": '"""doc"""\ndef join():\n    pass  # fmt\n'},
    )
    c(
        22,
        44,
        "Tweak logging format in pipeline",
        "",
        {"src/pipeline.py": "def run():\n    pass  # log\n"},
    )
    c(
        23,
        45,
        "Adjust queue size default",
        "",
        {"src/pipeline.py": "def run():\n    pass  # size\n"},
    )
    c(24, 46, "Clarify README install steps", "", {"README.md": "# Project (install steps)\n"})
    c(
        25,
        47,
        "Add unit test for cache eviction",
        "",
        {"tests_local/test_cache.py": "def test_x():\n    pass\n"},
    )
    c(
        26,
        48,
        "Rename join helper function",
        "",
        {"src/join.py": '"""doc"""\ndef do_join():\n    pass  # fmt\n'},
    )
    c(
        27,
        49,
        "Small cleanup in sidecar module",
        "",
        {"src/sidecar.py": "def handle():\n    return None\n"},
    )
    c(
        28,
        50,
        "Improve error message wording",
        "",
        {"src/pipeline.py": "def run():\n    pass  # msg\n"},
    )
    c(29, 51, "Final polish before release", "", {"README.md": "# Project (final polish)\n"})

    return repo


def test_significance_scoring_matches_golden_fixture(tmp_path):
    repo = _build_significance_fixture(tmp_path)

    output = git_harvest._run_git_log(repo, since=BASE - timedelta(days=1))
    parsed = git_harvest._parse_git_log(output)
    assert len(parsed) == 30

    scored = git_harvest.score_commits(parsed, min_significance=2)
    by_subject = {s.commit.subject: s for s in scored}

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(golden) == 30

    for expected in golden:
        actual = by_subject[expected["subject"]]
        assert actual.score == expected["score"], expected["subject"]
        assert list(actual.reasons) == expected["reasons"], expected["subject"]
        assert actual.kept == (expected["score"] >= 2), expected["subject"]
