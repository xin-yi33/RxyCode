import React, { useMemo } from 'react';
import { Box, Text, useStdout } from 'ink';
import {
  WORDMARK,
  getWordmarkDisplayWidth,
  logoInkForRow,
  padToDisplayWidth,
} from '../logo.js';

const PAD_GUARD = '\u2060';

function WordmarkRow({ line, ink, leading }: { line: string; ink: string; leading: number }) {
  const nodes: Array<{ text: string; solid: boolean }> = [];
  let buf = '';
  let solid: boolean | null = null;
  for (const ch of line) {
    const isSolid = ch === '█';
    if (solid === null) {
      solid = isSolid;
      buf = ch;
      continue;
    }
    if (isSolid === solid) {
      buf += ch;
      continue;
    }
    nodes.push({ text: buf, solid });
    buf = ch;
    solid = isSolid;
  }
  if (buf && solid !== null) nodes.push({ text: buf, solid });

  return (
    <Box flexDirection="row">
      <Text>{' '.repeat(leading)}</Text>
      {nodes.map((seg, j) =>
        seg.solid ? (
          <Text key={j} color={ink} backgroundColor={ink} bold>
            {seg.text}
          </Text>
        ) : (
          <Text key={j}>{seg.text}</Text>
        ),
      )}
      <Text>{PAD_GUARD}</Text>
    </Box>
  );
}

export default React.memo(function Banner() {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  const displayWidth = useMemo(() => getWordmarkDisplayWidth(WORDMARK), []);
  const logoLeading = Math.max(0, Math.floor((termWidth - displayWidth) / 2));
  const subtitleCore = 'General-Purpose AI Agent';
  const subtitle = `\u2726 ${subtitleCore} \u2726`;
  const subtitleLeading = Math.max(0, Math.floor((termWidth - subtitle.length) / 2));

  return (
    <Box flexDirection="column" alignItems="flex-start" width={termWidth} paddingTop={1} paddingBottom={1}>
      {WORDMARK.map((raw, i) => (
        <WordmarkRow
          key={i}
          ink={logoInkForRow(i)}
          leading={logoLeading}
          line={padToDisplayWidth(raw.replace(/ +$/, ''), displayWidth)}
        />
      ))}
      <Box marginTop={1} marginBottom={1}>
        <Text>{' '.repeat(subtitleLeading)}</Text>
        <Text color="#FFB6C1">{'\u2726 '}</Text>
        <Text color="#FF69B4">{subtitleCore}</Text>
        <Text color="#FFB6C1">{' \u2726'}</Text>
      </Box>
    </Box>
  );
});
