import React, { useCallback, useRef } from 'react';
import { Text, useInput, type Key } from 'ink';
import { C } from '../theme.js';
import {
  clampToGraphemeBoundary,
  nextGraphemeBoundary,
  previousGraphemeBoundary,
} from '../grapheme.js';

interface CursorInputProps {
  value: string;
  cursorOffset: number;
  onChange: (value: string, cursorOffset: number) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  isActive?: boolean;
}

// A controlled single-line text input that does NOT draw its own (fake) cursor.
// The visible caret is the terminal's native cursor, which is positioned by the
// parent (InputBox) via ANSI escape sequences. This yields a thin, terminal-
// controlled, blinking caret like the one in cmd / Windows Terminal, instead of
// ink-text-input's thick `chalk.inverse` block.
const normalizeInput = (input: string): string => input.replace(/\r\n?/g, '\n');

const isInsertable = (input: string): boolean => {
  const normalized = normalizeInput(input);
  const isPastePayload = input.length > 1;
  return normalized.length > 0 && Array.from(normalized).every((character) => (
    (character >= ' ' && character !== '\x7f')
    || (isPastePayload && (character === '\n' || character === '\t'))
  ));
};

export function handleCursorInputKey(
  input: string,
  key: Key,
  value: string,
  cursorOffset: number,
  onChange: (value: string, cursorOffset: number) => void,
  onSubmit: (value: string) => void,
): boolean {
  const safeOffset = clampToGraphemeBoundary(value, cursorOffset);

  if (key.return) {
    onSubmit(value);
    return true;
  }
  if (key.leftArrow) {
    onChange(value, previousGraphemeBoundary(value, safeOffset));
    return true;
  }
  if (key.rightArrow) {
    onChange(value, nextGraphemeBoundary(value, safeOffset));
    return true;
  }
  if ((key.backspace || key.delete) && safeOffset > 0) {
    const previousOffset = previousGraphemeBoundary(value, safeOffset);
    const next = value.slice(0, previousOffset) + value.slice(safeOffset);
    onChange(next, previousOffset);
    return true;
  }
  if (isInsertable(input) && !key.ctrl && !key.meta && !key.escape) {
    const normalized = normalizeInput(input);
    const next = value.slice(0, safeOffset) + normalized + value.slice(safeOffset);
    onChange(next, safeOffset + normalized.length);
    return true;
  }
  return false;
}

export default function CursorInput({
  value,
  cursorOffset,
  onChange,
  onSubmit,
  placeholder = '',
  isActive = true,
}: CursorInputProps) {
  const inputHandlerRef = useRef<(input: string, key: Key) => void>(() => {});
  inputHandlerRef.current = (input, key) => {
    handleCursorInputKey(input, key, value, cursorOffset, onChange, onSubmit);
  };

  const stableInputHandler = useCallback((input: string, key: Key) => {
    inputHandlerRef.current(input, key);
  }, []);
  useInput(stableInputHandler, { isActive });

  return (
    <Text>
      {value.length > 0 ? value : <Text color={C.overlay2}>{placeholder}</Text>}
    </Text>
  );
}
