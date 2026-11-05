"""Which files can be uploaded, and checking that a file really is what it claims."""

import io
import os
import zipfile
from collections.abc import Callable

from app.constants import MAX_FILENAME_LENGTH, UploadMessages
from app.exceptions import FileValidationError


def _is_pdf(data: bytes) -> bool:
    """PDFs start with ``%PDF-``. Readers accept it anywhere in the first 1 KB."""
    return b"%PDF-" in data[:1024]


def _is_docx(data: bytes) -> bool:
    """A .docx is a ZIP file holding ``word/document.xml``.

    The ZIP signature alone would also accept .xlsx, .pptx and any ZIP.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _is_utf8_text(data: bytes) -> bool:
    """UTF-8 (a leading BOM is fine) with no NUL bytes, which only binaries have."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return "\x00" not in text


#: Extension → (MIME type, content check). Adding a type is one line here.
#: The check reads the bytes, so a renamed ``.exe`` cannot pass as a PDF.
ALLOWED_TYPES: dict[str, tuple[str, Callable[[bytes], bool]]] = {
    ".pdf": ("application/pdf", _is_pdf),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _is_docx,
    ),
    ".txt": ("text/plain", _is_utf8_text),
}


def clean_filename(filename: str | None) -> str:
    r"""The name without any folder part, cut to fit the column.

    Some browsers send ``C:\Users\me\report.pdf``; only ``report.pdf`` is kept.
    """
    name = os.path.basename((filename or "").replace("\\", "/"))
    return name[:MAX_FILENAME_LENGTH]


def file_extension(filename: str) -> str:
    """Lowercased extension with its dot, e.g. ``".pdf"``; ``""`` if there is none."""
    return os.path.splitext(filename)[1].lower()


def validate_file(filename: str, data: bytes, max_size_bytes: int) -> str:
    """Check one upload and return the MIME type to store for it.

    The type comes from the extension and is then confirmed from the bytes.
    The browser's Content-Type header is never trusted: the client sets it.

    Raises:
        FileValidationError: With the reason this file was rejected.
    """
    extension = file_extension(filename)
    if extension not in ALLOWED_TYPES:
        raise FileValidationError(
            UploadMessages.UNSUPPORTED_TYPE.format(
                allowed=", ".join(sorted(ALLOWED_TYPES))
            )
        )
    if not data:
        raise FileValidationError(UploadMessages.EMPTY_FILE)
    if len(data) > max_size_bytes:
        raise FileValidationError(
            UploadMessages.TOO_LARGE.format(max_mb=max_size_bytes // (1024 * 1024))
        )
    mime_type, looks_valid = ALLOWED_TYPES[extension]
    if not looks_valid(data):
        raise FileValidationError(
            UploadMessages.INVALID_CONTENT.format(extension=extension)
        )
    return mime_type
