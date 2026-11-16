"""Answering with a backup model when the primary one fails."""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace

from docent_api.providers.base import (
    Finished,
    GenerationEvent,
    Generator,
    Message,
    ProviderError,
    TextDelta,
)

logger = logging.getLogger(__name__)


class FallbackGenerator:
    """Uses the primary model, and the fallback if the primary fails before writing anything.

    Once the primary has streamed text to the reader, switching models would splice two answers
    together, so a failure after that point is raised instead.
    """

    def __init__(self, primary: Generator, fallback: Generator) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return self.primary.name

    async def generate(
        self,
        system: str,
        messages: Sequence[Message],
        max_output_tokens: int = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        started = False
        try:
            async for event in self.primary.generate(
                system, messages, max_output_tokens, temperature
            ):
                started = started or isinstance(event, TextDelta)
                yield event
            return
        except ProviderError as error:
            if started:
                raise
            logger.warning(
                "%s failed, answering with %s: %s", self.primary.name, self.fallback.name, error
            )

        async for event in self.fallback.generate(system, messages, max_output_tokens, temperature):
            if isinstance(event, Finished):
                event = Finished(replace(event.usage, fell_back_from=self.primary.name))
            yield event
