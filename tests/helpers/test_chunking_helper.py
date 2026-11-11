"""HybridChunker with the real BGE tokenizer, on documents that need no models."""

import io
import re

import docx

from app.constants import ChunkType
from app.helpers.chunking_helper import chunk_document, get_chunker
from app.helpers.extraction_helper import extract

MODEL = "BAAI/bge-base-en-v1.5"
#: 512 minus BGE's two special tokens ([CLS] and [SEP]).
BUDGET = 510


def test_txt_keeps_its_heading_and_markdown_table() -> None:
    document = extract(
        "notes.txt",
        b"# Leave policy\n\nStaff get twenty days.\n\n"
        b"| Year | Days |\n|---|---|\n| 1 | 20 |\n",
    )

    [chunk] = chunk_document(document, MODEL)

    assert chunk.heading_path == ["Leave policy"]
    assert chunk.chunk_type is ChunkType.TABLE
    # Markdown pads cells with spaces; collapse them to compare.
    assert "| Year | Days |" in re.sub(" +", " ", chunk.text)
    assert chunk.embed_text.startswith("Leave policy\n")
    assert (chunk.page_start, chunk.page_end) == (None, None)


def test_long_text_is_split_within_the_token_budget() -> None:
    paragraphs = "\n\n".join(
        f"Paragraph {n} explains the leave rules in plain words. " * 8
        for n in range(60)
    )
    document = extract("long.txt", f"# Handbook\n\n{paragraphs}\n".encode())

    chunks = chunk_document(document, MODEL)

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count <= BUDGET for chunk in chunks)
    assert all(chunk.heading_path == ["Handbook"] for chunk in chunks)
    assert all(chunk.chunk_type is ChunkType.TEXT for chunk in chunks)


def test_a_big_table_is_split_by_rows_with_its_header_repeated() -> None:
    rows = "\n".join(f"| Employee {n} | Team {n % 7} | {n} days |" for n in range(300))
    header = "| Name | Team | Balance |\n|---|---|---|"
    document = extract("table.txt", f"# Leave balances\n\n{header}\n{rows}\n".encode())

    chunks = chunk_document(document, MODEL)

    assert len(chunks) > 1
    assert all(chunk.chunk_type is ChunkType.TABLE for chunk in chunks)
    assert all("Balance" in chunk.text.splitlines()[0] for chunk in chunks)
    assert all(chunk.token_count <= BUDGET for chunk in chunks)


def test_docx_headings_become_the_heading_path() -> None:
    document = docx.Document()
    document.add_heading("Policies", level=1)
    document.add_heading("Leave", level=2)
    document.add_paragraph("Staff get twenty days.")
    buffer = io.BytesIO()
    document.save(buffer)

    [chunk] = chunk_document(extract("policy.docx", buffer.getvalue()), MODEL)

    assert chunk.heading_path == ["Policies", "Leave"]
    assert chunk.text == "Staff get twenty days."


def test_the_chunker_is_built_once_per_model() -> None:
    assert get_chunker(MODEL) is get_chunker(MODEL)
