const PUBLIC_HTTPS_HOSTS = new Set(["rxycode.xyz", "www.rxycode.xyz"])

type LocationLike = Pick<Location, "href" | "hostname" | "port" | "protocol">

function normalizedHostname(hostname: string): string {
  return hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "")
}

function isLoopbackHostname(hostname: string): boolean {
  const host = normalizedHostname(hostname)
  if (host === "localhost" || host.endsWith(".localhost") || host === "::1") return true

  const octets = host.split(".")
  if (octets.length !== 4 || !/^127$/.test(octets[0])) return false
  return octets.every((octet) => /^\d{1,3}$/.test(octet) && Number(octet) <= 255)
}

/** Only the public login domains are upgraded; URL credentials are never carried forward. */
export function publicHttpsUpgradeUrl(location: LocationLike): string | null {
  const host = normalizedHostname(location.hostname)
  if (location.protocol !== "http:" || !PUBLIC_HTTPS_HOSTS.has(host)) return null
  // The public gateway only exposes standard HTTP/HTTPS ports. A custom port
  // must fail closed instead of being carried onto a likely unrelated TLS port.
  if (location.port && location.port !== "80") return null

  const target = new URL(location.href)
  target.protocol = "https:"
  if (target.port === "80") target.port = ""
  target.username = ""
  target.password = ""
  return target.href
}

/** The hash solver needs a protected transport, not the isSecureContext flag or Web Crypto. */
export function isAuthTransportAllowed(location: Pick<Location, "hostname" | "protocol">): boolean {
  if (location.protocol === "https:") return true
  return location.protocol === "http:" && isLoopbackHostname(location.hostname)
}

type DeviceSignals = {
  userAgent: string
  maxTouchPoints: number
  viewportWidth: number
}

/** A performance choice only; server-side ALTCHA verification is identical for every client. */
export function prefersMainThreadAltcha({
  userAgent,
  maxTouchPoints,
  viewportWidth,
}: DeviceSignals): boolean {
  const mobileUserAgent = /Android|iPhone|iPad|iPod|Mobile|Windows Phone|IEMobile/i.test(userAgent)
  const touch = maxTouchPoints > 0
  const narrow = viewportWidth <= 820
  return (mobileUserAgent && (touch || narrow)) || (touch && narrow)
}

export function currentClientPrefersMainThreadAltcha(): boolean {
  return prefersMainThreadAltcha({
    userAgent: navigator.userAgent,
    maxTouchPoints: navigator.maxTouchPoints,
    viewportWidth: window.innerWidth,
  })
}
