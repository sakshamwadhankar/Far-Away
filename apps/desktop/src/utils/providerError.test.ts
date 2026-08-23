import { describe, it, expect } from 'vitest';
import { summarizeProviderError } from './providerError';

const REAL_GEMINI_429 = String.raw`429 Too Many Requests. {'message': '{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash\nPlease retry in 57.621070225s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
       "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                       "quotaDimensions": {"location": "global", "model": "gemini-3.6-flash"},
                       "quotaValue": "20"}]},
      {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "57s"}
    ]
  }
}', 'status': 'Too Many Requests'}`;

describe('summarizeProviderError', () => {
  it('turns the Gemini quota wall into one actionable line', () => {
    const out = summarizeProviderError(REAL_GEMINI_429);
    expect(out).toContain('quota exceeded');
    expect(out).toContain('gemini-3.6-flash');
    expect(out).toContain('20');
    expect(out).toContain('/day');
    // The point of the exercise: drastically shorter than the raw blob.
    expect(out.length).toBeLessThan(250);
    expect(REAL_GEMINI_429.length).toBeGreaterThan(800);
  });

  it('says a daily cap will not clear with a short wait', () => {
    expect(summarizeProviderError(REAL_GEMINI_429)).toContain('does not reset');
  });

  it('distinguishes a 503 overload from a quota wall', () => {
    const raw = String.raw`503 Service Unavailable. {'message': '{
  "error": { "code": 503,
    "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
    "status": "UNAVAILABLE" } }', 'status': 'Service Unavailable'}`;
    const out = summarizeProviderError(raw);
    expect(out).toContain('overloaded');
    expect(out).not.toContain('quota');
    expect(out.length).toBeLessThan(200);
  });

  it('passes an unrecognised error through instead of swallowing it', () => {
    expect(summarizeProviderError('Connection reset by peer')).toBe(
      'Connection reset by peer',
    );
  });

  it('truncates a very long unrecognised error', () => {
    const out = summarizeProviderError('x'.repeat(5000));
    expect(out.length).toBeLessThan(320);
    expect(out.endsWith('…')).toBe(true);
  });

  it('handles empty input', () => {
    expect(summarizeProviderError('')).toBe('Unknown error');
  });
});
