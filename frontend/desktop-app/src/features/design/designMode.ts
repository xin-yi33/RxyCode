export interface DesignPin {
  id: string
  x: number
  y: number
  note: string
}

export function addPin(pins: readonly DesignPin[], pin: DesignPin): DesignPin[] {
  return [...pins, pin]
}

export function pinsToDraft(pins: readonly DesignPin[]): string {
  if (pins.length === 0) return ''
  return pins.map((pin) => `- [${pin.x},${pin.y}] ${pin.note}`).join('\n')
}

export function gx15VisualState(input: {
  active: boolean
  empty: boolean
  error: string | null
  narrow: boolean
  dark: boolean
}): 'inactive' | 'empty' | 'error' | 'narrow' | 'dark' | 'ok' {
  if (!input.active) return 'inactive'
  if (input.error !== null) return 'error'
  if (input.empty) return 'empty'
  if (input.narrow) return 'narrow'
  if (input.dark) return 'dark'
  return 'ok'
}
