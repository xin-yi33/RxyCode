import { describe, expect, test } from 'vitest';
import {
  createStickyState,
  onSendMessage,
  onScrollToBottom,
  onUserScrollUp,
  shouldAutoStick,
  type StickyState,
} from './sticky.js';

const ALL_STATES: StickyState[] = [
  { sticky: true, userScrolledUp: false },
  { sticky: true, userScrolledUp: true },
  { sticky: false, userScrolledUp: false },
  { sticky: false, userScrolledUp: true },
];

describe('createStickyState', () => {
  for (let i = 0; i < 10; i += 1) {
    test(`instance ${i} starts sticky near bottom`, () => {
      const state = createStickyState();
      expect(state).toEqual({ sticky: true, userScrolledUp: false });
      expect(shouldAutoStick(state)).toBe(true);
    });
  }
});

describe('onUserScrollUp matrix', () => {
  for (const before of ALL_STATES) {
    test(`disables sticky from ${JSON.stringify(before)}`, () => {
      const after = onUserScrollUp(before);
      expect(after).toEqual({ sticky: false, userScrolledUp: true });
      expect(shouldAutoStick(after)).toBe(false);
    });
  }
});

describe('onSendMessage matrix', () => {
  for (const before of ALL_STATES) {
    test(`re-enables sticky from ${JSON.stringify(before)}`, () => {
      const after = onSendMessage(before);
      expect(after).toEqual({ sticky: true, userScrolledUp: false });
      expect(shouldAutoStick(after)).toBe(true);
    });
  }
});

describe('onScrollToBottom matrix', () => {
  for (const before of ALL_STATES) {
    test(`re-enables sticky from ${JSON.stringify(before)}`, () => {
      const after = onScrollToBottom(before);
      expect(after).toEqual({ sticky: true, userScrolledUp: false });
      expect(shouldAutoStick(after)).toBe(true);
    });
  }
});

describe('shouldAutoStick truth table', () => {
  const expected: Record<string, boolean> = {
    'true,false': true,
    'true,true': false,
    'false,false': false,
    'false,true': false,
  };
  for (const state of ALL_STATES) {
    const key = `${state.sticky},${state.userScrolledUp}`;
    test(`sticky=${state.sticky} userScrolledUp=${state.userScrolledUp}`, () => {
      expect(shouldAutoStick(state)).toBe(expected[key]);
    });
  }
});

describe('action sequences', () => {
  const sequences: Array<{ name: string; steps: Array<(s: StickyState) => StickyState> }> = [
    { name: 'scroll up then send', steps: [onUserScrollUp, onSendMessage] },
    { name: 'scroll up then bottom', steps: [onUserScrollUp, onScrollToBottom] },
    { name: 'send then scroll up', steps: [onSendMessage, onUserScrollUp] },
    { name: 'double scroll up', steps: [onUserScrollUp, onUserScrollUp] },
    { name: 'double send', steps: [onSendMessage, onSendMessage] },
    { name: 'scroll-send-scroll', steps: [onUserScrollUp, onSendMessage, onUserScrollUp] },
    { name: 'send-scroll-bottom', steps: [onSendMessage, onUserScrollUp, onScrollToBottom] },
    { name: 'bottom-scroll-send', steps: [onScrollToBottom, onUserScrollUp, onSendMessage] },
  ];

  for (const { name, steps } of sequences) {
    test(name, () => {
      let state = createStickyState();
      for (const step of steps) state = step(state);
      expect(state.sticky).toBeTypeOf('boolean');
      expect(state.userScrolledUp).toBeTypeOf('boolean');
    });
  }
});
