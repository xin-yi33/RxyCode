import { describe, expect, it } from 'vitest';
import { decideModelSetup, NO_MODEL_WELCOME_HINT } from './modelSetup.js';

describe('decideModelSetup', () => {
  it('API failure never prompts', () => {
    expect(decideModelSetup({ fetchOk: false, modelCount: 0, alreadyAutoOpened: false })).toEqual({
      needsSetup: false,
      shouldAutoOpen: false,
    });
  });

  it('empty models prompts and auto-opens once', () => {
    expect(decideModelSetup({ fetchOk: true, modelCount: 0, alreadyAutoOpened: false })).toEqual({
      needsSetup: true,
      shouldAutoOpen: true,
    });
    expect(decideModelSetup({ fetchOk: true, modelCount: 0, alreadyAutoOpened: true })).toEqual({
      needsSetup: true,
      shouldAutoOpen: false,
    });
  });

  it('configured models never prompt', () => {
    expect(decideModelSetup({ fetchOk: true, modelCount: 1, alreadyAutoOpened: false })).toEqual({
      needsSetup: false,
      shouldAutoOpen: false,
    });
  });

  it('hint copy is fixed', () => {
    expect(NO_MODEL_WELCOME_HINT).toBe('尚未配置模型 — 输入 /addmodel 或按 Ctrl+P');
  });
});
