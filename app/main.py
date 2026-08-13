from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assessment, auth, classification, pdd
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Verra VCS v5.0 project design platform for grid-connected solar and "
        "wind. Calculations are deterministic and clause-cited; the language "
        "model drafts and explains but never produces a reported figure."
    ),
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(classification.router, prefix=settings.API_V1_PREFIX)
app.include_router(pdd.router, prefix=settings.API_V1_PREFIX)
app.include_router(assessment.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.ENVIRONMENT}
