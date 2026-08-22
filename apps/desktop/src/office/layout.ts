/**
 * office/layout.ts
 *
 * Pure geometry for the Virtual Office View: turns a node count into desk
 * positions inside a pixel-art room. No DOM, no canvas — fully unit-testable.
 *
 * Desks are arranged in a centered grid of up to MAX_COLS columns. Node order
 * is grouped by type (input first, output last) so pipelines read left→right,
 * top→bottom like the graph view.
 */

/** Pixel size of one desk unit (agent + desk + monitor footprint). */
export const DESK_W = 52;
export const DESK_H = 48;
/** Gap between desks, px. */
const GAP_X = 18;
const GAP_Y = 22;
/** Wall band thickness at the top of the room, px. */
export const WALL_H = 28;
/** Room padding around the desk area, px. */
const PAD_X = 26;
const PAD_BOTTOM = 34;

export const MIN_ROOM_W = 320;
export const MIN_ROOM_H = 200;
export const MAX_COLS = 6;

export interface DeskSlot {
  /** Top-left of the desk unit in room pixel coordinates. */
  x: number;
  y: number;
}

export interface OfficeLayout {
  roomW: number;
  roomH: number;
  cols: number;
  rows: number;
  slots: DeskSlot[];
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function computeDeskLayout(count: number): OfficeLayout {
  if (count <= 0) {
    return { roomW: MIN_ROOM_W, roomH: MIN_ROOM_H, cols: 0, rows: 0, slots: [] };
  }
  const cols = clamp(Math.ceil(Math.sqrt(count)), 1, MAX_COLS);
  const rows = Math.ceil(count / cols);

  const gridW = cols * DESK_W + (cols - 1) * GAP_X;
  const gridH = rows * DESK_H + (rows - 1) * GAP_Y;
  const roomW = Math.max(MIN_ROOM_W, gridW + PAD_X * 2);
  const roomH = Math.max(MIN_ROOM_H, WALL_H + gridH + PAD_BOTTOM);

  // Center the grid horizontally inside the room, below the wall band.
  const offsetX = Math.round((roomW - gridW) / 2);
  const offsetY = WALL_H + Math.round((roomH - WALL_H - PAD_BOTTOM - gridH) / 2);

  const slots: DeskSlot[] = [];
  for (let i = 0; i < count; i++) {
    const r = Math.floor(i / cols);
    const c = i % cols;
    slots.push({ x: offsetX + c * (DESK_W + GAP_X), y: offsetY + r * (DESK_H + GAP_Y) });
  }
  return { roomW, roomH, cols, rows, slots };
}

/**
 * Scale that fits the fixed-size room into an available viewport while
 * preserving aspect ratio. Falls back to 1 when measurements are unavailable
 * (e.g. jsdom reports zero-size containers).
 */
export function fitScale(availW: number, availH: number, roomW: number, roomH: number): number {
  if (availW <= 0 || availH <= 0 || roomW <= 0 || roomH <= 0) return 1;
  return Math.min(availW / roomW, availH / roomH);
}

/** Rendering priority so desks mirror pipeline reading order. */
const TYPE_ORDER: Record<string, number> = {
  input: 0,
  transform: 1,
  router: 2,
  compare: 3,
  loop: 4,
  model: 5,
  judge: 6,
  access: 7,
  output: 8,
};

export interface OfficeNodeLike {
  id: string;
  data: { type?: string };
}

/**
 * Stable sort: group nodes by type priority, preserving original order within
 * each group. Unknown types sort last but before outputs.
 */
export function orderNodesForOffice<T extends OfficeNodeLike>(nodes: T[]): T[] {
  return nodes
    .map((node, index) => ({ node, index }))
    .sort((a, b) => {
      const oa = TYPE_ORDER[a.node.data.type ?? ''] ?? TYPE_ORDER.access;
      const ob = TYPE_ORDER[b.node.data.type ?? ''] ?? TYPE_ORDER.access;
      if (oa !== ob) return oa - ob;
      return a.index - b.index;
    })
    .map((entry) => entry.node);
}
