import React from 'react';
import { Box, Text } from 'ink';
import type { Command } from '../types';

interface Props {
  commands: Command[];
  filter: string;
  selectedIndex: number;
}

export default function CommandPalette({ commands, filter, selectedIndex }: Props) {
  const filtered = commands.filter(c =>
    c.name.toLowerCase().includes(filter.toLowerCase())
  );

  if (filtered.length === 0) return null;

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="#555" paddingX={1} marginBottom={1}>
      <Text color="#FFD700" bold>{'  '}Commands</Text>
      {filtered.slice(0, 10).map((cmd, i) => (
        <Box key={cmd.name} justifyContent="space-between">
          <Box>
            <Text color={i === selectedIndex ? '#4FC3F7' : '#888'}>
              {'  '}{i === selectedIndex ? '>' : ' '}
            </Text>
            <Text color={i === selectedIndex ? '#4FC3F7' : '#ccc'}>
              {cmd.name}
              {cmd.args ? ` ${cmd.args}` : ''}
            </Text>
          </Box>
          <Text color="#555">{cmd.description}</Text>
        </Box>
      ))}
    </Box>
  );
}
