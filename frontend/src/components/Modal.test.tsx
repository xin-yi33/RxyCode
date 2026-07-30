import { describe, test, expect, vi } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import Modal from './Modal.js';
import type { ModalItem } from './Modal.js';

const sampleItems: ModalItem[] = [
  { id: '1', label: 'Session A', desc: '2024-01-01' },
  { id: '2', label: 'Session B', desc: '2024-01-02' },
  { id: '3', label: 'Session C', desc: '2024-01-03' },
];

describe('Modal component', () => {
  test('renders title, items, and footer', () => {
    const { lastFrame } = render(
      <Modal title="Session" items={sampleItems} onSelect={() => {}} onClose={() => {}} />
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Session');
    expect(f).toContain('Session A');
    expect(f).toContain('Session B');
    expect(f).toContain('Session C');
    expect(f).toContain('esc');
  });

  test('highlighted item shows arrow', () => {
    const { lastFrame } = render(
      <Modal title="Select Model" items={sampleItems} onSelect={() => {}} onClose={() => {}} accentColor="#89b4fa" />
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('\u276F');
  });

  test('ESC calls onClose', async () => {
    const onClose = vi.fn();
    const { stdin } = render(
      <Modal title="Memory" items={sampleItems} onSelect={() => {}} onClose={onClose} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\x1b');
    await new Promise(r => setTimeout(r, 50));
    expect(onClose).toHaveBeenCalled();
  });

  test('Enter calls onSelect with current index', async () => {
    const onSelect = vi.fn();
    const { stdin } = render(
      <Modal title="Skills" items={sampleItems} onSelect={onSelect} onClose={() => {}} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\r');
    await new Promise(r => setTimeout(r, 50));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  test('down arrow changes selection', async () => {
    const onSelect = vi.fn();
    const { stdin } = render(
      <Modal title="MCP Servers" items={sampleItems} onSelect={onSelect} onClose={() => {}} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\x1b[B');
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\r');
    await new Promise(r => setTimeout(r, 50));
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});
