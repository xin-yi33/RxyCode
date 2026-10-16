export type JourneyState = {
  permission: string
  target: string
  status: string
}

export function journeyState(mode: "local" | "cloud" | "remote" | null): JourneyState {
  if (mode === "local") return { permission: "full", target: "local", status: "ready" }
  if (mode === "cloud") return { permission: "cloud", target: "cloud", status: "needs-github" }
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
