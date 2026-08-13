# Bodhi Hub — Verra VCS v5.0 Project Design Platform

Automates VCS v5.0 project design documentation for grid-connected **solar PV
and wind** projects under methodology **VMR0017 v1.0** (an ACM0002 v22.0
revision).

**88 tests passing.**

---

## Architecture rule

> Calculations are deterministic Python with clause citations.
> The language model drafts prose, explains results, and flags missing data.
> It never produces a number that reaches a PDD.

A validation/verification body must be able to reproduce every reported figure
by hand from the cited clause. Every finding the system emits carries a
`source` string naming the document and paragraph it came from; those strings
feed the traceability matrix export.

Practical consequence: when the engine lacks the data to compute something
correctly, it emits `FAIL` rather than a plausible default. A number nobody can
defend at validation is worse than no number.

---

## Setup

```bash
conda create -n bodhi_vcs5 python=3.11 -y
conda activate bodhi_vcs5
pip install -r requirements-dev.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY
# also set POSTGRES_PASSWORD and GEMINI_API_KEY
```

Database (Docker Desktop must be running):

```bash
docker compose up -d
docker compose ps                      # wait for "healthy"
alembic upgrade head
```

First admin, then the server:

```bash
PYTHONPATH=. python scripts/create_admin.py
uvicorn app.main:app --reload --port 8000
```

Interactive API docs at http://127.0.0.1:8000/docs

Tests:

```bash
pytest -q
```

### Smoke test

```bash
read -rs PW && TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"YOUR_EMAIL\",\"password\":\"$PW\"}" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])"); unset PW

curl -s -X POST http://127.0.0.1:8000/api/v1/classification/evaluate \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Aligarh Solar One","proponent":"Test Co","country_iso2":"IN",
       "technology":"SOLAR_PV_TERRESTRIAL","installed_capacity_mw":50,
       "expected_annual_generation_mwh":87600,
       "initial_crediting_period_start":"2026-03-01"}' | python -m json.tool
```

---

## Layout

```
app/
  core/        config, database engine, Argon2 hashing + JWT
  models/      SQLAlchemy tables (users, audit_logs)
  domain/      pure calculation engines — no DB, no LLM, fully unit-tested
  schemas/     Pydantic request/response models
  api/         FastAPI routers and dependencies
  services/    audit trail; RAG and document generation to come
  data/        reference tables (LDC list, World Bank income groups)
  templates/   the 13 official Verra v5.0A/5.0B .docx templates
migrations/    Alembic — the only way the schema changes
scripts/       out-of-band operational scripts
tests/
```

`app/domain/` is the heart of the system. Nothing in it imports a database
session or an API client, which is why it can be tested exhaustively and why
its results are reproducible.

---

## Module status

| # | Module | Status |
|---|---|---|
| — | Authentication, RBAC, audit trail | **done** |
| 1 | Project Intake & Classification | **done** |
| 2 | Baseline & Additionality (VT0011 / VMR0017 / VT0008) | **done** |
| 3 | PDD Builder (docxtpl → 5.0A / 5.0B) | next |
| 4 | Monitoring Plan Builder | |
| 5 | ESG Assessment | |
| 6 | Monitoring Report Generator | |
| 7 | Compliance Checklist & Validation Engine | |
| 8 | Regulatory Updates Tracking | |

The auditor agent lands with Module 7, once there are structured findings for
it to reason over rather than raw prose.

### What Modules 1–2 cover

**`domain/classification.py`** — 5.0A/5.0B template routing at the 1 Jan 2027
cutover; VMR0017 Table 1 eligibility (technology x geography x capacity);
crediting period and registration deadlines; VT0011 combined-margin weights;
data-quality checks including an implied-capacity-factor band that catches
kW/MW and kWh/MWh mix-ups before they reach the baseline.

**`domain/emission_factors.py`** — VT0011 Steps 3-6. Per-unit emission factors
via Option A1 (fuel), A2 (efficiency) or A3 (defaults); simple and average
operating margin with the para 40 low-cost/must-run gate; build margin sample
selection per para 75 (SET-5 vs SET->=20%); combined margin per para 86.

**`domain/baseline.py`** — `BE_y = EG_PJ,y x EF_grid,CM,y`; project emissions
per VMR0017 eq. (1); embodied-emissions leakage per eq. (19); reductions per
eq. (17).

**`domain/additionality.py`** — VT0008 benchmark analysis with project IRR by
bisection, +/-10% sensitivity across four critical assumptions, and the common
practice F factor with footnote 17 handled.

---

## Regulatory facts that drive the design

1. **E&I crediting period is 5 years, renewable twice — 15 years maximum**
   (VCS Standard v5.0 s3.8.4, Table 8). Older PDDs assume 7 x 3 = 21 years. A
   financial model carrying 21 years of credit revenue overstates the
   with-credits IRR and can invert the additionality verdict.
   `build_cashflows` enforces the cap.
2. **Barrier analysis is unavailable under VMR0017** (s5.3.2). Additionality
   runs regulatory surplus -> investment analysis -> common practice only.
3. **VMR0017 added embodied-emissions leakage** (eq. 19/20); ACM0002 had no
   such term. A PDD migrated from ACM0002 will be missing it and will overstate
   reductions. The engine blocks rather than defaulting it to zero.
4. **Additional is not the same as CCP-eligible.** VT0008 s5.4.2 condition (a)
   establishes additionality; (b) and (c) govern CCP label eligibility. A
   project can be additional yet ineligible for CCP labels, which is
   commercially material.

---

## Security posture

- Argon2id password hashing. Not bcrypt: it truncates silently at 72 bytes and
  the passlib version handshake is a recurring startup failure.
- Short-lived access tokens with separate refresh tokens; the token type is
  asserted on decode, so a refresh token cannot be replayed as an access token.
- Every non-public route carries `Depends(get_current_user)`. No exceptions.
- No self-registration. Users are provisioned by an ADMIN; the first admin is
  created out of band via `scripts/create_admin.py`.
- Login failures return one generic message regardless of cause, so the
  endpoint cannot enumerate valid addresses.
- Failed attempts increment a counter and lock the account at
  `MAX_FAILED_LOGINS`. Unlock is an audited admin action.
- `audit_logs` is append-only. There is no application path that updates or
  deletes a row — it is the evidence trail a VVB inspects. Retention is handled
  by archival.
- Client data directories are gitignored.

### Transaction gotcha, fixed — read before touching `api/auth.py`

`get_db()` rolls back on any exception. An audit row written immediately before
`raise HTTPException(...)` is therefore **discarded along with the failed
request**. This silently disabled both the failure audit trail and account
lockout: the counter never survived to be incremented twice.

Failure paths call `_commit_then_raise(db, exc)` instead of raising directly.
Any new route that audits a failure must do the same.

---

## Known gaps

Ordered by how much they would hurt at validation.

1. **TOOL07 is unverified.** VT0011 is a delta document — it replaces
   paragraphs 25, 26, 39, 45, 50, 72, 75, 79 and 86 of CDM TOOL07, but the core
   OM/BM/CM equations live in TOOL07, which is not in the regulations pack. The
   implementation follows the standard TOOL07 formulation and is marked
   `UNVERIFIED` in source. Download TOOL07, check each docstring against it,
   and record the check before any output reaches a client.
2. **No endpoint tests.** `tests/test_auth.py` covers hashing and JWT,
   including token-type confusion, `alg=none`, forged signatures and the
   72-byte truncation case. It does not cover lockout counting, organization
   scoping, or audit persistence — those need a throwaway Postgres. The
   uncovered list is at the bottom of that file. The transaction bug above
   passed every existing test; it was found by hand, which is the argument for
   building this fixture.
3. **Dispatch data ingest not built.** The emission factor engine takes
   `PowerUnit` objects; nothing yet loads them from CEA or CERC sources.
4. **No filled reference PDD.** The templates are blank. Mapping placeholders
   without one completed example to check against is guesswork.
5. **Simple adjusted OM and dispatch data analysis raise `FAIL`.** Deliberate —
   they need the lambda split and hourly dispatch records respectively.
6. **Sensitivity varies one parameter at a time.** VVBs increasingly ask for
   combined worst-case scenarios.
7. **Multi-tenancy is application-layer**, not Postgres RLS. One missing
   `.filter()` leaks another organization's data.
8. **Benchmark IRR must be justified.** VT0008 Appendix 2 sA2.3 governs
   selection; a VVB will challenge an unsourced figure. Use CERC-approved
   return on equity, a WACC build-up, or bond yield plus a documented premium.

---

## Working notes

**Always read an autogenerated migration before applying it.** PostGIS installs
several dozen tables of its own (`spatial_ref_sys`, `topology`, and the entire
tiger geocoder). `migrations/env.py` filters reflection via `include_object`;
without it, autogenerate proposes dropping all of them.

```bash
alembic revision --autogenerate -m "message"
sed -n '/^def upgrade/,/^def downgrade/p' migrations/versions/<new>.py
alembic upgrade head
```

**Percent-encoded credentials break Alembic's config parser.** `env.py` builds
the engine directly from `settings.database_url` rather than through
`config.set_main_option`, which routes the value through `configparser` and
chokes on the `%` in an encoded password.

**Scripts need the project root on the path:** `PYTHONPATH=. python scripts/...`
