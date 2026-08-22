import { describe, it, expect } from 'vitest';
import {
  PAL,
  STATUS_VISUALS,
  drawAgent,
  drawDesk,
  drawDoorways,
  drawOfficeFlows,
  drawOfficeProps,
  drawOfficeWalls,
  drawSmokePuff,
  drawSpinningCoin,
  emoteBob,
  fallbackBubble,
  screenForStatus,
} from './sprites';
import type { OfficeImages } from './assets';

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

describe('drawing routines (jsdom-safe)', () => {
  function makeMockCtx(): CanvasRenderingContext2D {
    return {
      fillStyle: '',
      strokeStyle: '',
      lineWidth: 1,
      fillRect: () => {},
      strokeRect: () => {},
      beginPath: () => {},
      moveTo: () => {},
      lineTo: () => {},
      stroke: () => {},
      save: () => {},
      restore: () => {},
      setLineDash: () => {},
      drawImage: () => {},
    } as unknown as CanvasRenderingContext2D;
  }

  it('draws agent states safely without throwing', () => {
    const ctx = makeMockCtx();
    for (const status of ['idle', 'running', 'done', 'error'] as const) {
      expect(() => drawAgent(ctx, 10, 10, status, 30, null)).not.toThrow();
    }
  });

  it('draws desk and monitor states safely', () => {
    const ctx = makeMockCtx();
    for (const status of ['idle', 'running', 'done', 'error'] as const) {
      expect(() =>
        drawDesk(ctx, 10, 10, '#3a7d44', screenForStatus(status), status, 15, true, false, null),
      ).not.toThrow();
    }
  });

  it('draws walls, doorways, and props safely', () => {
    const ctx = makeMockCtx();
    const mockImgs: OfficeImages = { chars: {}, emotes: {} };
    expect(() =>
      drawOfficeWalls(
        ctx,
        mockImgs,
        [
          { x: 0, y: 0, w: 400, h: 32 },
          { x: 200, y: 32, w: 8, h: 100, isInterior: true },
        ],
        400,
        300,
      ),
    ).not.toThrow();
    expect(() => drawDoorways(ctx, [{ x: 190, y: 130, w: 28, h: 32 }])).not.toThrow();
    expect(() =>
      drawOfficeProps(
        ctx,
        mockImgs,
        [
          { kind: 'plant', x: 20, y: 40, w: 16, h: 16 },
          { kind: 'server', x: 50, y: 40, w: 18, h: 32 },
          { kind: 'waterCooler', x: 80, y: 40, w: 16, h: 28 },
          { kind: 'bookshelf', x: 110, y: 40, w: 28, h: 32 },
          { kind: 'window', x: 150, y: 10, w: 24, h: 20 },
          { kind: 'clock', x: 200, y: 10, w: 12, h: 12 },
          { kind: 'bulletin', x: 230, y: 10, w: 20, h: 14 },
        ],
        45,
      ),
    ).not.toThrow();
  });

  it('draws smoke puff and spinning coins safely', () => {
    const ctx = makeMockCtx();
    const mockImgs: OfficeImages = { chars: {}, emotes: {} };
    expect(() => drawSmokePuff(ctx, mockImgs, 30, 20, 10)).not.toThrow();
    expect(() => drawSpinningCoin(ctx, mockImgs, 10, 10, 15)).not.toThrow();
  });

  it('draws animated data flow conduits safely', () => {
    const ctx = makeMockCtx();
    const slotMap = new Map([
      ['n1', { x: 20, y: 40 }],
      ['n2', { x: 120, y: 40 }],
    ]);
    expect(() =>
      drawOfficeFlows(
        ctx,
        [{ id: 'e1', source: 'n1', target: 'n2' }],
        new Set(['e1']),
        slotMap,
        25,
      ),
    ).not.toThrow();
  });

  it('fallbackBubble works with minimal stub', () => {
    for (const status of ['idle', 'running', 'done', 'error'] as const) {
      const calls: string[] = [];
      const stub = {
        fillStyle: '',
        fillRect: (..._a: number[]) => {
          calls.push('fillRect');
        },
      } as unknown as CanvasRenderingContext2D;
      expect(() => fallbackBubble(stub, 0, 0, status)).not.toThrow();
      expect(calls.length).toBe(3);
    }
  });

  it('keeps the palette aligned with the Ninja Adventure master palette', () => {
    const packColors: ReadonlySet<string> = new Set([
      '#3b3643', '#816855', '#90775e', '#965340', '#9c6546', '#a3754e',
      '#bd7959', '#c8966b', '#d14b34', '#d3865f', '#e0394c', '#eecf9b',
      '#f1c471', '#56864c', '#71ddee', '#4a5270', '#ffffff',
    ]);
    for (const value of Object.values(PAL)) {
      if (!value.startsWith('#')) continue;
      expect(packColors.has(value.toLowerCase()), `unexpected off-palette color ${value}`).toBe(true);
    }
  });
});
