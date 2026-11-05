"""Docling: turns PDF, DOCX and TXT bytes into one structured document.

Not exported from ``app.helpers``: importing Docling takes about 3 s and
400 MB, which only the worker should pay.
"""

from functools import cache
from io import BytesIO

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.io import DocumentStream

from app.constants import DOCLING_EXTENSIONS, ExtractionMessages
from app.exceptions import ExtractionError
from app.helpers.file_type_helper import file_extension
from app.settings import get_settings

_READ_OK = {ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS}


@cache
def get_converter() -> DocumentConverter:
    """One converter per process, so its models load only once."""
    pdf_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=RapidOcrOptions(lang=[get_settings().UPLOAD_OCR_LANGUAGE]),
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.MD],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)},
    )


def load_models() -> None:
    """Load the PDF models now, so the first document does not wait for them."""
    get_converter().initialize_pipeline(InputFormat.PDF)


def extract(filename: str, data: bytes) -> DoclingDocument:
    """Read a file into a Docling document: text, headings, tables and pages.

    Raises:
        ExtractionError: The file is corrupt or has no text.
    """
    extension = file_extension(filename)
    # Docling picks its reader from the name's extension.
    name = f"document{DOCLING_EXTENSIONS.get(extension, extension)}"
    result = get_converter().convert(
        DocumentStream(name=name, stream=BytesIO(data)), raises_on_error=False
    )
    if result.status not in _READ_OK:
        raise ExtractionError(ExtractionMessages.UNREADABLE)

    document = result.document
    if not document.texts and not document.tables:
        raise ExtractionError(ExtractionMessages.NO_TEXT)
    return document
