# Bodhi Hub — Audit Automation & Document Generation

Internal tool implementing the architecture in `PRD.md`, `Architecture.md`,
`Rules.md`, `Design.md` and `Phases.md`, applied to the VCS v5.0 domain
specified in the Verra requirements mapping.

The pipeline runs end to end, from the browser:

```
upload → extract → validate → flag → review → assess → generate → export
```

The calculation engine is the Verra methodology: **VMR0017 v1.0** (an ACM0002
v22.0 revision) for grid-connected solar PV and wind.

**613 tests passing** — 586 domain, 27 endpoint.

> **Not yet run against a real model.** Every verification used stubbed
> extraction and narrative models — the fake output and the assertion about it
> were both written here. Extraction quality on a real PDF, reading a
> photographed form, whether confidence scores mean anything, and whether the
> narrative model respects the placeholder rule in practice are all unproven.
> Set `GEMINI_API_KEY` and put one real document through before any demo.

---

## The rule everything serves

> Rules.md, hard rule: the LLM must never generate, alter, or estimate any
> numeric calculation.

Every number originates in `app/domain/`, which imports no database session and
no model client. A validation body must be able to reproduce any reported
figure by hand from the clause cited beside it.

Stating that rule is easy. There are four distinct ways to break it, and each
has a mechanism rather than an instruction:

| Way it breaks | What stops it |
|---|---|
| The model does arithmetic | All calculation is in `app/domain/`, pure and tested |
| The model *reads* a computed figure off a source document and carries it forward | `extraction/guards.py` — the schema is checked against a blocklist of engine outputs at import time |
| A retrieved past report's figures leak into new prose | `rag/redaction.py` — every figure is stripped before indexing, so there is nothing to copy |
| The model types a number into narrative text | `generation/placeholders.py` — drafts must use `{{placeholders}}`; a literal digit is rejected and the section regenerated |

The second and fourth are the subtle ones. Both produce output that is fluent,
specific, wrong, and passes every other check — because no calculation was
performed at all.

**Missing data goes to a person, never to a search.** A required field absent
from a document is flagged, blocks the calculation, and lands in the review
queue for manual entry. Filling it from anywhere else would put an unsourced,
untraceable figure into a report under Bodhi-hub's name.

The same discipline governs judgement. The ESG module does not invent risks;
the not-applicable pass does not touch safeguards sections; validation rules
fire regardless of extraction confidence, because a model can read a typo
perfectly; and an unrecognised technology string is refused rather than matched
to the nearest type.

---

## Phase status

| Phase | Status |
|---|---|
| 1 — Formulas & golden dataset | **Blocked — client deliverable.** See `docs/GOLDEN_DATASET.md` |
| 2 — Calculation engine | **done** |
| 3 — Extraction pipeline | **done** |
| 4 — Validation & confidence scoring | **done** |
| 5 — RAG index | **built, corpus not supplied** — nothing indexed |
| 6 — Report generation | **done** — degrades gracefully with no corpus |
| 7 — Review dashboard | **done** |
| 8 — Audit trail & export | **done** |
| 9 — Parallel run & rollout | Blocked on Phases 1 and 5 |

### What the client still has to supply

Four things, none of which code can substitute for:

1. **The 300+ historical audit reports** — the style corpus for Phases 5 and 6.
   `scripts/index_reports.py` is ready; there is nothing to index.
2. **The existing calculation formulas**, written down, including **where
   rounding happens at intermediate steps**. Matching only the final figure
   while rounding differently in the middle agrees on the sample and diverges
   in production.
3. **Five to ten past audits with confirmed-correct results** — the golden
   dataset. Phase 2's exit criterion is a 100% match against it.
4. **Grid dispatch data** for the project electricity system. Without it the
   emission factor cannot be computed, and an assessment run from a document
   reports quantification as unavailable rather than inventing one.

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

http://localhost:5173 · API docs at http://127.0.0.1:8000/docs

**The app opens empty.** No project is loaded and no assessment runs at
sign-in — a tool that greets a new user with somebody else's numbers is one
they cannot trust, because they have no way to tell which figures on screen are
theirs. A worked example is available behind *Load sample project* on the
Project details tab.

---

## The flow

**1. Upload** — PDF, Word, Excel, CSV, or a photo of a form. Stored under a
generated key, deduplicated by content hash per organization, 25 MB cap.

**2. Extract** — into `ProjectExtraction`, a fixed schema where every field
carries a value, a confidence band, the page it came from and the sentence it
was taken from. Images go to the model as vision input rather than through a
separate OCR service: Rules.md already grants the LLM "extracting structured
data from documents", and it is one fewer hop where a digit can change.

**3. Validate** — deterministic rules over the extracted data. The most
valuable is the implied capacity factor: capacity and generation come from
different parts of a document, so a unit error in either is invisible alone and
obvious once divided.

**4. Review** — only flagged *fields* reach the queue, not whole documents,
ordered blocking-first. Each shows the extracted value beside the document's
own sentence, so nobody reopens the PDF. Approve, edit or reject; every
decision is audited and cannot be reopened.

**5. Assess** — the *Assess* button on an uploaded document. Reviewer
corrections override extracted values, rejected values are dropped, and
unresolved blocking items refuse the handover and send you back to the queue.
Technology strings map through an explicit keyword table with disqualifying
terms; "solar thermal" is refused rather than matched to solar PV, because CSP
is not a VMR0017 Table 1 type and the wrong match selects the wrong rules.

**6. Generate** — the model drafts with `{{placeholders}}`; substitution happens
in Python from engine output. Each section's fallback is the existing
deterministic clause-cited prose, so with no model configured the report is
byte-identical to before.

**7. Export** — the filled Verra Project Description as `.docx`, and the
traceability matrix as CSV.

---

## Storage

`STORAGE_BACKEND` selects `local` (default) or `s3`. S3 works with AWS, MinIO,
Cloudflare R2 or Backblaze via `S3_ENDPOINT_URL`; boto3 is imported lazily so a
local deployment never needs it installed.

**Keys are generated, never derived from the uploaded filename** —
`{organization}/{uuid}{suffix}`. A key built from a browser-supplied name is how
a path traversal becomes an overwrite of another organization's document. The
original name is kept on the database row for display only.

Local storage is correct for development and wrong for production: the
application volume is not replicated, and it does not survive a container being
replaced.

---

## Tests

```bash
pytest -q
```

Expect `613 passed`. `586 passed, 27 skipped` means Postgres is not reachable —
endpoint tests skip rather than fail so the domain suite still gives a signal.

### Verifying the suite has teeth

A test that cannot fail manufactures confidence:

```bash
cp app/api/auth.py /tmp/auth_good.py
sed -i '' 's/_commit_then_raise(db, _GENERIC_LOGIN_FAILURE)/raise _GENERIC_LOGIN_FAILURE/' app/api/auth.py
pytest tests/test_endpoints.py -q
cp /tmp/auth_good.py app/api/auth.py
pytest tests/test_endpoints.py -q
```

Expect `5 failed, 22 passed`, then `27 passed`.

---

## Layout

```
app/
  core/         config, database engine, Argon2 hashing + JWT
  models/       users, audit_logs, documents, extractions, review_items,
                historical_reports, report_chunks
  extraction/   Phase 3 — documents, schema, guards, pipeline
  validation/   Phase 4 — deterministic rules, flagging, review queue
  domain/       Phase 2 — calculation engines. No DB, no LLM, no exceptions
  rag/          Phase 5 — chunking, redaction, pgvector index, retrieval
  generation/   Phase 6 — narrative drafting, placeholders, report bridge
  services/     ingestion, handover, storage, docx rendering, auditor, audit
  api/          FastAPI routers and dependencies
  templates/    the 13 official Verra v5.0A/5.0B .docx templates
frontend/       Vite + React interface
scripts/        create_admin, index_reports
migrations/     Alembic — the only way the schema changes
tests/
```

`app/domain/` is the heart. Nothing in it imports a database session or an API
client, which is why it can be tested exhaustively and why its results are
reproducible.

---

## Interface

Design.md's palette and sidebar: green `#2E7D32`, Inter, 8px grid.

**Uploads** · **Review queue** · **Compliance register** · **Quantification**
(the derivation chain) · **Additionality** · **ESG risk** · **Project
Description** · **Project details**.

---

## Regulatory facts that drive the design

Each was found by reading the primary source, and each changed a number that
looked correct beforehand.

1. **E&I crediting period is 5 years, renewable twice — 15 maximum** (VCS
   Standard v5.0 s3.8.4, Table 8). Older PDDs assume 7 × 3 = 21.
2. **VMR0017 s9.1 mandates the embodied emission factor by technology** — solar
   PV 43, wind 13, geothermal 37, hydro 21, ocean 8 g CO2e/kWh. A lower figure
   on a 50 MW solar project overstates reductions by roughly 1,600 tCO2e a year.
3. **Barrier analysis is unavailable under VMR0017** (s5.3.2).
4. **VMR0017 added embodied-emissions leakage** (eq. 19/20); ACM0002 had no such
   term, so a migrated PDD will be missing it.
5. **Additional is not CCP-eligible.** VT0008 s5.4.2(a) establishes
   additionality; (b) and (c) govern the label, which affects the price.
6. **Non-permanence risk applies only to carbon sinks** (s3.2.8).

---

## Security posture

- Argon2id hashing. Not bcrypt: it truncates silently at 72 bytes.
- Short-lived access tokens, separate refresh tokens, token type asserted on
  decode.
- Every non-public route carries `Depends(get_current_user)`.
- No self-registration. `scripts/create_admin.py` validates the address with the
  same rule the login endpoint uses.
- Login failures return one generic message regardless of cause.
- Lockout at `MAX_FAILED_LOGINS`; unlock is an audited admin action.
- `audit_logs` is append-only — no application path updates or deletes a row.
- **Audit entries record which field was edited and by whom, never the value.**
  Rules.md forbids raw client financial data in logs.
- Uploads are extension-gated, size-capped and deduplicated by content hash;
  storage keys are generated rather than derived from the filename.
- Cross-organization scoping is covered by endpoint tests.
- The frontend holds the access token in memory only, never `localStorage`.

### Transaction gotcha — read before touching `api/auth.py`

`get_db()` rolls back on any exception, so an audit row written immediately
before `raise HTTPException(...)` is **discarded with the failed request**. This
silently disabled the failure audit trail and account lockout. Every domain test
passed throughout.

Failure paths call `_commit_then_raise(db, exc)`. Any new route auditing a
failure must do the same.

The same trap has a second form in tests: a `get_db` override that merely yields
a session removes the code path where the bug lives, and the suite then passes
against broken code.

---

## Known gaps

1. **Never run against a real model.** See the note at the top. Everything in
   Phases 3, 4 and 6 rests on assumptions this would test.
2. **TOOL07 is unverified.** VT0011 replaces specific paragraphs of it, but the
   core OM/BM/CM equations live there and it was not in the regulations pack.
   The regulatory registry reports it as a `FAIL` and names the affected
   functions.
3. **Four client deliverables outstanding** — see the phase status.
4. **Nothing is deployed.** `DEPLOY.md` covers VPS, Render, Railway and Fly. No
   backups, error tracking, log aggregation or staging environment.
5. **ESG docx rendering not built** — that template's risk rows use dropdown
   content controls, which need different handling from the PD template.
6. **Benchmark IRR must be justified** per VT0008 App. 2 sA2.3.
7. **Annual estimates held flat** — VT0011 para 72 Option 2 wants the build
   margin updated annually.
8. **Multi-tenancy is application-layer**, not Postgres RLS.
9. **The 10% ex-ante/ex-post variance threshold is a house heuristic**, not a
   VCS requirement, and is labelled as such wherever it surfaces.
10. **pgvector is a deviation** from Architecture.md's Chroma/Pinecone —
    deliberate, since Postgres was already running. Worth confirming with the
    client.

---

## Working notes

**Always read an autogenerated migration before applying it.** PostGIS installs
dozens of its own tables. `migrations/env.py` filters reflection via
`include_object`; without it autogenerate proposes dropping all of them.

```bash
alembic revision --autogenerate -m "message"
sed -n '/^def upgrade/,/^def downgrade/p' migrations/versions/<new>.py | grep -c drop_table
alembic upgrade head
```

**Percent-encoded credentials break Alembic's config parser.** `env.py` builds
the engine from `settings.database_url` directly rather than through
`config.set_main_option`, which routes it through `configparser` and chokes on
`%`. Both this and the `quote_plus` fix in `config.py` have tests, because both
were lost once to a file overwrite. `render_item` in the same file emits the
pgvector import that Alembic otherwise omits.

**Verra's template filenames are inconsistently cased** — the Project
Description ships as `v5.0A`, the Monitoring Report as `V5.0A`. macOS is
case-insensitive, Linux is not.

**Dry-run any new corpus before indexing it:**

```bash
PYTHONPATH=. python scripts/index_reports.py <dir> --org "Bodhi Hub" --dry-run
```

It costs nothing and refuses to proceed if any figure survives redaction.

**Scripts need the project root on the path:** `PYTHONPATH=. python scripts/...`

**In zsh, `#` is not a comment** in interactive shells by default.
`setopt interactive_comments` fixes it.
