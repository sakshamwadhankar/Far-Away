"""
backend/komvos/executors/model.py

Model executor with structured-output repair.
"""

import json
import logging
from typing import Any

from komvos.endpoints.base import GenRequest, Message
from komvos.executors.base import BaseExecutor, ExecutorContext
from komvos.scheduler.engine import EventKind, SchedulerEvent

logger = logging.getLogger(__name__)


class ModelExecutor(BaseExecutor):
    """
    Executes a model node by calling its endpoint.
    Implements structured-output repair (JSON repair) if response_format="json".
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        node = ctx.node
        if node.endpoint_ref is None:
            raise RuntimeError(f"Model node '{node.id}' has no endpoint_ref.")

        endpoint = ctx.registry.resolve(node.endpoint_ref)

        # Access control gate. Runs before anything that could touch the
        # network — before the API key is read from the keychain and before a
        # socket is opened — so a denied call never leaves the machine.
        endpoint.check_access(ctx.policy, node.id)

        # Gather inputs into a single combined string
        input_text_parts: list[str] = []
        for _port_name, value in ctx.inputs.items():
            if isinstance(value, str):
                input_text_parts.append(value)
            elif isinstance(value, dict):
                input_text_parts.append(json.dumps(value))
            else:
                input_text_parts.append(str(value))

        combined_input = "\n".join(input_text_parts) if input_text_parts else ""

        system_prompt = node.config.system_prompt if node.config else None
        response_format = (
            node.config.response_format
            if node.config and node.config.response_format
            else "text"
        )
        temperature = (
            node.config.temperature
            if node.config and node.config.temperature is not None
            else 0.7
        )
        max_tokens = (
            node.config.max_tokens
            if node.config and node.config.max_tokens is not None
            else 2048
        )
        # A policy ceiling caps the node's own setting; it can only lower it.
        if ctx.policy.max_tokens is not None:
            max_tokens = min(max_tokens, ctx.policy.max_tokens)

        messages: list[Message] = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=combined_input))

        max_attempts = 3 if response_format == "json" else 1

        total_usd = 0.0
        total_tokens_in = 0
        total_tokens_out = 0

        last_output_text = ""
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            ctx.check_cancel()

            # For json mode, some endpoints require "json" in the prompt
            # even if the format is set.
            # But we rely on the system_prompt or the user's prompt.
            req = GenRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            estimated_cost = endpoint.estimate_cost(req)

            output_text = ""
            tokens_out = 0

            async for token in endpoint.generate(req):
                ctx.check_cancel()
                output_text += token.text
                tokens_out += 1
                await ctx.emit(
                    SchedulerEvent(
                        kind=EventKind.TOKEN,
                        node_id=node.id,
                        data={
                            "text": token.text,
                            "index": token.index,
                            "attempt": attempt,
                        },
                    )
                )

            total_usd += estimated_cost.usd
            total_tokens_in += estimated_cost.tokens_in
            total_tokens_out += tokens_out
            last_output_text = output_text

            if response_format == "json":
                try:
                    parsed_json = json.loads(output_text)
                    outputs = self._build_outputs(node, parsed_json)
                    await self._emit_done(
                        ctx, outputs, total_usd, total_tokens_in, total_tokens_out
                    )
                    return outputs
                except json.JSONDecodeError as exc:
                    last_error = str(exc)
                    logger.warning(
                        f"Node '{node.id}' attempt {attempt} failed JSON parsing: {exc}"
                    )
                    if attempt < max_attempts:
                        # Append a repair prompt
                        messages.append(Message(role="assistant", content=output_text))
                        messages.append(
                            Message(
                                role="user",
                                content=(
                                    "The previous output was invalid JSON. "
                                    "Please fix this parsing error and "
                                    f"return ONLY valid JSON: {exc}"
                                ),
                            )
                        )
                    else:
                        logger.error(
                            f"Node '{node.id}' exceeded max attempts for JSON repair."
                        )
                        # We must fail cleanly but preserve raw output.
                        # We'll raise a ValueError that includes the raw output.
                        raise ValueError(
                            f"Failed to generate valid JSON after "
                            f"{max_attempts} attempts. "
                            f"Last error: {last_error}. Raw output: {last_output_text}"
                        ) from exc
            else:
                outputs = self._build_outputs(node, output_text)
                await self._emit_done(
                    ctx, outputs, total_usd, total_tokens_in, total_tokens_out
                )
                return outputs

        return {}  # Should not be reached

    def _build_outputs(self, node: Any, parsed_value: Any) -> dict[str, Any]:
        """Map the parsed value to all of the node's output ports."""
        outputs: dict[str, Any] = {}
        for port in node.outputs:
            outputs[port.name] = parsed_value
        return outputs

    async def _emit_done(
        self,
        ctx: ExecutorContext,
        outputs: dict[str, Any],
        usd: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Emit the NODE_DONE event with final cost metrics."""
        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.NODE_DONE,
                node_id=ctx.node.id,
                data={
                    "inputs": ctx.inputs,
                    "outputs": outputs,
                    "cost_usd": usd,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                },
            )
        )
