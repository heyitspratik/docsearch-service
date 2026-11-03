"""Upload validation: allowed types, content checks and the size limit."""

import io
import zipfile

import pytest

from app.exceptions import FileValidationError
from app.helpers.file_type_helper import file_extension, validate_file

MAX_SIZE = 1024 * 1024

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def zip_with(*names: str) -> bytes:
    """A ZIP file holding empty entries with these names."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "")
    return buffer.getvalue()


DOCX = zip_with("[Content_Types].xml", "word/document.xml")


@pytest.mark.parametrize(
    ("filename", "data", "mime_type"),
    [
        ("report.pdf", PDF, "application/pdf"),
        ("REPORT.PDF", PDF, "application/pdf"),
        ("letter.docx", DOCX, DOCX_MIME),
        ("notes.txt", "Grüße, naïve café".encode(), "text/plain"),
        ("bom.txt", b"\xef\xbb\xbfhello", "text/plain"),
    ],
)
def test_valid_files_return_their_mime_type(
    filename: str, data: bytes, mime_type: str
) -> None:
    assert validate_file(filename, data, MAX_SIZE) == mime_type


@pytest.mark.parametrize(
    ("filename", "data", "reason"),
    [
        ("setup.exe", b"MZ\x90\x00", "Unsupported file type"),
        ("no_extension", PDF, "Unsupported file type"),
        ("empty.pdf", b"", "File is empty"),
        ("renamed.pdf", b"MZ\x90\x00 not a pdf", "not a valid .pdf file"),
        ("sheet.docx", zip_with("xl/workbook.xml"), "not a valid .docx file"),
        ("broken.docx", b"PK\x03\x04 truncated", "not a valid .docx file"),
        ("latin1.txt", "café".encode("latin-1"), "not a valid .txt file"),
        ("binary.txt", b"abc\x00def", "not a valid .txt file"),
    ],
)
def test_invalid_files_are_rejected_with_a_reason(
    filename: str, data: bytes, reason: str
) -> None:
    with pytest.raises(FileValidationError) as error:
        validate_file(filename, data, MAX_SIZE)

    assert reason in str(error.value)


def test_unsupported_type_lists_what_is_allowed() -> None:
    with pytest.raises(FileValidationError) as error:
        validate_file("photo.png", b"\x89PNG", MAX_SIZE)

    assert ".docx, .pdf, .txt" in str(error.value)


def test_file_over_the_size_limit_is_rejected() -> None:
    too_big = PDF + b"0" * MAX_SIZE

    with pytest.raises(FileValidationError) as error:
        validate_file("big.pdf", too_big, MAX_SIZE)

    assert "larger than 1 MB" in str(error.value)


def test_validation_error_is_a_400() -> None:
    with pytest.raises(FileValidationError) as error:
        validate_file("a.exe", b"x", MAX_SIZE)

    assert error.value.status_code == 400


@pytest.mark.parametrize(
    ("filename", "extension"),
    [("a.PDF", ".pdf"), ("archive.tar.txt", ".txt"), ("README", "")],
)
def test_file_extension_is_the_lowercased_last_suffix(
    filename: str, extension: str
) -> None:
    assert file_extension(filename) == extension
