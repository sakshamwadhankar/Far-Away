/**
 * office/sprites.ts
 *
 * Pixel-art furniture for the Virtual Office View. The "Ninja Adventure"
 * pack provides characters, emotes, floors and props but no desks or
 * monitors, so those are composed here from axis-aligned pixel rectangles
 * using colors sampled from the pack's own master palette (Palette.png).
 * All drawing is deterministic: (state, tick) fully determines output.
 */

/** Ninja Adventure master-palette colors used by the furniture. */
export const PAL = {
  outline: '#3b3643',
  woodLight: '#eecf9b',
  woodMid: '#c8966b',
  woodDark: '#965340',
  wallFace: '#a3754e',
  wallTop: '#eecf9b',
  wallShadow: 'rgba(20, 27, 27, 0.35)',
  screenOff: '#4a5270',
  screenGlow: '#71ddee',
  ok: '#56864c',
  error: '#d14b34',
  gold: '#f1c471',
  white: '#ffffff',
} as const;

/** Execution states mirrored from PipelineNodeData.status. */
export type NodeRunStatus = 'idle' | 'running' | 'done' | 'error';

import type { StatusEmote } from './assets';

/**
 * Pure status → presentation mapping: which emote bubble floats above the
 * agent and what the desk monitor shows.
 */
export interface StatusVisual {
  emote: StatusEmote | null;
  /** Celebration window after flipping to done, ms. */
  celebrateMs: number;
}

export const STATUS_VISUALS: Record<NodeRunStatus, StatusVisual> = {
  idle: { emote: null, celebrateMs: 0 },
  running: { emote: 'thinking', celebrateMs: 0 },
  done: { emote: 'happy', celebrateMs: 1600 },
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

/** Desk-mat color per node type (kept in sync with canvas/nodes/PipelineNode.tsx TYPE_ACCENTS). */
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

function px(ctx: Ctx, color: string, x: number, y: number, w: number, h: number): void {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

/**
 * Draw a complete desk workstation inside a DESK_W×DESK_H unit at (x, y):
 * agent seated on the left facing the viewer, wooden desktop with a colored
 * type mat, monitor standing on the right. `agent` is the character's
 * 4-frame idle strip; frame 0 faces down (toward the viewer). When missing,
 * a flat silhouette is drawn.
 */
export function drawDesk(
  ctx: Ctx,
  x: number,
  y: number,
  matColor: string,
  screen: ScreenState,
  tick: number,
  hovered: boolean,
  agent?: HTMLImageElement | null,
): void {
  // Chair back peeking above the agent.
  px(ctx, PAL.outline, x + 5, y + 2, 20, 4);
  px(ctx, PAL.woodDark, x + 6, y + 3, 18, 2);

  // Agent seated facing the viewer, gently bobbing while busy.
  const busy = screen === 'working' || screen === 'ok' || screen === 'fail';
  const bob = busy && Math.floor(tick / 8) % 2 === 0 ? -1 : 0;
  if (agent) {
    ctx.drawImage(agent, 0, 0, 16, 16, x + 7, y + 4 + bob, 16, 16);
  } else {
    px(ctx, PAL.outline, x + 7, y + 4 + bob, 16, 16);
    px(ctx, PAL.wallFace, x + 8, y + 7 + bob, 14, 10);
  }

  // Desk top: light surface with outline and front lip.
  px(ctx, PAL.outline, x + 2, y + 22, 48, 14);
  px(ctx, PAL.woodMid, x + 3, y + 23, 46, 8);
  px(ctx, PAL.woodLight, x + 3, y + 23, 46, 2);
  px(ctx, PAL.woodDark, x + 3, y + 31, 46, 4);

  // Colored mat identifying the node type.
  px(ctx, matColor, x + 6, y + 30, 10, 3);
  px(ctx, PAL.outline, x + 20, y + 29, 9, 1); // pen on desk

  // Monitor standing on the desk's right side.
  drawMonitor(ctx, x + 29, y + 10, screen, tick);

  if (hovered) {
    // Selection halo around the whole unit.
    px(ctx, PAL.outline, x - 1, y - 1, 54, 1);
    px(ctx, PAL.outline, x - 1, y + 49, 54, 1);
    px(ctx, PAL.outline, x - 1, y - 1, 1, 50);
    px(ctx, PAL.outline, x + 53, y - 1, 1, 50);
  }
}

/** Desk monitor with per-state screen animation; origin is screen top-left. */
export function drawMonitor(ctx: Ctx, x: number, y: number, state: ScreenState, tick: number): void {
  // Casing.
  px(ctx, PAL.outline, x, y, 18, 15);
  px(ctx, PAL.woodDark, x + 1, y + 1, 16, 12);
  const sx = x + 2;
  const sy = y + 2;
  const sw = 14;
  const sh = 10;

  switch (state) {
    case 'off':
      px(ctx, PAL.screenOff, sx, sy, sw, sh);
      px(ctx, PAL.outline, sx + sw - 3, sy + sh - 3, 1, 1); // standby dot
      break;
    case 'working': {
      // Dark screen with scrolling text lines.
      px(ctx, PAL.outline, sx, sy, sw, sh);
      for (let i = 0; i < 3; i++) {
        const len = 4 + ((Math.floor(tick / 6) + i * 3) % 9);
        px(ctx, i === Math.floor(tick / 6) % 3 ? PAL.white : PAL.screenGlow, sx + 1, sy + 2 + i * 3, len, 1);
      }
      break;
    }
    case 'ok': {
      // Green screen with a check mark.
      px(ctx, PAL.ok, sx, sy, sw, sh);
      px(ctx, PAL.white, sx + 3, sy + 4, 2, 2);
      px(ctx, PAL.white, sx + 5, sy + 6, 2, 2);
      px(ctx, PAL.white, sx + 7, sy + 7, 1, 1);
      px(ctx, PAL.white, sx + 9, sy + 3, 2, 3);
      break;
    }
    case 'fail': {
      // Flashing red screen with an X.
      const flash = Math.floor(tick / 12) % 2 === 0;
      px(ctx, flash ? PAL.error : PAL.outline, sx, sy, sw, sh);
      px(ctx, PAL.white, sx + 4, sy + 3, 2, 2);
      px(ctx, PAL.white, sx + 8, sy + 3, 2, 2);
      px(ctx, PAL.white, sx + 6, sy + 5, 2, 2);
      px(ctx, PAL.white, sx + 4, sy + 7, 2, 2);
      px(ctx, PAL.white, sx + 8, sy + 7, 2, 2);
      break;
    }
  }

  // Stand foot on the desk.
  px(ctx, PAL.outline, x + 6, y + 15, 6, 2);
}

/**
 * Bobbing animation offset (px) for a floating emote bubble.
 */
export function emoteBob(tick: number): number {
  return Math.floor(tick / 16) % 2 === 0 ? 0 : -1;
}

/** Fallback speech bubble when the emote sprite is unavailable. */
export function fallbackBubble(ctx: Ctx, x: number, y: number, status: NodeRunStatus): void {
  const bg = status === 'running' ? PAL.screenOff : status === 'done' ? PAL.ok : PAL.error;
  px(ctx, PAL.outline, x, y, 12, 11);
  px(ctx, bg, x + 1, y + 1, 10, 9);
  px(ctx, PAL.white, x + 3, y + 5, 6, 1);
}
