"""The embedding model registry."""

import re

import pytest

from app.helpers import MODEL_SPECS, get_model_spec
from app.settings import Settings


def test_the_default_model_has_a_spec() -> None:
    spec = get_model_spec(Settings.model_fields["EMBEDDING_DENSE_MODEL"].default)

    assert spec.dimensions == 768
    assert spec.max_tokens == 512
    assert spec.query_prefix
    assert spec.passage_prefix == ""


def test_every_spec_is_listed_under_its_own_name() -> None:
    assert all(name == spec.name for name, spec in MODEL_SPECS.items())


def test_unknown_model_names_the_known_ones() -> None:
    with pytest.raises(ValueError, match=re.escape("BAAI/bge-base-en-v1.5")):
        get_model_spec("no/such-model")
