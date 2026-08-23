/**
 * Condense a raw provider error into one line a person can act on.
 *
 * Provider SDKs surface failures as a stringified JSON body — Google's quota
 * error alone is ~40 lines of nested `details`. Dropping that verbatim into
 * the chat buries the one fact that matters (you are out of quota) in noise.
 * The full text is still written to the run trace, which is where the detail
 * belongs; this is only for the conversational surface.
 *
 * Anything unrecognised is passed through, trimmed to a sane length, so a
 * novel error is never swallowed or mangled.
 */

const MAX_PASSTHROUGH = 300;

function firstMatch(text: string, pattern: RegExp): string | null {
  const m = text.match(pattern);
  return m ? m[1] : null;
}

export function summarizeProviderError(raw: string): string {
  if (!raw) return 'Unknown error';

  const isQuota =
    raw.includes('RESOURCE_EXHAUSTED') ||
    raw.includes('429') ||
    /quota/i.test(raw);

  if (isQuota) {
    const model = firstMatch(raw, /"model":\s*"([^"]+)"/);
    const limit = firstMatch(raw, /"quotaValue":\s*"?(\d+)"?/);
    const perDay = /PerDay|per_day|RequestsPerDay/i.test(raw);
    const retry = firstMatch(raw, /"retryDelay":\s*"(\d+)s?"/)
      ?? firstMatch(raw, /retry in (\d+)(?:\.\d+)?s/i);

    const parts: string[] = ['API quota exceeded'];
    if (model) parts.push(`for ${model}`);
    if (limit) parts.push(`— limit ${limit} request${limit === '1' ? '' : 's'}${perDay ? '/day' : ''}`);

    let msg = parts.join(' ') + '.';
    msg += perDay
      ? ' A daily cap does not reset with a short wait — use a different model or key, or wait for the quota to reset.'
      : retry
        ? ` Retry in about ${retry}s.`
        : '';
    return msg;
  }

  // Provider overload. Distinct from a quota wall: it clears on its own, so
  // the useful advice is "wait", not "change model or key".
  if (raw.includes('UNAVAILABLE') || /(^|[^0-9])503([^0-9]|$)/.test(raw)) {
    const model = firstMatch(raw, /"model":\s*"([^"]+)"/);
    return (
      `The model provider is temporarily overloaded${model ? ` (${model})` : ''}` +
      ' — a 503 on their side, not a limit on your account.' +
      ' It usually clears on its own; try again in a moment.'
    );
  }

  const collapsed = raw.replace(/\s+/g, ' ').trim();
  return collapsed.length > MAX_PASSTHROUGH
    ? `${collapsed.slice(0, MAX_PASSTHROUGH)}…`
    : collapsed;
}
