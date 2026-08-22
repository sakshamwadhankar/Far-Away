import { describe, it, expect } from 'vitest';
import {
  PAL,
  STATUS_VISUALS,
  emoteBob,
  fallbackBubble,
  screenForStatus,
} from './sprites';

describe('status → presentation mapping', () => {
  it('shows the thinking bubble while running', () => {
    expect(STATUS_VISUALS.running.emote).toBe('thinking');
    expect(screenForStatus('running')).toBe('working');
  });

  it('celebrates a done node with a happy bubble and green screen', () => {
    expect(STATUS_VISUALS.done.emote).toBe('happy');
    expect(screenForStatus('done')).toBe('ok');
  });

  it('alarms on error with an alert bubble and red screen', () => {
    expect(STATUS_VISUALS.error.emote).toBe('alert');
    expect(screenForStatus('error')).toBe('fail');
  });

  it('leaves idle desks dark and quiet', () => {
    expect(STATUS_VISUALS.idle.emote).toBeNull();
    expect(screenForStatus('idle')).toBe('off');
  });
});

describe('animation helpers', () => {
  it('bobs emotes between two offsets deterministically', () => {
    const values = new Set([0, 1, 2, 3, 4, 5].map((t) => emoteBob(t * 16)));
    expect(values.size).toBeLessThanOrEqual(2);
    expect([...values]).toEqual(expect.arrayContaining([0, -1]));
  });
});

describe('fallback drawing', () => {
  it('is safe to call without a real canvas (jsdom guard)', () => {
    // fallbackBubble only touches fillRect; we assert it does not throw for
    // every status by feeding it a minimal stub.
    for (const status of ['idle', 'running', 'done', 'error'] as const) {
      const calls: string[] = [];
      const stub = { fillStyle: '', fillRect: (..._a: number[]) => { calls.push('fillRect'); } } as unknown as CanvasRenderingContext2D;
      expect(() => fallbackBubble(stub, 0, 0, status)).not.toThrow();
      expect(calls.length).toBe(3);
    }
  });

  it('keeps the palette aligned with the Ninja Adventure master palette', () => {
    // Colors sampled from Palette.png of the asset pack.
    const packColors: ReadonlySet<string> = new Set([
      '#3b3643', '#816855', '#90775e', '#965340', '#9c6546', '#a3754e',
      '#bd7959', '#c8966b', '#d14b34', '#d3865f', '#e0394c', '#eecf9b',
      '#f1c471', '#56864c', '#71ddee', '#4a5270', '#ffffff',
    ]);
    for (const value of Object.values(PAL)) {
      if (!value.startsWith('#')) continue; // rgba() shadows are derived
      expect(packColors.has(value.toLowerCase()), `unexpected off-palette color ${value}`).toBe(true);
    }
  });
});
