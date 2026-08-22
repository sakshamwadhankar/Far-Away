/// <reference types="vite/client" />
/**
 * office/tileset.ts
 *
 * Loads the Kenney "Tiny Town" packed tile sheet (16×16 px tiles, CC0) and
 * slices it into per-tile canvases so the OfficeView can blit environment
 * tiles (floor, walls, props). The pack contains no characters or desks, so
 * those are drawn programmatically in sprites.ts using this pack's palette.
 *
 * Loading is fault-tolerant: if the image cannot be decoded (e.g. jsdom
 * tests), `available` stays false and callers fall back to flat fills.
 */

export const TILE_SIZE = 16;
export const SHEET_COLS = 12;

/** Tile indices into kenney_tiny-town/Tilemap/tilemap_packed.png. */
export enum Tile {
  GrassPlain = 0,
  TreeAutumn = 3,
  TreePine = 4,
  BushRound = 5,
  BushSmall = 30,
  MushroomRed = 29,
  StoneFloorPlain = 109,
  StoneWallCap = 96,
  StoneWallBrick = 100,
  StoneWallBase = 101,
  SignBoard = 83,
  CoinGold = 93,
  Beehive = 94,
  TargetSign = 95,
  WaterCooler = 104,
  PotBrown = 107,
  BucketWater = 131,
}

/** Kenney Tiny Town shared palette, sampled from the packed sheet. */
export const PAL = {
  outline: '#3f2631',
  woodLight: '#eaa56c',
  woodMid: '#bd6c4a',
  woodDark: '#763b36',
  stoneLight: '#c0cbdc',
  stoneMid: '#8b9bb4',
  stoneDark: '#5a6988',
  water: '#76e4ff',
  waterDeep: '#009adc',
  gold: '#fdbe53',
  goldDark: '#e38628',
  red: '#ff706d',
  redDark: '#e84537',
  green: '#84c669',
  greenDark: '#479f4a',
} as const;

export interface Tileset {
  /** Per-tile canvases indexed by tile id, or null when unavailable. */
  tiles: Map<Tile, HTMLCanvasElement>;
  available: boolean;
}

function sliceTile(
  source: HTMLImageElement,
  id: number,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = TILE_SIZE;
  canvas.height = TILE_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('2D context unavailable');
  const col = id % SHEET_COLS;
  const row = Math.floor(id / SHEET_COLS);
  ctx.drawImage(source, col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE, 0, 0, TILE_SIZE, TILE_SIZE);
  return canvas;
}

export function tileCoords(id: number): { col: number; row: number } {
  return { col: id % SHEET_COLS, row: Math.floor(id / SHEET_COLS) };
}

/**
 * Decode the sheet and slice every named tile. Never rejects — a decode
 * failure resolves to `{ tiles: new Map(), available: false }` so the view
 * can render a palette-only fallback instead of crashing.
 */
export function loadTileset(sheetUrl: string): Promise<Tileset> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || typeof Image === 'undefined') {
      resolve({ tiles: new Map(), available: false });
      return;
    }
    const img = new Image();
    img.onload = () => {
      const tiles = new Map<Tile, HTMLCanvasElement>();
      try {
        for (const id of Object.values(Tile).filter((v): v is Tile => typeof v === 'number')) {
          tiles.set(id, sliceTile(img, id));
        }
        resolve({ tiles, available: true });
      } catch {
        resolve({ tiles: new Map(), available: false });
      }
    };
    img.onerror = () => resolve({ tiles: new Map(), available: false });
    img.src = sheetUrl;
  });
}
