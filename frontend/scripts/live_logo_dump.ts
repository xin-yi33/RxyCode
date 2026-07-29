#!/usr/bin/env npx tsx
/** Tiny live dump helper — Unicode wordmark only. */
import fs from 'node:fs';
import path from 'node:path';
import { detectArch, detectLogoProfile } from '../src/terminalHost.js';
import { renderWordmarkFrame } from '../src/logo.js';

const label = process.argv[2] || 'dump';
const outDir = path.resolve(process.argv[3] || path.join('..', 'qa-artifacts', 'logo-profiles'));
fs.mkdirSync(outDir, { recursive: true });
const host = detectLogoProfile();
const lines = [
  `label=${label}`,
  `host=${host} arch=${detectArch()} platform=${process.platform} glyph=unicode-U+2588`,
  ...renderWordmarkFrame(100),
  '',
];
const target = path.join(outDir, `live-${label}.txt`);
fs.writeFileSync(target, lines.join('\n'), 'utf8');
console.log(`wrote ${target}`);
