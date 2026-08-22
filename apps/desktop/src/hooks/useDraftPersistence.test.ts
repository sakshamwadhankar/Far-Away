import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Pipeline } from '@shared/types';
import {
  clearDraft,
  DRAFT_STORAGE_KEY,
  AUTOSAVE_DEBOUNCE_MS,
  loadDraft,
  useAutosaveDraft,
} from './useDraftPersistence';
import type { StoredDraft } from './useDraftPersistence';

function makePipeline(name: string): Pipeline {
  return {
    schema_version: '2.1',
    id: '00000000-0000-4000-a000-000000000001',
    name,
    version: '1.0.0',
    nodes: [],
    edges: [],
    endpoints: {},
  } as Pipeline;
}

describe('useDraftPersistence', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeDraft(name: string): StoredDraft {
    return { savedAt: Date.now(), pipeline: makePipeline(name) };
  }

  it('writes the draft once the debounce elapses', () => {
    let draft: StoredDraft | null = makeDraft('one');
    const { rerender } = renderHook(
      ({ deps }: { deps: number[] }) =>
        useAutosaveDraft(() => draft, deps),
      { initialProps: { deps: [0] } },
    );

    expect(loadDraft()).toBeNull();
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS - 1);
    });
    expect(loadDraft()).toBeNull(); // not yet

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(loadDraft()?.pipeline.name).toBe('one');

    // A later change replaces the stored draft.
    draft = makeDraft('two');
    rerender({ deps: [1] });
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS);
    });
    expect(loadDraft()?.pipeline.name).toBe('two');
  });

  it('resets the timer when deps change before the debounce fires', () => {
    const draft: StoredDraft = makeDraft('reset');
    const { rerender } = renderHook(
      ({ deps }: { deps: number[] }) => useAutosaveDraft(() => draft, deps),
      { initialProps: { deps: [0] } },
    );

    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS - 200);
    });
    rerender({ deps: [1] }); // interaction happened -> timer restarts
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS - 300);
    });
    expect(loadDraft()).toBeNull();

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(loadDraft()?.pipeline.name).toBe('reset');
  });

  it('skips writing when getPipeline returns null (mid-run / empty)', () => {
    renderHook(() => useAutosaveDraft(() => null, [0]));
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS * 2);
    });
    expect(loadDraft()).toBeNull();
    expect(window.localStorage.getItem(DRAFT_STORAGE_KEY)).toBeNull();
  });

  it('ignores corrupt stored data and clears cleanly', () => {
    window.localStorage.setItem(DRAFT_STORAGE_KEY, '{not json');
    expect(loadDraft()).toBeNull();

    window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(makeDraft('ok')));
    expect(loadDraft()?.pipeline.name).toBe('ok');
    clearDraft();
    expect(loadDraft()).toBeNull();
  });
});
