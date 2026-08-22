"""
backend/tests/benchmark_latency.py

Merge D / MVP Requirement: Cloud node overhead < 1.3x raw API latency.
This script compares raw HTTP request latency against Komvos' full DAG
scheduler latency for the exact same mock payload, to prove the engine overhead
meets the PRD metric.
"""

import asyncio
import time

from komvos.compiler.dag import compile
from komvos.endpoints.base import Cost, GenRequest, ModelEndpoint
from komvos.scheduler.engine import EndpointRegistry
from komvos.scheduler.runner import PipelineRunner


class FastMockEndpoint(ModelEndpoint):
    """A mock endpoint that simulates a network call with a fixed delay."""

    def __init__(self, id: str, delay: float = 0.1):
        self.id = id
        self.delay = delay

    async def generate(self, req: GenRequest):
        from komvos.endpoints.base import Token

        # Simulate network latency
        await asyncio.sleep(self.delay)
        yield Token(text="Response", index=0)

    async def health(self):
        return True

    def capabilities(self):
        from komvos.endpoints.base import Caps

        return Caps(max_context=8192, json_mode=True, tools=False, vision=False)

    def estimate_cost(self, req: GenRequest) -> Cost:
        return Cost(usd=0.01, tokens_in=10, tokens_out=10)


async def run_benchmark():
    # 1. Measure raw "API" latency
    delay = 0.2  # 200ms network delay
    endpoint = FastMockEndpoint(id="mock:fast", delay=delay)
    req = GenRequest(messages=[{"role": "user", "content": "Hello"}])

    start_raw = time.perf_counter()
    async for _ in endpoint.generate(req):
        pass
    end_raw = time.perf_counter()
    raw_latency = end_raw - start_raw

    print(f"Raw API Latency: {raw_latency*1000:.2f} ms")

    # 2. Measure Komvos DAG latency
    pipeline_def = {
        "schema_version": "2.0",
        "id": "benchmark-pipe",
        "name": "Benchmark Pipe",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "in",
                "type": "input",
                "outputs": [{"name": "prompt", "type": "text"}],
            },
            {
                "id": "model",
                "type": "model",
                "endpoint_ref": "mock:fast",
                "inputs": [{"name": "input", "type": "text"}],
                "outputs": [{"name": "output", "type": "text"}],
            },
            {
                "id": "out",
                "type": "output",
                "inputs": [{"name": "result", "type": "text"}],
            },
        ],
        "edges": [
            {"from": "in.prompt", "to": "model.input"},
            {"from": "model.output", "to": "out.result"},
        ],
        "endpoints": {
            "mock:fast": {"kind": "mock"},
        },
    }

    dag = compile(pipeline_def)
    registry = EndpointRegistry({"mock:fast": endpoint})

    # We use PipelineRunner as it contains the full stack (queue, budget wrapping)
    runner = PipelineRunner(
        run_id="run-bench",
        dag=dag,
        registry=registry,
        budget_usd=10.0,
    )
    queue: asyncio.Queue = asyncio.Queue()

    start_nf = time.perf_counter()
    task = asyncio.create_task(runner.run(queue))

    # Consume queue
    while True:
        evt = await queue.get()
        if evt is None:
            break

    await task
    end_nf = time.perf_counter()
    nf_latency = end_nf - start_nf

    print(f"Komvos Full Pipeline Latency: {nf_latency*1000:.2f} ms")

    # 3. Assert metric
    ratio = nf_latency / raw_latency
    print(f"Overhead Ratio: {ratio:.2f}x")

    if ratio > 1.3:
        print(f"FAIL: Komvos overhead ({ratio:.2f}x) exceeds PRD limit (1.3x).")
        exit(1)
    else:
        print("PASS: Komvos overhead is within PRD limit.")


def test_benchmark_latency():
    # Make it pytest compatible
    asyncio.run(run_benchmark())


if __name__ == "__main__":
    asyncio.run(run_benchmark())
