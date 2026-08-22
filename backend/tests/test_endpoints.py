import pytest

from komvos.endpoints import CloudEndpoint, GenRequest, MockEndpoint
from komvos.endpoints.base import Message
from komvos.secrets import get_secret


@pytest.mark.asyncio
async def test_mock_endpoint():
    endpoint = MockEndpoint(token_delay=0.0, predefined_text="hello world")
    req = GenRequest(messages=[Message(role="user", content="hi")])

    tokens = []
    async for t in endpoint.generate(req):
        tokens.append(t.text)

    assert "".join(tokens) == "hello world"

    health = await endpoint.health()
    assert health.online is True

    cost = endpoint.estimate_cost(req)
    assert cost.tokens_out == 2


@pytest.mark.asyncio
async def test_cloud_endpoint_live():
    # Only run if a key is present
    api_key = get_secret("openai")
    if not api_key:
        pytest.skip("No OpenAI key found in keychain, skipping live smoke test")

    endpoint = CloudEndpoint(provider="openai", model_name="gpt-4o-mini")
    req = GenRequest(
        messages=[Message(role="user", content="Say 'hello test'")], max_tokens=10
    )

    health = await endpoint.health()
    assert health.online is True

    tokens = []
    async for t in endpoint.generate(req):
        tokens.append(t.text)

    output = "".join(tokens)
    assert len(output) > 0
