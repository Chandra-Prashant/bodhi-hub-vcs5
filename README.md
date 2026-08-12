# Bodhi Hub — Verra VCS v5.0 Project Design Platform

Automates VCS v5.0 project design documentation for grid-connected **solar PV
and wind** projects under methodology **VMR0017 v1.0** (an ACM0002 v22.0
revision).

## Architecture rule

> Calculations are deterministic Python with clause citations.
> The language model drafts prose, explains results, and flags missing data.
> It never produces a number that reaches a PDD.

A validation/verification body must be able to reproduce every reported figure
by hand from the cited clause. Every finding the system emits carries a
`source` string naming the document and paragraph it came from; those strings
feed the traceability matrix export.

## Setup

```bash
conda create -n bodhi_vcs5 python=3.11 -y
conda activate bodhi_vcs5
pip install -r requirements-dev.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY
# fill in POSTGRES_PASSWORD and GEMINI_API_KEY too

docker compose up -d
alembic upgrade head

uvicorn app.main:app --reload --port 8000
```

Tests:

```bash
pytest -q
```

## Layout

```
app/
  core/        config, database engine, password hashing + JWT
  models/      SQLAlchemy tables (users, audit_logs, ...)
  domain/      pure calculation engines — no DB, no LLM, fully unit-tested
  schemas/     Pydantic request/response models
  api/         FastAPI routers
  services/    RAG, document generation
  data/        reference tables (LDC list, World Bank income groups)
  templates/   the 13 official Verra v5.0A/5.0B .docx templates
migrations/    Alembic — the only way the schema changes
tests/
```

`app/domain/` is the heart of the system. Nothing in it imports a database
session or an API client, which is why it can be tested exhaustively and why
its results are reproducible.

## Module status

| # | Module | Status |
|---|---|---|
| 1 | Project Intake & Classification | done |
| 2 | Baseline & Additionality (VT0010 / VT0011 / VT0008) | next |
| 3 | PDD Builder (docxtpl → 5.0A / 5.0B) | |
| 4 | Monitoring Plan Builder | |
| 5 | ESG Assessment | |
| 6 | Monitoring Report Generator | |
| 7 | Compliance Checklist & Validation Engine | |
| 8 | Regulatory Updates Tracking | |

The auditor agent lands with Module 7, once there are structured findings for
it to reason over rather than raw prose.

## Two regulatory facts that drive the design

1. **E&I crediting period is 5 years, renewable twice — 15 years maximum**
   (VCS Standard v5.0 §3.8.4, Table 8). Older PDDs assume 7 × 3 = 21 years.
   A financial model built on 21 years of credit revenue produces the wrong
   additionality verdict.
2. **Barrier analysis is not available under VMR0017** (§5.3.2). Additionality
   runs regulatory surplus → investment analysis → common practice only.

## Security posture

- Argon2id password hashing (not bcrypt — it truncates at 72 bytes and the
  passlib version handshake is a recurring startup failure).
- Short-lived access tokens with separate refresh tokens; token type is
  asserted on decode.
- Every non-public route carries `Depends(get_current_user)`. No exceptions.
- `audit_logs` is append-only. There is no application path that updates or
  deletes a row — it is the evidence trail a VVB inspects. Retention is
  handled by archival.
- Client data directories are gitignored.
