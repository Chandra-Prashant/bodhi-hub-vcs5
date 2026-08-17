"""
Extraction pipeline — Phase 3.

Reads a project document and produces a validated `ExtractionResult`. The model
call is isolated behind `Extractor.complete()` so the parsing, validation and
confidence logic — which is where the behaviour that matters lives — is
testable without a model or an API key.

The model's only job here is locating values in text. It is given a fixed JSON
schema and told, explicitly, not to compute anything. Everything downstream of
the response is deterministic Python.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from app.extraction.documents import (
    DocumentContent,
    UnsupportedDocument,
    load_document,
)
from app.extraction.guards import assert_extraction_safe
from app.extraction.schema import (
    Confidence,
    ExtractedField,
    ExtractionResult,
    ExtractionStatus,
    ProjectExtraction,
    band,
    field_specification,
)

# Checked at import: a schema change that crosses the calculated-field boundary
# fails here rather than on a client document.
assert_extraction_safe(ProjectExtraction.model_fields)


_PROMPT_TEMPLATE = """\
You extract stated values from project documents. You do not calculate.

Return a single JSON object whose keys are EXACTLY the field names listed
below. Use no other key names — a key we do not recognise is discarded, so an
invented name loses the value you found.

FIELDS TO EXTRACT:
{fields}

Include every field in your response. Where the document does not state a
value, return it with "value": null rather than omitting the key.

For each field return:
  value        the value exactly as the document states it, or null
  score        0.0-1.0, how certain you are this is the right value
  source_page  the page number you found it on, or null
  source_text  the sentence or table row you took it from, verbatim
  note         anything a human reviewer should know

Rules, without exception:
- Never compute, derive, convert, sum, or estimate a value. If a figure is not
  stated in the document, return null. A field you had to work out is a field
  you must leave empty.
- Never convert units. Return the number as written and note the unit in
  `note`. Unit conversion is a calculation and happens downstream.
- Never repair a value that looks wrong. Return it as stated with a low score
  and say why in `note`. Correcting it hides an error a reviewer needs to see.
- If the document states a figure that is clearly a calculated result — total
  emission reductions, an IRR, a grid emission factor — do not return it. Those
  are computed by the system, not read from documents.
- `source_text` must be copied verbatim from the document. A reviewer uses it
  to check you without reopening the file.
- Lower your score when the value is ambiguous, appears more than once with
  different values, or you inferred it from context rather than reading it.
"""

SYSTEM_PROMPT = _PROMPT_TEMPLATE.format(fields=field_specification())


IMAGE_INSTRUCTION = """\
The document is supplied as an image of a form. Read the values written on it.

Lower your score wherever handwriting is unclear, a field is partly obscured,
a digit could be read two ways, or a box is ticked ambiguously. A misread digit
in a figure is the failure this whole system exists to prevent, so an honest
low score is far more useful than a confident guess — a low score sends the
field to a person, and a wrong value with a high score does not.

Copy into source_text what you can actually see near the value, so a reviewer
can check your reading against the image.
"""


class Extractor(ABC):
    """The model boundary. Everything else in this module is deterministic."""

    name = "abstract"

    @abstractmethod
    def complete(self, system: str, document_text: str,
                 image: bytes | None = None, media_type: str = "") -> str:
        """Return the model's raw JSON response.

        `image` carries a photographed or scanned form. Reading one is
        extraction, which Rules.md already grants the model — not a separate
        OCR stage.
        """


class GeminiExtractor(Extractor):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-flash-latest") -> None:
        self.api_key = api_key
        self.model = model
        self.name = model

    def complete(self, system: str, document_text: str,
                 image: bytes | None = None, media_type: str = "") -> str:
        from google import genai
        from google.genai import types

        from app.services.retry import with_retry

        client = genai.Client(api_key=self.api_key)

        if image is not None:
            parts = [
                types.Part.from_text(
                    text=f"{system}\n\n{IMAGE_INSTRUCTION}"),
                types.Part.from_bytes(data=image,
                                      mime_type=media_type or "image/jpeg"),
            ]
        else:
            parts = [types.Part.from_text(
                text=f"{system}\n\n--- DOCUMENT ---\n{document_text}")]

        # A 503 or 429 from an overloaded model must not mark a document for
        # manual entry — see app/services/retry.py.
        response = with_retry(lambda: client.models.generate_content(
            model=self.model,
            contents=parts,
            config={"response_mime_type": "application/json"},
        ))
        return response.text


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def _coerce_date(raw: object) -> date | None:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw.strip():
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %B %Y"):
            try:
                from datetime import datetime

                return datetime.strptime(raw.strip(), fmt).date()
            except ValueError:
                continue
    return None


def unknown_keys(payload: str) -> list[str]:
    """Keys the model returned that the schema does not define.

    Surfaced rather than ignored: a response full of unrecognised names means
    the model is not following the field list, and the symptom otherwise looks
    like a document that simply had little in it.
    """
    try:
        text = payload.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        raw = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(raw, dict):
        return []
    return sorted(set(raw) - set(ProjectExtraction.model_fields))


def parse_response(payload: str) -> ProjectExtraction:
    """Turn a model response into a validated ProjectExtraction.

    Unknown keys are dropped rather than raising: a model returning an extra
    field should not fail a document, and the schema forbids extras precisely
    so they cannot slip through unnoticed here.
    """
    text = payload.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Extraction response was not a JSON object.")

    fields: dict[str, ExtractedField] = {}
    for name, annotation in ProjectExtraction.model_fields.items():
        entry = raw.get(name)
        if not isinstance(entry, dict):
            fields[name] = ExtractedField()
            continue

        value = entry.get("value")
        if name == "initial_crediting_period_start":
            value = _coerce_date(value)
        elif value is not None:
            value = str(value).strip() or None

        try:
            score = float(entry.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = min(max(score, 0.0), 1.0)

        page = entry.get("source_page")
        fields[name] = ExtractedField(
            value=value,
            confidence=band(score) if value is not None else Confidence.NOT_FOUND,
            score=score if value is not None else 0.0,
            source_page=int(page) if isinstance(page, (int, float)) else None,
            source_text=str(entry.get("source_text", ""))[:600],
            note=str(entry.get("note", ""))[:400],
        )

    return ProjectExtraction(**fields)


def extract(
    path: Path,
    extractor: Extractor,
    minimum_fields: int = 3,
) -> ExtractionResult:
    """Run the pipeline over one document.

    Never raises for an expected failure. An unreadable document, an
    unparseable response or a near-empty extraction all come back as a FAILED
    result carrying its reason, because Rules.md requires the document to be
    flagged for manual entry rather than the failure disappearing.
    """
    try:
        content: DocumentContent = load_document(path)
    except UnsupportedDocument as exc:
        return ExtractionResult(
            document_name=path.name, status=ExtractionStatus.FAILED,
            error=str(exc), model=extractor.name)
    except Exception as exc:  # noqa: BLE001 — any reader failure flags the doc
        return ExtractionResult(
            document_name=path.name, status=ExtractionStatus.FAILED,
            error=f"Could not read {path.name}: {exc}", model=extractor.name)

    pages = content.pages
    try:
        response = extractor.complete(
            SYSTEM_PROMPT, content.text, content.image, content.media_type)
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            document_name=path.name, status=ExtractionStatus.FAILED,
            error=f"Extraction model failed: {exc}",
            pages_read=pages, model=extractor.name)

    try:
        data = parse_response(response)
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            document_name=path.name, status=ExtractionStatus.FAILED,
            error=f"Extraction response could not be parsed: {exc}",
            pages_read=pages, model=extractor.name)

    found = data.fields_found()
    if len(found) < minimum_fields:
        stray = unknown_keys(response)
        detail = (
            f" The model returned {len(stray)} key(s) the schema does not "
            f"define ({', '.join(stray[:6])}), so it is not following the "
            f"field list — this is a prompt problem, not a document problem."
            if stray else
            " This document probably is not a project description, or needs "
            "manual entry.")
        return ExtractionResult(
            document_name=path.name, status=ExtractionStatus.FAILED,
            data=data, pages_read=pages, model=extractor.name,
            error=(f"Only {len(found)} field(s) extracted, below the minimum "
                   f"of {minimum_fields}.{detail}"))

    clean = not data.fields_needing_review() and not data.missing_required()
    status = ExtractionStatus.EXTRACTED if clean else ExtractionStatus.PARTIAL
    return ExtractionResult(
        document_name=path.name, status=status, data=data,
        pages_read=pages, model=extractor.name)
