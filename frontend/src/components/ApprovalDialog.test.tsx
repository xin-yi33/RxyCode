import { describe, test, expect, vi } from 'vitest';
import { render } from 'ink-testing-library';
import React from 'react';
import ApprovalDialog from './ApprovalDialog.js';
import type { ApprovalInfo } from '../hooks/useApi.js';

const sample: ApprovalInfo = {
  approvalId: 'abc123',
  tool: 'bash',
  risk: 'DANGER',
  args: '{"command":"rm -rf /"}',
};

describe('ApprovalDialog component', () => {
  test('renders tool name, risk level and args', () => {
    const { lastFrame } = render(
      <ApprovalDialog approval={sample} onDecision={() => {}} />
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Safety Approval');
    expect(f).toContain('bash');
    expect(f).toContain('DANGER');
    expect(f).toContain('rm -rf /');
  });

  test('renders all three options', () => {
    const { lastFrame } = render(
      <ApprovalDialog approval={sample} onDecision={() => {}} />
    );
    const f = lastFrame() ?? '';
    expect(f).toContain('Approve');
    expect(f).toContain('Reject');
    expect(f).toContain('Always allow');
  });

  test('pressing "a" approves', async () => {
    const onDecision = vi.fn();
    const { stdin } = render(
      <ApprovalDialog approval={sample} onDecision={onDecision} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('a');
    await new Promise(r => setTimeout(r, 50));
    expect(onDecision).toHaveBeenCalledWith('approved');
  });

  test('pressing "r" rejects', async () => {
    const onDecision = vi.fn();
    const { stdin } = render(
      <ApprovalDialog approval={sample} onDecision={onDecision} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('r');
    await new Promise(r => setTimeout(r, 50));
    expect(onDecision).toHaveBeenCalledWith('rejected');
  });

  test('pressing "l" always-allows the level', async () => {
    const onDecision = vi.fn();
    const { stdin } = render(
      <ApprovalDialog approval={sample} onDecision={onDecision} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('l');
    await new Promise(r => setTimeout(r, 50));
    expect(onDecision).toHaveBeenCalledWith('always_allow_level');
  });

  test('arrow down + enter selects second option (reject)', async () => {
    const onDecision = vi.fn();
    const { stdin } = render(
      <ApprovalDialog approval={sample} onDecision={onDecision} />
    );
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\x1b[B');
    await new Promise(r => setTimeout(r, 50));
    stdin.write('\r');
    await new Promise(r => setTimeout(r, 50));
    expect(onDecision).toHaveBeenCalledWith('rejected');
  });

  test('long args do not overflow the frame', () => {
    const longArgs = 'x'.repeat(500);
    const { lastFrame } = render(
      <ApprovalDialog approval={{ ...sample, args: longArgs }} onDecision={() => {}} />
    );
    const f = lastFrame() ?? '';
    // The full 500-char payload must NOT appear verbatim (component
    // truncates to 200 + '...', and Ink truncates to terminal width).
    expect(f).not.toContain(longArgs);
  });
});
