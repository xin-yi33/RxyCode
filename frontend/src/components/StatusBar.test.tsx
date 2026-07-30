import { describe, it, expect } from 'vitest';
import React from 'react';
import stringWidth from 'string-width';
import StatusBar from './StatusBar.js';
import { renderWithSize, renderWide } from '../testUtil.js';

describe('StatusBar', () => {
  it('shows online + context usage + mode when status is present', () => {
    const status = {
      model: 'deepseek', mode: 'build', context_used_k: 12.3, context_max_k: 256,
      cache_size: '10MB', cache_rate: '50%',
    } as any;
    const { lastFrame } = renderWide(<StatusBar status={status} mode="build" model="deepseek" />);
    const f = lastFrame() ?? '';
    expect(f).toContain('online');
    expect(f).toContain('12.3k');
    expect(f).toContain('10MB');
    expect(f).toContain('Build');
  });

  it('shows offline when status is null', () => {
    const { lastFrame } = renderWide(<StatusBar status={null} mode="plan" model="gpt" thinkingExpanded />);
    const f = lastFrame() ?? '';
    expect(f).toContain('offline');
    expect(f).toContain('Plan');
  });

  it('fits an 80-column terminal on exactly one row', () => {
    const status = {
      model: 'deepseek', mode: 'build', context_used_k: 12.3, context_max_k: 256,
      cache_size: '10MB', cache_rate: '50%',
    } as any;
    const { lastFrame } = renderWithSize(
      <StatusBar status={status} mode="build" model="deepseek" />,
      80,
      24,
    );
    const frame = lastFrame() ?? '';
    const lines = frame.split('\n');
    expect(lines).toHaveLength(1);
    expect(stringWidth(lines[0])).toBeLessThanOrEqual(80);
    expect(frame).toContain('online');
    expect(frame).toContain('Build');
  });
});
