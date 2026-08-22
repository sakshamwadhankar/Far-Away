/**
 * Read a localStorage key that was renamed during the NeuralFlow -> Komvos
 * rebrand, migrating the old entry on first read.
 *
 * Naively switching keys would reset the stored value and re-trigger
 * onboarding / the product tour for every existing user; this copies the old
 * value to the new key (once) and removes the legacy entry.
 */
export function migratedRead(oldKey: string, newKey: string): string | null {
  try {
    const fresh = window.localStorage.getItem(newKey);
    if (fresh !== null) return fresh;
    const legacy = window.localStorage.getItem(oldKey);
    if (legacy !== null) {
      window.localStorage.setItem(newKey, legacy);
      window.localStorage.removeItem(oldKey);
    }
    return legacy;
  } catch {
    return null;
  }
}

/** Write-through helper: always writes the current (new) key. */
export function writeMigratedKey(newKey: string, value: string): void {
  try {
    window.localStorage.setItem(newKey, value);
  } catch {
    // Storage unavailable — best effort.
  }
}
