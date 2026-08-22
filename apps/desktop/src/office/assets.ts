/// <reference types="vite/client" />
/**
 * office/assets.ts
 *
 * Loads the sprites used by the Virtual Office View from the bundled
 * "Ninja Adventure" asset pack (pixel-boy, CC0 — see
 * src/assets/office/LICENSE-NinjaAdventure.txt):
 *
 *  - char_<type>.png   Idle strips (64×16, four 16×16 frames: down/up/left/right)
 *                      one distinct character per pipeline node type
 *  - floors.png        Interior floor sheet (352×272, 16px tiles); the plain
 *                      brick tile lives at column 1, row 1
 *  - emote_*.png       14×13 status bubbles (… / smile / !)
 *  - prop_book.png     16×16 desk prop
 *  - prop_coin.png     7×7 cost marker
 *  - plant.png         4-frame 16×16 animated plant strip
 *
 * Loading never rejects: if an image cannot be decoded (e.g. jsdom), its slot
 * stays undefined and OfficeView falls back to flat fills.
 */

export const TILE = 16;
/** Plain seamless floor tile inside floors.png (column, row in 16px tiles). */
export const FLOOR_TILE_POS = { col: 1, row: 1 };

import type { NodeType } from '@shared/types';

export type StatusEmote = 'thinking' | 'happy' | 'alert';

// Static imports so Vite bundles + fingerprints every asset and vitest can
// resolve them without runtime URL tricks.
import charInput from '../assets/office/char_input.png';
import charModel from '../assets/office/char_model.png';
import charOutput from '../assets/office/char_output.png';
import charJudge from '../assets/office/char_judge.png';
import charLoop from '../assets/office/char_loop.png';
import charRouter from '../assets/office/char_router.png';
import charTransform from '../assets/office/char_transform.png';
import charCompare from '../assets/office/char_compare.png';
import charAccess from '../assets/office/char_access.png';
import floorsSheet from '../assets/office/floors.png';
import emoteThinking from '../assets/office/emote_thinking.png';
import emoteHappy from '../assets/office/emote_happy.png';
import emoteAlert from '../assets/office/emote_alert.png';
import propBook from '../assets/office/prop_book.png';
import propCoin from '../assets/office/prop_coin.png';
import plantStrip from '../assets/office/plant.png';

const CHAR_URLS: Record<NodeType, string> = {
  input: charInput,
  model: charModel,
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
};

/** All images the office view draws; any entry may be missing on load failure. */
export interface OfficeImages {
  chars: Partial<Record<NodeType, HTMLImageElement>>;
  emotes: Partial<Record<StatusEmote, HTMLImageElement>>;
  floors?: HTMLImageElement;
  book?: HTMLImageElement;
  coin?: HTMLImageElement;
  plant?: HTMLImageElement;
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

/** Load every office sprite in parallel; resolves even when decoding fails. */
export async function loadOfficeAssets(): Promise<OfficeImages> {
  const entries = await Promise.all([
    ...Object.entries(CHAR_URLS).map(async ([k, url]) => [`char:${k}`, await loadImage(url)] as const),
    ...Object.entries(EMOTE_URLS).map(async ([k, url]) => [`emote:${k}`, await loadImage(url)] as const),
    ...([['floors', floorsSheet], ['book', propBook], ['coin', propCoin], ['plant', plantStrip]] as const)
      .map(async ([k, url]) => [k, await loadImage(url)] as const),
  ]);

  const images: OfficeImages = { chars: {}, emotes: {} };
  for (const [key, img] of entries) {
    if (!img) continue;
    const [kind, name] = key.split(':');
    switch (kind) {
      case 'char': images.chars[name as NodeType] = img; break;
      case 'emote': images.emotes[name as StatusEmote] = img; break;
      case 'floors': images.floors = img; break;
      case 'book': images.book = img; break;
      case 'coin': images.coin = img; break;
      case 'plant': images.plant = img; break;
    }
  }
  return images;
}
