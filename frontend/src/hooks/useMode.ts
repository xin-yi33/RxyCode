import { useCallback, useState } from 'react';
import type { Mode } from '../types.js';

const MODES: Mode[] = ['build', 'plan', 'compose'];

export function useMode(initial: Mode = 'build') {
  const [mode, setMode] = useState<Mode>(initial);

  const cycleMode = useCallback(() => {
    setMode(prev => {
      const idx = MODES.indexOf(prev);
      return MODES[(idx + 1) % MODES.length];
    });
  }, []);

  return { mode, setMode, cycleMode };
}
