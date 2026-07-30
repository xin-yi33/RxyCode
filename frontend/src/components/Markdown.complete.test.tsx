import React from 'react';
import { render } from 'ink-testing-library';
import { describe, expect, test } from 'vitest';
import Markdown from './Markdown.js';

describe('Markdown complete code rendering', () => {
  test('renders code beyond the previous fifty-line limit', () => {
    const code = Array.from({ length: 70 }, (_, index) => `line-${index + 1}`).join('\n');
    const { lastFrame } = render(<Markdown content={`\`\`\`text\n${code}\n\`\`\``} />);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('line-1');
    expect(frame).toContain('line-70');
    expect(frame).not.toContain('more lines');
  });
});
