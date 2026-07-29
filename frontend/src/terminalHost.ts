/**
 * Terminal host detection (logging / QA). Logo is always Unicode — no ASCII # path.
 */
export type LogoProfile = 'legacy-win' | 'modern-win' | 'macos' | 'other';

export function detectArch(): 'x64' | 'ia32' | 'arm64' | 'other' {
  const a = process.arch;
  if (a === 'x64' || a === 'ia32' || a === 'arm64') return a;
  return 'other';
}

export function detectLogoProfile(env: NodeJS.ProcessEnv = process.env): LogoProfile {
  const force = (env.RXYCODE_LOGO_PROFILE || '').trim().toLowerCase();
  if (force === 'ascii' || force === 'legacy' || force === 'legacy-win') return 'legacy-win';
  if (force === 'unicode' || force === 'modern' || force === 'modern-win') return 'modern-win';
  if (force === 'macos') return 'macos';

  if (process.platform === 'darwin') return 'macos';
  if (process.platform === 'win32') {
    if (env.WT_SESSION || env.WT_PROFILE_ID) return 'modern-win';
    if (env.TERM_PROGRAM === 'vscode' || env.TERM_PROGRAM === 'cursor') return 'modern-win';
    if (env.TERM_PROGRAM === 'WarpTerminal') return 'modern-win';
    if (env.ConEmuANSI || env.CMDER_ROOT) return 'modern-win';
    return 'legacy-win';
  }
  return 'other';
}

/** @deprecated Logo is always Unicode; kept for call-site compatibility. */
export function shouldUseAsciiWordmark(_profile?: LogoProfile): boolean {
  return false;
}
