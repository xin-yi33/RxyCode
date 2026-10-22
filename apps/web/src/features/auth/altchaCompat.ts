import { sha256 } from "js-sha256"
import { isAuthTransportAllowed } from "./authTransport"

const CHALLENGE_URL = "/api/v1/auth/altcha"
const MAX_COUNTER = 100_000
const SOLVE_TIMEOUT_MS = 90_000
const YIELD_EVERY = 256

export type AltchaCompatCode = "INSECURE_CONTEXT" | "NETWORK" | "CHALLENGE" | "COMPUTE"

export class AltchaCompatError extends Error {
  constructor(readonly code: AltchaCompatCode) {
    super(code)
    this.name = "AltchaCompatError"
  }
}

type ChallengeV1 = {
  algorithm: "SHA-256"
  challenge: string
  maxnumber: number
  salt: string
  signature: string
}

function isChallengeV1(value: unknown): value is ChallengeV1 {
  if (!value || typeof value !== "object") return false
  const candidate = value as Record<string, unknown>
  return (
    candidate.algorithm === "SHA-256" &&
    typeof candidate.challenge === "string" && /^[a-f\d]{64}$/i.test(candidate.challenge) &&
    typeof candidate.signature === "string" && /^[a-f\d]{64}$/i.test(candidate.signature) &&
    typeof candidate.salt === "string" && /^[\x20-\x7e]{1,256}$/.test(candidate.salt) &&
    Number.isSafeInteger(candidate.maxnumber) &&
    (candidate.maxnumber as number) > 0 &&
    (candidate.maxnumber as number) <= MAX_COUNTER
  )
}

function expiryFromSalt(salt: string): number | null {
  const query = salt.split("?", 2)[1]
  if (!query) return null
  const value = new URLSearchParams(query).get("expires") ?? new URLSearchParams(query).get("expire")
  if (!value || !/^\d+$/.test(value)) return null
  const seconds = Number(value)
  return Number.isSafeInteger(seconds) ? seconds * 1000 : null
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError")
}

export async function solveAltchaCompat(signal: AbortSignal): Promise<{
  payload: string
  expiresAt: number
}> {
  if (!isAuthTransportAllowed(window.location)) {
    throw new AltchaCompatError("INSECURE_CONTEXT")
  }
  if (signal.aborted) throw abortError()

  const started = performance.now()
  const controller = new AbortController()
  let timedOut = false
  const abortFromOwner = () => controller.abort()
  signal.addEventListener("abort", abortFromOwner, { once: true })
  const timeout = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, SOLVE_TIMEOUT_MS)

  try {
    let response: Response
    try {
      response = await fetch(CHALLENGE_URL, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      })
    } catch {
      if (signal.aborted) throw abortError()
      if (timedOut) throw new AltchaCompatError("COMPUTE")
      throw new AltchaCompatError("NETWORK")
    }
    if (!response.ok) throw new AltchaCompatError("NETWORK")

    let challenge: unknown
    try {
      challenge = await response.json()
    } catch {
      throw new AltchaCompatError("CHALLENGE")
    }
    if (!isChallengeV1(challenge)) throw new AltchaCompatError("CHALLENGE")

    const expiresAt = expiryFromSalt(challenge.salt)
    if (!expiresAt || expiresAt <= Date.now()) throw new AltchaCompatError("CHALLENGE")

    const solvingStarted = performance.now()
    for (let number = 0; number <= challenge.maxnumber; number += 1) {
      if (signal.aborted) throw abortError()
      if (timedOut || performance.now() - started >= SOLVE_TIMEOUT_MS) {
        throw new AltchaCompatError("COMPUTE")
      }
      if (Date.now() >= expiresAt) throw new AltchaCompatError("CHALLENGE")

      // ALTCHA V1 hashes the original salt followed by the decimal counter.
      if (sha256(`${challenge.salt}${number}`) === challenge.challenge.toLowerCase()) {
        const took = Math.floor((performance.now() - solvingStarted) * 10) / 10
        const json = JSON.stringify({
          algorithm: challenge.algorithm,
          challenge: challenge.challenge,
          number,
          salt: challenge.salt,
          signature: challenge.signature,
          took,
        })
        return { payload: btoa(json), expiresAt }
      }

      if (number % YIELD_EVERY === YIELD_EVERY - 1) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
      }
    }
    throw new AltchaCompatError("CHALLENGE")
  } finally {
    window.clearTimeout(timeout)
    signal.removeEventListener("abort", abortFromOwner)
  }
}
