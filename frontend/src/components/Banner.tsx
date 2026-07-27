import React from 'react';
import { Box, Text, useStdout } from 'ink';
import { WORDMARK, WORDMARK_DISPLAY_WIDTH, padToDisplayWidth } from '../logo.js';

// Ink/yoga trim trailing ASCII spaces; WORD JOINER is 0-width (not ZWJ) and keeps pad.
const PAD_GUARD = '\u2060';

export default React.memo(function Banner() {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;

  const logoLeading = Math.floor((termWidth - WORDMARK_DISPLAY_WIDTH) / 2);

  const subtitleWidth = 24;
  const subtitleLeading = Math.floor((termWidth - subtitleWidth) / 2);

  const lines = WORDMARK.map((line) =>
    padToDisplayWidth(line.replace(/ +$/, ''), WORDMARK_DISPLAY_WIDTH) + PAD_GUARD,
  );

  return (
    <Box flexDirection="column" alignItems="flex-start" width={termWidth} paddingTop={1} paddingBottom={1}>
      {lines.map((line, i) => (
        <Text key={i} color={i === 0 ? '#FFB6C1' : '#FF69B4'} bold>{' '.repeat(logoLeading) + line}</Text>
      ))}
      <Box marginTop={1} marginBottom={1}>
        <Text>{' '.repeat(subtitleLeading)}</Text>
        <Text color="#FFB6C1">{'\u2726 '}</Text>
        <Text color="#FF69B4">General-Purpose AI Agent</Text>
        <Text color="#FFB6C1">{' \u2726'}</Text>
      </Box>
    </Box>
  );
});
