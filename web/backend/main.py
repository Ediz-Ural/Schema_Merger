"""FastAPI application wiring.

The app is a thin shell: it owns the session store, turns the core's
configuration error into an honest HTTP status, and mounts the routes.  Run it
with ``uvicorn web.backend.main:app --reload``.

**API key handling.** The provider key is read from the process environment
(``.env`` via ``core.llm``) and is used only inside the core's provider clients.
It is never accepted in a request, never written to a session workspace, and
never echoed in a response -- ``GET /provider`` reports the provider name and
whether a key is configured, nothing else.  If a deployment ever wants to take a
key from the browser, it must keep it in memory for that process only and never
write it to disk (spec section 14).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.llm import LLMConfigurationError, LLMRequestError

from .routes import SessionStore, router


#: Where session workspaces are created; a temp folder when unset.
WORKSPACE_ROOT_ENV = "SCHEMA_MERGER_WEB_ROOT"

#: Browser origins allowed to call the API (the Phase 6b frontend in dev).
CORS_ORIGINS_ENV = "SCHEMA_MERGER_CORS_ORIGINS"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def create_app(*, sessions: SessionStore | None = None) -> FastAPI:
    """Build the application; tests pass their own store rooted in ``tmp_path``."""

    app = FastAPI(
        title="Schema Merger API",
        version="0.1.0",
        description=(
            "Heterojen tabloları hedef şemaya göre birleştiren çekirdeğin HTTP arayüzü. "
            "İki fazlı akış korunur: analyze (LLM) → kullanıcı onayı → apply (LLM yok)."
        ),
    )
    root = os.environ.get(WORKSPACE_ROOT_ENV)
    app.state.sessions = sessions or SessionStore(Path(root) if root else None)

    origins = os.environ.get(CORS_ORIGINS_ENV)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[item.strip() for item in origins.split(",") if item.strip()]
        if origins
        else list(DEFAULT_CORS_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(LLMConfigurationError)
    async def _llm_not_configured(request: Request, error: LLMConfigurationError) -> JSONResponse:
        """A missing key is a server configuration problem, not a bad request.

        The core's message names the environment variable and never contains a
        key value, so it is safe to return verbatim.
        """

        return JSONResponse(
            status_code=503,
            content={"error": "llm_not_configured", "message": str(error)},
        )

    @app.exception_handler(LLMRequestError)
    async def _llm_request_failed(request: Request, error: LLMRequestError) -> JSONResponse:
        """The provider was configured but refused or failed the call.

        That is an upstream failure, not the caller's mistake, so it answers
        ``502`` with the provider's own message -- which names the model or the
        limit that blocked it and never contains a key.
        """

        return JSONResponse(
            status_code=502,
            content={"error": "llm_request_failed", "message": str(error)},
        )

    app.include_router(router)
    return app


app = create_app()
