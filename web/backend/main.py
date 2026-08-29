"""FastAPI application wiring.

The app is a thin shell: it owns the session store, turns the core's
configuration error into an honest HTTP status, and mounts the routes.  Run it
with ``uvicorn web.backend.main:app --reload``.

**API key handling.** Every user brings their own key, so a public instance
never spends the operator's.  A key is accepted once, over ``PUT /provider``,
and then lives **only in this process's memory** (see :mod:`web.backend.auth`):
it is not written to the accounts database, not written to a session workspace,
and never echoed in a response -- ``GET /provider`` reports the provider, the
model and whether a key is held, nothing else.  Restarting the server forgets
every key, which is the intended trade.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.llm import LLMConfigurationError, LLMRequestError

from .auth import UserStore
from .routes import SessionStore, router


#: Where session workspaces are created; a temp folder when unset.
WORKSPACE_ROOT_ENV = "SCHEMA_MERGER_WEB_ROOT"

#: Set to "1" only after adding a shared session/key store of your own.
MULTIPROCESS_OVERRIDE_ENV = "SCHEMA_MERGER_ALLOW_MULTIPROCESS"

#: Where accounts are stored.  Defaults to ``users.db`` beside the workspaces;
#: with no workspace root at all the accounts live in memory for this run only.
DATABASE_ENV = "SCHEMA_MERGER_DB"

#: Browser origins allowed to call the API (the Phase 6b frontend in dev).
CORS_ORIGINS_ENV = "SCHEMA_MERGER_CORS_ORIGINS"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def create_app(*, sessions: SessionStore | None = None, users: UserStore | None = None) -> FastAPI:
    """Build the application; tests pass their own stores rooted in ``tmp_path``."""

    app = FastAPI(
        title="Schema Merger API",
        version="0.1.0",
        description=(
            "Heterojen tabloları hedef şemaya göre birleştiren çekirdeğin HTTP arayüzü. "
            "İki fazlı akış korunur: analyze (LLM) → kullanıcı onayı → apply (LLM yok)."
        ),
    )
    _refuse_multiprocess()
    root = os.environ.get(WORKSPACE_ROOT_ENV)
    app.state.sessions = sessions or SessionStore(Path(root) if root else None)
    app.state.users = users or UserStore(_database_path(root))

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


def _refuse_multiprocess() -> None:
    """Stop loudly when the server is started with more than one worker.

    Sessions and each user's API key live in this process's memory, on purpose:
    a key is never written to disk.  Several workers would each hold a
    *different* slice of that memory, so the same user would be told "no key"
    on one request and served on the next -- a silent wrong answer.  The rest
    of this project refuses to guess rather than merge blindly; this refuses
    for the same reason.
    """

    if os.environ.get(MULTIPROCESS_OVERRIDE_ENV) == "1":
        return
    workers = _requested_workers()
    if workers <= 1:
        return
    raise RuntimeError(
        f"Schema Merger tek süreçte çalışır, {workers} işçi istendi. Oturumlar ve "
        "kullanıcıların API anahtarları yalnızca sürecin belleğinde tutulduğu için "
        "(anahtar diske yazılmaz) istekler farklı işçilere düşerse kullanıcı rastgele "
        "'anahtar yok' hatası alır. Tek işçiyle başlatın: "
        "'uvicorn web.backend.main:app' (varsayılan) ya da '--workers 1'. Paylaşımlı bir "
        f"oturum/anahtar deposu ekleyip bilinçli devam ediyorsanız {MULTIPROCESS_OVERRIDE_ENV}=1 verin."
    )


def _requested_workers() -> int:
    """Best-effort worker count from the command line and the environment."""

    count = 1
    concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
    if concurrency.isdigit():
        count = int(concurrency)
    argv = sys.argv[1:]
    for index, item in enumerate(argv):
        if item in {"--workers", "-w"} and index + 1 < len(argv) and argv[index + 1].isdigit():
            count = max(count, int(argv[index + 1]))
        elif item.startswith("--workers="):
            tail = item.split("=", 1)[1]
            if tail.isdigit():
                count = max(count, int(tail))
    return count


def _database_path(root: str | None) -> Path | None:
    """Accounts file: an explicit path, else next to the workspaces, else memory."""

    configured = os.environ.get(DATABASE_ENV)
    if configured:
        path = Path(configured)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    if root:
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "users.db"
    return None


app = create_app()
