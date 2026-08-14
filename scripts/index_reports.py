#!/usr/bin/env python
"""
Index a directory of historical reports into the RAG corpus — Phase 5.

    PYTHONPATH=. python scripts/index_reports.py <directory> --org "Bodhi Hub"
    PYTHONPATH=. python scripts/index_reports.py <directory> --org "Bodhi Hub" --dry-run

`--dry-run` chunks and redacts without embedding or writing anything, and
prints a sample. Run it first on any new corpus: it costs nothing, and it is
the only cheap way to see whether the chunker found the document's headings and
whether redaction is catching every figure in *this* format. A corpus indexed
before checking that is a corpus that has to be rebuilt.

Everything indexed is stored redacted. The originals stay where they are.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.extraction.pipeline import UnsupportedDocument
from app.models.rag import HistoricalReport
from app.rag.chunking import chunk_file
from app.rag.index import GeminiEmbedder, index_report
from app.rag.redaction import contains_figure, redact_numbers

SUPPORTED = {".pdf", ".docx", ".doc", ".txt", ".md"}


def gather(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED
        and not p.name.startswith((".", "~$"))
    )


def dry_run(paths: list[Path], sample: int) -> int:
    """Chunk and redact without embedding, and report what would happen."""
    total_chunks = 0
    unreadable: list[tuple[str, str]] = []
    leaks: list[tuple[str, str]] = []
    shown = 0

    for path in paths:
        try:
            chunks = chunk_file(path)
        except UnsupportedDocument as exc:
            unreadable.append((path.name, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001
            unreadable.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue

        total_chunks += len(chunks)
        for chunk in chunks:
            redacted = redact_numbers(chunk.text)
            if contains_figure(redacted):
                leaks.append((path.name, redacted[:200]))
            if shown < sample:
                print(f"\n--- {path.name} · {chunk.heading or '(no heading)'} ---")
                print(redacted[:400])
                shown += 1

    print(f"\n{'=' * 60}")
    print(f"readable documents   {len(paths) - len(unreadable)} / {len(paths)}")
    print(f"chunks               {total_chunks}")
    print(f"mean chunks per doc  "
          f"{total_chunks / max(len(paths) - len(unreadable), 1):.1f}")

    if unreadable:
        print(f"\nunreadable ({len(unreadable)}) — these need OCR or manual handling:")
        for name, reason in unreadable[:15]:
            print(f"  {name}: {reason[:90]}")
        if len(unreadable) > 15:
            print(f"  ... and {len(unreadable) - 15} more")

    if leaks:
        # Fatal on purpose. A figure surviving redaction means a past farm's
        # numbers can reach a model writing about a different farm, which is
        # the exact failure Architecture.md rules out.
        print(f"\nREDACTION LEAKS ({len(leaks)}) — DO NOT INDEX THIS CORPUS:")
        for name, text in leaks[:10]:
            print(f"  {name}: {text}")
        print("\nAdd the missing pattern to app/rag/redaction.py and re-run.")
        return 1

    print("\nNo figures survived redaction. Safe to index.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--org", required=True,
                        help="Organization the corpus belongs to. Retrieval is "
                             "scoped to it, so one firm's house style is never "
                             "retrieved into another's report.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", type=int, default=3,
                        help="Redacted chunks to print during a dry run.")
    parser.add_argument("--report-type", default=None)
    args = parser.parse_args(argv[1:])

    if not args.directory.is_dir():
        print(f"{args.directory} is not a directory.", file=sys.stderr)
        return 2

    paths = gather(args.directory)
    if not paths:
        print(f"No supported documents under {args.directory}. "
              f"Looking for: {', '.join(sorted(SUPPORTED))}", file=sys.stderr)
        return 2

    print(f"Found {len(paths)} document(s) under {args.directory}")

    if args.dry_run:
        return dry_run(paths, args.sample)

    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set — embedding needs it.", file=sys.stderr)
        return 2

    embedder = GeminiEmbedder(settings.GEMINI_API_KEY)
    indexed = skipped = failed = 0

    with SessionLocal() as db:
        already = {
            r.filename for r in db.scalars(
                select(HistoricalReport).where(
                    HistoricalReport.organization == args.org))
        }

        for path in paths:
            if path.name in already:
                skipped += 1
                continue
            try:
                report = index_report(db, path, args.org, embedder,
                                      args.report_type)
                db.commit()
                indexed += 1
                print(f"  indexed {path.name} ({report.chunk_count} chunks)")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed += 1
                print(f"  FAILED {path.name}: {exc}", file=sys.stderr)

    print(f"\nindexed {indexed} · skipped {skipped} (already present) · "
          f"failed {failed}")
    return 1 if failed and not indexed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
