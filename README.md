# Bodhi Hub — Audit Automation & Document Generation

Internal tool implementing the architecture in `PRD.md`, `Architecture.md`,
`Rules.md`, `Design.md` and `Phases.md`, applied to the VCS v5.0 domain
specified in the Verra requirements mapping.

The pipeline is the one the planning documents describe — ingest, extract,
validate, calculate, generate, review, export. The calculation engine is the
Verra methodology: **VMR0017 v1.0** (an ACM0002 v22.0 revision) for
grid-connected solar PV and wind.

**413 tests passing** — 386 domain, 27 endpoint.

---

## The rule everything else serves

> Rules.md, hard rule: the LLM must never generate, alter, or estimate any
> numeric calculation.

Every number originates in `app/domain/`, which contains no database session
and no model client. A validation body must be able to reproduce any reported
figure by hand from the clause cited beside it.

Four consequences worth stating, because each one cost a bug to learn:

1. **The engine fails rather than defaults.** Missing data produces `FAIL`, not
   a plausible substitute. A number nobody can defend at validation is worse
   than no number.
2. **Extraction may not read a calculated figure off a document.** Documents
   state their own emission reductions, IRR and grid emission factor. Carrying
   one forward puts a figure nobody in this system computed into a report under
   our name — while every check passes, because no calculation happened.
   `app/extraction/guards.py` blocks it at import time.
3. **Validation rules ignore confidence.** A model can read a typo perfectly.
   Confidence describes the reading, not the value, so a rule fires at score
   1.0.
4. **The frontend holds no regulatory constants.** The ESG risk matrix is
   served from the engine, because two copies eventually disagree and the
   disagreement is silent.

The same discipline governs judgement. The ESG module does not invent risks;
the not-applicable pass does not touch safeguards sections; the auditor detects
gaps deterministically and lets a model explain them, never the reverse.

---

## Phase status

Against `Phases.md`:

| Phase | Status |
|---|---|
| 1 — Formulas & golden dataset | Client deliverable. See `docs/GOLDEN_DATASET.md` |
| 2 — Calculation engine | **done** — the eight VCS modules below |
| 3 — Extraction pipeline | **done** |
| 4 — Validation & confidence scoring | **done** |
| 5 — RAG index of historical reports | not started — needs the 300+ reports |
| 6 — Report generation | partial — template + numbers done, narrative not |
| 7 — Review dashboard | partial — flags surfaced, no approve/edit/reject |
| 8 — Audit trail & export | **done** — append-only log, Word and CSV export |
| 9 — Parallel run & rollout | not started |

### The eight VCS modules (Phase 2's domain)

| # | Module | Status |
|---|---|---|
| 1 | Project Intake & Classification | done |
| 2 | Baseline & Additionality (VT0011 / VMR0017 / VT0008) | done |
| 3 | PDD Builder — fills the official Verra template | done |
| 4 | Monitoring Plan & Data/Parameters | done |
| 5 | ESG Risk Assessment | done (docx rendering pending) |
| 6 | Monitoring Report Generator | done (no API route or UI) |
| 7 | Compliance Engine, Traceability & Auditor | done |
| 8 | Regulatory Updates Tracking | done |

---

## Setup

```bash
conda create -n bodhi_vcs5 python=3.11 -y
conda activate bodhi_vcs5
pip install -r requirements-dev.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put that in `SECRET_KEY`; set `POSTGRES_PASSWORD` and `GEMINI_API_KEY`.

```bash
docker compose up -d
docker compose ps
alembic upgrade head
PYTHONPATH=. python scripts/create_admin.py
uvicorn app.main:app --reload --port 8000
```

Interface, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

http://localhost:5173 — API docs at http://127.0.0.1:8000/docs

---

## Tests

```bash
pytest -q
```

Expect `413 passed`. `386 passed, 27 skipped` means Postgres is not reachable —
the endpoint tests skip rather than fail so the domain suite still gives a
signal. `pytest -q -rs` prints the reason.

Endpoint tests create a throwaway `bodhi_vcs5_test` database and drop it
afterwards; they never touch real data.

### Verifying the suite has teeth

A test that cannot fail manufactures confidence:

```bash
cp app/api/auth.py /tmp/auth_good.py
sed -i '' 's/_commit_then_raise(db, _GENERIC_LOGIN_FAILURE)/raise _GENERIC_LOGIN_FAILURE/' app/api/auth.py
pytest tests/test_endpoints.py -q
cp /tmp/auth_good.py app/api/auth.py
pytest tests/test_endpoints.py -q
```

Expect `5 failed, 22 passed`, then `27 passed`. Two failures are clean
assertions naming the problem; three are collateral from the rollback
discarding fixture data. Read the assertions first.

---

## Layout

```
app/
  core/         config, database engine, Argon2 hashing + JWT
  models/       SQLAlchemy tables (users, audit_logs)
  extraction/   Phase 3 — document → fixed schema, with confidence
  validation/   Phase 4 — deterministic rules, flagging, review queue
  domain/       Phase 2 — calculation engines. No DB, no LLM, no exceptions
  schemas/      Pydantic request/response models
  api/          FastAPI routers and dependencies
  services/     docx rendering, document builders, auditor, audit trail
  data/         reference tables (LDC list, World Bank income groups)
  templates/    the 13 official Verra v5.0A/5.0B .docx templates
frontend/       Vite + React interface
migrations/     Alembic — the only way the schema changes
tests/
```

`app/domain/` is the heart. Nothing in it imports a database session or an API
client, which is why it can be tested exhaustively and why its results are
reproducible.

### Pipeline modules

**`extraction/`** — reads PDF, Word and text documents into `ProjectExtraction`,
a fixed Pydantic schema where every field carries a value, a confidence band, a
score, the page it came from and the sentence it was taken from. The model
boundary sits behind an `Extractor` ABC, so parsing, banding and validation are
testable without an API key. Failures return a `FAILED` result with a reason —
Rules.md requires the document to be flagged for manual entry, never for the
failure to disappear.

Confidence bands: `HIGH` ≥ 0.90, `MEDIUM` ≥ 0.70, otherwise `LOW`. Required and
optional fields are distinguished, because an absent optional field is not an
uncertain one and sending a reviewer to verify a blank turns a targeted queue
back into a full manual check.

**`validation/`** — a registry of pure rules over the extracted data: type and
range checks, ISO country format, benchmark percent-versus-fraction, crediting
window, and cross-field consistency. The most valuable is the implied capacity
factor: capacity and generation are usually extracted from different parts of a
document, so a unit error in either is invisible alone and obvious once
divided.

Rules produce `ERROR` / `WARNING` / `INFO`. An `ERROR` stops the calculation
engine. Review items carry the source sentence and page so a reviewer checks
without reopening the file.

### Domain engines

**`classification.py`** — 5.0A/5.0B routing at the 1 Jan 2027 cutover; VMR0017
Table 1 eligibility; crediting period and registration deadlines; VT0011
combined-margin weights.

**`emission_factors.py`** — VT0011 Steps 3–6: per-unit factors via Options
A1/A2/A3, operating margin with the para 40 low-cost/must-run gate, build margin
sample selection per para 75, combined margin per para 86.

**`baseline.py`** — `BE_y = EG_PJ,y × EF_grid,CM,y`, project emissions per
VMR0017 eq. (1), embodied leakage per eq. (19), reductions per eq. (17).

**`additionality.py`** — VT0008 benchmark analysis, IRR by bisection, ±10%
sensitivity, common practice F factor with footnote 17.

**`monitoring.py`** — VMR0017 s9.1/s9.2 parameters including the mandated
embodied-EF defaults; `EFRes` for hydro and `GWPagent` for battery storage.

**`monitoring_report.py`** — ex-post quantification from metered generation;
period continuity (a gap forfeits credits, an overlap double-issues); meter
calibration; ex-ante versus ex-post variance.

**`esg.py`** — the 5×5 matrix from the ESG template, twelve safeguard
categories, s3.18.1(2) commensurate-mitigation checks.

**`compliance.py`** — twenty VCS requirements mapped to the findings evidencing
them, four statuses, traceability matrix CSV.

**`regulatory.py`** — eleven documents mapped to thirty-nine code dependencies,
SHA-256 integrity checking, update impact checklists.

---

## Interface

Five screens, all driven by `POST /assessment/run`, which executes every engine
in one request so a compliance verdict can never come from different inputs
than the figures beside it.

Compliance register · Quantification (the derivation chain) · Additionality ·
ESG risk · Project Description (completion state and `.docx` download).

Plus a traceability matrix CSV — the register a validation body works from.

**Design.md is not yet applied.** The interface uses a violet-indigo accent with
Bricolage Grotesque and IBM Plex; the specification calls for green `#2E7D32`,
Inter, and a sidebar of Uploads / Review Queue / Reports / Audit Log.

---

## Regulatory facts that drive the design

Each was found by reading the primary source, and each changed a number that
looked correct beforehand.

1. **E&I crediting period is 5 years, renewable twice — 15 maximum** (VCS
   Standard v5.0 s3.8.4, Table 8). Older PDDs assume 7 × 3 = 21. A model
   carrying 21 years of credit revenue overstates the with-credits IRR and can
   invert the additionality verdict.
2. **VMR0017 s9.1 mandates the embodied emission factor by technology** — solar
   PV 43, wind 13, geothermal 37, hydro 21, ocean 8 g CO2e/kWh. Not a free
   input. A lower figure on a 50 MW solar project overstates reductions by
   roughly 1,600 tCO2e a year.
3. **Barrier analysis is unavailable under VMR0017** (s5.3.2). Regulatory
   surplus → investment analysis → common practice only.
4. **VMR0017 added embodied-emissions leakage** (eq. 19/20); ACM0002 had no such
   term, so a migrated PDD will be missing it.
5. **Additional is not CCP-eligible.** VT0008 s5.4.2(a) establishes
   additionality; (b) and (c) govern the label, which affects the price.
6. **Non-permanence risk applies only to carbon sinks** (s3.2.8) — which is why
   the not-applicable pass can mark it N/A for solar and wind but not the
   capacity-limit section for hydro.

---

## Security posture

- Argon2id hashing. Not bcrypt: it truncates silently at 72 bytes.
- Short-lived access tokens, separate refresh tokens, token type asserted on
  decode.
- Every non-public route carries `Depends(get_current_user)`.
- No self-registration. `scripts/create_admin.py` validates the address with the
  same rule the login endpoint uses.
- Login failures return one generic message regardless of cause. Tested against
  unknown addresses, wrong passwords and locked accounts.
- Lockout at `MAX_FAILED_LOGINS`; unlock is an audited admin action.
- `audit_logs` is append-only — no application path updates or deletes a row.
- Cross-organization scoping covered by endpoint tests.
- The frontend holds the access token in memory only, never `localStorage`.
- Rules.md: raw farm/client financial data and API keys are never logged.

### Transaction gotcha — read before touching `api/auth.py`

`get_db()` rolls back on any exception, so an audit row written immediately
before `raise HTTPException(...)` is **discarded with the failed request**. This
silently disabled the failure audit trail and account lockout — the counter
never survived to be incremented twice. Every domain test passed throughout.

Failure paths call `_commit_then_raise(db, exc)`. Any new route auditing a
failure must do the same.

The same trap has a second form in tests. A `get_db` override that merely yields
a session removes the code path where the bug lives, and the suite then passes
against broken code — the first `tests/conftest.py` did exactly that.

---

## Known gaps

1. **TOOL07 is unverified.** VT0011 replaces specific paragraphs of it, but the
   core OM/BM/CM equations live there and it was not in the regulations pack.
   Marked `UNVERIFIED` in source; Module 8 reports it as a `FAIL` and names the
   affected functions. **The only gap code cannot close.**
2. **Nothing is deployed.** `DEPLOY.md` covers VPS, Render, Railway and Fly.
3. **Phase 5 not started** — the RAG index needs the 300+ historical reports.
4. **Phase 6 partial** — reports assemble template plus calculated numbers, but
   the narrative sections are written from templates rather than generated
   against retrieved examples.
5. **Phase 7 partial** — flags and gaps are surfaced; there is no approve /
   edit / reject workflow or review history.
6. **No file storage.** Architecture.md specifies S3-compatible object storage
   for uploads and generated reports; documents are currently read from disk.
7. **No OCR.** Scanned documents are refused with a clear message rather than
   silently extracted as empty.
8. **Design.md styling not applied.**
9. **Dispatch data ingest not built** — the emission factor engine takes
   `PowerUnit` objects; nothing loads them from CEA or CERC.
10. **No filled reference PDD** to check generated prose against.
11. **Benchmark IRR must be justified** per VT0008 App. 2 sA2.3.
12. **Annual estimates held flat** — VT0011 para 72 Option 2 wants the build
    margin updated annually.
13. **Multi-tenancy is application-layer**, not Postgres RLS.
14. **The 10% ex-ante/ex-post variance threshold is a house heuristic**, not a
    VCS requirement, and is labelled as such wherever it surfaces.
15. **`additionality.py` uses float.** The IRR-versus-benchmark comparison
    decides additionality, and a project near the benchmark can flip on
    representation error — structurally the same failure the PRD describes for
    profit and loss. Converting the financial path to `Decimal` is outstanding.

---

## Working notes

**Always read an autogenerated migration before applying it.** PostGIS installs
dozens of its own tables. `migrations/env.py` filters reflection via
`include_object`; without it autogenerate proposes dropping all of them.

```bash
alembic revision --autogenerate -m "message"
sed -n '/^def upgrade/,/^def downgrade/p' migrations/versions/<new>.py
alembic upgrade head
```

**Percent-encoded credentials break Alembic's config parser.** `env.py` builds
the engine directly from `settings.database_url` rather than through
`config.set_main_option`, which routes it through `configparser` and chokes on
`%`. `tests/conftest.py` uses `make_url(...).set(database=...)` for the same
reason.

**Verra's template filenames are inconsistently cased** — the Project
Description ships as `v5.0A`, the Monitoring Report as `V5.0A`. macOS is
case-insensitive, Linux is not. `services/pdd_builder._resolve` falls back to a
case-insensitive match.

**Scripts need the project root on the path:** `PYTHONPATH=. python scripts/...`

**On Apple Silicon**, `postgis/postgis:15-3.4` runs under emulation. It works
but is slower.

**Before changing a regulatory constant**, check what governs it:

```bash
python -c "
from app.domain.regulatory import dependency_index
print(dependency_index()['domain.constants.EI_MAX_TOTAL_CREDITING_YEARS'])"
```

**In zsh, `#` is not a comment** in interactive shells by default, so a trailing
comment becomes an argument. `setopt interactive_comments` fixes it.
