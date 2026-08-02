import { resolveTransportKind } from "./config.ts";
import { httpTransport } from "./httpTransport.ts";
import { stdioTransport } from "./stdioTransport.ts";
import type { ChatTransport } from "./types.ts";

let cached: ChatTransport | null = null;

export function getChatTransport(): ChatTransport {
  if (!cached) {
    cached = resolveTransportKind() === "stdio" ? stdioTransport : httpTransport;
  }
  return cached;
}

/** Reset cached transport (unit tests only). */
export function resetChatTransportForTests(): void {
  cached = null;
}

export type {
  ChatApiCallbacks,
  ChatTransport,
  MessageUpdater,
  TransportKind,
} from "./types.ts";
export { resolveTransportKind } from "./config.ts";
export { notifyToStreamEvent } from "./notifyToStreamEvent.ts";
