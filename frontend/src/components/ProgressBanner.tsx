import React, { useEffect, useState } from 'react';
import { Box, Text } from 'ink';
import { C } from '../theme.js';

interface Props {
  isStreaming: boolean;
  startedAt: number | null;
  stepLabel: string;
  activity: string;
}

export default React.memo(function ProgressBanner({ isStreaming, startedAt, stepLabel, activity }: Props) {
  const [pulse, setPulse] = useState(true);
  useEffect(() => {
    if (!isStreaming || !startedAt) return;
    const iv = setInterval(() => setPulse(p => !p), 600);
    return () => clearInterval(iv);
  }, [isStreaming, startedAt]);

  if (!isStreaming || !startedAt) return null;

  const dotColor = pulse ? C.accent : C.overlay2;
  const dotChar = pulse ? '\u2B22' : '\u25CB';

  return (
    <Box flexDirection="column" paddingX={1} flexShrink={0}>
      <Box>
        <Text color={dotColor} bold>{'  '}{dotChar} </Text>
        <Text color={C.overlay2} bold>运行中</Text>
        {stepLabel && <Text color={C.primary}> · {stepLabel}</Text>}
        <Text color={C.overlay2}> · {activity || '...'}</Text>
        <Text color={C.overlay2} bold> · ESC 取消</Text>
      </Box>
    </Box>
  );
});
