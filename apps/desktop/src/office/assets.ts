/// <reference types="vite/client" />
/**
 * office/assets.ts
 *
 * Loads the pixel-art sprites and tilesets used by the Virtual Office View
 * from the bundled "Ninja Adventure" asset pack (CC0):
 *
 *  - char_<type>.png   Full 64×112 sprite sheets (4 cols × 7 rows, 16×16 px frames):
 *                      Row 0: Idle (Down, Up, Left, Right)
 *                      Row 1: Walk Down (4-frame walk cycle)
 *                      Row 2: Walk Up (4-frame walk cycle)
 *                      Row 3: Walk Left (4-frame walk cycle)
 *                      Row 4: Walk Right (4-frame walk cycle)
 *                      Row 5: Action / Typing (4-frame work cycle)
 *                      Row 6: Jump / Celebrating (4-frame victory cycle)
 *  - tileset_interior.png (256×320): Bookshelves, clocks, windows, servers, tables, decor
 *  - tileset_walls.png    (160×176): Perimeter & partition walls, wall tops, baseboards
 *  - tileset_elements.png (144×48):  Wall plaques, notice boards, signs
 *  - tileset_house.png    (528×368): Architectural windows, doors, structural frames
 *  - floors.png           (352×272): Wood planks, stone tiles, carpet borders
 *  - plant.png            (64×16):   4-frame animated swaying potted plant
 *  - smoke.png            (192×32):  Animated smoke / spark puffs for error states
 *  - spark.png            (70×8):    Animated glowing energy pulses for data flows
 *  - coin_anim.png        (40×10):   4-frame spinning gold coin animation
 *  - emote_*.png          (14×13+):  Emote bubbles (thinking, happy, alert, idea, music, sleep)
 *  - prop_book.png, prop_coin.png: Desk props & markers
 *
 * Loading never rejects: missing/unsupported decodes (e.g. jsdom tests)
 * resolve to undefined slots and OfficeView gracefully uses fallback vector rendering.
 */

import type { NodeType } from '@shared/types';

export const TILE = 16;

/** Interior floor tile locations in floors.png (column, row in 16px units). */
export const FLOOR_TILES = {
  woodWarm: { col: 1, row: 1 },
  woodLight: { col: 4, row: 1 },
  woodDark: { col: 7, row: 1 },
  slateTech: { col: 1, row: 7 },
  checkered: { col: 4, row: 7 },
  carpetBlue: { col: 10, row: 1 },
  carpetRed: { col: 13, row: 1 },
  carpetGreen: { col: 16, row: 1 },
} as const;

/** Plain floor tile for compatibility. */
export const FLOOR_TILE_POS = FLOOR_TILES.woodWarm;

export type StatusEmote = 'thinking' | 'happy' | 'alert' | 'idea' | 'music' | 'sleep';

// Static imports so Vite bundles and hashes every asset for production builds.
import charInput from '../assets/office/char_input.png';
import charModel from '../assets/office/char_model.png';
import charOutput from '../assets/office/char_output.png';
import charJudge from '../assets/office/char_judge.png';
import charLoop from '../assets/office/char_loop.png';
import charRouter from '../assets/office/char_router.png';
import charTransform from '../assets/office/char_transform.png';
import charCompare from '../assets/office/char_compare.png';
import charAccess from '../assets/office/char_access.png';

import tilesetInterior from '../assets/office/tileset_interior.png';
import tilesetWalls from '../assets/office/tileset_walls.png';
import tilesetElements from '../assets/office/tileset_elements.png';
import tilesetHouse from '../assets/office/tileset_house.png';
import floorsSheet from '../assets/office/floors.png';

import plantStrip from '../assets/office/plant.png';
import smokeStrip from '../assets/office/smoke.png';
import sparkStrip from '../assets/office/spark.png';
import coinAnimStrip from '../assets/office/coin_anim.png';
import propBook from '../assets/office/prop_book.png';
import propCoin from '../assets/office/prop_coin.png';

import emoteThinking from '../assets/office/emote_thinking.png';
import emoteHappy from '../assets/office/emote_happy.png';
import emoteAlert from '../assets/office/emote_alert.png';
import emoteIdea from '../assets/office/emote_idea.png';
import emoteMusic from '../assets/office/emote_music.png';
import emoteSleep from '../assets/office/emote_sleep.png';

const CHAR_URLS: Record<NodeType, string> = {
  input: charInput,
  model: charModel,
  // No dedicated sprite shipped for the computer node yet; it is a model-driven
  // operator, so it borrows the model character until artwork exists.
  computer: charModel,
  output: charOutput,
  judge: charJudge,
  loop: charLoop,
  router: charRouter,
  transform: charTransform,
  compare: charCompare,
  access: charAccess,
};

const EMOTE_URLS: Record<StatusEmote, string> = {
  thinking: emoteThinking,
  happy: emoteHappy,
  alert: emoteAlert,
  idea: emoteIdea,
  music: emoteMusic,
  sleep: emoteSleep,
};

/** All images available to the office room renderer. */
export interface OfficeImages {
  chars: Partial<Record<NodeType, HTMLImageElement>>;
  emotes: Partial<Record<StatusEmote, HTMLImageElement>>;
  interior?: HTMLImageElement;
  walls?: HTMLImageElement;
  elements?: HTMLImageElement;
  house?: HTMLImageElement;
  floors?: HTMLImageElement;
  plant?: HTMLImageElement;
  smoke?: HTMLImageElement;
  spark?: HTMLImageElement;
  coinAnim?: HTMLImageElement;
  book?: HTMLImageElement;
  coin?: HTMLImageElement;
}

function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || typeof Image === 'undefined') return resolve(null);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/** Load every office sprite and tileset in parallel without throwing. */
export async function loadOfficeAssets(): Promise<OfficeImages> {
  const charEntries = Object.entries(CHAR_URLS).map(async ([k, url]) => [`char:${k}`, await loadImage(url)] as const);
  const emoteEntries = Object.entries(EMOTE_URLS).map(async ([k, url]) => [`emote:${k}`, await loadImage(url)] as const);
  const sheetEntries: Array<readonly [string, string]> = [
    ['interior', tilesetInterior],
    ['walls', tilesetWalls],
    ['elements', tilesetElements],
    ['house', tilesetHouse],
    ['floors', floorsSheet],
    ['plant', plantStrip],
    ['smoke', smokeStrip],
    ['spark', sparkStrip],
    ['coinAnim', coinAnimStrip],
    ['book', propBook],
    ['coin', propCoin],
  ];

  const sheetsLoaded = sheetEntries.map(async ([k, url]) => [k, await loadImage(url)] as const);
  const allResults = await Promise.all([...charEntries, ...emoteEntries, ...sheetsLoaded]);

  const images: OfficeImages = { chars: {}, emotes: {} };
  for (const [key, img] of allResults) {
    if (!img) continue;
    if (key.startsWith('char:')) {
      const name = key.slice(5) as NodeType;
      images.chars[name] = img;
    } else if (key.startsWith('emote:')) {
      const name = key.slice(6) as StatusEmote;
      images.emotes[name] = img;
    } else {
      switch (key) {
        case 'interior': images.interior = img; break;
        case 'walls': images.walls = img; break;
        case 'elements': images.elements = img; break;
        case 'house': images.house = img; break;
        case 'floors': images.floors = img; break;
        case 'plant': images.plant = img; break;
        case 'smoke': images.smoke = img; break;
        case 'spark': images.spark = img; break;
        case 'coinAnim': images.coinAnim = img; break;
        case 'book': images.book = img; break;
        case 'coin': images.coin = img; break;
      }
    }
  }

  return images;
}
