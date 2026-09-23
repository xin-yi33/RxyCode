import { resolveTransportKind } from "./config.ts";
import { httpTransport } from "./httpTransport.ts";
import { stdioTransport } from "./stdioTransport.ts";
import type { ChatTransport } from "./types.ts";

let cached: ChatTransport | null = null;

export function getChatTransport(): ChatTransport {
  const kind = resolveTransportKind();
  // Tests flip RXYCODE_TRANSPORT in one process. A cached client from the
  // previous kind would ignore the new env and answer on the wrong pipe.
  if (!cached || cached.kind !== kind) {
    cached = kind === "stdio" ? stdioTransport : httpTransport;
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
