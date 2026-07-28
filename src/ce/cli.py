"""Content Engine CLI.

Registration only. Command bodies live in their own modules (TDD 7); this
file exists so `ce --help` always shows the complete contract from TDD 9,
whether or not a given work package has been built.

Unimplemented commands raise NotImplementedYet, which names the work package
responsible. That is deliberate: `ce --help` is the map of the whole system
from day one, and every stub tells you where to go next.

NOTE: this module intentionally does NOT use `from __future__ import
annotations`. Typer resolves parameter types at runtime and postponed
annotations have historically confused it for Optional/List parameters.
"""

import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from ce import __version__, console
from ce.exit_codes import CEError, Exit

app = typer.Typer(
    name="ce",
    help="Content Engine - turn a finished project into publish-ready content.",
    no_args_is_help=True,
    add_completion=False,
)

project_app = typer.Typer(help="Create and inspect projects.", no_args_is_help=True)
capture_app = typer.Typer(
    help="Ingest audio, screenshots and friction notes.", no_args_is_help=True
)
brief_app = typer.Typer(help="Inspect and select candidate briefs.", no_args_is_help=True)
publish_app = typer.Typer(help="Publish to owned channels.", no_args_is_help=True)
metrics_app = typer.Typer(help="Pull performance data.", no_args_is_help=True)
index_app = typer.Typer(help="Maintain the derived index.", no_args_is_help=True)

app.add_typer(project_app, name="project")
app.add_typer(capture_app, name="capture")
app.add_typer(brief_app, name="brief")
app.add_typer(publish_app, name="publish")
app.add_typer(metrics_app, name="metrics")
app.add_typer(index_app, name="index")


# ---------------------------------------------------------------------------
# Global options
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        console.out(f"ce {__version__}")
        raise typer.Exit(Exit.OK)


@app.callback()
def main_callback(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug output to stderr."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Describe actions without performing them."
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to engine.yml.", exists=False),
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Shared state for every subcommand."""
    console.set_verbose(verbose)
    ctx.obj = {"verbose": verbose, "dry_run": dry_run, "config": config}
    console.debug(f"config={config} dry_run={dry_run}")


# ---------------------------------------------------------------------------
# project  (WP-03)
# ---------------------------------------------------------------------------


@project_app.command("new")
def project_new(
    slug: str = typer.Argument(..., help="Immutable identifier, [a-z0-9-]+."),
    title: str | None = typer.Option(None, "--title"),
    repo: list[Path] | None = typer.Option(
        None, "--repo", help="Repeatable. Must be in the allowlist."
    ),
) -> None:
    """Create a project and scaffold its data directory."""
    from ce import project as lifecycle

    created = lifecycle.create(Path("data"), slug, title=title, repo_paths=repo)
    console.success(f"created project {created.slug}")


@project_app.command("list")
def project_list(
    status: str | None = typer.Option(None, "--status", help="active|harvested|complete|abandoned"),
) -> None:
    """List projects."""
    from ce import project as lifecycle

    projects = lifecycle.list_all(Path("data"), status)
    if not projects:
        console.out("(no projects)")
        return
    width = max(len(p.slug) for p in projects)
    for p in projects:
        console.out(f"  {p.slug.ljust(width)}  {p.status.value:<10}  {p.title}")


@project_app.command("show")
def project_show(slug: str = typer.Argument(...)) -> None:
    """Show a project, its captures and its briefs."""
    from ce import store

    console.out(store.read_project_summary(Path("data"), slug))


@project_app.command("close")
def project_close(
    slug: str = typer.Argument(...),
    abandoned: bool = typer.Option(
        False, "--abandoned", help="Abandoned projects are still harvestable."
    ),
) -> None:
    """Mark a project finished."""
    from ce import project as lifecycle

    closed = lifecycle.close(Path("data"), slug, abandoned=abandoned)
    console.success(f"closed project {closed.slug} ({closed.status.value})")


# ---------------------------------------------------------------------------
# capture  (WP-04)
# ---------------------------------------------------------------------------


def _report_batch(outcome) -> None:
    """Shared tail end of `--dir` batch mode: print failures, then a
    summary. Exits non-zero only if *everything* failed — a partial batch
    is a reported outcome, not an error (skip-and-continue by design)."""
    for path, error in outcome.failed:
        console.failure(f"{path.name}: {error}")
    if not outcome.succeeded and not outcome.failed:
        console.out("(no matching files found)")
        return
    console.out(f"\n{len(outcome.succeeded)} succeeded, {len(outcome.failed)} failed")
    if outcome.failed and not outcome.succeeded:
        raise typer.Exit(Exit.ERROR)


@capture_app.command("audio")
def capture_audio(
    file: Path | None = typer.Argument(None, help="Audio file to ingest. Omit with --dir."),
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    folder: Path | None = typer.Option(
        None, "--dir", help="Batch-ingest every audio file in this folder."
    ),
    moment: str = typer.Option("in_situ", "--moment", help="in_situ|retro"),
    context: str | None = typer.Option(None, "--context", help="One line: what was happening."),
) -> None:
    """Ingest and transcribe an audio capture, or a whole folder with --dir."""
    from ce.capture import audio as audio_capture
    from ce.config import load_engine_config
    from ce.llm.gateway import Gateway
    from ce.models import CaptureMoment

    if (file is None) == (folder is None):
        raise CEError("pass exactly one of FILE or --dir")

    try:
        moment_enum = CaptureMoment(moment)
    except ValueError:
        raise CEError(f"unknown --moment {moment!r}, expected in_situ|retro") from None

    data_root = Path("data")
    config = load_engine_config()
    gateway = Gateway(config, data_root=data_root)

    if folder is not None:
        outcome = audio_capture.ingest_and_transcribe_batch(
            data_root,
            folder,
            project,
            config,
            gateway=gateway,
            moment=moment_enum,
            context=context,
        )
        for captured in outcome.succeeded:
            console.success(f"captured and transcribed {captured.id} ({captured.source_path.name})")
        _report_batch(outcome)
        return

    captured = audio_capture.ingest(data_root, file, project, moment=moment_enum, context=context)
    transcribed = audio_capture.transcribe(data_root, captured, config, gateway=gateway)
    console.success(f"captured and transcribed {transcribed.id}")


@capture_app.command("screen")
def capture_screen(
    file: Path | None = typer.Argument(None, help="Screenshot/screencast file. Omit with --dir."),
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    folder: Path | None = typer.Option(
        None, "--dir", help="Batch-ingest every screenshot/screencast in this folder."
    ),
    context: str | None = typer.Option(None, "--context"),
) -> None:
    """Ingest a screenshot or screencast, or a whole folder with --dir."""
    from ce.capture import ingest as capture_ingest

    if (file is None) == (folder is None):
        raise CEError("pass exactly one of FILE or --dir")

    if folder is not None:
        outcome = capture_ingest.ingest_screen_batch(Path("data"), folder, project, context=context)
        for captured in outcome.succeeded:
            console.success(
                f"captured {captured.id} ({captured.type.value}, {captured.source_path.name})"
            )
        _report_batch(outcome)
        return

    captured = capture_ingest.ingest_screen(Path("data"), file, project, context=context)
    console.success(f"captured {captured.id} ({captured.type.value})")


@capture_app.command("friction")
def capture_friction(
    note: str = typer.Argument(..., help="One line, written the moment something surprised you."),
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
) -> None:
    """Append a timestamped line to friction.md."""
    from ce.capture import ingest as capture_ingest

    captured = capture_ingest.append_friction(Path("data"), project, note)
    console.success(f"logged friction note {captured.id}")


@capture_app.command("list")
def capture_list(project: str = typer.Argument(...)) -> None:
    """List captures for a project."""
    from ce.capture import ingest as capture_ingest

    captures = capture_ingest.list_captures(Path("data"), project)
    if not captures:
        console.out("(no captures)")
        return
    for c in captures:
        line = f"  {c.id}  {c.type.value:<10}  {c.moment.value:<7}  {c.captured_at:%Y-%m-%d %H:%M}"
        if c.context:
            line += f"  — {c.context}"
        console.out(line)


# ---------------------------------------------------------------------------
# harvest  (WP-08, orchestrates WP-05 / WP-06 / WP-07)
# ---------------------------------------------------------------------------


@app.command("harvest")
def harvest(
    project: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Re-run stages whose inputs are unchanged."),
    skip_research: bool = typer.Option(False, "--skip-research"),
) -> None:
    """Extract git history, transcribe pending audio, research, and build the brief inventory.

    Gates G1 (allowlist) and G2 (secrets) run first and cannot be bypassed by --force.

    `--force` is accepted for CLI-contract completeness (TDD 9) but isn't
    yet meaningfully enforced: neither `harvest/git.py`'s `extract()` nor
    `harvest/research.py`'s `research()` implement stage-level resumability
    (WP-05/WP-07 didn't need it to meet their own Done-when criteria), so
    there is no "unchanged inputs" state to skip yet. Revisit once a real
    manifest scheme is designed for the whole harvest stage.
    """
    from ce import index as index_module
    from ce import store
    from ce.capture import audio as audio_capture
    from ce.config import load_engine_config
    from ce.harvest import git as git_harvest_module
    from ce.harvest import inventory as inventory_module
    from ce.harvest import research as research_module
    from ce.llm.gateway import Gateway
    from ce.models import CaptureType

    data_root = Path("data")
    config = load_engine_config()
    proj = store.read_project(data_root, project)
    gateway = Gateway(config, data_root=data_root)
    harvest_dir = store.harvest_dir(data_root, project)

    git_harvest = git_harvest_module.extract(
        proj,
        config.harvest.git.lookback_days,
        gateway=gateway,
        harvest_dir=harvest_dir,
        min_significance=config.harvest.git.min_significance,
    )

    for capture in store.list_captures(data_root, project):
        if capture.type == CaptureType.AUDIO:
            audio_capture.transcribe(data_root, capture, config, gateway=gateway)
    captures = store.list_captures(data_root, project)

    if skip_research:
        research_harvest = research_module.ResearchHarvest(sources=[])
    else:
        query = proj.selection.hypothesis or proj.title
        search_client = research_module.build_search_client(config.harvest.research.provider)
        research_harvest = research_module.research(
            query,
            gateway=gateway,
            harvest_dir=harvest_dir,
            max_sources=config.harvest.research.max_sources,
            search_client=search_client,
        )

    dedupe_conn = index_module.connect(data_root / "index.db")
    try:
        briefs = inventory_module.generate(
            proj,
            git_harvest,
            research_harvest,
            captures,
            data_root=data_root,
            gateway=gateway,
            dedupe=inventory_module.DedupeSettings(
                conn=dedupe_conn,
                embeddings_client=index_module.OpenAIEmbeddingsClient(),
                embeddings_model=config.embeddings.model,
                threshold=config.gates.dedupe.threshold,
                scope_days=config.gates.dedupe.scope_days,
            ),
            min_briefs=config.harvest.inventory.min_briefs,
            max_briefs=config.harvest.inventory.max_briefs,
        )
    finally:
        dedupe_conn.close()

    console.success(f"harvested {project}: {len(briefs)} brief(s) -- see harvest/inventory.md")


# ---------------------------------------------------------------------------
# brief  (WP-08 / WP-09)
# ---------------------------------------------------------------------------


@brief_app.command("list")
def brief_list(
    project: str = typer.Argument(...),
    status: str | None = typer.Option(
        None, "--status", help="candidate|selected|produced|published|dropped"
    ),
) -> None:
    """List candidate briefs."""
    from ce import store
    from ce.models import BriefStatus

    briefs = store.read_briefs(Path("data"), project)
    if status is not None:
        try:
            target = BriefStatus(status)
        except ValueError:
            raise CEError(f"unknown brief status {status!r}") from None
        briefs = [b for b in briefs if b.status == target]

    if not briefs:
        console.out("(no briefs)")
        return
    width = max(len(b.id) for b in briefs)
    for b in briefs:
        console.out(
            f"  {b.id.ljust(width)}  {b.status.value:<10}  {b.archetype.value:<20}  {b.title}"
        )


@brief_app.command("select")
def brief_select(brief_id: str = typer.Argument(..., help="e.g. br-01")) -> None:
    """Promote a brief to a piece. Refuses briefs with weak grounding."""
    from ce.produce import writer

    piece = writer.select_brief(brief_id, data_root=Path("data"))
    console.success(f"selected {brief_id} -> piece {piece.id}")


# ---------------------------------------------------------------------------
# produce / verify / assets / render / package
# ---------------------------------------------------------------------------


@app.command("produce")
def produce(
    piece_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the LLM response cache."),
) -> None:
    """Draft, grade and revise until the piece scores. Stops for your edit (ADR-008).

    `--force` is accepted for CLI-contract completeness (TDD 9) but isn't
    meaningfully enforced yet: `produce()` always redoes the full loop and
    overwrites `article.md`/`grades.json` on every call, the same accepted
    gap as `ce harvest --force` (no stage-level resumability built).
    """
    from ce import index as index_module
    from ce import store
    from ce.config import load_engine_config
    from ce.harvest import git as git_harvest_module
    from ce.harvest import research as research_module
    from ce.llm.gateway import Gateway
    from ce.produce import writer

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    brief = next(
        (b for b in store.read_briefs(data_root, project.slug) if b.id == piece.brief_id), None
    )
    if brief is None:
        raise CEError(f"brief {piece.brief_id!r} (piece {piece_id!r}'s source) no longer exists")

    config = load_engine_config()
    gateway = Gateway(config, data_root=data_root)
    voice = writer.VoiceRagSettings(
        embeddings_client=index_module.OpenAIEmbeddingsClient(),
        embeddings_model=config.embeddings.model,
    )
    harvest_dir = store.harvest_dir(data_root, project.slug)

    produced = writer.produce(
        piece,
        brief,
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=git_harvest_module.read_git_harvest(harvest_dir),
        research_harvest=research_module.read_research_harvest(harvest_dir),
        min_grade=config.produce.min_grade,
        max_attempts=config.produce.max_attempts,
        grade_weights=config.produce.grade_weights,
        voice=voice,
        cache=not no_cache,
    )

    final = produced.grades[-1] if produced.grades else None
    if final:
        console.success(
            f"drafted {piece_id}: {len(produced.grades)} attempt(s), final grade {final.total:.1f}"
        )
    console.out(f"edit article.md, then: ce verify {piece_id}")


@app.command("verify")
def verify(
    piece_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Proceed despite unverifiable claims."),
) -> None:
    """Extract and verify factual claims (gate G4)."""
    from datetime import UTC, datetime

    from ce import store
    from ce.config import load_engine_config
    from ce.exit_codes import GateBlocked
    from ce.gates import claims as claims_module
    from ce.harvest import git as git_harvest_module
    from ce.harvest import research as research_module
    from ce.llm.gateway import Gateway
    from ce.models import PieceStatus, VerificationSummary

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    brief = next(
        (b for b in store.read_briefs(data_root, project.slug) if b.id == piece.brief_id), None
    )
    if brief is None:
        raise CEError(f"brief {piece.brief_id!r} (piece {piece_id!r}'s source) no longer exists")

    config = load_engine_config()
    if not config.gates.claims.enabled:
        console.success(
            f"claim verification disabled (config.gates.claims.enabled=false); skipping {piece_id}"
        )
        return

    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    if not article_path.exists():
        raise CEError(f"{article_path} does not exist -- run `ce produce {piece_id}` first")
    article = article_path.read_text(encoding="utf-8")

    harvest_dir = store.harvest_dir(data_root, project.slug)
    gateway = Gateway(config, data_root=data_root)

    result = claims_module.verify(
        article,
        brief,
        project,
        data_root=data_root,
        gateway=gateway,
        git_harvest=git_harvest_module.read_git_harvest(harvest_dir),
        research_harvest=research_module.read_research_harvest(harvest_dir),
        search_client=research_module.build_search_client(config.harvest.research.provider),
        fetch_client=research_module.HttpFetchClient(),
    )
    claims_module.write_verification_json(
        store.verification_json_path(data_root, project.slug, piece.id), result
    )

    try:
        claims_module.check(result, block_on_unverifiable=config.gates.claims.block_on_unverifiable)
    except GateBlocked as exc:
        if not force:
            raise
        console.warn(f"{exc.message} (proceeding: --force)")

    now = datetime.now(UTC)
    failed = result.failed(block_on_unverifiable=config.gates.claims.block_on_unverifiable)
    piece.verification = VerificationSummary(
        claims_checked=len(result.claims), claims_failed=len(failed), ran_at=now
    )
    piece.status = PieceStatus.VERIFIED
    store.write_piece(data_root, project.slug, piece)

    console.success(f"verified {piece_id}: {len(result.claims)} claim(s), {len(failed)} failed")


@app.command("assets")
def assets(
    piece_id: str = typer.Argument(...),
    only: str | None = typer.Option(None, "--only", help="diagram|codecard|thumbnail|hero"),
) -> None:
    """Render diagrams, code cards and thumbnails."""
    from ce import assets as assets_module
    from ce import store
    from ce.assets.codecard import PlaywrightScreenshotRenderer
    from ce.assets.diagram import MermaidCliRenderer

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    brief = next(
        (b for b in store.read_briefs(data_root, project.slug) if b.id == piece.brief_id), None
    )
    if brief is None:
        raise CEError(f"brief {piece.brief_id!r} (piece {piece_id!r}'s source) no longer exists")

    result = assets_module.generate(
        piece,
        brief,
        data_root=data_root,
        only=only,
        diagram_renderer=MermaidCliRenderer(),
        screenshot_renderer=PlaywrightScreenshotRenderer(),
    )

    for path in result.produced:
        console.success(f"wrote {path}")
    for reason in result.skipped:
        console.out(f"  (skipped) {reason}")
    console.out(f"\n{len(result.produced)} asset(s) produced, {len(result.skipped)} skipped")


@app.command("render")
def render(
    piece_id: str = typer.Argument(...),
    platform: list[str] | None = typer.Option(
        None, "--platform", help="Repeatable. Default: all configured."
    ),
) -> None:
    """Adapt the article into per-platform renditions."""
    from ce import store
    from ce.config import load_engine_config, load_platform_config
    from ce.llm.gateway import Gateway
    from ce.produce import renditions as renditions_module

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    if not article_path.exists():
        raise CEError(f"{article_path} does not exist -- run `ce produce {piece_id}` first")
    article = article_path.read_text(encoding="utf-8")

    names = platform or list(renditions_module.DEFAULT_PLATFORMS)
    unknown = [n for n in names if n not in renditions_module.DEFAULT_PLATFORMS]
    if unknown:
        raise CEError(
            f"unknown platform(s): {', '.join(unknown)}, expected one of "
            f"{', '.join(renditions_module.DEFAULT_PLATFORMS)}"
        )
    platform_configs = {
        name: load_platform_config(Path("config/platforms") / f"{name}.yml") for name in names
    }

    config = load_engine_config()
    gateway = Gateway(config, data_root=data_root)

    results = renditions_module.render(
        piece,
        article,
        data_root=data_root,
        gateway=gateway,
        platform_configs=platform_configs,
        site_url=config.identity.site_url,
        utm_template=config.utm.template,
    )

    for r in results:
        console.success(f"wrote {r.platform.value} rendition")
    console.out(f"\n{len(results)} rendition(s) written")


@app.command("package")
def package(piece_id: str = typer.Argument(...)) -> None:
    """Assemble outbox/<piece-id>/ including REVIEW.html."""
    from ce import store
    from ce.config import load_engine_config, load_platform_config
    from ce.package import builder as builder_module

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    brief = next(
        (b for b in store.read_briefs(data_root, project.slug) if b.id == piece.brief_id), None
    )
    if brief is None:
        raise CEError(f"brief {piece.brief_id!r} (piece {piece_id!r}'s source) no longer exists")

    config = load_engine_config()
    platform_configs = {
        name: load_platform_config(Path("config/platforms") / f"{name}.yml")
        for name in ("linkedin", "facebook", "youtube")
    }

    result = builder_module.package(
        piece,
        brief,
        project,
        data_root=data_root,
        outbox_root=Path("outbox"),
        config=config,
        platform_configs=platform_configs,
    )

    console.success(f"wrote {result.review_html_path}")
    console.out(
        f"{len(result.image_paths)} image(s), {len(result.platforms)} platform rendition(s) "
        f"packaged in {result.outbox_dir}"
    )


# ---------------------------------------------------------------------------
# publish / posted / metrics
# ---------------------------------------------------------------------------


@publish_app.command("site")
def publish_site(
    piece_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print frontmatter and file plan only."),
) -> None:
    """Publish to the static site and verify OG tags before packaging renditions."""
    from ce import store
    from ce.config import load_engine_config
    from ce.publish import site as site_module

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")
    project, piece = found

    brief = next(
        (b for b in store.read_briefs(data_root, project.slug) if b.id == piece.brief_id), None
    )
    if brief is None:
        raise CEError(f"brief {piece.brief_id!r} (piece {piece_id!r}'s source) no longer exists")

    article_path = store.piece_dir(data_root, project.slug, piece.id) / piece.article_path
    if not article_path.exists():
        raise CEError(f"{article_path} does not exist -- run `ce produce {piece_id}` first")

    config = load_engine_config()

    if dry_run:
        built_plan = site_module.plan(
            piece,
            brief,
            project,
            article_path.read_text(encoding="utf-8"),
            data_root=data_root,
            site_url=config.identity.site_url,
        )
        console.out(f"would write {config.identity.site_repo / built_plan.content_path}")
        if built_plan.hero_dest:
            console.out(
                f"would copy {built_plan.hero_source} -> "
                f"{config.identity.site_repo / built_plan.hero_dest}"
            )
        console.out("")
        console.out(built_plan.content_text)
        return

    published = site_module.publish(
        piece,
        brief,
        project,
        data_root=data_root,
        site_repo=config.identity.site_repo,
        site_url=config.identity.site_url,
        http_client=site_module.HttpxClient(),
    )

    console.success(f"published {piece_id} -> {published.published.url}")


@app.command("posted")
def posted(
    piece_id: str = typer.Argument(...),
    platform: str = typer.Option(..., "--platform", help="linkedin|facebook|youtube"),
    url: str = typer.Option(..., "--url", help="URL of the live post."),
) -> None:
    """Record a manual post. Generated for you by REVIEW.html."""
    from datetime import UTC, datetime

    from ce import store
    from ce.models import PostPlatform, PostRecord

    data_root = Path("data")
    found = store.find_piece(data_root, piece_id)
    if found is None:
        raise CEError(f"piece {piece_id!r} not found")

    try:
        platform_enum = PostPlatform(platform)
    except ValueError as exc:
        valid = ", ".join(p.value for p in PostPlatform)
        raise CEError(f"unknown platform {platform!r}, expected one of: {valid}") from exc

    records = store.read_posted(data_root)
    records.append(
        PostRecord(
            piece_id=piece_id,
            platform=platform_enum,
            url=url,
            posted_at=datetime.now(UTC),
        )
    )
    store.write_posted(data_root, records)

    console.success(f"recorded {piece_id} posted to {platform_enum.value}: {url}")


@metrics_app.command("pull")
def metrics_pull(
    since: str | None = typer.Option(None, "--since", help="YYYY-MM-DD"),
) -> None:
    """Refresh UTM site clicks (every platform) and YouTube stats in posted.yml."""
    from datetime import date

    from ce.config import load_engine_config
    from ce.metrics import pull as pull_module
    from ce.metrics.umami import HttpxUmamiClient
    from ce.metrics.youtube import YouTubeDataApiClient

    config = load_engine_config()
    since_date = date.fromisoformat(since) if since else None
    data_root = Path("data")

    records = pull_module.pull(
        data_root,
        config,
        umami_client=HttpxUmamiClient(
            api_url=config.analytics.umami.api_url,
            website_id=config.analytics.umami.website_id,
        ),
        youtube_client=YouTubeDataApiClient(),
        since=since_date,
    )

    console.success(f"pulled metrics for {len(records)} post(s) -> {data_root / 'performance.md'}")


# ---------------------------------------------------------------------------
# sweep / index / cost / doctor
# ---------------------------------------------------------------------------


@app.command("sweep")
def sweep(
    sources: str = typer.Option("hn,rss", "--sources", help="Comma separated."),
) -> None:
    """Scan for recurring demand signals to inform project selection."""
    from ce.config import load_engine_config
    from ce.exit_codes import SweepError
    from ce.sweep import scan as scan_module
    from ce.sweep.hn import AlgoliaHNClient
    from ce.sweep.rss import HttpxRssClient

    requested = tuple(s.strip() for s in sources.split(",") if s.strip())
    unknown = set(requested) - set(scan_module.ALL_SOURCES)
    if unknown:
        raise SweepError(f"unknown --sources value(s): {', '.join(sorted(unknown))}")

    config = load_engine_config()
    data_root = Path("data")

    result = scan_module.scan(
        data_root,
        config,
        hn_client=AlgoliaHNClient(),
        rss_client=HttpxRssClient(),
        sources=requested,
    )

    digest_path = data_root / "sweeps" / f"{result.date.isoformat()}.md"
    if result.failed_sources:
        console.warn(
            f"{len(result.failed_sources)} source(s) failed: {', '.join(result.failed_sources)}"
        )
    console.success(f"swept {len(result.ranks)} topic(s) -> {digest_path}")


@index_app.command("rebuild")
def index_rebuild() -> None:
    """Rebuild the derived SQLite index and embeddings from data/ (ADR-002)."""
    from ce import index as index_module
    from ce.config import load_engine_config

    data_root = Path("data")
    config = load_engine_config()
    count = index_module.rebuild(
        data_root,
        data_root / "index.db",
        embeddings_client=index_module.OpenAIEmbeddingsClient(),
        model=config.embeddings.model,
    )
    console.success(f"indexed {count} piece(s)")


@app.command("cost")
def cost(
    month: str | None = typer.Option(None, "--month", help="YYYY-MM. Default: current month."),
) -> None:
    """Summarise LLM spend from data/ledger.jsonl."""
    from ce.llm import ledger as ledger_mod

    data_root = Path("data")
    records = ledger_mod.read_all(data_root / "ledger.jsonl")
    breakdown = ledger_mod.per_prompt_breakdown(records, month)
    label = month or ledger_mod.current_month()

    console.heading(f"LLM cost - {label}")
    if not breakdown:
        console.out("  (no calls recorded)")
    else:
        width = max(len(s.prompt) for s in breakdown)
        for s in breakdown:
            console.out(
                f"  {s.prompt.ljust(width)}  {s.calls:>3} calls"
                f"  {s.in_tokens:>8} in  {s.out_tokens:>8} out  ${s.usd:.4f}"
            )
    console.out()
    console.out(f"  total: ${sum(s.usd for s in breakdown):.4f}")


@app.command("doctor")
def doctor_cmd(
    strict: bool = typer.Option(
        False, "--strict", help="Treat not-yet-needed dependencies as required."
    ),
) -> None:
    """Verify the local environment."""
    from ce import doctor

    raise typer.Exit(doctor.run(strict=strict))


# ---------------------------------------------------------------------------
# gui  (WP-17)
# ---------------------------------------------------------------------------


@app.command("gui")
def gui_cmd(
    port: int = typer.Option(8420, "--port", help="Bind port. Server is 127.0.0.1-only."),
) -> None:
    """Start the local web dashboard (TDD 10.10, ADR-009). No auth, no daemon --
    runs only as long as this process is left open."""
    try:
        from ce.gui.app import serve
    except ModuleNotFoundError as exc:
        raise CEError(
            "the GUI's dependencies aren't installed.",
            hint='pip install -e ".[gui]"',
        ) from exc

    serve(port=port)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console script entry point. Maps CEError onto the TDD 9 exit codes.

    Loads `.env` from the current directory before anything else runs, so
    API keys can live in a gitignored file instead of requiring `setx`/
    persistent env vars. Explicit path (not `find_dotenv()`'s default
    frame-guessing, which would resolve relative to this installed
    package's location, not the operator's pipeline-home cwd) — same
    cwd-relative convention as `data/`, `config/engine.yml`, `prompts/`.
    Existing environment variables still win (`override=False`, the
    default) if a key is set both ways.

    Every invocation is teed to `data/runs/<run-id>-<command>.log` (TDD §14,
    WP-17's `ce/run_log.py`) -- not just GUI-triggered ones, since §14
    describes it as a system-wide behavior, not a GUI-only one.
    """
    load_dotenv(Path(".env"))
    from ce import run_log

    with run_log.tee(Path("data"), sys.argv[1:]):
        try:
            app()
        except CEError as exc:
            console.failure(exc.message)
            if exc.hint:
                console.hint(exc.hint)
            raise SystemExit(int(exc.exit_code)) from None


if __name__ == "__main__":
    main()
