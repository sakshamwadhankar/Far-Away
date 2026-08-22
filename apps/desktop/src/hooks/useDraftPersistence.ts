import { useEffect, useRef } from 'react';
import type { Pipeline } from '@shared/types';

/**
 * Debounced canvas autosave + crash-recovery draft, stored in localStorage.
 *
 * The stored shape records when the draft was written and whether it
 * originated from a bundled template, so the restore banner can say where the
 * work came from instead of silently passing a template off as the user's own.
 */

export const DRAFT_STORAGE_KEY = 'komvos_autosave_draft_v1';

// 1.5 s after the last change. Canvas edits (dragging, connecting ports,
// typing in a config field) fire many state updates per second; 1.5 s of
// quiet means autosave runs once per natural pause instead of per keystroke,
// so it never competes with interaction for the main thread. It is also far
// below the interval at which a crash would lose meaningful work.
export const AUTOSAVE_DEBOUNCE_MS = 1500;

export interface StoredDraft {
  savedAt: number;
  /** Set when the draft originated from loading a bundled template. */
  templateName?: string;
  pipeline: Pipeline;
}

export function loadDraft(): StoredDraft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredDraft;
    if (!parsed || typeof parsed !== 'object' || !parsed.pipeline?.nodes) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearDraft(): void {
  try {
    window.localStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode etc.) — nothing to clear.
  }
}

/**
 * Autosave `getPipeline()`'s result DEBOUNCE_MS after the last change to
 * `deps`. Passing `null` from getPipeline skips the write (e.g. mid-run or
 * empty canvas). The timer resets on every dep change; unmount cancels it so
 * tests and route teardown do not write after the fact.
 */
export function useAutosaveDraft(
  getPipeline: () => StoredDraft | null,
  deps: readonly unknown[],
): void {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const getterRef = useRef(getPipeline);
  getterRef.current = getPipeline;

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const draft = getterRef.current();
      if (!draft) return;
      try {
        window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      } catch {
        // Storage full/unavailable — autosave is best-effort by design.
      }
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
