export interface GraphemeSpan {
  segment: string;
  start: number;
  end: number;
}

const combiningMark = /\p{Mark}/u;
const variationSelector = /[\uFE00-\uFE0F]/u;
const emojiModifier = /[\u{1F3FB}-\u{1F3FF}]/u;
const zeroWidthJoiner = '\u200D';

export function graphemeSpans(value: string): GraphemeSpan[] {
  if (typeof Intl.Segmenter === 'function') {
    const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
    return Array.from(segmenter.segment(value), ({ segment, index }) => ({
      segment,
      start: index,
      end: index + segment.length,
    }));
  }

  const spans: GraphemeSpan[] = [];
  for (const codePoint of Array.from(value)) {
    const start = spans.length > 0 ? spans[spans.length - 1].end : 0;
    const previous = spans[spans.length - 1];
    const joinsPrevious = previous && (
      combiningMark.test(codePoint)
      || variationSelector.test(codePoint)
      || emojiModifier.test(codePoint)
      || previous.segment.endsWith(zeroWidthJoiner)
      || codePoint === zeroWidthJoiner
    );
    if (joinsPrevious) {
      previous.segment += codePoint;
      previous.end += codePoint.length;
    } else {
      spans.push({ segment: codePoint, start, end: start + codePoint.length });
    }
  }
  return spans;
}

export function clampToGraphemeBoundary(value: string, offset: number): number {
  const clamped = Math.max(0, Math.min(value.length, offset));
  if (clamped === 0 || clamped === value.length) return clamped;
  for (const span of graphemeSpans(value)) {
    if (clamped <= span.start) return span.start;
    if (clamped < span.end) return span.start;
  }
  return value.length;
}

export function previousGraphemeBoundary(value: string, offset: number): number {
  const current = clampToGraphemeBoundary(value, offset);
  let previous = 0;
  for (const span of graphemeSpans(value)) {
    if (span.end >= current) return span.start;
    previous = span.end;
  }
  return previous;
}

export function nextGraphemeBoundary(value: string, offset: number): number {
  const current = clampToGraphemeBoundary(value, offset);
  for (const span of graphemeSpans(value)) {
    if (span.start >= current) return span.end;
  }
  return value.length;
}
