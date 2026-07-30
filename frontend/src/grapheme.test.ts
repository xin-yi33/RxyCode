import { describe, expect, test } from 'vitest';
import {
  clampToGraphemeBoundary,
  graphemeSpans,
  nextGraphemeBoundary,
  previousGraphemeBoundary,
} from './grapheme.js';

describe('grapheme cursor boundaries', () => {
  test('treats a family emoji as one editable unit', () => {
    const value = `A👨‍👩‍👧‍👦B`;
    const spans = graphemeSpans(value);
    expect(spans.map((span) => span.segment)).toEqual(['A', '👨‍👩‍👧‍👦', 'B']);
    expect(nextGraphemeBoundary(value, 1)).toBe(spans[1].end);
    expect(previousGraphemeBoundary(value, spans[1].end)).toBe(1);
    expect(clampToGraphemeBoundary(value, 3)).toBe(1);
  });

  test('treats combining marks as part of the base character', () => {
    const value = `e\u0301x`;
    expect(graphemeSpans(value).map((span) => span.segment)).toEqual(['é', 'x']);
    expect(nextGraphemeBoundary(value, 0)).toBe(2);
    expect(previousGraphemeBoundary(value, 2)).toBe(0);
  });
});
