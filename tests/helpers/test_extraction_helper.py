"""Docling extraction. These inputs need no downloaded models."""

import io

import docx
import pytest

from app.constants import ExtractionMessages
from app.exceptions import ExtractionError
from app.helpers.extraction_helper import extract

NOTES = (
    b"# Leave policy\n\nStaff get twenty days.\n\n"
    b"| Year | Days |\n|---|---|\n| 1 | 20 |\n"
)


def make_docx() -> bytes:
    document = docx.Document()
    document.add_heading("Leave policy", level=1)
    document.add_paragraph("Staff get twenty days.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Year"
    table.cell(0, 1).text = "Days"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_txt_is_read_as_markdown_with_headings_and_tables() -> None:
    document = extract("notes.txt", NOTES)

    assert [item.text for item in document.texts] == [
        "Leave policy",
        "Staff get twenty days.",
    ]
    assert len(document.tables) == 1


def test_docx_keeps_headings_and_tables() -> None:
    document = extract("policy.docx", make_docx())

    assert "Leave policy" in [item.text for item in document.texts]
    assert len(document.tables) == 1


def test_corrupt_file_is_unreadable() -> None:
    with pytest.raises(ExtractionError) as error:
        extract("broken.pdf", b"%PDF-1.4 not really a pdf")

    assert error.value.message == ExtractionMessages.UNREADABLE


def test_file_without_text_is_rejected() -> None:
    with pytest.raises(ExtractionError) as error:
        extract("blank.txt", b"\n   \n")

    assert error.value.message == ExtractionMessages.NO_TEXT
