/**
 * P5 manual smoke: stdio transport — chat, approval, interrupt (stub appserver).
 * Run: bun run scripts/p5-stdio-smoke.ts
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getChatTransport, resetChatTransportForTests } from "../src/transport/index.ts";
import type { ChatMessage } from "../src/types.ts";
import type { ApprovalInfo } from "../src/ApprovalDialog.tsx";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);

process.env.RXYCODE_TRANSPORT = "stdio";
process.env.RXYCODE_APPSERVER_STUB = "1";
process.env.RXYCODE_PROJECT_ROOT = repoRoot;
process.env.RXYCODE_APPSERVER_PYTHON =
  process.env.RXYCODE_APPSERVER_PYTHON ?? process.env.PYTHON ?? "python";

resetChatTransportForTests();
const transport = getChatTransport();

async function prompt(text: string, opts?: { onApproval?: (info: ApprovalInfo) => void }): Promise<ChatMessage[]> {
  let messages: ChatMessage[] = [];
  await transport.sendChatMessage(text, "build", {
    onMessages: (u) => {
      messages = u(messages);
    },
    onStreaming: () => {},
    onStatus: () => {},
    onApprovalRequest: (info) => {
      if (info && opts?.onApproval) opts.onApproval(info);
    },
  });
  return messages;
}

console.log("=== P5 stdio smoke ===");
console.log("transport:", transport.kind);

const chat = await prompt("hello");
const assistant = chat.find((m) => m.role === "assistant");
if (!assistant?.content.includes("stub:hello")) {
  console.error("FAIL chat:", assistant?.content);
  process.exit(1);
}
console.log("PASS chat round-trip:", assistant.content);

let approvalSeen = false;
const approvalMsgs = await prompt("trigger-approval", {
  onApproval: async (info) => {
    approvalSeen = true;
    console.log("PASS approval request:", info.tool, info.risk);
    await transport.respondApproval(info.approvalId, "approved");
  },
});
if (!approvalSeen) {
  console.error("FAIL approval: no request");
  process.exit(1);
}
const approvalResult = approvalMsgs.find((m) => m.role === "assistant");
console.log("PASS approval flow:", approvalResult?.content);
if (!approvalResult?.content.includes("approved")) {
  console.error("FAIL approval: expected approved decision in response");
  process.exit(1);
}

await transport.cancelActiveRequest();
console.log("PASS interrupt API (session/interrupt via cancelActiveRequest)");

await transport.shutdown?.();
console.log("=== ALL P5 STDIO SMOKE PASSED ===");
