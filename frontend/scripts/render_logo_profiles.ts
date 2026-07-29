#!/usr/bin/env npx tsx
/** Dump Unicode WORDMARK (+ host meta) for QA. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { detectArch, detectLogoProfile } from '../src/terminalHost.js';
import { getWordmarkDisplayWidth, renderWordmarkFrame, WORDMARK } from '../src/logo.js';

const cols = Number(process.env.COLUMNS || 100);
const outDir = path.resolve(
  process.argv[2] || path.join(process.cwd(), '..', 'qa-artifacts', 'logo-profiles'),
);
fs.mkdirSync(outDir, { recursive: true });

const host = detectLogoProfile();
const arch = detectArch();
const lines = renderWordmarkFrame(cols);
const body = [
  `# unicode-only wordmark host=${host} arch=${arch}`,
  `# display_width=${getWordmarkDisplayWidth(WORDMARK)} cols=${cols}`,
  `# cell-fill: █ uses matching fg+bg ink; field #000000`,
  '',
  ...lines,
  '',
  '✦ General-Purpose AI Agent ✦',
  '',
].join(os.EOL);

const target = path.join(outDir, `wordmark-unicode-${host}-${arch}.txt`);
fs.writeFileSync(target, body, 'utf8');
console.log(`wrote ${target}`);
