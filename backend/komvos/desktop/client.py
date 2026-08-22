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


class DesktopClient:
    """
    Client for the local computer-server action layer.
    Guaranteed loopback-only connection.
    """

    def __init__(self, base_url: str | None = None) -> None:
        url = base_url or get_computer_server_url()
        self._base_url = url.rstrip("/")
        self._validate_loopback(self._base_url)

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
            res = await self._send_cmd(cmd, {"x": x, "y": y})
            return bool(res.get("success", True))
        except Exception as exc:
            logger.debug(
                "Server click failed (%s), attempting in-process fallback", exc
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
            res = await self._send_cmd("type_text", {"text": text})
            return bool(res.get("success", True))
        except Exception as exc:
            logger.debug(
                "Server typing failed (%s), attempting in-process fallback", exc
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
            res = await self._send_cmd("press_key", {"key": key})
            return bool(res.get("success", True))
        except Exception as exc:
            logger.debug(
                "Server key press failed (%s), attempting in-process fallback", exc
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
            res = await self._send_cmd("hotkey", {"keys": keys})
            return bool(res.get("success", True))
        except Exception as exc:
            logger.debug(
                "Server hotkey failed (%s), attempting in-process fallback", exc
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
            res = await self._send_cmd(
                "scroll",
                {"x": x, "y": y, "scroll_x": scroll_x, "scroll_y": scroll_y},
            )
            return bool(res.get("success", True))
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

    async def execute_action(self, action: DesktopAction) -> bool:
        """Execute a validated and governed DesktopAction."""
        if action.action_type in (
            ActionType.WAIT,
            ActionType.DONE,
            ActionType.SCREENSHOT,
        ):
            return True

        if action.action_type == ActionType.CLICK:
            x = action.x or 0
            y = action.y or 0
            return await self.click(x, y, button="left", double=False)

        if action.action_type == ActionType.DOUBLE_CLICK:
            x = action.x or 0
            y = action.y or 0
            return await self.click(x, y, button="left", double=True)

        if action.action_type == ActionType.RIGHT_CLICK:
            x = action.x or 0
            y = action.y or 0
            return await self.click(x, y, button="right", double=False)

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
