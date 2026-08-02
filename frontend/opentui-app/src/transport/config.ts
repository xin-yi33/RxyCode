import type { TransportKind } from "./types.ts";

/** Resolve transport from RXYCODE_TRANSPORT (default http per P5 task card). */
export function resolveTransportKind(): TransportKind {
  const raw = (process.env.RXYCODE_TRANSPORT ?? "http").trim().toLowerCase();
  if (raw === "stdio") return "stdio";
  if (raw === "http") return "http";
  throw new Error(`Unknown RXYCODE_TRANSPORT=${JSON.stringify(raw)}. Use 'http' or 'stdio'.`);
}
