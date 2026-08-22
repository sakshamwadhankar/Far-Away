/**
 * office/layout.ts
 *
 * Pure architectural geometry for the Virtual Office View: turns a node count
 * into rooms, partition walls, doorways, decorative props, and desk workstations.
 *
 * Fully deterministic & unit-testable (no DOM or canvas dependencies).
 */

/** Pixel footprint of a single desk unit (agent + desk + monitor). */
export const DESK_W = 52;
export const DESK_H = 48;

/** Spacing between desks in a room. */
export const GAP_X = 18;
export const GAP_Y = 22;

/** Architectural dimensions (16px tile aligned). */
export const WALL_TOP_H = 32; // North back wall height
export const WALL_BOTTOM_H = 16;
export const WALL_SIDE_W = 16;
export const DOOR_W = 28;
export const DOOR_H = 32;

export const MIN_ROOM_W = 384;
export const MIN_ROOM_H = 256;
export const MAX_COLS = 6;

export type FloorStyle = 'woodWarm' | 'woodLight' | 'woodDark' | 'slateTech' | 'checkered' | 'carpetBlue' | 'carpetRed' | 'carpetGreen';

export type PropKind =
  | 'plant'
  | 'server'
  | 'bookshelf'
  | 'waterCooler'
  | 'clock'
  | 'window'
  | 'bulletin'
  | 'chest'
  | 'rug'
  | 'cabinet'
  | 'coffeeStation'
  | 'lamp'
  | 'whiteboard'
  | 'trashBin'
  | 'crate';

export interface RoomProp {
  kind: PropKind;
  x: number;
  y: number;
  w: number;
  h: number;
  variant?: number;
}

export interface WallSegment {
  x: number;
  y: number;
  w: number;
  h: number;
  isInterior?: boolean;
}

export interface Doorway {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface OfficeRoom {
  id: string;
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  floorStyle: FloorStyle;
  slots: number[]; // indices into layout.slots
}

export interface DeskSlot {
  x: number;
  y: number;
  roomId?: string;
  zoneName?: string;
}

export interface OfficeLayout {
  roomW: number;
  roomH: number;
  cols: number;
  rows: number;
  slots: DeskSlot[];
  rooms: OfficeRoom[];
  walls: WallSegment[];
  doorways: Doorway[];
  props: RoomProp[];
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

/**
 * Computes an authentic multi-room office layout with walls, decor props,
 * and desk positions sized to fit the given agent count.
 */
export function computeDeskLayout(count: number): OfficeLayout {
  if (count <= 0) {
    return {
      roomW: MIN_ROOM_W,
      roomH: MIN_ROOM_H,
      cols: 0,
      rows: 0,
      slots: [],
      rooms: [],
      walls: [
        { x: 0, y: 0, w: MIN_ROOM_W, h: WALL_TOP_H },
        { x: 0, y: 0, w: WALL_SIDE_W, h: MIN_ROOM_H },
        { x: MIN_ROOM_W - WALL_SIDE_W, y: 0, w: WALL_SIDE_W, h: MIN_ROOM_H },
        { x: 0, y: MIN_ROOM_H - WALL_BOTTOM_H, w: MIN_ROOM_W, h: WALL_BOTTOM_H },
      ],
      doorways: [],
      props: [
        { kind: 'window', x: 80, y: 4, w: 24, h: 20 },
        { kind: 'clock', x: 192, y: 6, w: 12, h: 12 },
        { kind: 'window', x: 280, y: 4, w: 24, h: 20 },
        { kind: 'plant', x: 24, y: 36, w: 16, h: 16 },
        { kind: 'bookshelf', x: MIN_ROOM_W - 48, y: 32, w: 28, h: 28 },
      ],
    };
  }

  const cols = clamp(Math.ceil(Math.sqrt(count)), 1, MAX_COLS);
  const rows = Math.ceil(count / cols);

  const gridW = cols * DESK_W + (cols - 1) * GAP_X;
  const gridH = rows * DESK_H + (rows - 1) * GAP_Y;

  // Add room borders, side aisles, and architectural margins
  const padX = 36;
  const padBottom = 40;
  const roomW = Math.max(MIN_ROOM_W, Math.ceil((gridW + padX * 2) / 16) * 16);
  const roomH = Math.max(MIN_ROOM_H, Math.ceil((WALL_TOP_H + gridH + padBottom) / 16) * 16);

  // Center desk grid horizontally and position below north wall
  const offsetX = Math.round((roomW - gridW) / 2);
  const offsetY = WALL_TOP_H + Math.round((roomH - WALL_TOP_H - padBottom - gridH) / 2) + 6;

  const slots: DeskSlot[] = [];
  for (let i = 0; i < count; i++) {
    const r = Math.floor(i / cols);
    const c = i % cols;
    slots.push({
      x: offsetX + c * (DESK_W + GAP_X),
      y: offsetY + r * (DESK_H + GAP_Y),
    });
  }

  // Generate outer perimeter walls
  const walls: WallSegment[] = [
    { x: 0, y: 0, w: roomW, h: WALL_TOP_H },
    { x: 0, y: 0, w: WALL_SIDE_W, h: roomH },
    { x: roomW - WALL_SIDE_W, y: 0, w: WALL_SIDE_W, h: roomH },
    { x: 0, y: roomH - WALL_BOTTOM_H, w: roomW, h: WALL_BOTTOM_H },
  ];

  const doorways: Doorway[] = [];
  const rooms: OfficeRoom[] = [];

  // Partition multi-room zones when there are multiple desks/columns
  if (cols >= 3 && count >= 4) {
    const splitX = Math.round(roomW / 2);
    // Interior partition wall between left and right departments
    walls.push({ x: splitX - 4, y: WALL_TOP_H, w: 8, h: Math.round(roomH * 0.45) - WALL_TOP_H, isInterior: true });
    doorways.push({ x: splitX - 14, y: Math.round(roomH * 0.45), w: DOOR_W, h: DOOR_H });
    walls.push({ x: splitX - 4, y: Math.round(roomH * 0.45) + DOOR_H, w: 8, h: roomH - WALL_BOTTOM_H - (Math.round(roomH * 0.45) + DOOR_H), isInterior: true });

    rooms.push({
      id: 'room-left',
      name: 'OPERATIONS & INGESTION',
      x: WALL_SIDE_W,
      y: WALL_TOP_H,
      w: splitX - WALL_SIDE_W - 4,
      h: roomH - WALL_TOP_H - WALL_BOTTOM_H,
      floorStyle: 'woodWarm',
      slots: slots.map((_, idx) => idx).filter((idx) => slots[idx].x < splitX),
    });

    rooms.push({
      id: 'room-right',
      name: 'AI CORE & DISPATCH',
      x: splitX + 4,
      y: WALL_TOP_H,
      w: roomW - splitX - 4 - WALL_SIDE_W,
      h: roomH - WALL_TOP_H - WALL_BOTTOM_H,
      floorStyle: 'slateTech',
      slots: slots.map((_, idx) => idx).filter((idx) => slots[idx].x >= splitX),
    });
  } else {
    // Single grand command center
    rooms.push({
      id: 'room-main',
      name: 'AGENT COMMAND CENTER',
      x: WALL_SIDE_W,
      y: WALL_TOP_H,
      w: roomW - WALL_SIDE_W * 2,
      h: roomH - WALL_TOP_H - WALL_BOTTOM_H,
      floorStyle: 'woodWarm',
      slots: slots.map((_, idx) => idx),
    });
  }

  // Populate decorative props along walls and corners
  const props: RoomProp[] = [];

  // North wall features (windows, clocks, wall lamps, whiteboard, bulletin charts)
  const windowSpacing = Math.round(roomW / 4);
  props.push({ kind: 'window', x: windowSpacing - 12, y: 6, w: 24, h: 20 });
  props.push({ kind: 'clock', x: Math.round(roomW / 2) - 6, y: 8, w: 12, h: 12 });
  props.push({ kind: 'window', x: roomW - windowSpacing - 12, y: 6, w: 24, h: 20 });

  // Wall lamps with flickering warm glow
  props.push({ kind: 'lamp', x: 20, y: 8, w: 8, h: 12 });
  props.push({ kind: 'lamp', x: roomW - 28, y: 8, w: 8, h: 12 });
  if (cols >= 3 && count >= 4) {
    const splitX = Math.round(roomW / 2);
    props.push({ kind: 'lamp', x: splitX - 18, y: 8, w: 8, h: 12 });
    props.push({ kind: 'lamp', x: splitX + 10, y: 8, w: 8, h: 12 });
  }

  // Strategy whiteboard and bulletin boards
  props.push({ kind: 'whiteboard', x: windowSpacing + 28, y: 6, w: 26, h: 18 });
  props.push({ kind: 'bulletin', x: roomW - windowSpacing - 44, y: 6, w: 20, h: 16 });

  // Left Room / Break & Ingestion decor
  props.push({ kind: 'coffeeStation', x: WALL_SIDE_W + 4, y: WALL_TOP_H + 4, w: 18, h: 22 });
  props.push({ kind: 'plant', x: WALL_SIDE_W + 4, y: WALL_TOP_H + 32, w: 16, h: 16, variant: 0 });
  props.push({ kind: 'cabinet', x: WALL_SIDE_W + 4, y: roomH - WALL_BOTTOM_H - 36, w: 16, h: 26 });
  props.push({ kind: 'crate', x: WALL_SIDE_W + 22, y: roomH - WALL_BOTTOM_H - 24, w: 14, h: 14 });

  // Right Room / AI Core & Server cluster decor
  props.push({ kind: 'server', x: roomW - WALL_SIDE_W - 22, y: WALL_TOP_H + 4, w: 18, h: 32 });
  props.push({ kind: 'server', x: roomW - WALL_SIDE_W - 22, y: WALL_TOP_H + 38, w: 18, h: 32 });
  props.push({ kind: 'plant', x: roomW - WALL_SIDE_W - 22, y: roomH - WALL_BOTTOM_H - 58, w: 16, h: 16, variant: 1 });
  props.push({ kind: 'waterCooler', x: roomW - WALL_SIDE_W - 22, y: roomH - WALL_BOTTOM_H - 32, w: 16, h: 28 });

  if (cols >= 3 && count >= 4) {
    const splitX = Math.round(roomW / 2);
    props.push({ kind: 'bookshelf', x: splitX + 8, y: WALL_TOP_H + 4, w: 28, h: 32 });
  } else {
    props.push({ kind: 'bookshelf', x: WALL_SIDE_W + 4, y: roomH - WALL_BOTTOM_H - 64, w: 28, h: 32 });
  }

  // Add small trash bins next to first few desk units
  for (let i = 0; i < Math.min(slots.length, 3); i++) {
    const s = slots[i];
    props.push({ kind: 'trashBin', x: s.x + DESK_W + 3, y: s.y + 24, w: 8, h: 10 });
  }

  return { roomW, roomH, cols, rows, slots, rooms, walls, doorways, props };
}

/**
 * Scale that fits the room into the container while preserving aspect ratio.
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
 * Stable sort: groups nodes by type priority while preserving relative order.
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
