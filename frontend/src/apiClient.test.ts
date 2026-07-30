import { afterEach, describe, expect, it, vi } from 'vitest';

const originalToken = process.env.RXYCODE_API_TOKEN;

afterEach(() => {
  if (originalToken === undefined) delete process.env.RXYCODE_API_TOKEN;
  else process.env.RXYCODE_API_TOKEN = originalToken;
  vi.resetModules();
});

describe('local API client security', () => {
  it('automatically attaches the launcher bearer token', async () => {
    process.env.RXYCODE_API_TOKEN = 'per-launch-test-token';
    vi.resetModules();
    const { authorizationHeaders } = await import('./apiClient.js');

    expect(authorizationHeaders()).toEqual({
      Authorization: `Bearer ${process.env.RXYCODE_API_TOKEN}`,
    });
  });

  it('logs only a slash command name, never its credential arguments', async () => {
    const { safeCommandLabel } = await import('./apiClient.js');
    expect(
      safeCommandLabel('/addmodel provider sk-do-not-log https://example.test alias'),
    ).toBe('/addmodel');
  });
});
