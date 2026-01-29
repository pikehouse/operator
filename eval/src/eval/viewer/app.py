"""FastAPI application factory for eval viewer."""

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from pathlib import Path


def create_app(db_path: Path, operator_db_path: Path | None = None) -> FastAPI:
    """Create FastAPI application for viewing eval results.

    Args:
        db_path: Path to eval.db database
        operator_db_path: Optional path to operator.db for reasoning entries

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(title="Eval Viewer")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    # Store paths in app state for access in routes
    app.state.db_path = db_path
    app.state.operator_db_path = operator_db_path
    app.state.templates = templates

    # Import and include routes
    from .routes import router
    app.include_router(router)

    return app
