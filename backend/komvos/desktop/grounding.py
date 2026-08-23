"""
backend/komvos/desktop/grounding.py

Set-of-Marks grounding for desktop vision models.

Models frequently hallucinate pixel coordinates when prompted with raw screenshots.
This module extracts interactive UI elements from the accessibility tree, overlays
numbered mark badges onto the screenshot, and maps each mark number to its exact
pixel coordinates (x, y).

When no elements can be detected (e.g. custom canvases or games), it generates
a numbered coarse grid fallback across the entire screen so the model can always
reference an unambiguous mark ID.
"""

from __future__ import annotations

import base64
import importlib
import io
import logging
from typing import Any

from komvos.desktop.models import MarkedScreen, ScreenElement

logger = logging.getLogger(__name__)

# Badge styling constants
BADGE_BG_COLOR = (200, 217, 74)  # Accent lime #C8D94A
BADGE_TEXT_COLOR = (43, 46, 38)  # #2B2E26
BADGE_BORDER_COLOR = (184, 200, 58)
GRID_LINE_COLOR = (200, 217, 74, 120)


def extract_interactive_elements(
    a11y_tree: dict[str, Any] | list[Any] | None,
    screen_width: int,
    screen_height: int,
) -> list[ScreenElement]:
    """
    Extract interactive elements (buttons, inputs, links, list items, etc.)
    with bounding boxes from the accessibility tree.
    """
    elements: list[ScreenElement] = []
    if not a11y_tree:
        return elements

    mark_counter = 1
    seen_boxes: set[tuple[int, int, int, int]] = set()

    def _parse_bbox(node: dict[str, Any]) -> tuple[int, int, int, int] | None:
        rect = node.get("rect") or node.get("bounds") or node.get("bbox")
        if isinstance(rect, list | tuple) and len(rect) == 4:
            return int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])

        pos = node.get("position")
        size = node.get("size")
        if isinstance(pos, dict) and isinstance(size, dict):
            x = int(pos.get("x", 0) or 0)
            y = int(pos.get("y", 0) or 0)
            w = int(size.get("width", 0) or size.get("w", 0) or 0)
            h = int(size.get("height", 0) or size.get("h", 0) or 0)
            return x, y, w, h

        if (
            "x" in node
            and "y" in node
            and ("width" in node or "w" in node)
            and ("height" in node or "h" in node)
        ):
            x = int(node["x"] or 0)
            y = int(node["y"] or 0)
            w = int(node.get("width") or node.get("w") or 0)
            h = int(node.get("height") or node.get("h") or 0)
            return x, y, w, h

        return None

    def _walk_node(node: dict[str, Any]) -> None:
        nonlocal mark_counter
        if not isinstance(node, dict):
            return

        bbox = _parse_bbox(node)
        role = str(
            node.get("role")
            or node.get("type")
            or node.get("class")
            or "element"
        )
        name = str(
            node.get("name")
            or node.get("title")
            or node.get("label")
            or node.get("text")
            or ""
        )

        if bbox is not None and not is_junk_element(role, name):
            x, y, w, h = bbox
            if 0 <= x < screen_width and 0 <= y < screen_height and w >= 8 and h >= 8:
                box_key = (x, y, w, h)
                if box_key not in seen_boxes:
                    seen_boxes.add(box_key)
                    cx = x + w // 2
                    cy = y + h // 2
                    elements.append(
                        ScreenElement(
                            mark_id=mark_counter,
                            role=role,
                            name=name,
                            bbox=(x, y, w, h),
                            center=(cx, cy),
                        )
                    )
                    mark_counter += 1

        children = (
            node.get("children")
            or node.get("nodes")
            or node.get("elements")
            or []
        )
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    _walk_node(child)

    if isinstance(a11y_tree, list):
        for item in a11y_tree:
            if isinstance(item, dict):
                _walk_node(item)
    elif isinstance(a11y_tree, dict):
        _walk_node(a11y_tree)

    return elements


def generate_grid_elements(
    screen_width: int,
    screen_height: int,
    cols: int = 10,
    rows: int = 8,
) -> list[ScreenElement]:
    """Generate coarse fallback grid cells across the screen."""
    elements: list[ScreenElement] = []
    cell_w = screen_width // cols
    cell_h = screen_height // rows

    mark_id = 1
    for r in range(rows):
        for c in range(cols):
            x = c * cell_w
            y = r * cell_h
            cx = x + cell_w // 2
            cy = y + cell_h // 2
            elements.append(
                ScreenElement(
                    mark_id=mark_id,
                    role="grid_cell",
                    name=f"Grid Cell {mark_id} (R{r+1},C{c+1})",
                    bbox=(x, y, cell_w, cell_h),
                    center=(cx, cy),
                )
            )
            mark_id += 1

    return elements


#: Plausible range for a display-scaling factor. Outside this, the derived
#: ratio is more likely a tree that does not span the screen than real DPI.
_MIN_INPUT_SCALE = 1.0
_MAX_INPUT_SCALE = 3.0

#: How closely the x and y ratios must agree to be believed as one DPI factor.
_SCALE_AXIS_TOLERANCE = 0.05


#: Window classes and titles Windows keeps around that are not real UI. They
#: carry a rectangle and so become clickable marks, and a vision model will
#: happily spend its whole step budget clicking them — observed in the wild as
#: a run looping on "Non Client Input Sink Window" until it timed out.
_JUNK_ROLE_FRAGMENTS = (
    "non client input sink",
    "msctfime",
    "default ime",
    "ime",
    "tooltips_class32",
    "gdi+ window",
    "chrome legacy window",
    "olddebug",
    "workerw",
    "progman",
)


def is_junk_element(role: str, name: str) -> bool:
    """True for phantom OS windows that are never a useful click target."""
    haystack = f"{role} {name}".lower()
    return any(fragment in haystack for fragment in _JUNK_ROLE_FRAGMENTS)


def derive_input_scale(
    elements: list[ScreenElement], image_width: int, image_height: int
) -> tuple[float, float]:
    """
    Factor converting accessibility-tree coordinates to screenshot pixels.

    Windows reports accessibility geometry in LOGICAL units while screenshots
    and synthetic input use PHYSICAL pixels. At 125% scaling a 1920x1200 screen
    yields a tree spanning only 1536x960, so an unscaled mark badge is painted
    a quarter of the way up-and-left of the widget it labels, and the click
    derived from it misses by the same margin.

    The factor is derived from how far the tree actually extends rather than
    from any OS call, so it needs no platform branch. It is only trusted when
    both axes agree and the result looks like real display scaling; anything
    else returns (1.0, 1.0), leaving behaviour exactly as before.
    """
    if not elements or image_width <= 0 or image_height <= 0:
        return (1.0, 1.0)

    max_x = max(e.bbox[0] + e.bbox[2] for e in elements)
    max_y = max(e.bbox[1] + e.bbox[3] for e in elements)
    if max_x <= 0 or max_y <= 0:
        return (1.0, 1.0)

    scale_x = image_width / max_x
    scale_y = image_height / max_y

    for value in (scale_x, scale_y):
        if not _MIN_INPUT_SCALE <= value <= _MAX_INPUT_SCALE:
            return (1.0, 1.0)
    if abs(scale_x - scale_y) > _SCALE_AXIS_TOLERANCE * max(scale_x, scale_y):
        # Axes disagree — the tree probably does not span the screen, so a
        # derived factor would be guesswork. Leave coordinates untouched.
        return (1.0, 1.0)

    return (scale_x, scale_y)


def scale_elements(
    elements: list[ScreenElement], scale: tuple[float, float]
) -> list[ScreenElement]:
    """Return `elements` with bbox and center mapped into screenshot pixels."""
    sx, sy = scale
    if sx == 1.0 and sy == 1.0:
        return elements
    scaled: list[ScreenElement] = []
    for e in elements:
        x, y, w, h = e.bbox
        scaled.append(
            e.model_copy(
                update={
                    "bbox": (
                        round(x * sx),
                        round(y * sy),
                        round(w * sx),
                        round(h * sy),
                    ),
                    "center": (round(e.center[0] * sx), round(e.center[1] * sy)),
                }
            )
        )
    return scaled


def annotate_screenshot(
    image_bytes: bytes,
    a11y_tree: dict[str, Any] | list[Any] | None = None,
    active_window: str | None = None,
) -> MarkedScreen:
    """
    Annotate a screenshot image with numbered mark badges or a coarse grid fallback.
    Returns the MarkedScreen with base64 encoded image and element registry.
    """
    width = 1280
    height = 800

    # Try using PIL if available in the environment
    try:
        pil_image = importlib.import_module("PIL.Image")
        pil_draw = importlib.import_module("PIL.ImageDraw")
        pil_font = importlib.import_module("PIL.ImageFont")
        if image_bytes:
            try:
                img = pil_image.open(io.BytesIO(image_bytes)).convert("RGBA")
                width, height = img.size
            except Exception:
                img = pil_image.new("RGBA", (width, height), (30, 30, 30, 255))
        else:
            img = pil_image.new("RGBA", (width, height), (30, 30, 30, 255))

        elements = extract_interactive_elements(a11y_tree, width, height)
        grid_used = False

        # Map accessibility coordinates into screenshot pixels BEFORE badges
        # are drawn, so the marks the model sees sit on the real widgets and
        # elem.center is a usable click target. Grid elements are generated in
        # image space already and need no scaling.
        elements = scale_elements(
            elements, derive_input_scale(elements, width, height)
        )

        if not elements:
            elements = generate_grid_elements(width, height)
            grid_used = True

        overlay = pil_image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = pil_draw.Draw(overlay)
        font = pil_font.load_default()

        if grid_used:
            for elem in elements:
                x, y, w, h = elem.bbox
                draw.rectangle(
                    [x, y, x + w, y + h],
                    outline=(200, 217, 74, 90),
                    width=1,
                )

        for elem in elements:
            cx, cy = elem.center
            label = str(elem.mark_id)
            bbox = draw.textbbox((cx, cy), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            pad_x = 4
            pad_y = 2
            rx0 = max(0, cx - tw // 2 - pad_x)
            ry0 = max(0, cy - th // 2 - pad_y)
            rx1 = min(width, cx + tw // 2 + pad_x)
            ry1 = min(height, cy + th // 2 + pad_y)

            draw.rounded_rectangle(
                [rx0, ry0, rx1, ry1],
                radius=4,
                fill=BADGE_BG_COLOR,
                outline=BADGE_BORDER_COLOR,
                width=1,
            )
            draw.text(
                (rx0 + pad_x, ry0 + pad_y - 1),
                label,
                fill=BADGE_TEXT_COLOR,
                font=font,
            )

        annotated_img = pil_image.alpha_composite(img, overlay).convert("RGB")
        max_width = 1024
        if width > max_width:
            scale = max_width / width
            new_height = max(1, int(height * scale))
            export_img = annotated_img.resize(
                (max_width, new_height), pil_image.Resampling.LANCZOS
            )
        else:
            export_img = annotated_img

        buf = io.BytesIO()
        export_img.save(buf, format="JPEG", quality=75, optimize=True)
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")

        return MarkedScreen(
            elements=elements,
            grid_used=grid_used,
            screen_width=width,
            screen_height=height,
            active_window=active_window,
            image_base64=b64_str,
        )
    except Exception as exc:
        logger.debug("Annotating with PIL failed or PIL unavailable: %s", exc)

    # Pure Python fallback without PIL
    elements = extract_interactive_elements(a11y_tree, width, height)
    elements = scale_elements(elements, derive_input_scale(elements, width, height))
    grid_used = False
    if not elements:
        elements = generate_grid_elements(width, height)
        grid_used = True

    b64_str = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else ""
    return MarkedScreen(
        elements=elements,
        grid_used=grid_used,
        screen_width=width,
        screen_height=height,
        active_window=active_window,
        image_base64=b64_str,
    )
