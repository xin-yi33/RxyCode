import { describe, it, expect } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ProgressBanner from './ProgressBanner.js';

describe('ProgressBanner', () => {
  it('renders nothing when not streaming', () => {
    const { lastFrame } = render(
      <ProgressBanner isStreaming={false} startedAt={null} stepLabel="" activity="" />,
    );
    expect(lastFrame()).toBe('');
  });

  it('renders the cancel hint and activity when streaming', () => {
    const { lastFrame } = render(
      <ProgressBanner isStreaming={true} startedAt={Date.now()} stepLabel="第 1/3 步" activity="thinking" />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('ESC');
    expect(f).toContain('thinking');
  });
});
