"""
backend/komvos/executors/computer.py

Computer node executor for governed desktop automation.

Implements the governed loop:
  observe -> decide -> GATE -> act -> verify -> repeat

The Gate is absolute: every desktop action must be classified and pass
governance before it can be dispatched to the local desktop action layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from komvos.desktop.client import DesktopClient
from komvos.desktop.destructive import classify_action
from komvos.desktop.grounding import annotate_screenshot
from komvos.desktop.models import (
    ActionType,
    DesktopAction,
    DestructiveClassification,
    MarkedScreen,
)
from komvos.desktop.verifier import verify_action
from komvos.endpoints.base import AccessDeniedError, GenRequest, Message
from komvos.executors.base import BaseExecutor, ExecutorContext
from komvos.governance.approvals import APPROVAL_TIMEOUT_SECONDS
from komvos.governance.context import record_decision
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDomain,
)
from komvos.governance.posture import answer_effects, consult_posture
from komvos.scheduler.engine import EventKind, SchedulerEvent

logger = logging.getLogger(__name__)


def _approval_notifier(
    ctx: ExecutorContext,
    domain: str,
    capability: str,
    reason: str,
    screenshot: str | None = None,
) -> Any:
    """Emits approval_pending event over the scheduler when posture asks a human."""

    async def notify(question: Any) -> None:
        effects = answer_effects(GovernanceDomain(domain), capability)
        await ctx.emit(
            SchedulerEvent(
                kind=EventKind.APPROVAL_PENDING,
                node_id=ctx.node.id,
                data={
                    "approval_id": question.approval_id,
                    "domain": domain,
                    "capability": capability,
                    "reason": question.reason or reason,
                    "allow_once_effect": effects["allow_once"],
                    "allow_for_run_effect": effects["allow_for_run"],
                    "deny_effect": effects["deny"],
                    "timeout_seconds": APPROVAL_TIMEOUT_SECONDS,
                    "screenshot": screenshot,
                },
            )
        )

    return notify


class ComputerExecutor(BaseExecutor):
    """
    Governed desktop automation executor.
    Connects to the vision endpoint and local loopback desktop server.
    """

    async def execute(self, ctx: ExecutorContext) -> dict[str, Any]:
        ctx.check_cancel()

        # ── 1. Resolve endpoint ───────────────────────────────────────────────
        endpoint_ref = ctx.node.endpoint_ref
        if not endpoint_ref:
            raise ValueError(f"Computer node '{ctx.node.id}' missing endpoint_ref.")

        endpoint = ctx.registry.resolve(endpoint_ref)
        if endpoint is None:
            raise ValueError(f"Endpoint '{endpoint_ref}' could not be resolved.")

        # Check endpoint provider access
        endpoint.check_access(ctx.policy, ctx.node.id)

        # ── 2. Parse task input ───────────────────────────────────────────────
        task = ""
        for k in ("task", "instruction", "prompt", "text", "input"):
            if k in ctx.inputs and ctx.inputs[k]:
                task = str(ctx.inputs[k])
                break
        if not task and ctx.inputs:
            task = str(next(iter(ctx.inputs.values())))
        if not task:
            task = "Observe screen and report status."

        # ── 3. Configure bounds ───────────────────────────────────────────────
        max_steps = 30
        timeout_seconds = 300.0

        if ctx.node.config:
            cfg_dict = (
                ctx.node.config.model_dump()
                if hasattr(ctx.node.config, "model_dump")
                else vars(ctx.node.config)
            )
            if "max_steps" in cfg_dict and cfg_dict["max_steps"]:
                max_steps = int(cfg_dict["max_steps"])
            if "timeout_seconds" in cfg_dict and cfg_dict["timeout_seconds"]:
                timeout_seconds = float(cfg_dict["timeout_seconds"])

        client = DesktopClient()
        history: list[str] = []
        last_screenshot_b64 = ""
        start_time = time.monotonic()
        steps_taken = 0

        # ── 4. Main governed loop ─────────────────────────────────────────────
        while steps_taken < max_steps:
            ctx.check_cancel()

            elapsed = time.monotonic() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Computer node execution exceeded timeout of {timeout_seconds}s "
                    f"at step {steps_taken}/{max_steps}."
                )

            # Step A: OBSERVE
            screen_bytes = await client.screenshot()
            a11y_tree = await client.get_accessibility_tree()
            active_window = await client.get_active_window()

            # Step B: GROUND
            marked_screen = annotate_screenshot(
                screen_bytes, a11y_tree=a11y_tree, active_window=active_window
            )
            last_screenshot_b64 = marked_screen.image_base64

            if last_screenshot_b64:
                await ctx.emit(
                    SchedulerEvent(
                        kind=EventKind.TOKEN,
                        node_id=ctx.node.id,
                        data={
                            "text": (
                                "[Vision: Screen grounded with "
                                f"{len(marked_screen.elements)} marks]"
                            ),
                            "screenshot": last_screenshot_b64,
                            "index": steps_taken,
                        },
                    )
                )

            # Step C: DECIDE
            action = await self._decide_action(
                endpoint=endpoint,
                task=task,
                history=history,
                marked_screen=marked_screen,
                ctx=ctx,
            )

            # Check if task is finished
            if action.action_type == ActionType.DONE:
                result_text = (
                    action.thought or action.text or "Task marked as complete."
                )
                return {
                    "result": result_text,
                    "status": "completed",
                    "steps_taken": steps_taken + 1,
                    "last_screenshot": last_screenshot_b64,
                }

            # Map target mark to pixel coordinates and element details
            target_elem_name = None
            target_elem_role = None
            if action.target_mark is not None:
                for elem in marked_screen.elements:
                    if elem.mark_id == action.target_mark:
                        action.x, action.y = elem.center
                        target_elem_name = elem.name
                        target_elem_role = elem.role
                        break

            # Step D: GATE (Absolute governance before action)
            classification = classify_action(
                action=action,
                target_element_name=target_elem_name,
                target_element_role=target_elem_role,
            )

            await self._gate_action(
                action=action,
                classification=classification,
                marked_screen=marked_screen,
                ctx=ctx,
            )

            # Step E: ACT
            act_ok = await client.execute_action(action)
            if not act_ok:
                logger.warning("Action execution failed at mechanical client level.")

            # Settle delay for UI reaction
            await asyncio.sleep(0.4)

            # Step F: VERIFY
            post_screen_bytes = await client.screenshot()
            post_a11y = await client.get_accessibility_tree()
            post_window = await client.get_active_window()
            post_marked_screen = annotate_screenshot(
                post_screen_bytes,
                a11y_tree=post_a11y,
                active_window=post_window,
            )

            verification = verify_action(
                marked_screen, post_marked_screen, action
            )

            # Record verification outcome
            delta_str = f"{verification.delta_score:.4f}"
            await record_decision(
                domain=GovernanceDomain.DESKTOP,
                outcome=(
                    DecisionOutcome.ALLOWED
                    if verification.passed
                    else DecisionOutcome.DENIED
                ),
                origin=DecisionOrigin.PIPELINE_POLICY,
                capability=f"desktop:verify:{action.action_type.value}",
                reason=f"Verifier: {verification.reason} (delta={delta_str})",
                node_id=ctx.node.id,
                governed_by=ctx.policy_sources,
                effective_policy=ctx.policy,
            )

            mark_desc = action.target_mark or (action.x, action.y)
            ver_desc = (
                "Verified"
                if verification.passed
                else f"Verification failed: {verification.reason}"
            )
            step_desc = (
                f"Step {steps_taken + 1}: {action.action_type.value} "
                f"(mark={mark_desc}) — {ver_desc}"
            )
            history.append(step_desc)
            steps_taken += 1

        return {
            "result": f"Reached maximum step limit ({max_steps} steps).",
            "status": "step_limit_reached",
            "steps_taken": steps_taken,
            "last_screenshot": last_screenshot_b64,
        }

    async def _decide_action(
        self,
        endpoint: Any,
        task: str,
        history: list[str],
        marked_screen: MarkedScreen,
        ctx: ExecutorContext,
    ) -> DesktopAction:
        """Call vision model to decide next structured desktop action."""
        elements_preview = []
        for elem in marked_screen.elements[:80]:
            name_str = f" - '{elem.name}'" if elem.name else ""
            elements_preview.append(
                f"Mark {elem.mark_id}: [{elem.role}]{name_str} at center {elem.center}"
            )
        elements_text = "\n".join(elements_preview)

        history_text = (
            "\n".join(history[-6:])
            if history
            else "No previous actions taken yet."
        )

        system_msg = (
            "You are an expert autonomous desktop assistant.\n"
            "You receive a screenshot with numbered mark badges and element list.\n"
            "Select a MARK NUMBER to interact with elements on screen.\n"
            "Return JSON matching:\n"
            "{\n"
            '  "action_type": "click" | "double_click" | "right_click" | '
            '"type_text" | "press_key" | "hotkey" | "scroll" | "wait" | "done",\n'
            '  "target_mark": <integer mark number>,\n'
            '  "text": <string to type>,\n'
            '  "key": <single key name>,\n'
            '  "keys": <array of key names>,\n'
            '  "thought": <brief reasoning>,\n'
            '  "expected_outcome": <expected change>\n'
            "}"
        )

        user_content = (
            f"GOAL: {task}\n\n"
            f"ACTIVE WINDOW: {marked_screen.active_window or 'Unknown'}\n"
            f"GRID FALLBACK USED: {marked_screen.grid_used}\n\n"
            f"PREVIOUS STEPS:\n{history_text}\n\n"
            f"DETECTED ELEMENTS:\n{elements_text}\n\n"
            "Choose the next action to advance toward the goal. Return ONLY JSON."
        )

        req = GenRequest(
            messages=[
                Message(role="system", content=system_msg),
                Message(role="user", content=user_content),
            ],
            temperature=0.1,
            max_tokens=600,
            response_format="json",
        )

        # Stream response
        raw_chunks = []
        async for token in endpoint.generate(req):
            raw_chunks.append(token.text)
            await ctx.emit(
                SchedulerEvent(
                    kind=EventKind.TOKEN,
                    node_id=ctx.node.id,
                    data={"token": token.text, "index": token.index},
                )
            )

        raw_response = "".join(raw_chunks).strip()
        return self._parse_action(raw_response)

    def _parse_action(self, text: str) -> DesktopAction:
        """Parse raw model output into a valid DesktopAction."""
        try:
            # Clean markdown code blocks if present
            cleaned = re.sub(r"^```json\s*", "", text, flags=re.MULTILINE)
            cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            action_type_str = (
                str(
                    data.get("action_type")
                    or data.get("action")
                    or ("click" if "target_mark" in data else "done")
                )
                .lower()
                .strip()
            )

            valid_types = {a.value for a in ActionType}
            if action_type_str not in valid_types:
                action_type_str = "click" if "mark" in data else "done"

            return DesktopAction(
                action_type=ActionType(action_type_str),
                target_mark=data.get("target_mark"),
                x=data.get("x"),
                y=data.get("y"),
                text=data.get("text"),
                key=data.get("key"),
                keys=data.get("keys"),
                scroll_dx=data.get("scroll_dx"),
                scroll_dy=data.get("scroll_dy"),
                thought=data.get("thought"),
                expected_outcome=data.get("expected_outcome"),
            )
        except Exception as exc:
            logger.debug(
                "Failed to parse JSON action (%s), attempting regex extraction",
                exc,
            )
            if "done" in text.lower():
                return DesktopAction(action_type=ActionType.DONE, thought=text)

            mark_match = re.search(r"mark\D*(\d+)", text, re.IGNORECASE)
            if mark_match:
                return DesktopAction(
                    action_type=ActionType.CLICK,
                    target_mark=int(mark_match.group(1)),
                    thought=text,
                )

            return DesktopAction(action_type=ActionType.WAIT, thought=text)

    async def _gate_action(
        self,
        action: DesktopAction,
        classification: DestructiveClassification,
        marked_screen: MarkedScreen,
        ctx: ExecutorContext,
    ) -> None:
        """
        Enforce governance policy and consult posture before executing any action.
        """
        pipeline_policy = ctx.pipeline_policy or ctx.policy

        # ── 1. Check Desktop Control Permission ──────────────────────────────
        if not pipeline_policy.allow_desktop:
            pipeline_reason = (
                f"Node '{ctx.node.id}' (computer) requires desktop control, "
                "which its access policy does not grant."
            )
            posture_outcome = await consult_posture(
                domain=GovernanceDomain.DESKTOP,
                capability="allow_desktop",
                node_id=ctx.node.id,
                pipeline_reason=pipeline_reason,
                effective_policy=ctx.policy,
                governed_by=ctx.policy_sources,
                cancel_token=ctx.cancel_token,
                notify=_approval_notifier(
                    ctx,
                    "desktop",
                    "allow_desktop",
                    pipeline_reason,
                    screenshot=marked_screen.image_base64,
                ),
            )
            if not posture_outcome.allowed:
                raise AccessDeniedError(
                    node_id=ctx.node.id,
                    capability="allow_desktop",
                    detail=posture_outcome.reason,
                )

        # ── 2. Check Allowed Applications Gating ─────────────────────────────
        active_app = marked_screen.active_window or "Desktop"
        if pipeline_policy.allowed_applications:
            allowed_set = {
                a.lower().strip() for a in pipeline_policy.allowed_applications
            }
            app_matches = any(
                allowed in active_app.lower() for allowed in allowed_set
            )
            if not app_matches:
                pipeline_reason = (
                    f"Active application '{active_app}' is not in the allowed list: "
                    f"[{', '.join(pipeline_policy.allowed_applications)}]."
                )
                posture_outcome = await consult_posture(
                    domain=GovernanceDomain.DESKTOP,
                    capability=f"app:{active_app}",
                    node_id=ctx.node.id,
                    pipeline_reason=pipeline_reason,
                    effective_policy=ctx.policy,
                    governed_by=ctx.policy_sources,
                    cancel_token=ctx.cancel_token,
                    notify=_approval_notifier(
                        ctx,
                        "desktop",
                        f"app:{active_app}",
                        pipeline_reason,
                        screenshot=marked_screen.image_base64,
                    ),
                )
                if not posture_outcome.allowed:
                    raise AccessDeniedError(
                        node_id=ctx.node.id,
                        capability=f"app:{active_app}",
                        detail=posture_outcome.reason,
                    )

        # ── 3. Check Destructive Action Gating ────────────────────────────────
        if classification.is_destructive and not pipeline_policy.allow_destructive:
            pipeline_reason = (
                f"Destructive action '{action.action_type.value}' withheld: "
                f"{classification.reason}"
            )
            posture_outcome = await consult_posture(
                domain=GovernanceDomain.DESKTOP,
                capability=f"destructive:{action.action_type.value}",
                node_id=ctx.node.id,
                pipeline_reason=pipeline_reason,
                effective_policy=ctx.policy,
                governed_by=ctx.policy_sources,
                cancel_token=ctx.cancel_token,
                notify=_approval_notifier(
                    ctx,
                    "desktop",
                    f"destructive:{action.action_type.value}",
                    pipeline_reason,
                    screenshot=marked_screen.image_base64,
                ),
            )
            if not posture_outcome.allowed:
                raise AccessDeniedError(
                    node_id=ctx.node.id,
                    capability="allow_destructive",
                    detail=posture_outcome.reason,
                )

        # ── 4. Record ALLOWED Decision ────────────────────────────────────────
        await record_decision(
            domain=GovernanceDomain.DESKTOP,
            outcome=DecisionOutcome.ALLOWED,
            origin=DecisionOrigin.PIPELINE_POLICY,
            capability=f"desktop:{action.action_type.value}",
            reason=f"Action permitted ({classification.reason})",
            node_id=ctx.node.id,
            governed_by=ctx.policy_sources,
            effective_policy=ctx.policy,
        )
