import React from 'react';
import { Box, Text, useStdout } from 'ink';
import stringWidth from 'string-width';
import type { Mode, StatusInfo } from '../types.js';
import { MODE_COLORS, MODE_LABELS } from '../types.js';
import { C } from '../theme.js';

interface Props {
  status: StatusInfo | null;
  mode: Mode;
  model: string;
  thinkingExpanded: boolean;
}

type SegmentKey = 'connection' | 'context' | 'cache' | 'mode' | 'thinking' | 'cancel' | 'shortcuts';

const SEGMENT_ORDER: SegmentKey[] = ['connection', 'context', 'cache', 'mode', 'thinking', 'cancel', 'shortcuts'];
const OPTIONAL_PRIORITY: SegmentKey[] = ['context', 'cache', 'cancel', 'shortcuts'];

export default React.memo(function StatusBar({ status, mode, thinkingExpanded }: Props) {
  const { stdout } = useStdout();
  const terminalWidth = stdout?.columns ?? 80;
  const contentWidth = Math.max(1, terminalWidth - 2);
  const ctxUsed = (status?.context_used_k ?? 0).toFixed(1);
  const ctxMax = (status?.context_max_k ?? 256).toString();
  const cacheSize = status?.cache_size ?? '0B';
  const cacheRate = status?.cache_rate ?? '0.0%';

  const modeColor = MODE_COLORS[mode];
  const connected = status !== null;
  const connIcon = connected ? '●' : '○';
  const connColor = connected ? C.green : C.accent;
  const connLabel = connected ? 'online' : 'offline';

  const text: Record<SegmentKey, string> = {
    connection: `${connIcon} ${connLabel}`,
    context: `上下文:${ctxUsed}k/${ctxMax}k`,
    cache: `缓存:${cacheSize}/${cacheRate}`,
    mode: MODE_LABELS[mode],
    thinking: `思考:${thinkingExpanded ? '开' : '关'}`,
    cancel: 'Esc:终止',
    shortcuts: 'Tab:切换 /:命令 Ctrl+T:思考 Ctrl+P:设置',
  };
  const visible = new Set<SegmentKey>(['connection', 'mode', 'thinking']);
  for (const key of OPTIONAL_PRIORITY) {
    const candidate = SEGMENT_ORDER.filter((segment) => visible.has(segment) || segment === key);
    if (stringWidth(candidate.map((segment) => text[segment]).join(' │ ')) <= contentWidth) {
      visible.add(key);
    }
  }
  const segments = SEGMENT_ORDER.filter((key) => visible.has(key));

  const renderSegment = (key: SegmentKey) => {
    switch (key) {
      case 'connection':
        return <Text color={connColor} bold>{text[key]}</Text>;
      case 'context':
        return <Text color={C.primary}>{text[key]}</Text>;
      case 'cache':
        return <Text color={C.teal}>{text[key]}</Text>;
      case 'mode':
        return <Text color={modeColor} bold>{text[key]}</Text>;
      case 'thinking':
        return <Text color={thinkingExpanded ? C.green : C.overlay2}>{text[key]}</Text>;
      default:
        return <Text color={C.overlay2}>{text[key]}</Text>;
    }
  };

  return (
    <Box paddingX={1} flexShrink={0} width={terminalWidth} height={1} overflow="hidden">
      {segments.map((key, index) => (
        <React.Fragment key={key}>
          {index > 0 && <Text color={C.borderDim}> │ </Text>}
          {renderSegment(key)}
        </React.Fragment>
      ))}
    </Box>
  );
});
