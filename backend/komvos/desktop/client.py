"""
backend/komvos/desktop/client.py

Thin action layer client for local desktop automation.

THIN MODE ONLY: Komvos owns the entire agent loop (observe -> decide -> GATE -> act).
This client acts purely as the mechanical execution layer to perform screen capture,
mouse clicks, text input, key presses, and accessibility tree inspection.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from komvos.desktop.detection import get_computer_server_url
from komvos.desktop.models import ActionType, DesktopAction

logger = logging.getLogger(__name__)


def _get_pyautogui() -> Any:
    """Safely obtain pyautogui if available in the environment."""
    try:
        return importlib.import_module("pyautogui")
    except Exception:
        return None


def _get_imagegrab() -> Any:
    """Safely obtain PIL.ImageGrab if available in the environment."""
    try:
        return importlib.import_module("PIL.ImageGrab")
    except Exception:
        return None


class _ServerCannotActuate(RuntimeError):
    """Raised internally to divert an action to in-process input."""


class DesktopClient:
    """
    Client for the local computer-server action layer.
    Guaranteed loopback-only connection.
    """

    def __init__(self, base_url: str | None = None) -> None:
        url = base_url or get_computer_server_url()
        self._base_url = url.rstrip("/")
        self._validate_loopback(self._base_url)
        #: None until probed; see _server_can_actuate.
        self._server_actuates: bool | None = None

    @staticmethod
    def _validate_loopback(url: str) -> None:
        """Enforce strict loopback security: remote destinations are forbidden."""
        raw = url if "//" in url else f"//{url}"
        hostname = urlsplit(raw).hostname
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(
                f"Security violation: Desktop server URL '{url}' must be loopback."
            )

    async def _send_cmd(
        self, command: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a command to the computer-server /cmd endpoint."""
        payload = {"command": command, "params": params or {}}
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            resp = await client.post(f"{self._base_url}/cmd", json=payload)
            resp.raise_for_status()
            text = resp.text.strip()
            if text.startswith("data:"):
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("data:"):
                        raw_json = stripped[5:].strip()
                        if raw_json:
                            return json.loads(raw_json)  # type: ignore[no-any-return]
            return resp.json()  # type: ignore[no-any-return]

    async def screenshot(self) -> bytes:
        """Capture screen state and return raw PNG image bytes."""
        try:
            res = await self._send_cmd("screenshot")
            if res.get("success") and res.get("image_data"):
                return base64.b64decode(res["image_data"])
        except Exception as exc:
            logger.debug("Failed to capture screenshot via server: %s", exc)

        # In-process screen capture with Windows input desktop attachment
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
                user32.CloseDesktop(hdesk)
        except Exception as exc:
            logger.debug("Desktop switch error: %s", exc)

        imagegrab = _get_imagegrab()
        if imagegrab:
            try:
                from io import BytesIO

                img = imagegrab.grab()
                buf = BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
            except Exception as exc:
                logger.debug(
                    "Screen capture in-process fallback failed: %s", exc
                )

        return b""

    @staticmethod
    def _get_windows_a11y_tree() -> list[dict[str, Any]]:
        """
        Direct in-process Windows UI element tree extraction
        via EnumDesktopWindows.
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            DESKENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            hdesk = user32.OpenInputDesktop(0, False, 0x0100)
            if not hdesk:
                return []

            elements: list[dict[str, Any]] = []

            def get_node_info(hwnd: int) -> tuple[str, str, int, int, int, int]:
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                return (
                    buf.value.strip(),
                    cls_buf.value.strip(),
                    rect.left,
                    rect.top,
                    w,
                    h,
                )

            def desk_enum_cb(hwnd: int, lparam: int) -> bool:
                if user32.IsWindowVisible(hwnd):
                    title, role, x, y, w, h = get_node_info(hwnd)
                    if w >= 16 and h >= 16 and x > -1000 and y > -1000:
                        node: dict[str, Any] = {
                            "title": title,
                            "role": role or "Window",
                            "position": {"x": x, "y": y},
                            "size": {"width": w, "height": h},
                            "rect": [x, y, w, h],
                            "children": [],
                        }

                        def child_cb(chwnd: int, _: int) -> bool:
                            if user32.IsWindowVisible(chwnd):
                                (
                                    ctitle,
                                    crole,
                                    cx,
                                    cy,
                                    cw,
                                    ch,
                                ) = get_node_info(chwnd)
                                if (
                                    cw >= 8
                                    and ch >= 8
                                    and cx > -1000
                                    and cy > -1000
                                ):
                                    node["children"].append(
                                        {
                                            "title": ctitle,
                                            "role": crole or "Control",
                                            "position": {"x": cx, "y": cy},
                                            "size": {"width": cw, "height": ch},
                                            "rect": [cx, cy, cw, ch],
                                        }
                                    )
                            return True

                        user32.EnumChildWindows(
                            hwnd, WNDENUMPROC(child_cb), 0
                        )
                        elements.append(node)
                return True

            user32.EnumDesktopWindows(hdesk, DESKENUMPROC(desk_enum_cb), 0)
            user32.CloseDesktop(hdesk)
            return elements
        except Exception as exc:
            logger.debug("In-process Windows a11y tree failed: %s", exc)
            return []

    async def get_accessibility_tree(self) -> dict[str, Any] | list[Any] | None:
        """Retrieve the current accessibility tree for interactive elements."""
        try:
            res = await self._send_cmd("get_accessibility_tree")
            if res.get("success"):
                tree = res.get("tree") or res.get("elements")
                if tree:
                    return tree  # type: ignore[no-any-return]
        except Exception as exc:
            logger.debug("Accessibility tree retrieval skipped: %s", exc)

        # In-process Windows UI element tree fallback
        tree_fallback = self._get_windows_a11y_tree()
        return tree_fallback if tree_fallback else None

    async def get_active_window(self) -> str | None:
        """Get the title or process name of the active foreground window."""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "Desktop"
        except Exception:
            return None

    async def click(
        self, x: int, y: int, button: str = "left", double: bool = False
    ) -> bool:
        """Click at coordinates (x, y)."""
        cmd = (
            "double_click"
            if double
            else ("right_click" if button == "right" else "left_click")
        )
        try:
            if not await self._server_can_actuate():
                raise _ServerCannotActuate
            res = await self._send_cmd(cmd, {"x": x, "y": y})
            return bool(res.get("success", False))
        except Exception as exc:
            logger.debug(
                "Server click unavailable (%s), using in-process input", exc
            )
            ag = _get_pyautogui()
            if ag:
                try:
                    if double:
                        ag.doubleClick(x, y)
                    elif button == "right":
                        ag.rightClick(x, y)
                    else:
                        ag.click(x, y)
                    return True
                except Exception as e:
                    logger.debug("In-process click fallback unavailable: %s", e)
            return False

    async def type_text(self, text: str) -> bool:
        """Type text into the focused element."""
        try:
            if not await self._server_can_actuate():
                raise _ServerCannotActuate
            res = await self._send_cmd("type_text", {"text": text})
            return bool(res.get("success", False))
        except Exception as exc:
            logger.debug(
                "Server typing unavailable (%s), using in-process input", exc
            )
            ag = _get_pyautogui()
            if ag:
                try:
                    ag.write(text, interval=0.01)
                    return True
                except Exception as e:
                    logger.debug("In-process typing fallback unavailable: %s", e)
            return False

    async def press_key(self, key: str) -> bool:
        """Press a single key (e.g. 'enter', 'tab', 'escape')."""
        try:
            if not await self._server_can_actuate():
                raise _ServerCannotActuate
            res = await self._send_cmd("press_key", {"key": key})
            return bool(res.get("success", False))
        except Exception as exc:
            logger.debug(
                "Server key press unavailable (%s), using in-process input", exc
            )
            ag = _get_pyautogui()
            if ag:
                try:
                    ag.press(key)
                    return True
                except Exception as e:
                    logger.debug("In-process key press fallback unavailable: %s", e)
            return False

    async def hotkey(self, keys: list[str]) -> bool:
        """Press a keyboard combination (e.g. ['ctrl', 'c'])."""
        try:
            if not await self._server_can_actuate():
                raise _ServerCannotActuate
            res = await self._send_cmd("hotkey", {"keys": keys})
            return bool(res.get("success", False))
        except Exception as exc:
            logger.debug(
                "Server hotkey unavailable (%s), using in-process input", exc
            )
            ag = _get_pyautogui()
            if ag:
                try:
                    ag.hotkey(*keys)
                    return True
                except Exception as e:
                    logger.debug("In-process hotkey fallback unavailable: %s", e)
            return False

    async def scroll(
        self, x: int, y: int, scroll_x: int = 0, scroll_y: int = -5
    ) -> bool:
        """Scroll at coordinates (x, y)."""
        try:
            # The server handler is scroll(x, y) where x/y are scroll AMOUNTS,
            # not a screen position. Sending coordinates plus extra scroll_*
            # keys raised a TypeError on dispatch, so scrolling never worked.
            if not await self._server_can_actuate():
                raise _ServerCannotActuate
            res = await self._send_cmd(
                "scroll",
                {"x": scroll_x, "y": scroll_y},
            )
            return bool(res.get("success", False))
        except Exception as exc:
            logger.debug(
                "Server scroll failed (%s), attempting in-process fallback", exc
            )
            ag = _get_pyautogui()
            if ag:
                try:
                    ag.scroll(scroll_y, x=x, y=y)
                    return True
                except Exception as e:
                    logger.debug("In-process scroll fallback unavailable: %s", e)
            return False

    async def _server_can_actuate(self) -> bool:
        """
        Whether the computer-server can actually drive this desktop.

        On Windows the server frequently runs where it cannot reach the
        interactive session: `move_cursor` returns {"success": true} and does
        nothing, and `get_cursor_position` reports (0, 0) forever. Because the
        in-process fallbacks in this class only fire on an *exception*, that
        false success meant every action was silently dropped — the agent
        looked stuck while nothing was ever delivered.

        Detected without moving anything: compare the server's idea of the
        cursor position against this process's. A server that cannot see the
        real cursor cannot move it either. The answer is cached per process.
        """
        if self._server_actuates is not None:
            return self._server_actuates

        verdict = False
        ag = _get_pyautogui()
        if ag is not None:
            try:
                # Active probe: ask the server to move the pointer a few pixels
                # and check from THIS process whether it actually moved. A
                # passive position comparison is not enough — a server that
                # always answers (0, 0) looks correct whenever the pointer
                # genuinely rests in that corner.
                origin = ag.position()
                ox, oy = int(origin[0]), int(origin[1])
                sw, sh = ag.size()
                target_x = max(10, min(int(sw) - 11, ox + 7))
                target_y = max(10, min(int(sh) - 11, oy + 7))
                if (target_x, target_y) == (ox, oy):
                    target_x += 7

                await self._send_cmd(
                    "move_cursor", {"x": target_x, "y": target_y}
                )
                moved = ag.position()
                verdict = (
                    abs(int(moved[0]) - target_x) <= 2
                    and abs(int(moved[1]) - target_y) <= 2
                )

                # Put the pointer back wherever it started, either way.
                failsafe = ag.FAILSAFE
                try:
                    ag.FAILSAFE = False
                    ag.moveTo(ox, oy)
                finally:
                    ag.FAILSAFE = failsafe

                if not verdict:
                    logger.warning(
                        "Computer-server accepted move_cursor but the pointer "
                        "did not move; it cannot drive this desktop. Using "
                        "in-process input instead."
                    )
            except Exception as exc:
                logger.debug("Server actuation probe failed: %s", exc)
                verdict = False

        self._server_actuates = verdict
        return verdict

    async def _ensure_cursor_off_failsafe_corner(self) -> None:
        """
        Move the pointer off a screen corner before actuating.

        pyautogui keeps a fail-safe: with the cursor in any screen corner every
        call raises FailSafeException, so clicks and keystrokes alike silently
        stop working. A mis-resolved click at (0, 0) parks the cursor there and
        poisons every later action in the run.

        The fail-safe stays ENABLED — slamming the mouse into a corner mid-run
        must still abort. This only steps out of the corner the agent is about
        to act from, and never fights a human who is actively holding it there.
        """
        try:
            use_server = await self._server_can_actuate()
            ag = _get_pyautogui()

            if use_server:
                pos = await self._send_cmd("get_cursor_position")
                point = pos.get("position") or {}
                x = int(point.get("x", -1))
                y = int(point.get("y", -1))
                size = await self._send_cmd("get_screen_size")
                dims = size.get("size") or {}
                w = int(dims.get("width", 0))
                h = int(dims.get("height", 0))
            elif ag is not None:
                # The server's cursor readings are not of this desktop; only
                # this process sees the real pointer.
                px, py = ag.position()
                x, y = int(px), int(py)
                sw, sh = ag.size()
                w, h = int(sw), int(sh)
            else:
                return

            if x < 0 or y < 0 or w <= 0 or h <= 0:
                return

            margin = 2
            nudge = 5
            in_corner = (x <= margin or x >= w - 1 - margin) and (
                y <= margin or y >= h - 1 - margin
            )
            if not in_corner:
                return

            new_x = nudge if x <= margin else w - 1 - nudge
            new_y = nudge if y <= margin else h - 1 - nudge
            logger.info(
                "Cursor at fail-safe corner (%d, %d); moving to (%d, %d).",
                x,
                y,
                new_x,
                new_y,
            )
            if use_server:
                await self._send_cmd("move_cursor", {"x": new_x, "y": new_y})
            elif ag is not None:
                ag.moveTo(new_x, new_y)
        except Exception as exc:
            logger.debug("Could not check/clear fail-safe corner: %s", exc)

    async def execute_action(self, action: DesktopAction) -> bool:
        """Execute a validated and governed DesktopAction."""
        if action.action_type in (
            ActionType.WAIT,
            ActionType.DONE,
            ActionType.SCREENSHOT,
        ):
            return True

        await self._ensure_cursor_off_failsafe_corner()

        if action.action_type in (
            ActionType.CLICK,
            ActionType.DOUBLE_CLICK,
            ActionType.RIGHT_CLICK,
        ):
            # No coordinates means the mark never resolved. Defaulting to
            # (0, 0) clicked the screen corner, which both hit the wrong thing
            # and armed pyautogui's fail-safe for every action after it.
            if action.x is None or action.y is None:
                logger.warning(
                    "Refusing %s with no resolved coordinates (target_mark=%s).",
                    action.action_type.value,
                    action.target_mark,
                )
                return False
            return await self.click(
                action.x,
                action.y,
                button="right"
                if action.action_type == ActionType.RIGHT_CLICK
                else "left",
                double=action.action_type == ActionType.DOUBLE_CLICK,
            )

        if action.action_type == ActionType.TYPE_TEXT:
            return await self.type_text(action.text or "")

        if action.action_type == ActionType.PRESS_KEY:
            return await self.press_key(action.key or "enter")

        if action.action_type == ActionType.HOTKEY:
            return await self.hotkey(action.keys or [])

        if action.action_type == ActionType.SCROLL:
            x = action.x or 0
            y = action.y or 0
            dy = action.scroll_dy or -5
            dx = action.scroll_dx or 0
            return await self.scroll(x, y, scroll_x=dx, scroll_y=dy)

        return False
