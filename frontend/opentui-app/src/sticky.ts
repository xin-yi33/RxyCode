export interface StickyState {
  sticky: boolean;
  userScrolledUp: boolean;
}

export function createStickyState(): StickyState {
  return { sticky: true, userScrolledUp: false };
}

export function onUserScrollUp(state: StickyState): StickyState {
  return { sticky: false, userScrolledUp: true };
}

export function onScrollToBottom(_state: StickyState): StickyState {
  return { sticky: true, userScrolledUp: false };
}

export function onSendMessage(_state: StickyState): StickyState {
  return { sticky: true, userScrolledUp: false };
}

export function shouldAutoStick(state: StickyState): boolean {
  return state.sticky && !state.userScrolledUp;
}
