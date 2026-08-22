import { describe, it, expect } from 'vitest';
import {
  DESK_H,
  DESK_W,
  MAX_COLS,
  WALL_TOP_H,
  computeDeskLayout,
  orderNodesForOffice,
  type OfficeNodeLike,
} from './layout';

function makeNodes(types: string[]): OfficeNodeLike[] {
  return types.map((type, i) => ({ id: `node-${i}`, data: { type } }));
}

describe('computeDeskLayout', () => {
  it('handles an empty pipeline', () => {
    const layout = computeDeskLayout(0);
    expect(layout.slots).toHaveLength(0);
    expect(layout.cols).toBe(0);
    expect(layout.roomW).toBeGreaterThan(0);
    expect(layout.roomH).toBeGreaterThan(0);
    expect(layout.walls.length).toBeGreaterThan(0);
    expect(layout.props.length).toBeGreaterThan(0);
  });

  it('places every desk for a single node inside the room', () => {
    const layout = computeDeskLayout(1);
    expect(layout.slots).toHaveLength(1);
    const s = layout.slots[0];
    expect(s.x).toBeGreaterThanOrEqual(0);
    expect(s.y).toBeGreaterThanOrEqual(WALL_TOP_H); // below the wall band
    expect(s.x + DESK_W).toBeLessThanOrEqual(layout.roomW);
    expect(s.y + DESK_H).toBeLessThanOrEqual(layout.roomH);
  });

  it('gives every node a unique, non-overlapping slot', () => {
    const count = 11;
    const layout = computeDeskLayout(count);
    expect(layout.slots).toHaveLength(count);
    const seen = new Set(layout.slots.map((s) => `${s.x},${s.y}`));
    expect(seen.size).toBe(count);
  });

  it('caps the column count and grows rows instead', () => {
    const layout = computeDeskLayout(50);
    expect(layout.cols).toBe(MAX_COLS);
    expect(layout.rows * layout.cols).toBeGreaterThanOrEqual(50);
  });

  it('generates multi-room partitioned departments when count >= 4', () => {
    const layout = computeDeskLayout(6);
    expect(layout.rooms.length).toBe(2);
    expect(layout.doorways.length).toBeGreaterThanOrEqual(1);
    expect(layout.walls.some((w) => w.isInterior)).toBe(true);
    expect(layout.props.some((p) => p.kind === 'server')).toBe(true);
  });

  it('populates decorative environment props (plants, clocks, windows, bookshelves, coffeeStation, lamps, whiteboard, cabinet, crate)', () => {
    const layout = computeDeskLayout(4);
    const kinds = new Set(layout.props.map((p) => p.kind));
    expect(kinds.has('plant')).toBe(true);
    expect(kinds.has('window')).toBe(true);
    expect(kinds.has('clock')).toBe(true);
    expect(kinds.has('bookshelf')).toBe(true);
    expect(kinds.has('waterCooler')).toBe(true);
    expect(kinds.has('lamp')).toBe(true);
    expect(kinds.has('coffeeStation')).toBe(true);
    expect(kinds.has('cabinet')).toBe(true);
    expect(kinds.has('crate')).toBe(true);
    expect(kinds.has('whiteboard')).toBe(true);
    expect(kinds.has('trashBin')).toBe(true);
  });

  it('is deterministic for a given count', () => {
    expect(computeDeskLayout(7)).toEqual(computeDeskLayout(7));
  });
});

describe('orderNodesForOffice (real)', () => {
  it('groups by type priority while keeping stable order', () => {
    const nodes = makeNodes(['model', 'input', 'output', 'model']);
    const ordered = orderNodesForOffice(nodes);
    expect(ordered.map((n) => n.data.type)).toEqual(['input', 'model', 'model', 'output']);
    // The two models keep their original relative order.
    const modelIds = ordered.filter((n) => n.data.type === 'model').map((n) => n.id);
    expect(modelIds).toEqual(['node-0', 'node-3']);
  });

  it('does not mutate the input array', () => {
    const nodes = makeNodes(['output', 'input']);
    const copy = [...nodes];
    orderNodesForOffice(nodes);
    expect(nodes).toEqual(copy);
  });

  it('sorts unknown types after known ones but before outputs are last', () => {
    const nodes = makeNodes(['mystery', 'input', 'output']);
    const ordered = orderNodesForOffice(nodes);
    expect(ordered.map((n) => n.data.type)).toEqual(['input', 'mystery', 'output']);
  });
});
