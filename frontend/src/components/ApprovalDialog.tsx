import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { C } from '../theme.js';
import type { ApprovalInfo, ApprovalDecision } from '../hooks/useApi.js';

interface ApprovalDialogProps {
  approval: ApprovalInfo;
  onDecision: (decision: ApprovalDecision) => void;
}

const RISK_COLORS: Record<string, string> = {
  READ: C.green,
  WRITE: C.yellow,
  DANGER: C.accent,
};

const OPTIONS: Array<{ key: string; label: string; decision: ApprovalDecision }> = [
  { key: 'a', label: 'Approve (允许本次)', decision: 'approved' },
  { key: 'r', label: 'Reject (拒绝)', decision: 'rejected' },
  { key: 'l', label: 'Always allow this level (本会话同级别放行)', decision: 'always_allow_level' },
];

export default React.memo(function ApprovalDialog({ approval, onDecision }: ApprovalDialogProps) {
  const [idx, setIdx] = useState(0);
  const riskColor = RISK_COLORS[approval.risk] || C.yellow;

  useInput((ch, key) => {
    if (key.upArrow) { setIdx(i => Math.max(0, i - 1)); return; }
    if (key.downArrow) { setIdx(i => Math.min(OPTIONS.length - 1, i + 1)); return; }
    if (key.return) { onDecision(OPTIONS[idx].decision); return; }
    const lower = ch?.toLowerCase();
    const hit = OPTIONS.find(o => o.key === lower);
    if (hit) { onDecision(hit.decision); }
  });

  const argsPreview = approval.args.length > 200 ? approval.args.slice(0, 200) + '...' : approval.args;

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={riskColor} paddingX={1} flexShrink={0}>
      <Box>
        <Text color={riskColor} bold>{'  '}Safety Approval</Text>
        <Box flexGrow={1} />
        <Text color={riskColor} bold>{approval.risk}{' '}</Text>
      </Box>
      <Box><Text color={C.borderDim}>{'─'.repeat(40)}</Text></Box>
      <Box><Text color={C.subtext}>{'  '}Tool: <Text color={C.text} bold>{approval.tool}</Text></Text></Box>
      <Box><Text color={C.overlay2} wrap="truncate">{'  '}Args: {argsPreview}</Text></Box>
      <Box><Text color={C.borderDim}>{'─'.repeat(40)}</Text></Box>
      {OPTIONS.map((o, i) => {
        const sel = i === idx;
        return (
          <Box key={o.key}>
            <Text backgroundColor={sel ? C.surface1 : undefined}>
              <Text color={sel ? riskColor : C.subtext}>{sel ? ' ❯ ' : '   '}[{o.key}] {o.label}</Text>
            </Text>
          </Box>
        );
      })}
      <Box><Text color={C.overlay2}>{'  '}↑↓ 选择   ↵ 确认   a/r/l 快捷</Text></Box>
    </Box>
  );
});
