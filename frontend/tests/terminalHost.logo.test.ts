import { describe, expect, test } from 'vitest';
import {
  detectArch,
  detectLogoProfile,
  shouldUseAsciiWordmark,
} from '../src/terminalHost.js';
import {
  WORDMARK,
  getWordmark,
  getWordmarkDisplayWidth,
  renderWordmarkFrame,
  logoInkForRow,
  LOGO_INK_TOP,
  LOGO_INK_BODY,
  LOGO_FIELD_BG,
} from '../src/logo.js';

describe('terminalHost detection', () => {
  test('force overrides still resolve', () => {
    expect(detectLogoProfile({ RXYCODE_LOGO_PROFILE: 'macos' })).toBe('macos');
    expect(detectLogoProfile({ RXYCODE_LOGO_PROFILE: 'legacy' })).toBe('legacy-win');
  });

  test('ASCII wordmark path is disabled', () => {
    expect(shouldUseAsciiWordmark('legacy-win')).toBe(false);
  });

  test('detectArch returns known arch', () => {
    expect(['x64', 'ia32', 'arm64', 'other']).toContain(detectArch());
  });
});

describe('unicode wordmark', () => {
  test('always Unicode full blocks', () => {
    expect(getWordmark()[0]).toContain('█');
    expect(WORDMARK[0]).not.toContain('#');
  });

  test('brand colors frozen', () => {
    expect(LOGO_INK_TOP).toBe('#FFB6C1');
    expect(LOGO_INK_BODY).toBe('#FF69B4');
    expect(LOGO_FIELD_BG).toBe('#000000');
    expect(logoInkForRow(0)).toBe(LOGO_INK_TOP);
    expect(logoInkForRow(1)).toBe(LOGO_INK_BODY);
  });

  test('sixth glyph is D-shaped', () => {
    const d = WORDMARK.map((line) => line.slice(45, 52));
    expect(d[2]).not.toBe('███████');
  });

  test('renderWordmarkFrame centers within cols', () => {
    const frame = renderWordmarkFrame(100);
    expect(frame).toHaveLength(7);
    const dw = getWordmarkDisplayWidth();
    const leading = Math.floor((100 - dw) / 2);
    expect(frame[0].startsWith(' '.repeat(leading))).toBe(true);
  });
});
