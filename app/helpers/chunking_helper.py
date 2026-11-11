"""HybridChunker: splits a Docling document into chunks the embedding model can read.

Not exported from ``app.helpers``: the tokenizer loads PyTorch, which only the
worker should pay for.
"""

from functools import cache

from docling_core.transforms.chunker.doc_chunk import DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel
from pydantic import BaseModel, ConfigDict
from transformers import AutoTokenizer

from app.constants import ChunkType
from app.helpers.model_spec_helper import get_model_spec


class Chunk(BaseModel):
    """One piece of a document, ready to embed and store."""

    model_config = ConfigDict(frozen=True)

    index: int
    #: The chunk's own text: shown in answers and stored in ``document_chunk``.
    text: str
    #: Headings followed by the text: what gets embedded.
    embed_text: str
    chunk_type: ChunkType
    #: ``None`` for TXT and DOCX, which have no pages.
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    token_count: int


class _MarkdownTables(ChunkingSerializerProvider):
    """Writes tables as Markdown, which both people and LLMs read well."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc, table_serializer=MarkdownTableSerializer()
        )


@cache
def get_chunker(model_name: str) -> HybridChunker:
    """One chunker per model and process; loading the tokenizer takes a moment."""
    spec = get_model_spec(model_name)
    tokenizer = AutoTokenizer.from_pretrained(spec.name)
    # The model's limit includes its special tokens and any passage prefix.
    budget = (
        spec.max_tokens
        - tokenizer.num_special_tokens_to_add()
        - len(tokenizer.tokenize(spec.passage_prefix))
    )
    return HybridChunker(
        tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=budget),
        serializer_provider=_MarkdownTables(),
    )


def chunk_document(document: DoclingDocument, model_name: str) -> list[Chunk]:
    """Split along headings, merging small neighbours; no chunk exceeds the budget.

    A table that does not fit is split by rows, with its header repeated.
    """
    chunker = get_chunker(model_name)
    chunks = []
    for index, base_chunk in enumerate(chunker.chunk(document)):
        # The chunker yields DocChunks typed as their base class; this restores it.
        chunk = DocChunk.model_validate(base_chunk)
        items = chunk.meta.doc_items
        pages = sorted({prov.page_no for item in items for prov in item.prov})
        embed_text = chunker.contextualize(chunk)
        chunks.append(
            Chunk(
                index=index,
                text=chunk.text,
                embed_text=embed_text,
                chunk_type=(
                    ChunkType.TABLE
                    if any(item.label is DocItemLabel.TABLE for item in items)
                    else ChunkType.TEXT
                ),
                page_start=pages[0] if pages else None,
                page_end=pages[-1] if pages else None,
                heading_path=chunk.meta.headings or [],
                token_count=chunker.tokenizer.count_tokens(embed_text),
            )
        )
    return chunks
