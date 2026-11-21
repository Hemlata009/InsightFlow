"""InsightFlow local web API (FastAPI) used by the React explorer in web/."""

from .app import app, create_app

__all__ = ["app", "create_app"]
