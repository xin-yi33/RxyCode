// Vitest test - verify RxyCode logo renders correctly
import React from 'react';
import { test, expect, describe } from 'vitest';
import { render } from 'ink-testing-library';
import stringWidth from 'string-width';
import { WORDMARK, WORDMARK_DISPLAY_WIDTH, padToDisplayWidth, centerLine } from '../src/logo.js';
import { renderWithSize } from '../src/testUtil.js';

describe('logo structure', () => {
  test('logo has 7 lines (7x7 block style)', () => {
    expect(WORDMARK.length).toBe(7);
  });

  test('logo lines have consistent width of 61 chars (ljust)', () => {
    const widths = WORDMARK.map(line => line.length);
    console.log('Line widths:', widths);
    const allSame = widths.every(w => w === widths[0]);
    expect(allSame).toBe(true);
    expect(widths[0]).toBe(61);
  });

  test('sixth glyph is D-shaped (not H mid-bar)', () => {
    const d = WORDMARK.map((line) => line.slice(45, 52));
    // H would put a full ███████ on the third row
    expect(d[2]).not.toBe('███████');
    expect(d[0].startsWith('██')).toBe(true);
    expect(d[6].trimEnd().length).toBeGreaterThanOrEqual(6);
  });

  test('wordmark lines have equal display width when padded', () => {
    const widths = WORDMARK.map((line) =>
      stringWidth(padToDisplayWidth(line.replace(/ +$/, ''), WORDMARK_DISPLAY_WIDTH)),
    );
    expect(new Set(widths).size).toBe(1);
    expect(widths[0]).toBe(WORDMARK_DISPLAY_WIDTH);
  });
});

describe('centerLine', () => {
  test('centers short text by display width', () => {
    expect(centerLine('abc', 10)).toBe('   abc');
  });

  test('returns original when wider than terminal', () => {
    expect(centerLine('hello world', 5)).toBe('hello world');
  });

  test('centers exact width text', () => {
    expect(centerLine('abcde', 5)).toBe('abcde');
  });

  test('centers 61-char logo in 100-col terminal', () => {
    const centered = centerLine(WORDMARK[0], 100);
    expect(stringWidth(centered)).toBe(80); // 19 + 61 display width
    expect(centered.startsWith(' '.repeat(19))).toBe(true);
  });
});

describe('Banner component', () => {
  test('renders all 7 logo lines + subtitle', async () => {
    const BannerModule = await import('../src/components/Banner.js');
    const Banner = BannerModule.default;
    const { lastFrame } = render(React.createElement(Banner));
    const frame = lastFrame();
    console.log('\n=== Banner rendered output ===');
    console.log(frame);
    console.log('=== end ===\n');

    WORDMARK.forEach((line, i) => {
      const trimmedLine = line.trimEnd();
      expect(frame, `Logo line ${i} should be in frame`).toContain(trimmedLine);
    });

    expect(frame).toContain('General-Purpose AI Agent');
    expect(frame).not.toContain('Coding Assistant');
  });

  test('banner output is centered in 100-col terminal', async () => {
    const BannerModule = await import('../src/components/Banner.js');
    const Banner = BannerModule.default;
    const { lastFrame } = render(React.createElement(Banner));
    const frame = lastFrame();
    const lines = frame.split('\n');

    const logoLines = lines.filter(l => l.includes('█'));
    console.log('Logo lines found:', logoLines.length);
    expect(logoLines.length).toBe(7);

    const leadingSpacesList = logoLines.map(line => line.match(/^( *)/)?.[0].length || 0);
    console.log('Leading spaces per line:', leadingSpacesList);

    const expectedLeading = Math.floor((100 - WORDMARK_DISPLAY_WIDTH) / 2);
    leadingSpacesList.forEach((s, i) => {
      expect(s, `Line ${i} should have ${expectedLeading} leading spaces`).toBe(expectedLeading);
    });
  });

  test('banner has no ZWJ padding', async () => {
    const Banner = (await import('../src/components/Banner.js')).default;
    const { lastFrame } = renderWithSize(React.createElement(Banner), 100, 24);
    const frame = lastFrame() ?? '';
    expect(frame).not.toMatch(/\u200D/);
  });
});

describe('Banner display width matrix', () => {
  for (const cols of [80, 100, 120]) {
    test(`centers logo at ${cols} columns by display width`, async () => {
      const Banner = (await import('../src/components/Banner.js')).default;
      const { lastFrame } = renderWithSize(React.createElement(Banner), cols, 24);
      const frame = lastFrame() ?? '';

      expect(frame).not.toMatch(/\u200D/);

      const logoLines = frame.split('\n').filter((l) => l.includes('█'));
      expect(logoLines.length).toBe(7);

      const displayWidths = logoLines.map((l) => stringWidth(l));
      expect(new Set(displayWidths).size).toBe(1);

      const expectedLeading = Math.floor((cols - WORDMARK_DISPLAY_WIDTH) / 2);
      logoLines.forEach((line, i) => {
        const leading = line.match(/^( *)/)?.[1]?.length ?? 0;
        expect(leading, `line ${i} at ${cols} cols`).toBe(expectedLeading);
      });
    });
  }
});
