import { describe, expect, it } from 'vitest';
import { formatUserFacingStreamError, toUserFacingError } from './userFacingErrors';

const FORBIDDEN = /synthesizer|claim\s*manifest|grounded\s*claims?/i;

describe('toUserFacingError', () => {
  it('maps build incomplete without internal jargon', () => {
    const friendly = toUserFacingError('[Build incomplete: Task not verified: deploy (failed)]');
    expect(friendly).toContain('构建流程未完成');
    expect(FORBIDDEN.test(friendly)).toBe(false);
  });

  it('maps evidence failures to tool interrupted message', () => {
    const friendly = toUserFacingError('[evidence failed: Tool bash did not complete: failed]');
    expect(friendly).toContain('工具执行中断');
    expect(FORBIDDEN.test(friendly)).toBe(false);
  });

  it('formats stream errors with Error prefix', () => {
    expect(formatUserFacingStreamError('[Build incomplete: Synthesizer produced no grounded claims]'))
      .toBe('Error: 最终回答未能通过校验，内容与已验证结果不一致。请重试或简化任务。');
  });
});
