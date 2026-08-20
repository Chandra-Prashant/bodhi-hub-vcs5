# Bodhi Hub — VCS v5.0 Audit Automation

Reads project documents, checks what it finds, asks a person about anything
doubtful, performs the regulated calculations, and produces a Verra Project
Description in which every figure cites the clause that governs it.

Built against VCS Standard v5.0 and methodology VMR0017 v1.0 (a revision of
CDM ACM0002 v22.0) for grid-connected solar photovoltaic and wind projects.

**747 tests passing.**

---

## The rule the design serves

> The LLM must never generate, alter, or estimate any numeric calculation.
> — Rules.md, Hard Rule

Stating that is easy. Honouring it is not, because there are four distinct ways
to break it and two of them produce output that looks entirely correct. Each
has a mechanism rather than an instruction:

| How the rule could break | What prevents it |
|---|---|
| The model does arithmetic | All calculation lives in `app/domain/` — no AI, no database access, covered by tests against the clause each implements |
| The model reads an already-calculated figure off a document and carries it forward | `app/extraction/guards.py` checks the extraction schema at import time against every value the engine computes. A build that tried to extract emission reductions would fail before running |
| Figures from a past client report leak into new prose | `app/rag/redaction.py` strips every number before indexing, so there is nothing to copy |
| The model types a number into narrative | `app/generation/placeholders.py` rejects a draft containing digits and rewrites it |

The second and fourth are the subtle ones: a figure appears that nobody
calculated, and every other check passes because no calculation took place.

### The failure mode this system is built against

Every serious bug found during development was the same shape — **an absence
rendered as a result**:

- an unread field looking extracted
- a failed extraction looking approved
- a missing similar-project search reported as "not common practice", which is
  favourable
- an IRR the solver could not bracket described as "no positive net cashflow",
  which is also favourable

Each produced output that was fluent, plausible, and wrong in the project's
favour. Where a value is unknown the system says so; where two sources
disagree it refuses to choose. That is the point of it.

---

## Getting started

```bash
cp .env.example .env          # set SECRET_KEY, POSTGRES_PASSWORD, GEMINI_API_KEY
docker compose up -d          # PostgreSQL with pgvector
alembic upgrade head
PYTHONPATH=. python scripts/create_admin.py
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Then http://localhost:5173.

Tests need a database:

```bash
pytest -q
```

### Configuration

| Variable | Notes |
|---|---|
| `SECRET_KEY` | 32 characters minimum |
| `POSTGRES_PASSWORD` | URL-encoded internally; `@` and `%` are safe |
| `GEMINI_API_KEY` | Extraction and narrative |
| `GEMINI_MODEL` | Default `gemini-flash-latest` |
| `EMBEDDING_MODEL` | `gemini-embedding-001` |
| `EMBEDDING_DIM` | 768. Truncated from the model's 3072 and re-normalised. Changing it requires a migration — the column is sized to it |
| `STORAGE_BACKEND` | `local` or `s3` |

---

## How it is used

Projects hold documents. Each project has its own documents, review queue, ESG
assessment and Project Description; nothing crosses between them.

```
create project → upload documents → extract → validate → flag
              → review → assess → generate → export
```

| Tab | Purpose | Takes input? |
|---|---|---|
| **Uploads** | PDF, Word, Excel, CSV or a photograph of a form. ~13 fields extracted with a confidence score and the source sentence | The file |
| **Review queue** | Only flagged *fields*, not whole documents. Shows the extracted value beside what the document says | **Yes** — approve / edit / reject |
| **Compliance register** | 20 VCS v5.0 requirements with clause, status and evidence. Exports the traceability matrix | No |
| **Quantification** | Operating margin → build margin → combined margin → baseline → leakage → reductions, each row with its arithmetic and clause | No |
| **Additionality** | IRR with and without credits, benchmark, sensitivity, common practice, CCP eligibility | No |
| **ESG risk** | 12 safeguard categories. You supply severity and likelihood; the level is computed from Verra's matrix | **Yes** — judgement |
| **Project Description** | Completion state, what still needs an author, and the download | No |
| **Project details** | Manual intake and financial model | **Yes** — if no document |

**Run assessment** appears on every tab that takes input, so completing the ESG
assessment does not mean navigating elsewhere to see its effect.

### Two downloads

**Working draft** keeps Verra's guidance text, which is what tells an author
what each unwritten section requires. **Submission copy** strips it, and is
refused while findings are unresolved — removing the guidance from an
unfinished document deletes the only marks showing which sections were never
written.

### Several documents per project

A project is described by a bundle: an information memorandum, a technical
report, a financial model, a land schedule. Values merge across all of them,
and each carries the file, page and sentence it came from.

**Where two documents disagree, the assessment refuses rather than choosing.**

```
Documents disagree. Choose a value before calculating.
  installed_capacity_mw:
        50   Aligarh-PIM.pdf p1
      49.5   Aligarh-Technical-Report.pdf p12
```

Neither alternative is defensible. "Newest wins" is silently wrong the day
somebody uploads an old file last. "Highest confidence wins" sounds principled
and is not — confidence measures how clearly a value was *read*, not whether it
is *right*. A capacity that differs between two source documents is a fact
about the project, not noise. See `app/services/merge.py`.

Values differing only in formatting — `50` and `50.0` — are treated as
agreement, so reviewers are not trained to dismiss conflicts.

---

## What the system will not write

Roughly two-thirds of a Project Description assembles itself. The rest is
marked `author_supplied` in `app/domain/compliance.py`: right to operate,
project start date evidence, stakeholder engagement, no double counting,
records.

These are attestations, not descriptions. Somebody is stating a fact they can
be held to, and there is no data in the system to support them. The model
could produce a fluent paragraph confirming the proponent holds all necessary
rights — it would read perfectly and be a fabrication, in a document submitted
to a validation body.

The system's contribution there is making sure none of them is missed.

---

## Architecture

```
app/domain/       Regulated calculation. No AI, no database. Pure functions,
                  tested against the clause each implements
app/extraction/   Model boundary. Reads documents into a fixed schema with
                  per-field confidence, page and source sentence
app/validation/   Deterministic rules. Fire regardless of confidence
app/services/     Ingestion, handover, merge, storage, docx assembly, audit
app/rag/          Past-report index. Numbers redacted before indexing
app/generation/   Narrative drafting with placeholder enforcement
app/api/          FastAPI routes
frontend/         Vite + React
```

### Deliberate deviations from the spec

- **pgvector rather than Chroma or Pinecone.** Architecture.md names the
  latter. PostgreSQL was already required, so this is one datastore, one
  backup, one deployment — and chunks live in the same transaction as
  everything else.
- **Images read directly by the model rather than a separate OCR step.**
  Reading a form is extraction, which Rules.md already permits, and it removes
  a stage at which a digit could change.

---

## Still needed from the client

Four items. None can be substituted by further development.

1. **300+ historical audit reports** — the RAG index is built and tested;
   there is nothing to index. Every figure is stripped before indexing, so
   these inform wording and structure only.
2. **The existing formulas, written down** — including where rounding occurs
   at intermediate steps. A formula matching only on the final figure while
   rounding differently in the middle will agree on the sample and diverge in
   production.
3. **5–10 past audits with confirmed results** — Phase 2's stated exit
   criterion is a 100% match against these. Format in `docs/GOLDEN_DATASET.md`.
4. **Grid dispatch data** — the emission factor is calculated from the
   generating units of the connected grid. A project document states its own
   capacity; it does not describe the national grid. Without this,
   quantification reports unavailable rather than assuming a factor.

---

## Known gaps

- **Extraction accuracy has not been measured at scale.** The pipeline is
  tested, and has been run against real documents, but no systematic accuracy
  measurement has been done. Phases.md provides for it in Phase 3.
- **CDM TOOL07 was not in the supplied documentation.** VT0011 modifies
  specific paragraphs of it; the implementation follows the standard published
  formulation and is marked in code as requiring verification.
- **Not yet deployed.** Instructions in `DEPLOY.md`.
- **Verra's ESG template pre-writes 44 risk questions.** The system assesses
  one per category and reports the rest as outstanding rather than fabricating
  answers.
- **The generation-variance threshold is a review heuristic**, not a Verra
  requirement, and is labelled as such wherever it appears.
- **Multi-tenancy is application-layer**, not row-level security.

---

## Phase status

| Phase | Status |
|---|---|
| 1 — Formulas and golden dataset | Awaiting client |
| 2 — Calculation engine | Complete |
| 3 — Extraction pipeline | Complete |
| 4 — Validation and confidence | Complete |
| 5 — Historical report index | Built; no corpus supplied |
| 6 — Report generation | Complete |
| 7 — Review dashboard | Complete |
| 8 — Audit trail and export | Complete |
| 9 — Parallel run | Depends on 1 and 5 |

---

## Working notes

- `PYTHONPATH=.` is needed for scripts.
- Never run `create_all()` — Alembic only.
- `migrations/env.py` builds its engine directly rather than using
  `set_main_option`: configparser chokes on `%` in passwords. Guarded by
  `tests/test_migrations_env.py`.
- Verra ships the PD template as `v5.0A` and the MR template as `V5.0A`.
  Case-sensitive filesystems care.
- In zsh, `#` is not a comment interactively: `setopt interactive_comments`.
