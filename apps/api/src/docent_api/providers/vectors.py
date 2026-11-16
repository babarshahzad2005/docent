"""Checks shared by the embedding adapters."""

from collections.abc import Sequence

from docent_api.providers.base import ProviderUnavailable


def check_count(provider: str, vectors: Sequence[object], texts: Sequence[str]) -> None:
    """A response with a vector missing would silently misalign passages and vectors."""
    if len(vectors) != len(texts):
        raise ProviderUnavailable(provider, f"got {len(vectors)} of {len(texts)} vectors")
