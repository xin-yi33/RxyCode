/** PhaseG-H16: models/set_active params. effort is optional_field; omit when unset. */

export function buildSetActiveParams(
  id: string,
  effort?: string | null
): { id: string; effort?: string } {
  if (effort === undefined || effort === null || effort === '') return { id }
  return { id, effort }
}

export async function requestSetActive(
  request: (method: string, params: unknown, timeoutMs: number) => Promise<unknown>,
  id: string,
  effort?: string | null
): Promise<boolean> {
  const result = (await request('models/set_active', buildSetActiveParams(id, effort), 30_000)) as {
    ok?: boolean
  }
  return result.ok === true
}
