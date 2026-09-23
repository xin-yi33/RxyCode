export function packageMismatch(
  appVersion: string,
  appserverProtocol: string,
  expectedProtocol: string
): string | null {
  if (appserverProtocol !== expectedProtocol) {
    return `protocol mismatch: app ${appVersion} expected ${expectedProtocol}, appserver ${appserverProtocol}`
  }
  return null
}

export function keepPreviousOnUpdateFailure(updateOk: boolean): 'keep' | 'replace' {
  return updateOk ? 'replace' : 'keep'
}
