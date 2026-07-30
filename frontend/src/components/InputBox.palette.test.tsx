import { describe, test, expect, vi } from 'vitest';
import { render } from 'ink-testing-library';
import React, { useState } from 'react';
import InputBox, { paletteTopRow } from './InputBox.js';

const baseProps = {
  mode: 'build' as const,
  onSubmit: () => {},
  onCycleMode: () => {},
  onCommand: () => {},
  isStreaming: false,
  onCancel: () => {},
  showCommandPalette: true,
  onToggleCommandPalette: () => {},
  onCommandPaletteSelect: () => {},
};

function PaletteHarness({ initiallyOpen = true }: { initiallyOpen?: boolean }) {
  const [showCommandPalette, setShowCommandPalette] = useState(initiallyOpen);
  return (
    <InputBox
      {...baseProps}
      showCommandPalette={showCommandPalette}
      onToggleCommandPalette={() => setShowCommandPalette((visible) => !visible)}
    />
  );
}

describe('Command palette (opencode style)', () => {
  test('shows one readable ESC cancel label and cancels once while streaming', async () => {
    const onCancel = vi.fn();
    const { lastFrame, stdin } = render(
      <InputBox {...baseProps} showCommandPalette={false} isStreaming={true} onCancel={onCancel} />,
    );
    const frame = lastFrame() ?? '';
    expect(frame.match(/ESC 取消/g)).toHaveLength(1);
    expect(frame).not.toContain('\\u53D6\\u6D88');

    await new Promise(resolve => setTimeout(resolve, 50));
    stdin.write('\u001b');
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  test('renders title, search placeholder, footer and a known command', () => {
    const { lastFrame } = render(<InputBox {...baseProps} />);
    const f = lastFrame() ?? '';
    expect(f).toContain('\u547D\u4EE4\u9762\u677F');
    expect(f).toContain('\u641C\u7D22\u547D\u4EE4');
    expect(f).toContain('esc');
    expect(f).toContain('/session');
  });

  test('fixed height: line count stable while navigating (no flicker)', () => {
    const { lastFrame, stdin } = render(<InputBox {...baseProps} />);
    const countLines = (s: string) => s.split('\n').length;
    const before = countLines(lastFrame() ?? '');
    for (let i = 0; i < 6; i++) stdin.write('\x1b[B');
    for (let i = 0; i < 3; i++) stdin.write('\x1b[A');
    const after = countLines(lastFrame() ?? '');
    expect(after).toBe(before);
  });

  test('paletteTopRow geometry is deterministic', () => {
    expect(paletteTopRow(40)).toBe(40 - 18 + 1);
    expect(paletteTopRow(100)).toBe(100 - 18 + 1);
  });

  test('Enter selects current item and calls onCommandPaletteSelect', async () => {
    const onSelect = vi.fn();
    const { stdin } = render(<InputBox {...baseProps} onCommandPaletteSelect={onSelect} />);
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\r'); // Enter
    await new Promise(r => setTimeout(r, 50));
    expect(onSelect).toHaveBeenCalled();
  });

  test('ESC closes palette', async () => {
    const onToggle = vi.fn();
    const { stdin } = render(<InputBox {...baseProps} onToggleCommandPalette={onToggle} />);
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\x1b'); // ESC
    await new Promise(r => setTimeout(r, 50));
    expect(onToggle).toHaveBeenCalled();
  });

  test('keeps existing text and the first input after a Ctrl+P palette round trip', async () => {
    const { lastFrame, stdin } = render(<PaletteHarness initiallyOpen={false} />);
    await new Promise(r => setTimeout(r, 50));
    stdin.write('ABC');
    await new Promise(r => setTimeout(r, 50));
    expect(lastFrame()).toContain('ABC');
    stdin.write('\x10');
    await new Promise(r => setTimeout(r, 50));
    expect(lastFrame()).toContain('\u547D\u4EE4\u9762\u677F');
    stdin.write('\x1b');
    await new Promise(r => setTimeout(r, 50));
    stdin.write('Z');
    await new Promise(r => setTimeout(r, 50));
    expect(lastFrame()).toContain('ABCZ');
  });
});
