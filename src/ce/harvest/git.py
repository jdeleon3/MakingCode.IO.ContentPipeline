"""Git harvest + significance scoring (TDD 10.3, WP-05).

`extract()` turns each of a project's repos into a scored, redaction-checked
`RepoHarvest`, written to `harvest/git.json`. Gates run in TDD 6's order —
G1 (allowlist) before any git subprocess touches the repo, G2 (secrets)
before any content from the repo can reach an LLM:

1. G1 `gates.allowlist.check()` — raises before any git subprocess runs.
2. `git log --numstat` — messages, paths, and line-count stats only.
3. The path deny-list drops matched files from those stats.
4. G2 `gates.secrets.scan_repo()` over the deny-list-filtered working tree.
   Any finding blocks the run and writes `redaction-report.json`.
5. Significance scoring (`_score_one` below, one rule per TDD 10.3's
   `SIGNIFICANCE` table) on the surviving commits.
6. One `commit_summarize` LLM call per *kept* commit — receiving only the
   message, file count, and insertion/deletion stats collected above. The
   only git subprocess this module ever runs is `log --numstat`; nothing
   here fetches a patch or a full per-commit diff, so "raw diffs never
   reach an LLM" (TDD 6.2) holds by construction, not by a redaction step.

Only the secret scan is faked in tests — `git` itself is installed in this
dev environment (unlike `gitleaks`; see `gates/secrets.py`), so git log
parsing and significance scoring run against a real, dynamically-built
fixture repo.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel

from ce.exit_codes import GateBlocked, HarvestError
from ce.gates import allowlist
from ce.gates import secrets as secrets_gate
from ce.gates.secrets import SecretScanner
from ce.llm.gateway import Gateway
from ce.models import Project, PublishableLevel, RepoRef

# ASCII "record separator" / "unit separator" — control characters that
# never appear in a commit message, used to delimit `git log` output so a
# body containing "|" or newlines can't be confused with field boundaries.
_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"
_GIT_LOG_FORMAT = f"{_RECORD_SEP}%H{_FIELD_SEP}%aI{_FIELD_SEP}%an{_FIELD_SEP}%s{_FIELD_SEP}%b"
_NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")

_DEPENDENCY_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "Pipfile",
    "Pipfile.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "yarn.lock",
    "pnpm-lock.yaml",
}

_REVERSAL_PREFIX_RE = re.compile(r"^(revert|fixup)\b", re.IGNORECASE)
_REVERTS_TRAILER_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)
_FIX_PREFIX_RE = re.compile(r"^fix\b", re.IGNORECASE)
_NOISE_PREFIX_RE = re.compile(r"^(chore|style|typo|bump|wip|fmt|lint)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# git log parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCommit:
    """One commit, after deny-list filtering — `files` never includes a
    path `gates.secrets.is_denied` matched, and no field here ever holds
    diff content, only metadata `git log --numstat` already gives us."""

    sha: str
    at: datetime
    author: str
    subject: str
    body: str
    files: tuple[str, ...]
    insertions: int
    deletions: int

    @property
    def message(self) -> str:
        return f"{self.subject}\n\n{self.body}" if self.body else self.subject


def _run_git_log(repo_path: Path, since: datetime) -> str:
    cmd = [
        "git",
        "log",
        f"--since={since:%Y-%m-%d}",
        "--numstat",
        f"--pretty=format:{_GIT_LOG_FORMAT}",
    ]
    proc = subprocess.run(  # noqa: S603
        cmd, cwd=repo_path, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise HarvestError(f"git log failed in {repo_path}: {proc.stderr[-2000:]}")
    return proc.stdout


def _parse_git_log(output: str) -> list[ParsedCommit]:
    commits: list[ParsedCommit] = []
    for chunk in output.split(_RECORD_SEP):
        if not chunk.strip():
            continue
        sha, at_iso, author, subject, rest = chunk.split(_FIELD_SEP, 4)

        body_lines: list[str] = []
        files: list[tuple[str, int, int]] = []
        for line in rest.splitlines():
            match = _NUMSTAT_RE.match(line)
            if match:
                ins_s, del_s, path = match.groups()
                # Binary files report "-" for both counts (TDD 10.3 doesn't
                # mention them; treated as zero-weight for scoring purposes
                # rather than raising, since a binary asset commit is still
                # a real commit worth keeping/dropping on its other merits).
                ins = 0 if ins_s == "-" else int(ins_s)
                dele = 0 if del_s == "-" else int(del_s)
                files.append((path, ins, dele))
            elif line.strip():
                body_lines.append(line)

        kept_files = [
            f for f in files if not secrets_gate.is_denied(PurePosixPath(f[0]).as_posix())
        ]
        commits.append(
            ParsedCommit(
                sha=sha,
                at=datetime.fromisoformat(at_iso),
                author=author,
                subject=subject,
                body="\n".join(body_lines).strip(),
                files=tuple(f[0] for f in kept_files),
                insertions=sum(f[1] for f in kept_files),
                deletions=sum(f[2] for f in kept_files),
            )
        )
    return commits


# ---------------------------------------------------------------------------
# Significance scoring (TDD 10.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredCommit:
    commit: ParsedCommit
    score: int
    reasons: tuple[str, ...]
    kept: bool


def _score_one(commit: ParsedCommit, prior: list[ParsedCommit]) -> tuple[int, list[str]]:
    """One commit's score against every significance rule (TDD 10.3's
    `SIGNIFICANCE` table).
    `prior` is every commit strictly before this one, chronologically,
    within the harvested range — needed by the two rules that look
    backward in time (a revert's target, and the gap since the last commit).
    """
    score = 0
    reasons: list[str] = []

    if _REVERSAL_PREFIX_RE.match(commit.subject):
        score += 3
        reasons.append("reversal")

    revert_match = _REVERTS_TRAILER_RE.search(commit.body)
    if revert_match:
        reverted_sha = revert_match.group(1).lower()
        reverted = next((p for p in prior if p.sha.lower().startswith(reverted_sha[:7])), None)
        if reverted is not None and 0 <= (commit.at - reverted.at).days <= 14:
            score += 3
            reasons.append("reversal")

    if len(commit.message) > 100:
        score += 2
        reasons.append("explained")

    if commit.deletions > 100:
        score += 2
        reasons.append("large_deletion")

    if any(Path(f).name in _DEPENDENCY_MANIFESTS for f in commit.files):
        score += 2
        reasons.append("tooling_change")

    if _FIX_PREFIX_RE.match(commit.subject) and prior:
        gap = commit.at - prior[-1].at
        if gap.days > 2:
            score += 1
            reasons.append("war_story")

    if any(part.lower() in ("docs", "adr") for f in commit.files for part in Path(f).parts[:-1]):
        score += 1
        reasons.append("written_thinking")

    if _NOISE_PREFIX_RE.match(commit.subject):
        score -= 5
        reasons.append("noise")

    return score, reasons


def score_commits(commits: list[ParsedCommit], min_significance: int) -> list[ScoredCommit]:
    """Scores every commit in chronological order (oldest first) so
    "prior" is well-defined for the two history-dependent rules. Returned
    in the same chronological order."""
    ordered = sorted(commits, key=lambda c: c.at)
    scored: list[ScoredCommit] = []
    for i, commit in enumerate(ordered):
        prior = ordered[:i]
        raw_score, reasons = _score_one(commit, prior)
        scored.append(
            ScoredCommit(
                commit=commit,
                score=raw_score,
                reasons=tuple(reasons),
                kept=raw_score >= min_significance,
            )
        )
    return scored


# ---------------------------------------------------------------------------
# git.json output
# ---------------------------------------------------------------------------


class CommitRecord(BaseModel):
    sha: str
    at: datetime
    msg: str
    files_changed: int
    insertions: int
    deletions: int
    score: int
    reasons: list[str]
    summary: str


class RedactionSummary(BaseModel):
    scanned: int
    findings: int


class RepoHarvest(BaseModel):
    repo: str
    range: str
    total_commits: int
    kept: int
    dropped: int
    commits: list[CommitRecord]
    redaction: RedactionSummary


class GitHarvest(BaseModel):
    """`git.json`'s top-level shape is `{"repos": [...]}`, one `RepoHarvest`
    per `project.repos` entry — a deviation from TDD 10.3's literal example
    (which shows a single repo's fields at the top level). `Project.repos`
    is a list precisely because a project can harvest more than one repo
    (TDD 5.2's `client-thing` example), and the TDD's flat shape has nowhere
    to put a second one. Every field TDD 10.3 names is still present,
    one level down.
    """

    repos: list[RepoHarvest]


def _commit_prompt_vars(commit: ParsedCommit, repo: RepoRef) -> dict[str, Any]:
    """Vars for the `commit_summarize` prompt. `publishable: lessons-only`
    (TDD 6.1) means no repo name and no file paths ever enter the prompt —
    only a file *count* — so the constraint holds structurally, not just by
    an instruction the model could ignore.
    """
    lessons_only = repo.publishable == PublishableLevel.LESSONS_ONLY
    return {
        "message": commit.message,
        "files_changed": len(commit.files),
        "file_paths": [] if lessons_only else list(commit.files),
        "insertions": commit.insertions,
        "deletions": commit.deletions,
        "repo_name": None if lessons_only else repo.name,
        "lessons_only": lessons_only,
    }


def _write_git_json(path: Path, harvest: GitHarvest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(harvest.model_dump_json(indent=2), encoding="utf-8")


def read_git_harvest(harvest_dir: Path) -> GitHarvest:
    """Reads back `harvest_dir/git.json` (written by `extract()`). Needed
    by WP-09's `produce()`, which runs as a separate `ce produce`
    invocation after `ce harvest` already exited -- see
    `research.read_research_harvest`'s docstring for the same rationale.
    """
    path = harvest_dir / "git.json"
    if not path.exists():
        return GitHarvest(repos=[])
    return GitHarvest.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# extract() — TDD 10.3 public interface
# ---------------------------------------------------------------------------


def extract(
    project: Project,
    lookback_days: int,
    *,
    gateway: Gateway,
    harvest_dir: Path,
    min_significance: int,
    secret_scanner: SecretScanner | None = None,
    now: datetime | None = None,
) -> GitHarvest:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=lookback_days)
    scanner = secret_scanner or secrets_gate.GitleaksScanner()

    repo_harvests: list[RepoHarvest] = []
    for repo in project.repos:
        allowlist.check(repo, gateway.config)

        raw_output = _run_git_log(repo.path, since)
        parsed = _parse_git_log(raw_output)

        findings, scanned_count = secrets_gate.scan_repo(repo.path, scanner)
        if findings:
            secrets_gate.write_redaction_report(
                harvest_dir / "redaction-report.json", repo.path, findings
            )
            raise GateBlocked(
                "G2",
                f"secret scan found {len(findings)} finding(s) in {repo.name!r}; "
                "see redaction-report.json",
            )

        scored = score_commits(parsed, min_significance)
        kept = [s for s in scored if s.kept]

        records: list[CommitRecord] = []
        for s in kept:
            commit = s.commit
            result = gateway.complete(
                "commit_summarize", _commit_prompt_vars(commit, repo), tier="cheap"
            )
            records.append(
                CommitRecord(
                    sha=commit.sha,
                    at=commit.at,
                    msg=commit.subject,
                    files_changed=len(commit.files),
                    insertions=commit.insertions,
                    deletions=commit.deletions,
                    score=s.score,
                    reasons=list(s.reasons),
                    summary=result.content.strip(),
                )
            )

        repo_harvests.append(
            RepoHarvest(
                repo=repo.name,
                range=f"{since:%Y-%m-%d}..{now:%Y-%m-%d}",
                total_commits=len(parsed),
                kept=len(kept),
                dropped=len(parsed) - len(kept),
                commits=records,
                redaction=RedactionSummary(scanned=scanned_count, findings=0),
            )
        )

    harvest = GitHarvest(repos=repo_harvests)
    _write_git_json(harvest_dir / "git.json", harvest)
    return harvest
