export type JourneyState = {
  permission: string
  target: string
  status: string
}

export function journeyState(
  mode: "local" | "cloud" | "remote" | null,
  authKind: string,
): JourneyState {
  if (mode === "local") {
    return authKind
      ? { permission: "full", target: "local", status: "ready" }
      : { permission: "", target: "local", status: "needs-login" }
  }
  if (mode === "cloud") {
    return authKind === "github"
      ? { permission: "cloud", target: "cloud", status: "ready" }
      : { permission: "", target: "cloud", status: "needs-github" }
  }
  if (mode === "remote") {
    return { permission: "", target: "remote", status: "waiting_for_local_confirmation" }
  }
  return { permission: "", target: "", status: "choose" }
}

export function journeyMarkup(state: JourneyState): string {
  return (
    `<section data-journey data-permission="${state.permission}" ` +
    `data-target="${state.target}" data-status="${state.status}"></section>`
  )
}
