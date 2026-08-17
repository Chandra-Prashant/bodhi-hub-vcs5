"""
ESG Risk Assessment renderer.

This template is unlike the Project Description, which is why it was left until
last. Its risk rows are not plain cells: severity, likelihood and risk level are
Word **dropdown content controls** (`w:sdt` with a `w:dropDownList`), 246 of
them across the document. Writing into the cell text the way `docx_filler` does
would put a string next to the control rather than in it, and Word would show
the dropdown still reading "Select".

A dropdown's current value lives in the runs inside its `w:sdtContent`. Setting
that is what makes the control display a chosen option.

WHAT THIS FILLS, AND WHAT IT LEAVES
-----------------------------------
Verra pre-writes the risk questions — six for biodiversity, eight for human
rights, and so on: 44 rows in total. The ESG module collects one assessed risk
per safeguard category, so a category's first row is filled and its remaining
rows are left for the author and reported.

That is deliberate rather than a shortfall. Answering Verra's other questions
means reading them and deciding, which is the judgement the ESG module already
declines to fabricate. A row filled with a plausible-looking assessment nobody
made is worse than an empty one, because an empty row is visibly outstanding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from app.domain.esg import CATEGORY_TITLES, ESGAssessment, RiskCategory, RiskEntry
from app.services.docx_filler import _set_cell_value, _set_paragraph_text

ESG_TEMPLATE = "VCS-ESG-Risk-Assessment-Template-v5.0.docx"

# The dropdown option wording, exactly as the template lists it. A value that
# is not one of these renders as free text in the control and reads as an
# override to anyone opening the file in Word.
LIKELIHOOD_OPTIONS = {
    1: "Very unlikely (1)",
    2: "Not expected (2)",
    3: "Moderately likely (3)",
    4: "Very likely (4)",
    5: "Expected (5)",
}
SEVERITY_OPTIONS = {
    1: "Negligible (1)",
    2: "Minor (2)",
    3: "Medium (3)",
    4: "Major (4)",
    5: "Severe (5)",
}

_CATEGORY_IN_HEADING = re.compile(r"\(([EGS]\d)\)")


class EsgRenderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Content controls
# ---------------------------------------------------------------------------


def _sdt_elements(cell: _Cell) -> list:
    """Every dropdown content control in a cell, in document order."""
    return cell._tc.findall(f".//{qn('w:sdt')}")


def _set_dropdown(sdt, value: str) -> bool:
    """Set a dropdown's displayed value.

    The value is written into the first run inside `w:sdtContent`. Any further
    runs are emptied — a control whose old text survives in a second run shows
    both values concatenated.
    """
    content = sdt.find(qn("w:sdtContent"))
    if content is None:
        return False

    runs = content.findall(f".//{qn('w:r')}")
    if not runs:
        return False

    first, *rest = runs
    text_node = first.find(qn("w:t"))
    if text_node is None:
        text_node = first.makeelement(qn("w:t"), {})
        first.append(text_node)
    text_node.text = value
    text_node.set(qn("xml:space"), "preserve")

    for run in rest:
        node = run.find(qn("w:t"))
        if node is not None:
            node.text = ""
    return True


def dropdown_options(sdt) -> list[str]:
    """What a control offers. Used to check a value before writing it."""
    return [
        item.get(qn("w:displayText")) or item.get(qn("w:value")) or ""
        for item in sdt.findall(f".//{qn('w:listItem')}")
    ]


# ---------------------------------------------------------------------------
# Locating the category tables
# ---------------------------------------------------------------------------


@dataclass
class CategoryTable:
    category: RiskCategory
    table: Table
    heading: str

    @property
    def risk_rows(self) -> list:
        return list(self.table.rows[1:])

    @property
    def assessable_rows(self) -> list:
        """Rows that can actually hold an assessment.

        Verra pre-marks some rows "N/A" — S2's first row, for instance — and
        those carry no dropdowns. Writing into one would overwrite a
        not-applicable determination Verra made deliberately, and leave the
        assessment with no severity or likelihood recorded.
        """
        return [row for row in self.risk_rows
                if len(row.cells) >= 4 and len(_sdt_elements(row.cells[2])) >= 3]


def find_category_tables(doc: Document) -> dict[RiskCategory, CategoryTable]:
    """Match each risk table to its safeguard category via the heading above it.

    Matched by the code in the heading — "(S3)" — rather than by table index,
    because index-based lookup breaks silently the first time Verra inserts a
    section.
    """
    found: dict[RiskCategory, CategoryTable] = {}
    heading = ""

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text and ("Heading" in paragraph.style.name
                         or "real" in paragraph.style.name):
                heading = text
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            if not table.rows:
                continue
            if table.rows[0].cells[0].text.strip() != "ID":
                continue
            match = _CATEGORY_IN_HEADING.search(heading)
            if not match:
                continue
            try:
                category = RiskCategory(match.group(1))
            except ValueError:
                continue
            found.setdefault(category, CategoryTable(category, table, heading))

    return found


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------


@dataclass
class EsgRenderReport:
    categories_written: list[str] = field(default_factory=list)
    categories_without_table: list[str] = field(default_factory=list)
    rows_left_for_author: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_rows_left(self) -> int:
        return sum(self.rows_left_for_author.values())

    def as_text(self) -> str:
        lines = [
            f"{len(self.categories_written)} category row(s) written; "
            f"{self.total_rows_left} of Verra's own risk questions still need "
            f"an author.",
        ]
        for category, count in sorted(self.rows_left_for_author.items(),
                                      key=lambda kv: -kv[1]):
            lines.append(f"  {category}: {count}")
        lines.extend(f"  ! {w}" for w in self.warnings)
        return "\n".join(lines)


def _fill_row(row, entry: RiskEntry, report: EsgRenderReport) -> None:
    cells = row.cells
    if len(cells) < 4:
        report.warnings.append(
            f"{entry.risk_id}: unexpected row shape ({len(cells)} cells).")
        return

    _set_cell_value(cells[0], entry.risk_id)

    if entry.description.strip():
        _set_cell_value(cells[1], entry.description.strip())

    level_cell = cells[2]
    controls = _sdt_elements(level_cell)
    if len(controls) < 3:
        report.warnings.append(
            f"{entry.risk_id}: expected 3 dropdowns in the risk level cell, "
            f"found {len(controls)}. Set them by hand in Word.")
    else:
        # Document order is Likelihood, Severity, then Risk level — the order
        # the cell's own labels read in.
        likelihood, severity, level = controls[:3]
        _set_dropdown(likelihood, LIKELIHOOD_OPTIONS[entry.likelihood])
        _set_dropdown(severity, SEVERITY_OPTIONS[entry.severity])
        _set_dropdown(level, entry.level.value)

    if entry.justification.strip():
        # Appended after the dropdown paragraphs so the controls are untouched.
        last = level_cell.paragraphs[-1]
        new = last.insert_paragraph_before(entry.justification.strip())
        _set_paragraph_text(new, entry.justification.strip())

    if entry.mitigation.strip():
        _set_cell_value(cells[3], entry.mitigation.strip())


def render_esg(
    assessment: ESGAssessment,
    output_path: Path,
    template_dir: Path | None = None,
) -> EsgRenderReport:
    """Write an ESG assessment into the official Verra template."""
    from app.services.pdd_builder import TEMPLATE_DIR, _resolve

    directory = template_dir or TEMPLATE_DIR
    source = _resolve(ESG_TEMPLATE) if template_dir is None else (
        directory / ESG_TEMPLATE)
    if not source.exists():
        raise EsgRenderError(f"{ESG_TEMPLATE} not found in {directory}.")

    doc = Document(str(source))
    tables = find_category_tables(doc)
    report = EsgRenderReport()

    by_category: dict[RiskCategory, RiskEntry] = {}
    for entry in assessment.entries:
        by_category.setdefault(entry.category, entry)

    for category, entry in by_category.items():
        target = tables.get(category)
        if target is None:
            # G4 (Emergency Preparedness and Response) has no risk table in the
            # v5.0 template. Reported rather than silently dropped, so nobody
            # assumes an assessed category made it into the document.
            report.categories_without_table.append(
                f"{category.value} {CATEGORY_TITLES[category][1]}")
            continue

        rows = target.assessable_rows
        if not rows:
            report.warnings.append(
                f"{category.value}: no row in this table accepts an assessment "
                f"— every row is pre-marked N/A by Verra. Record the risk in "
                f"the Project Description instead.")
            continue

        if entry.not_applicable:
            cells = rows[0].cells
            _set_cell_value(cells[0], entry.risk_id)
            if entry.na_justification.strip():
                _set_cell_value(cells[2], f"N/A — {entry.na_justification.strip()}")
                _set_cell_value(cells[3], "N/A")
        else:
            _fill_row(rows[0], entry, report)

        report.categories_written.append(category.value)
        remaining = len(target.risk_rows) - 1
        if remaining > 0:
            report.rows_left_for_author[category.value] = remaining

    if report.categories_without_table:
        report.warnings.append(
            "No risk table exists in the template for: "
            + "; ".join(report.categories_without_table)
            + ". Record these in the Project Description instead.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return report
