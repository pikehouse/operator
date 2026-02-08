"""FastAPI application factory for eval viewer."""

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from pathlib import Path


def create_app(
    db_source: Path | str,
    operator_db_path: Path | None = None,
    remote: bool = False,
) -> FastAPI:
    """Create FastAPI application for viewing eval results.

    Args:
        db_source: Path to eval.db (local) or PostgreSQL URL (remote)
        operator_db_path: Optional path to operator.db for reasoning entries
        remote: If True, db_source is a PostgreSQL URL

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(title="Eval Viewer")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    # Store config in app state for access in routes
    app.state.remote = remote
    if remote:
        app.state.db_url = str(db_source)
        app.state.db_path = None
    else:
        app.state.db_path = db_source
        app.state.db_url = None
    app.state.operator_db_path = operator_db_path
    app.state.templates = templates

    # Import and include routes
    from .routes import router
    app.include_router(router)

    return app
