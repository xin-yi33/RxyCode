import React, { useState } from 'react';
import { render } from 'ink-testing-library';
import { describe, expect, test, vi } from 'vitest';
import CursorInput from './CursorInput.js';

function Harness({ initial, onValue, onSubmit = () => undefined }: {
  initial: string;
  onValue: (value: string, offset: number) => void;
  onSubmit?: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const [offset, setOffset] = useState(initial.length);
  return (
    <CursorInput
      value={value}
      cursorOffset={offset}
      onChange={(next, nextOffset) => {
        setValue(next);
        setOffset(nextOffset);
        onValue(next, nextOffset);
      }}
      onSubmit={onSubmit}
    />
  );
}

describe('CursorInput grapheme editing', () => {
  test('backspace removes a complete family emoji', async () => {
    const onValue = vi.fn();
    const { stdin } = render(<Harness initial={'A👨‍👩‍👧‍👦'} onValue={onValue} />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    stdin.write('\x7f');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onValue).toHaveBeenLastCalledWith('A', 1);
  });

  test('left arrow moves across a combining sequence in one step', async () => {
    const onValue = vi.fn();
    const { stdin } = render(<Harness initial={'e\u0301x'} onValue={onValue} />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    stdin.write('\x1b[D');
    await new Promise((resolve) => setTimeout(resolve, 50));
    stdin.write('\x1b[D');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onValue).toHaveBeenLastCalledWith('éx', 0);
  });

  test('preserves and submits a multi-line bracketed-paste payload', async () => {
    const onValue = vi.fn();
    const onSubmit = vi.fn();
    const { stdin } = render(<Harness initial="" onValue={onValue} onSubmit={onSubmit} />);
    await new Promise((resolve) => setTimeout(resolve, 50));

    stdin.write('first line\r\nsecond line');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onValue).toHaveBeenLastCalledWith('first line\nsecond line', 'first line\nsecond line'.length);

    stdin.write('\r');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onSubmit).toHaveBeenCalledWith('first line\nsecond line');
  });
});
