"""What the app needs to know about each embedding model."""

from pydantic import BaseModel, ConfigDict

from app.constants import EmbeddingMessages

# BGE v1.5 recommends this prefix on short queries; passages get none.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class ModelSpec(BaseModel):
    """One embedding model. Its name is also its tokenizer's name on HuggingFace."""

    model_config = ConfigDict(frozen=True)

    name: str
    #: Length of each vector; the Qdrant collection is created with it.
    dimensions: int
    #: Longest input the model reads, special tokens included; the rest is cut off.
    max_tokens: int
    query_prefix: str = ""
    passage_prefix: str = ""


#: Adding a model is one entry here.
MODEL_SPECS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        ModelSpec(
            name="BAAI/bge-base-en-v1.5",
            dimensions=768,
            max_tokens=512,
            query_prefix=_BGE_QUERY_PREFIX,
        ),
        ModelSpec(
            name="BAAI/bge-small-en-v1.5",
            dimensions=384,
            max_tokens=512,
            query_prefix=_BGE_QUERY_PREFIX,
        ),
    )
}


def get_model_spec(name: str) -> ModelSpec:
    """The spec for ``name``.

    Raises:
        ValueError: The model is not in ``MODEL_SPECS``.
    """
    if name not in MODEL_SPECS:
        raise ValueError(
            EmbeddingMessages.UNKNOWN_MODEL.format(
                name=name, known=", ".join(MODEL_SPECS)
            )
        )
    return MODEL_SPECS[name]
