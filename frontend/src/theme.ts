// Classic RxyCode terminal look (true black + pink brand).
// Do NOT swap to Catppuccin/OpenCode skins — style freeze.
export const C = {
  bg: '#000000',
  surface0: '#111111',
  surface1: '#222222',
  surface2: '#333333',
  overlay2: '#555555',
  subtext: '#aaaaaa',
  text: '#ffffff',
  primary: '#FF69B4',
  accent: '#FFB6C1',
  mauve: '#FF69B4',
  green: '#00ff7f',
  yellow: '#f9e2af',
  teal: '#94e2d5',
  sky: '#89dceb',
  red: '#f38ba8',
  border: '#FF69B4',
  borderDim: '#333333',
} as const;

export type CatColor = (typeof C)[keyof typeof C];
