# Bodhi Hub — Verra VCS v5.0 Project Design Platform

Automates VCS v5.0 project design documentation for grid-connected **solar PV
and wind** projects under methodology **VMR0017 v1.0** (an ACM0002 v22.0
revision).

**267 tests passing** — 240 domain, 27 endpoint.

---

## Architecture rule

> Calculations are deterministic Python with clause citations.
> The language model drafts prose, explains results, and flags missing data.
> It never produces a number that reaches a PDD.

A validation/verification body must be able to reproduce every reported figure
by hand from the cited clause. Every finding the system emits carries a
`source` string naming the document and paragraph it came from, and those
strings feed the traceability matrix export in Module 7.

Practical consequence: when the engine lacks the data to compute something
correctly, it emits `FAIL` rather than a plausible default. A number nobody can
defend at validation is worse than no number.

The same rule governs judgement, not just arithmetic. The ESG module does not
invent risks. The not-applicable pass does not touch safeguards sections. The
auditor detects gaps deterministically and lets a model explain them, never the
reverse.

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
docker compose ps
alembic upgrade head
```

Wait for status `healthy` before continuing.

First admin, then the server:

```bash
PYTHONPATH=. python scripts/create_admin.py
uvicorn app.main:app --reload --port 8000
```

Interactive API docs at http://127.0.0.1:8000/docs

---

## Tests

```bash
pytest -q
```

Expect `267 passed`. If you see `240 passed, 27 skipped`, Postgres is not
reachable — the endpoint tests skip rather than fail so the domain suite still
gives a signal without Docker. `pytest -q -rs` prints the skip reason.

The endpoint tests create a throwaway `bodhi_vcs5_test` database alongside the
development one and drop it afterwards; they never touch real data.

### Verifying the suite has teeth

A test that cannot fail manufactures confidence. To check the regression suite
still detects the transaction bug described below:

```bash
cp app/api/auth.py /tmp/auth_good.py
sed -i '' 's/_commit_then_raise(db, _GENERIC_LOGIN_FAILURE)/raise _GENERIC_LOGIN_FAILURE/' app/api/auth.py
pytest tests/test_endpoints.py -q      # expect 5 failed, 22 passed
cp /tmp/auth_good.py app/api/auth.py
pytest tests/test_endpoints.py -q      # expect 27 passed
```

Two of those five failures are clean assertions naming the problem; the other
three are collateral `InvalidRequestError` from the rollback discarding the
fixture's own data. Read the assertion failures first.

---

## Layout

```
app/
  core/        config, database engine, Argon2 hashing + JWT
  models/      SQLAlchemy tables (users, audit_logs)
  domain/      pure calculation engines — no DB, no LLM, fully unit-tested
  schemas/     Pydantic request/response models
  api/         FastAPI routers and dependencies
  services/    docx rendering, PDD builder, auditor, audit trail
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
| 3 | PDD Builder (official template, filled in place) | **done** |
| 4 | Monitoring Plan & Data/Parameters | **done** |
| 5 | ESG Risk Assessment | **done** (docx rendering pending) |
| 6 | Monitoring Report Generator | not started |
| 7 | Compliance Engine, Traceability & Auditor | **done** |
| 8 | Regulatory Updates Tracking | not started |

### What each domain module does

**`classification.py`** — 5.0A/5.0B template routing at the 1 Jan 2027 cutover;
VMR0017 Table 1 eligibility (technology x geography x capacity); crediting
period and registration deadlines; VT0011 combined-margin weights; an
implied-capacity-factor band that catches kW/MW and kWh/MWh mix-ups before they
reach the baseline.

**`emission_factors.py`** — VT0011 Steps 3-6. Per-unit factors via Option A1
(fuel), A2 (efficiency) or A3 (defaults); simple and average operating margin
with the para 40 low-cost/must-run gate; build margin sample selection per para
75 (SET-5 vs SET->=20%); combined margin per para 86.

**`baseline.py`** — `BE_y = EG_PJ,y x EF_grid,CM,y`; project emissions per
VMR0017 eq. (1); embodied-emissions leakage per eq. (19); reductions per
eq. (17).

**`additionality.py`** — VT0008 benchmark analysis with project IRR by
bisection, +/-10% sensitivity across four critical assumptions, and the common
practice F factor with footnote 17 handled.

**`monitoring.py`** — VMR0017 s9.1/s9.2 parameter registry, including the
mandated embodied-emission-factor defaults table. Conditional parameters:
`EFRes` for hydro, `GWPagent` and `Me,released,y` for battery storage.

**`esg.py`** — the 5x5 severity/likelihood matrix transcribed from the ESG
template, all twelve safeguard categories with clause references, and
s3.18.1(2) commensurate-mitigation checks.

**`compliance.py`** — twenty VCS v5.0 requirements mapped to the findings that
evidence them, four statuses, and the traceability matrix CSV export.

**`pdd_content.py` / `pdd_applicability.py`** — assembles field values and
prose for the Project Description, including a technology-aware
not-applicable pass.

**`services/auditor.py`** — deterministic gap ranking
(BLOCKER/REQUIRED/REVIEW/INFO) with an explain-only LLM narrative layer.

---

## Regulatory facts that drive the design

Each of these was found by reading the primary source, and each changed a
number or a behaviour that looked correct beforehand.

1. **E&I crediting period is 5 years, renewable twice — 15 years maximum**
   (VCS Standard v5.0 s3.8.4, Table 8). Older PDDs assume 7 x 3 = 21 years. A
   financial model carrying 21 years of credit revenue overstates the
   with-credits IRR and can invert the additionality verdict.
2. **VMR0017 s9.1 mandates the embodied emission factor by technology** — solar
   PV 43, wind 13, geothermal 37, hydropower 21, ocean 8 g CO2e/kWh. It is not
   a free input. Substituting a lower figure on a 50 MW solar project overstates
   reductions by roughly 1,600 tCO2e a year.
3. **Barrier analysis is unavailable under VMR0017** (s5.3.2). Additionality
   runs regulatory surplus -> investment analysis -> common practice only.
4. **VMR0017 added embodied-emissions leakage** (eq. 19/20); ACM0002 had no such
   term. A PDD migrated from ACM0002 will be missing it. The engine blocks
   rather than defaulting it to zero.
5. **Additional is not the same as CCP-eligible.** VT0008 s5.4.2 condition (a)
   establishes additionality; (b) and (c) govern CCP label eligibility. A
   project can be additional yet ineligible for CCP labels.
6. **Non-permanence risk applies only to carbon sinks** (VCS Standard v5.0
   s3.2.8). Fossil-CO2 displacement is exempt — which is why the
   not-applicable pass can safely mark it N/A for solar and wind, but not the
   capacity-limit section for hydro.

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
  endpoint cannot enumerate valid addresses. Tested against unknown addresses,
  wrong passwords and locked accounts.
- Failed attempts increment a counter and lock the account at
  `MAX_FAILED_LOGINS`. Unlock is an audited admin action.
- `audit_logs` is append-only. There is no application path that updates or
  deletes a row — it is the evidence trail a VVB inspects. Retention is handled
  by archival.
- Client data directories are gitignored.

### Transaction gotcha — read before touching `api/auth.py`

`get_db()` rolls back on any exception. An audit row written immediately before
`raise HTTPException(...)` is therefore **discarded along with the failed
request**. This silently disabled both the failure audit trail and account
lockout: the counter never survived to be incremented twice. Every test in the
domain suite passed throughout.

Failure paths call `_commit_then_raise(db, exc)` instead of raising directly.
Any new route that audits a failure must do the same.

The same trap has a second form in the tests. A `get_db` override that merely
yields a session removes the code path where the bug lives, and the suite then
passes against broken code — the first version of `tests/conftest.py` did
exactly that. The override mirrors `get_db`'s commit/rollback semantics for
this reason.

---

## Known gaps

Ordered by how much they would hurt at validation.

1. **TOOL07 is unverified.** VT0011 is a delta document — it replaces
   paragraphs 25, 26, 39, 45, 50, 72, 75, 79 and 86 of CDM TOOL07, but the core
   OM/BM/CM equations live in TOOL07, which is not in the regulations pack. The
   implementation follows the standard TOOL07 formulation and is marked
   `UNVERIFIED` in source. Download TOOL07, check each docstring against it,
   and record the check before any output reaches a client. **This is the only
   remaining gap that code cannot close.**
2. **Dispatch data ingest not built.** The emission factor engine takes
   `PowerUnit` objects; nothing yet loads them from CEA or CERC sources.
3. **No filled reference PDD.** The templates are blank. The generated prose is
   defensible and clause-cited, but Verra reviewers have phrasing preferences
   that only surface in an accepted document.
4. **Benchmark IRR must be justified.** VT0008 Appendix 2 sA2.3 governs
   selection; a VVB will challenge an unsourced figure. Use CERC-approved
   return on equity, a WACC build-up, or bond yield plus a documented premium.
5. **Annual estimates are held flat.** VT0011 para 72 Option 2 requires the
   build margin to be updated annually; per-year factors are needed before
   submission. The engine warns rather than hiding it.
6. **ESG docx rendering not built.** The ESG template's risk rows use dropdown
   content controls, which need different handling from the PD template.
7. **Simple adjusted OM and dispatch data analysis raise `FAIL`.** Deliberate —
   they need the lambda split and hourly dispatch records respectively.
8. **Sensitivity varies one parameter at a time.** VVBs increasingly ask for
   combined worst-case scenarios.
9. **Multi-tenancy is application-layer**, not Postgres RLS. Cross-organization
   scoping is now tested at the endpoint level, but one missing `.filter()` on
   a future route would still leak.

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
chokes on the `%` in an encoded password. For the same reason `tests/conftest.py`
uses `make_url(...).set(database=...)` rather than string surgery.

**Scripts need the project root on the path:** `PYTHONPATH=. python scripts/...`

**On Apple Silicon**, `postgis/postgis:15-3.4` runs under emulation
(`linux/amd64` on `linux/arm64`). It works but is slower; worth revisiting if
Postgres becomes sluggish or flaky under load.
