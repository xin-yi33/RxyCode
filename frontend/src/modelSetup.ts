export const NO_MODEL_WELCOME_HINT =
  '尚未配置模型 — 输入 /addmodel 或按 Ctrl+P';

export type ModelSetupDecision = {
  needsSetup: boolean;
  shouldAutoOpen: boolean;
};

export function decideModelSetup(args: {
  fetchOk: boolean;
  modelCount: number;
  alreadyAutoOpened: boolean;
}): ModelSetupDecision {
  if (!args.fetchOk) {
    return { needsSetup: false, shouldAutoOpen: false };
  }
  if (args.modelCount > 0) {
    return { needsSetup: false, shouldAutoOpen: false };
  }
  return {
    needsSetup: true,
    shouldAutoOpen: !args.alreadyAutoOpened,
  };
}
