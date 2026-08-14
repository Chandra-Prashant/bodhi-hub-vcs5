from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import assessment, auth, classification, documents, pdd
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Verra VCS v5.0 project design platform for grid-connected solar and "
        "wind. Calculations are deterministic and clause-cited; the language "
        "model drafts and explains but never produces a reported figure."
    ),
    # Setting docs_url=None alone is not enough: FastAPI still serves
    # /openapi.json, which documents every route, its schema and its auth
    # requirements. The schema has to be disabled too, and disabling it is what
    # actually removes the Swagger and ReDoc pages.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(classification.router, prefix=settings.API_V1_PREFIX)
app.include_router(pdd.router, prefix=settings.API_V1_PREFIX)
app.include_router(assessment.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENVIRONMENT}


# ---------------------------------------------------------------------------
# Built frontend
# ---------------------------------------------------------------------------
#
# In production the API serves the interface, which keeps the browser
# same-origin: no CORS, and the access token never crosses an origin boundary.
# In development Vite serves it on :5173 and proxies /api here, so this mount
# is absent and nothing changes.
#
# Registered last so every API route and /health win over the SPA fallback.

_static = Path(settings.STATIC_DIR)

if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        """Serve the single-page app for any non-API path.

        An unknown /api path has already 404'd by this point; only browser
        routes reach here, and they all render the same app shell.
        """
        candidate = _static / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static / "index.html")
