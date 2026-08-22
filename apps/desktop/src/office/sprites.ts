/**
 * office/sprites.ts
 *
 * Pixel-art renderer for the Virtual Office View using authentic assets from the
 * CC0 "Ninja Adventure" asset pack (Palette.png, tilesets, characters, and FX).
 *
 * All rendering is deterministic: (state, tick, images) fully determines output.
 */

import type { OfficeImages, StatusEmote } from './assets';
import { DESK_H, DESK_W, type Doorway, type RoomProp, type WallSegment } from './layout';

/** Ninja Adventure master-palette colors. */
export const PAL = {
  outline: '#3b3643',
  woodLight: '#eecf9b',
  woodMid: '#c8966b',
  woodDark: '#965340',
  wallFace: '#a3754e',
  wallTop: '#eecf9b',
  wallShadow: 'rgba(20, 27, 27, 0.40)',
  screenOff: '#4a5270',
  screenGlow: '#71ddee',
  ok: '#56864c',
  error: '#d14b34',
  gold: '#f1c471',
  white: '#ffffff',
  serverDark: '#3b3643',
  water: '#71ddee',
} as const;

export type NodeRunStatus = 'idle' | 'running' | 'done' | 'error';

export interface StatusVisual {
  emote: StatusEmote | null;
  celebrateMs: number;
}

export const STATUS_VISUALS: Record<NodeRunStatus, StatusVisual> = {
  idle: { emote: null, celebrateMs: 0 },
  running: { emote: 'thinking', celebrateMs: 0 },
  done: { emote: 'happy', celebrateMs: 2000 },
  error: { emote: 'alert', celebrateMs: 0 },
};

export type ScreenState = 'off' | 'working' | 'ok' | 'fail';

export function screenForStatus(status: NodeRunStatus): ScreenState {
  switch (status) {
    case 'running': return 'working';
    case 'done': return 'ok';
    case 'error': return 'fail';
    default: return 'off';
  }
}

/** Desk-mat accents matching node types. */
export const OFFICE_TYPE_COLORS: Record<string, string> = {
  input: '#3a7d44',
  model: '#2b4baa',
  output: '#7d3a7c',
  loop: '#a86a1a',
  judge: '#b83232',
  router: '#1a7d9d',
  transform: '#4a9d1a',
  compare: '#6b3ab8',
  access: '#5a6988',
};
export const OFFICE_FALLBACK_COLOR = '#5a5e54';

type Ctx = CanvasRenderingContext2D;

export function px(ctx: Ctx, color: string, x: number, y: number, w: number, h: number): void {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

// ─── Character Animator ───────────────────────────────────────────────────────

/**
 * Draws a 16×16 character from a full 64×112 sprite sheet:
 * Row 0: Idle Down (col 0), Idle Up (col 1), Idle Left (col 2), Idle Right (col 3)
 * Row 5: Action / Typing (cols 0..3)
 * Row 6: Jump / Celebrating (cols 0..3)
 */
export function drawAgent(
  ctx: Ctx,
  x: number,
  y: number,
  status: NodeRunStatus,
  tick: number,
  sheet?: HTMLImageElement | null,
): void {
  let row = 0;
  let col = 0;
  let offsetX = 0;
  let offsetY = 0;

  switch (status) {
    case 'running': {
      // 4-frame fast action/typing cycle
      row = 5;
      col = Math.floor(tick / 4) % 4;
      break;
    }
    case 'done': {
      // 4-frame celebratory jump cycle
      row = 6;
      col = Math.floor(tick / 5) % 4;
      offsetY = col === 1 || col === 2 ? -2 : 0;
      break;
    }
    case 'error': {
      // Shaking distress
      row = 0;
      col = 0;
      offsetX = Math.floor(tick / 2) % 2 === 0 ? 1 : -1;
      break;
    }
    case 'idle':
    default: {
      // Idle facing down with subtle breathing
      row = 0;
      col = 0;
      offsetY = Math.floor(tick / 30) % 2 === 0 ? 0 : -1;
      break;
    }
  }

  if (sheet) {
    // If the sprite sheet is at least 64x112, use full animation rows.
    // If it's a 1-row sheet (64x16), clamp to row 0.
    const actualRow = (sheet.height >= 112) ? row : 0;
    const actualCol = (sheet.height >= 112) ? col : (status === 'running' ? Math.floor(tick / 6) % 4 : 0);
    ctx.drawImage(
      sheet,
      actualCol * 16,
      actualRow * 16,
      16,
      16,
      x + offsetX,
      y + offsetY,
      16,
      16,
    );
  } else {
    // Graceful silhouette fallback for jsdom
    px(ctx, PAL.outline, x + offsetX, y + offsetY, 16, 16);
    px(ctx, PAL.wallFace, x + offsetX + 1, y + offsetY + 3, 14, 10);
  }
}

// ─── Workstation & Furniture ──────────────────────────────────────────────────

/**
 * Draws a complete workstation: seated agent, wooden desk, colored mat,
 * interactive CRT terminal, and selection highlight.
 */
export function drawDesk(
  ctx: Ctx,
  x: number,
  y: number,
  matColor: string,
  screen: ScreenState,
  status: NodeRunStatus,
  tick: number,
  hovered: boolean,
  selected: boolean,
  agentSheet?: HTMLImageElement | null,
): void {
  // Chair back peeking behind agent
  px(ctx, PAL.outline, x + 5, y + 2, 20, 5);
  px(ctx, PAL.woodDark, x + 6, y + 3, 18, 3);

  // Agent character
  drawAgent(ctx, x + 7, y + 4, status, tick, agentSheet);

  // Desk surface: wooden finish with highlight & shadow bevels
  px(ctx, PAL.outline, x + 2, y + 22, 48, 15);
  px(ctx, PAL.woodMid, x + 3, y + 23, 46, 9);
  px(ctx, PAL.woodLight, x + 3, y + 23, 46, 2);
  px(ctx, PAL.woodDark, x + 3, y + 32, 46, 4);

  // Type accent desk mat + paper/pen
  px(ctx, matColor, x + 6, y + 29, 12, 4);
  px(ctx, PAL.white, x + 20, y + 27, 6, 6); // notebook
  px(ctx, PAL.outline, x + 21, y + 28, 4, 1);
  px(ctx, PAL.outline, x + 21, y + 30, 4, 1);
  px(ctx, PAL.gold, x + 27, y + 28, 1, 4); // pencil

  // Monitor terminal
  drawMonitor(ctx, x + 30, y + 10, screen, tick);

  // Selection / hover highlight ring
  if (selected || hovered) {
    const ringColor = selected ? PAL.gold : PAL.screenGlow;
    ctx.strokeStyle = ringColor;
    ctx.lineWidth = 1;
    ctx.strokeRect(x - 2.5, y - 2.5, 57, 53);
  }
}

/** Desk monitor with stateful CRT animation. */
export function drawMonitor(ctx: Ctx, x: number, y: number, state: ScreenState, tick: number): void {
  // Bezel casing
  px(ctx, PAL.outline, x, y, 18, 15);
  px(ctx, PAL.woodDark, x + 1, y + 1, 16, 12);
  const sx = x + 2;
  const sy = y + 2;
  const sw = 14;
  const sh = 10;

  switch (state) {
    case 'off':
      px(ctx, PAL.screenOff, sx, sy, sw, sh);
      // Blinking standby LED
      if (Math.floor(tick / 20) % 2 === 0) {
        px(ctx, PAL.gold, sx + sw - 3, sy + sh - 3, 2, 2);
      }
      break;
    case 'working': {
      // Scrolling cybernetic code lines
      px(ctx, PAL.outline, sx, sy, sw, sh);
      for (let i = 0; i < 3; i++) {
        const len = 4 + ((Math.floor(tick / 5) + i * 3) % 9);
        const lineY = sy + 2 + i * 3;
        px(ctx, i === Math.floor(tick / 4) % 3 ? PAL.white : PAL.screenGlow, sx + 1, lineY, len, 1);
      }
      break;
    }
    case 'ok': {
      // Green victory screen with checkmark
      px(ctx, PAL.ok, sx, sy, sw, sh);
      px(ctx, PAL.white, sx + 3, sy + 4, 2, 2);
      px(ctx, PAL.white, sx + 5, sy + 6, 2, 2);
      px(ctx, PAL.white, sx + 7, sy + 7, 1, 1);
      px(ctx, PAL.white, sx + 9, sy + 3, 2, 3);
      break;
    }
    case 'fail': {
      // Flashing red warning terminal with X
      const flash = Math.floor(tick / 10) % 2 === 0;
      px(ctx, flash ? PAL.error : PAL.outline, sx, sy, sw, sh);
      px(ctx, PAL.white, sx + 4, sy + 3, 2, 2);
      px(ctx, PAL.white, sx + 8, sy + 3, 2, 2);
      px(ctx, PAL.white, sx + 6, sy + 5, 2, 2);
      px(ctx, PAL.white, sx + 4, sy + 7, 2, 2);
      px(ctx, PAL.white, sx + 8, sy + 7, 2, 2);
      break;
    }
  }

  // Stand foot
  px(ctx, PAL.outline, x + 6, y + 15, 6, 2);
}

export function emoteBob(tick: number): number {
  return Math.floor(tick / 16) % 2 === 0 ? 0 : -1;
}

export function fallbackBubble(ctx: Ctx, x: number, y: number, status: NodeRunStatus): void {
  const bg = status === 'running' ? PAL.screenOff : status === 'done' ? PAL.ok : PAL.error;
  px(ctx, PAL.outline, x, y, 14, 12);
  px(ctx, bg, x + 1, y + 1, 12, 10);
  px(ctx, PAL.white, x + 3, y + 5, 8, 2);
}

// ─── Environment & Architecture ───────────────────────────────────────────────

/** Draw floor tiles with wood planks or stone styles. */
export function drawFloorArea(
  ctx: Ctx,
  imgs: OfficeImages,
  x: number,
  y: number,
  w: number,
  h: number,
  style: string,
): void {
  if (imgs.floors) {
    let col = 1;
    let row = 1;
    if (style === 'slateTech') {
      col = 1;
      row = 7;
    } else if (style === 'woodDark') {
      col = 7;
      row = 1;
    } else if (style === 'checkered') {
      col = 4;
      row = 7;
    }

    const sx = col * 16;
    const sy = row * 16;
    for (let py = y; py < y + h; py += 16) {
      for (let pxPos = x; pxPos < x + w; pxPos += 16) {
        const dw = Math.min(16, x + w - pxPos);
        const dh = Math.min(16, y + h - py);
        ctx.drawImage(imgs.floors, sx, sy, dw, dh, pxPos, py, dw, dh);
      }
    }
  } else {
    // Flat fallback
    px(ctx, style === 'slateTech' ? '#5a6988' : '#efd9ae', x, y, w, h);
  }
}

/** Draw perimeter & partition walls. */
export function drawOfficeWalls(
  ctx: Ctx,
  _imgs: OfficeImages,
  walls: WallSegment[],
  roomW: number,
  _roomH: number,
): void {
  for (const wall of walls) {
    if (wall.isInterior) {
      // Interior partition wall with wooden post styling
      px(ctx, PAL.outline, wall.x, wall.y, wall.w, wall.h);
      px(ctx, PAL.woodDark, wall.x + 1, wall.y, wall.w - 2, wall.h);
      px(ctx, PAL.woodLight, wall.x + 2, wall.y, 2, wall.h);
      px(ctx, PAL.wallShadow, wall.x + wall.w, wall.y, 3, wall.h);
      continue;
    }

    if (wall.h >= 28 && wall.y === 0) {
      // North back wall (32px tall)
      px(ctx, PAL.outline, wall.x, 0, wall.w, wall.h);
      px(ctx, PAL.wallFace, wall.x, 0, wall.w, wall.h - 4);
      px(ctx, PAL.wallTop, wall.x, 0, wall.w, 8);

      // Panel seams every 24px
      ctx.fillStyle = PAL.woodDark;
      for (let wx = 12; wx < wall.w; wx += 24) {
        ctx.fillRect(wx, 8, 1, 20);
      }

      // Baseboard skirting & drop shadow onto floor
      px(ctx, PAL.woodDark, wall.x, wall.h - 4, wall.w, 4);
      px(ctx, PAL.wallShadow, wall.x, wall.h, wall.w, 4);
    } else {
      // Perimeter border walls
      px(ctx, PAL.outline, wall.x, wall.y, wall.w, wall.h);
      px(ctx, PAL.woodDark, wall.x + 1, wall.y + 1, Math.max(1, wall.w - 2), Math.max(1, wall.h - 2));
    }
  }

  // Corner reinforcement studs
  px(ctx, PAL.outline, 0, 0, 16, 16);
  px(ctx, PAL.outline, roomW - 16, 0, 16, 16);
}

/** Draw door openings between rooms. */
export function drawDoorways(ctx: Ctx, doorways: Doorway[]): void {
  for (const door of doorways) {
    // Archway lintel & threshold shadow
    px(ctx, PAL.woodDark, door.x, door.y, door.w, 4);
    px(ctx, PAL.woodLight, door.x + 2, door.y + 1, door.w - 4, 1);
    px(ctx, PAL.wallShadow, door.x, door.y + 4, door.w, 2);
  }
}

/** Draw props: animated plants, servers, water cooler, bookshelf, windows, clock. */
export function drawOfficeProps(
  ctx: Ctx,
  imgs: OfficeImages,
  props: RoomProp[],
  tick: number,
): void {
  for (const prop of props) {
    switch (prop.kind) {
      case 'plant': {
        // 4-frame animated swaying potted plant
        if (imgs.plant) {
          const frame = Math.floor(tick / 10) % 4;
          ctx.drawImage(imgs.plant, frame * 16, 0, 16, 16, prop.x, prop.y, 16, 16);
        } else {
          px(ctx, PAL.woodDark, prop.x + 4, prop.y + 10, 8, 6);
          px(ctx, PAL.ok, prop.x + 2, prop.y + 2, 12, 8);
        }
        break;
      }
      case 'server': {
        // Server rack with blinking status LEDs
        px(ctx, PAL.outline, prop.x, prop.y, prop.w, prop.h);
        px(ctx, PAL.serverDark, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
        for (let row = 0; row < 4; row++) {
          const ry = prop.y + 4 + row * 6;
          px(ctx, PAL.outline, prop.x + 2, ry, prop.w - 4, 4);
          const ledOn = (Math.floor(tick / 8) + row) % 2 === 0;
          px(ctx, ledOn ? PAL.screenGlow : PAL.ok, prop.x + 4, ry + 1, 2, 2);
          px(ctx, !ledOn ? PAL.gold : PAL.screenOff, prop.x + 8, ry + 1, 2, 2);
        }
        break;
      }
      case 'waterCooler': {
        // Water dispenser with translucent blue bottle
        px(ctx, PAL.outline, prop.x + 2, prop.y, 12, 14); // jug
        px(ctx, PAL.water, prop.x + 3, prop.y + 1, 10, 12);
        px(ctx, PAL.white, prop.x + 4, prop.y + 3, 2, 6); // glass shine
        px(ctx, PAL.outline, prop.x, prop.y + 14, 16, 14); // body
        px(ctx, PAL.white, prop.x + 1, prop.y + 15, 14, 12);
        px(ctx, PAL.screenOff, prop.x + 6, prop.y + 18, 4, 4); // tap
        break;
      }
      case 'bookshelf': {
        // Wooden bookshelf with books
        if (imgs.interior) {
          // Slice bookshelf from interior sheet (col 0, row 3: 16x32)
          ctx.drawImage(imgs.interior, 0, 48, 16, 32, prop.x, prop.y, 16, 32);
          ctx.drawImage(imgs.interior, 16, 48, 12, 32, prop.x + 16, prop.y, 12, 32);
        } else {
          px(ctx, PAL.outline, prop.x, prop.y, prop.w, prop.h);
          px(ctx, PAL.woodDark, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
          px(ctx, PAL.woodLight, prop.x + 2, prop.y + 10, prop.w - 4, 2);
          px(ctx, PAL.woodLight, prop.x + 2, prop.y + 20, prop.w - 4, 2);
        }
        break;
      }
      case 'window': {
        // Arched window showing outside daylight
        px(ctx, PAL.outline, prop.x, prop.y, prop.w, prop.h);
        px(ctx, PAL.woodDark, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
        px(ctx, PAL.screenGlow, prop.x + 2, prop.y + 2, prop.w - 4, prop.h - 4);
        px(ctx, PAL.white, prop.x + 3, prop.y + 3, 4, prop.h - 6);
        px(ctx, PAL.woodDark, prop.x + Math.floor(prop.w / 2), prop.y + 2, 1, prop.h - 4);
        px(ctx, PAL.woodDark, prop.x + 2, prop.y + Math.floor(prop.h / 2), prop.w - 4, 1);
        break;
      }
      case 'clock': {
        // Wall clock with ticking hand
        px(ctx, PAL.outline, prop.x, prop.y, prop.w, prop.h);
        px(ctx, PAL.white, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
        px(ctx, PAL.outline, prop.x + 5, prop.y + 5, 2, 2); // center pin
        const angle = (tick % 60) * (Math.PI / 30);
        const hx = prop.x + 6 + Math.round(Math.sin(angle) * 3);
        const hy = prop.y + 6 - Math.round(Math.cos(angle) * 3);
        px(ctx, PAL.error, hx, hy, 1, 1);
        break;
      }
      case 'bulletin': {
        // Cork notice board
        px(ctx, PAL.outline, prop.x, prop.y, prop.w, prop.h);
        px(ctx, PAL.woodMid, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
        px(ctx, PAL.white, prop.x + 3, prop.y + 3, 5, 4);
        px(ctx, PAL.gold, prop.x + 10, prop.y + 4, 6, 5);
        break;
      }
    }
  }
}

/** Animated smoke puff for nodes in error state. */
export function drawSmokePuff(
  ctx: Ctx,
  imgs: OfficeImages,
  x: number,
  y: number,
  tick: number,
): void {
  if (imgs.smoke) {
    // 6-frame animated smoke puff (32x32 frames)
    const frame = Math.floor(tick / 4) % 6;
    ctx.drawImage(imgs.smoke, frame * 32, 0, 32, 32, x - 6, y - 18, 24, 24);
  } else {
    // Particle fallback
    const off = (tick % 8) * 2;
    px(ctx, PAL.screenOff, x + 8, y - 8 - off, 4, 4);
    px(ctx, PAL.white, x + 10, y - 12 - off, 2, 2);
  }
}

/** Animated spinning gold coin for finished nodes. */
export function drawSpinningCoin(
  ctx: Ctx,
  imgs: OfficeImages,
  x: number,
  y: number,
  tick: number,
): void {
  if (imgs.coinAnim) {
    const frame = Math.floor(tick / 5) % 4;
    ctx.drawImage(imgs.coinAnim, frame * 10, 0, 10, 10, x, y, 10, 10);
  } else if (imgs.coin) {
    ctx.drawImage(imgs.coin, x, y);
  } else {
    px(ctx, PAL.gold, x, y, 6, 6);
  }
}

// ─── Flow Particles ───────────────────────────────────────────────────────────

export interface OfficeDataFlowEdge {
  id: string;
  source: string;
  target: string;
}

export function drawOfficeFlows(
  ctx: Ctx,
  edges: OfficeDataFlowEdge[],
  animatedEdgeIds: Set<string>,
  slotMap: Map<string, { x: number; y: number }>,
  tick: number,
): void {
  if (animatedEdgeIds.size === 0) return;

  for (const edge of edges) {
    if (!animatedEdgeIds.has(edge.id)) continue;
    const a = slotMap.get(edge.source);
    const b = slotMap.get(edge.target);
    if (!a || !b) continue;

    const ax = a.x + DESK_W / 2;
    const ay = a.y + DESK_H - 6;
    const bx = b.x + DESK_W / 2;
    const by = b.y + DESK_H - 6;

    // Glowing conduit cable
    ctx.save();
    ctx.strokeStyle = PAL.screenGlow;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.lineDashOffset = -(tick % 8);
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
    ctx.restore();

    // Moving pulse energy particle
    const t = (tick % 30) / 30;
    const pxPos = Math.round(ax + (bx - ax) * t);
    const pyPos = Math.round(ay + (by - ay) * t);

    px(ctx, PAL.gold, pxPos - 2, pyPos - 2, 5, 5);
    px(ctx, PAL.white, pxPos - 1, pyPos - 1, 3, 3);
  }
}
