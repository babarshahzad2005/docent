"""Builds the Word test files in `files/` from GOV.UK guidance text (Open Government Licence v3.0).

    uv run python tests/extraction/make_docx_files.py

Openly licensed real-world .docx files are scarce, so these are made with Word's own built-in
styles (Title, Heading 1 and 2, List Bullet) and real tables, which is the structure Docent
reads. The text is quoted from the PDFs in `files/`; see `files/SOURCES.md`.
"""

from pathlib import Path

from docx import Document

FILES = Path(__file__).parent / "files"


def holiday_guidance() -> None:
    document = Document()
    document.add_heading("Holiday Entitlement", level=0)
    document.add_heading("1 Calculating Leave for a Full Leave Year", level=1)
    document.add_paragraph(
        "Workers who have regular working hours and a fixed length of working day should have "
        "their holiday calculated in days. This is the most straight-forward calculation."
    )
    document.add_heading("Days per Week", level=2)
    document.add_paragraph(
        "The statutory holiday entitlement for a worker who works a full leave year is the "
        "lower of 28 days or 5.6 x days worked per week."
    )
    table = document.add_table(rows=3, cols=3)
    for row, values in zip(
        table.rows,
        [
            ("Worker", "Days per week", "Statutory leave"),
            ("Andrew", "4", "22.4 days"),
            ("Beckie", "6", "28.0 days"),
        ],
        strict=True,
    ):
        for cell, value in zip(row.cells, values, strict=True):
            cell.text = value
    document.add_paragraph("Therefore, Beckie’s statutory leave entitlement is 28.0 days.")
    document.add_heading("Hours per Week / Compressed Hours", level=2)
    document.add_paragraph(
        "Where workers work a fixed number of hours each week but not the same number of hours "
        "each day, the legislation does not state exactly how to incorporate the 28-day "
        "statutory cap."
    )
    document.add_heading(
        "2 Calculating Leave for Somebody Starting Part-Way Through a Leave Year", level=1
    )
    document.add_paragraph(
        "Where workers start employment part-way through a leave year, the leave must be "
        "pro-rated to their time in employment."
    )
    document.save(FILES / "holiday-guidance.docx")


def staffing_guidance() -> None:
    document = Document()
    document.add_heading("Introduction", level=1)
    document.add_heading("About this guidance", level=2)
    document.add_paragraph(
        "An index of Acas’s employer advice is available and any employer can contact the Acas "
        "Helpline on 0300 123 1100 for advice."
    )
    document.add_heading("Key points", level=2)
    for point in (
        "Teachers must be told of the standards against which their performance will be assessed.",
        "Teachers have to be given a written appraisal report.",
    ):
        document.add_paragraph(point, style="List Bullet")
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Check"
    table.cell(0, 1).text = "Who"
    merged = table.cell(1, 0).merge(table.cell(1, 1))
    merged.text = "Applies to all staff"
    table.cell(2, 0).text = "Childcare disqualification"
    table.cell(2, 1).text = "Staff in relevant childcare"
    document.save(FILES / "staffing-guidance.docx")


if __name__ == "__main__":
    holiday_guidance()
    staffing_guidance()
    print("Wrote", sorted(path.name for path in FILES.glob("*.docx")))
