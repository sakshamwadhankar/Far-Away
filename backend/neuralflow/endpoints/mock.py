import asyncio
from typing import AsyncIterator
from .base import ModelEndpoint, GenRequest, Token, Health, Caps, Cost

class MockEndpoint(ModelEndpoint):
    id: str = "mock-endpoint"

    def __init__(self, token_delay: float = 0.01, predefined_text: str = "This is a mock response."):
        self.token_delay = token_delay
        self.predefined_text = predefined_text

    async def generate(self, req: GenRequest) -> AsyncIterator[Token]:
        words = self.predefined_text.split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(self.token_delay)
            # append space except for the last word
            text = word + (" " if i < len(words) - 1 else "")
            yield Token(text=text, index=i)

    async def health(self) -> Health:
        return Health(online=True, loaded=True, warm=True)

    def capabilities(self) -> Caps:
        return Caps(max_context=4096, json_mode=True, tools=False, vision=False)

    def estimate_cost(self, req: GenRequest) -> Cost:
        return Cost(usd=0.001, tokens_in=10, tokens_out=len(self.predefined_text.split(" ")))
