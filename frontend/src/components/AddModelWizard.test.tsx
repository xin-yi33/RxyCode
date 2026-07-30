import { describe, it, expect, vi } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import AddModelWizard from './AddModelWizard.js';

const base = {
  step: 'provider_model_id' as const,
  data: {} as Record<string, string>,
  onSubmit: () => {},
  onCancel: () => {},
};

const settle = (ms = 40) => new Promise((r) => setTimeout(r, ms));

describe('AddModelWizard', () => {
  it('renders the current step title and box chrome', () => {
    const { lastFrame } = render(<AddModelWizard {...base} />);
    const f = lastFrame() ?? '';
    expect(f).toContain('添加模型');
    expect(f).toContain('[1/4]');
  });

  it('calls onSubmit with the typed text on Enter', async () => {
    const onSubmit = vi.fn();
    const { stdin } = render(<AddModelWizard {...base} onSubmit={onSubmit} />);
    await settle();
    stdin.write('gpt-4');
    await settle();
    stdin.write('\r');
    await settle();
    expect(onSubmit).toHaveBeenCalledWith('gpt-4');
  });

  it('calls onCancel on ESC', async () => {
    const onCancel = vi.fn();
    const { stdin } = render(<AddModelWizard {...base} onCancel={onCancel} />);
    await settle();
    stdin.write('\x1b');
    await settle();
    expect(onCancel).toHaveBeenCalled();
  });

  it('masks the API key while it is being entered', async () => {
    const { stdin, lastFrame } = render(
      <AddModelWizard {...base} step="api_key" />,
    );
    await settle();
    stdin.write('sk-visible-secret');
    await settle();

    const frame = lastFrame() ?? '';
    expect(frame).not.toContain('sk-visible-secret');
    expect(frame).toContain('*'.repeat('sk-visible-secret'.length));
  });

  it('shows the error line when the error prop is set', () => {
    const { lastFrame } = render(<AddModelWizard {...base} error='bad url' />);
    expect((lastFrame() ?? '')).toContain('bad url');
  });

  it('shows collected (masked) fields from data', () => {
    const { lastFrame } = render(
      <AddModelWizard
        step="api_url"
        data={{ providerModelId: 'gpt-4', apiKey: 'sk-1234567890abcd' }}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('gpt-4');
    expect(f).toContain('sk-1...abcd'); // masked key
    expect(f).toContain('[3/4]');
  });
});
