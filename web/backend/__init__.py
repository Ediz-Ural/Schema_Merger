"""FastAPI backend that exposes the deterministic core over HTTP."""

from .main import app, create_app

__all__ = ["app", "create_app"]
