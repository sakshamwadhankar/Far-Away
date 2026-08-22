// jsdom exposes localStorage only for a real origin. Depending on the jsdom /
// vitest combination it can still be absent, and several tests depend on it,
// so guarantee a working implementation before any test module loads.
if (typeof globalThis.localStorage === 'undefined') {
  let store: Record<string, string> = {};
  const shim: Storage = {
    get length() { return Object.keys(store).length; },
    clear: () => { store = {}; },
    getItem: (k: string) => (k in store ? store[k] : null),
    key: (i: number) => Object.keys(store)[i] ?? null,
    removeItem: (k: string) => { delete store[k]; },
    setItem: (k: string, v: string) => { store[k] = String(v); },
  };
  Object.defineProperty(globalThis, 'localStorage', { value: shim, configurable: true, writable: true });
}
