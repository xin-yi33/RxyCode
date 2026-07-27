/** Map internal agent errors to user-facing Chinese messages (E2/E3/E8). */

const MSG_BUILD_INCOMPLETE =
  '构建流程未完成，部分步骤未通过验证。请查看任务详情后重试。';
const MSG_GROUNDING =
  '最终回答未能通过校验，内容与已验证结果不一致。请重试或简化任务。';
const MSG_TOOL_INTERRUPTED = '工具执行中断，未能完成所需操作。请重试。';
const MSG_TIMEOUT = '请求超时，请稍后重试。';
const MSG_CANCELLED = '操作已取消。';
const MSG_DEFAULT = '处理未完成，请重试。';

const GROUNDING_MARKERS = [
  'grounded claim',
  'claim manifest',
  'synthesis manifest',
  'synthesizer',
  'grounding failed',
  'verified synthesis',
  'verbatim source',
];

const FORBIDDEN = /synthesizer|claim\s*manifest|grounded\s*claims?/i;

export function toUserFacingError(raw: string): string {
  const text = String(raw ?? '').trim();
  if (!text) return MSG_DEFAULT;

  const lowered = text.toLowerCase();

  if (
    lowered === 'cancelled' ||
    lowered.includes('cancellederror') ||
    (lowered.includes('cancel') && lowered.startsWith('cancel'))
  ) {
    return MSG_CANCELLED;
  }

  if (lowered.includes('timeout') || lowered.includes('timed out')) {
    return MSG_TIMEOUT;
  }

  if (
    lowered.startsWith('[evidence failed') ||
    (lowered.includes('did not complete') && lowered.includes('tool'))
  ) {
    return MSG_TOOL_INTERRUPTED;
  }

  if (GROUNDING_MARKERS.some(marker => lowered.includes(marker))) {
    return MSG_GROUNDING;
  }

  if (lowered.startsWith('[build incomplete')) {
    return MSG_BUILD_INCOMPLETE;
  }

  return MSG_DEFAULT;
}

export function formatUserFacingStreamError(message: string): string {
  const friendly = toUserFacingError(message);
  if (FORBIDDEN.test(friendly)) {
    return `Error: ${MSG_DEFAULT}`;
  }
  return `Error: ${friendly}`;
}
