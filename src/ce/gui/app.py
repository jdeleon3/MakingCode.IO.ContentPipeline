"""FastAPI app factory + `ce gui` entry point (TDD 10.10, WP-17).

Binds `127.0.0.1` only, no authentication -- ADR-009's trust boundary is the
same one running the CLI itself already has (single operator, local
machine). Not a daemon: the server runs only for as long as this process is
left open, and its shutdown handler stops any child `ce` subprocess it
started so nothing outlives it.
"""

from __future__ import annotations

import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ce.gui import runner
from ce.gui.routes import briefs as briefs_routes
from ce.gui.routes import dashboard as dashboard_routes
from ce.gui.routes import doctor as doctor_routes
from ce.gui.routes import pieces as pieces_routes
from ce.gui.routes import renditions as renditions_routes
from ce.gui.routes import runs as runs_routes

_PACKAGE_DIR = Path(__file__).parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    runner.terminate_all()


def create_app() -> FastAPI:
    app = FastAPI(title="Content Engine", lifespan=_lifespan)
    app.state.templates = Jinja2Templates(directory=_PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=_PACKAGE_DIR / "static"), name="static")

    app.include_router(dashboard_routes.router)
    app.include_router(doctor_routes.router)
    app.include_router(runs_routes.router)
    app.include_router(briefs_routes.router)
    app.include_router(pieces_routes.router)
    app.include_router(renditions_routes.router)

    return app


def serve(*, port: int = 8420, host: str = "127.0.0.1", open_browser: bool = True) -> None:
    """Block, serving the GUI until interrupted. `host` is only a parameter
    for testability -- there is no `--host` CLI flag (TDD 9's contract names
    only `--port`), so production callers always get the 127.0.0.1 default.
    """
    import uvicorn

    app = create_app()
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
