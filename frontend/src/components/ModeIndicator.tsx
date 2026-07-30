import React from 'react';
import { Box, Text } from 'ink';
import type { Mode } from '../types';
import { MODE_COLORS, MODE_LABELS } from '../types';

interface Props {
  mode: Mode;
  model: string;
}

export default function ModeIndicator({ mode, model }: Props) {
  const color = MODE_COLORS[mode];
  return (
    <Box paddingLeft={2} paddingY={0}>
      <Text color={color} bold>{MODE_LABELS[mode]}</Text>
      <Text color="#666"> {'\u00b7'} {model}</Text>
    </Box>
  );
}
