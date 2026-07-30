#!/usr/bin/env npx tsx
/** Render centered WORDMARK text dump for W25 Win32 evidence. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  WORDMARK,
  WORDMARK_DISPLAY_WIDTH,
  padToDisplayWidth,
  centerLine,
} from '../src/logo.js';

const cols = Number(process.env.COLUMNS || process.stdout.columns || 120);
const leading = Math.max(0, Math.floor((cols - WORDMARK_DISPLAY_WIDTH) / 2));
const padGuard = ' ';

const lines = WORDMARK.map((line) => {
  const trimmed = line.replace(/ +$/, '');
  const padded = padToDisplayWidth(trimmed, WORDMARK_DISPLAY_WIDTH);
  const centered = centerLine(padded, cols);
  return ' '.repeat(leading) + centered + padGuard;
});

const header = [
  `# RxyCode WORDMARK dump — ${new Date().toISOString()}`,
  `# platform=${process.platform} cols=${cols} display_width=${WORDMARK_DISPLAY_WIDTH}`,
  '',
];

const body = header.concat(lines).join(os.EOL) + os.EOL;
const outPaths = process.argv.slice(2);
if (!outPaths.length) {
  process.stdout.write(body);
  process.exit(0);
}
for (const target of outPaths) {
  const resolved = path.resolve(target);
  fs.mkdirSync(path.dirname(resolved), { recursive: true });
  fs.writeFileSync(resolved, body, 'utf8');
  console.log(`wrote ${resolved}`);
}
