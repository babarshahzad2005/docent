"""The models Docent uses, chosen in ADR 0010. Application code gets its models from here."""

from docent_api.providers.base import Embedder, Generator, Reranker
from docent_api.providers.fallback import FallbackGenerator
from docent_api.providers.gemini import GeminiEmbedder, GeminiGenerator
from docent_api.providers.groq import GroqGenerator
from docent_api.providers.voyage import VoyageReranker
from docent_api.settings import Settings, get_settings

EMBEDDING_DIMENSIONS = 1024


def generator_for(spec: str, settings: Settings) -> Generator:
    """Build a generator from "provider:model", e.g. "groq:openai/gpt-oss-120b"."""
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"answer model must look like provider:model, got {spec!r}")
    if provider == "groq":
        reasoning = "low" if model.startswith("openai/gpt-oss") else None
        return GroqGenerator(settings.groq_api_key, model, reasoning_effort=reasoning)
    if provider == "gemini":
        return GeminiGenerator(settings.gemini_api_key, model, {"thinkingLevel": "minimal"})
    raise ValueError(f"unknown answer model provider {provider!r}")


def answer_generator(settings: Settings | None = None) -> Generator:
    """The answer model, falling back to the backup model when it fails."""
    settings = settings or get_settings()
    return FallbackGenerator(
        generator_for(settings.answer_model, settings),
        generator_for(settings.fallback_answer_model, settings),
    )


def embedder(settings: Settings | None = None) -> Embedder:
    """Stored vectors only match the model that made them: changing this means re-embedding."""
    settings = settings or get_settings()
    return GeminiEmbedder(settings.gemini_api_key, dimensions=EMBEDDING_DIMENSIONS)


def reranker(settings: Settings | None = None) -> Reranker:
    settings = settings or get_settings()
    return VoyageReranker(settings.voyage_api_key)
