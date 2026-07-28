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

from pathlib import Path

import typer

from ce import __version__, console
from ce.exit_codes import CEError, Exit, NotImplementedYet

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


@capture_app.command("audio")
def capture_audio(
    file: Path = typer.Argument(..., help="Audio file to ingest."),
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    moment: str = typer.Option("in_situ", "--moment", help="in_situ|retro"),
    context: str | None = typer.Option(None, "--context", help="One line: what was happening."),
) -> None:
    """Ingest and transcribe an audio capture."""
    from ce.capture import audio as audio_capture
    from ce.config import load_engine_config
    from ce.llm.gateway import Gateway
    from ce.models import CaptureMoment

    try:
        moment_enum = CaptureMoment(moment)
    except ValueError:
        raise CEError(f"unknown --moment {moment!r}, expected in_situ|retro") from None

    data_root = Path("data")
    captured = audio_capture.ingest(data_root, file, project, moment=moment_enum, context=context)
    config = load_engine_config()
    gateway = Gateway(config, data_root=data_root)
    transcribed = audio_capture.transcribe(data_root, captured, config, gateway=gateway)
    console.success(f"captured and transcribed {transcribed.id}")


@capture_app.command("screen")
def capture_screen(
    file: Path = typer.Argument(...),
    project: str = typer.Option(..., "--project", "-p", help="Project slug."),
    context: str | None = typer.Option(None, "--context"),
) -> None:
    """Ingest a screenshot or screencast."""
    from ce.capture import ingest as capture_ingest

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
    """
    raise NotImplementedYet("harvest", "WP-08")


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
    raise NotImplementedYet("brief list", "WP-08")


@brief_app.command("select")
def brief_select(brief_id: str = typer.Argument(..., help="e.g. br-01")) -> None:
    """Promote a brief to a piece. Refuses briefs with weak grounding."""
    raise NotImplementedYet("brief select", "WP-09")


# ---------------------------------------------------------------------------
# produce / verify / assets / render / package
# ---------------------------------------------------------------------------


@app.command("produce")
def produce(
    piece_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the LLM response cache."),
) -> None:
    """Draft, grade and revise until the piece scores. Stops for your edit (ADR-008)."""
    raise NotImplementedYet("produce", "WP-09")


@app.command("verify")
def verify(
    piece_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Proceed despite unverifiable claims."),
) -> None:
    """Extract and verify factual claims (gate G4)."""
    raise NotImplementedYet("verify", "WP-10")


@app.command("assets")
def assets(
    piece_id: str = typer.Argument(...),
    only: str | None = typer.Option(None, "--only", help="diagram|codecard|thumbnail|hero"),
) -> None:
    """Render diagrams, code cards and thumbnails."""
    raise NotImplementedYet("assets", "WP-11")


@app.command("render")
def render(
    piece_id: str = typer.Argument(...),
    platform: list[str] | None = typer.Option(
        None, "--platform", help="Repeatable. Default: all configured."
    ),
) -> None:
    """Adapt the article into per-platform renditions."""
    raise NotImplementedYet("render", "WP-12")


@app.command("package")
def package(piece_id: str = typer.Argument(...)) -> None:
    """Assemble outbox/<piece-id>/ including REVIEW.html."""
    raise NotImplementedYet("package", "WP-13")


# ---------------------------------------------------------------------------
# publish / posted / metrics
# ---------------------------------------------------------------------------


@publish_app.command("site")
def publish_site(
    piece_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print frontmatter and file plan only."),
) -> None:
    """Publish to the static site and verify OG tags before packaging renditions."""
    raise NotImplementedYet("publish site", "WP-14")


@app.command("posted")
def posted(
    piece_id: str = typer.Argument(...),
    platform: str = typer.Option(..., "--platform", help="linkedin|facebook|youtube"),
    url: str = typer.Option(..., "--url", help="URL of the live post."),
) -> None:
    """Record a manual post. Generated for you by REVIEW.html."""
    raise NotImplementedYet("posted", "WP-15")


@metrics_app.command("pull")
def metrics_pull(
    since: str | None = typer.Option(None, "--since", help="YYYY-MM-DD"),
) -> None:
    """Fetch site, YouTube and Facebook metrics into posted.yml."""
    raise NotImplementedYet("metrics pull", "WP-15")


# ---------------------------------------------------------------------------
# sweep / index / cost / doctor
# ---------------------------------------------------------------------------


@app.command("sweep")
def sweep(
    sources: str = typer.Option("hn,rss", "--sources", help="Comma separated."),
) -> None:
    """Scan for recurring demand signals to inform project selection."""
    raise NotImplementedYet("sweep", "WP-16")


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
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console script entry point. Maps CEError onto the TDD 9 exit codes."""
    try:
        app()
    except CEError as exc:
        console.failure(exc.message)
        if exc.hint:
            console.hint(exc.hint)
        raise SystemExit(int(exc.exit_code)) from None


if __name__ == "__main__":
    main()
