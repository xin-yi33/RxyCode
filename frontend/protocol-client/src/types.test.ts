import { describe, expect, test } from "bun:test";
import type {
  FinalAnswer,
  InitializeRequest,
  MessageDelta,
  PromptRequest,
} from "./generated/types.ts";

describe("generated protocol types", () => {
  test("exports concrete request and notification interfaces", () => {
    const init: InitializeRequest = {
      method: "initialize",
      client_name: "test",
      client_version: "0.0.0",
      protocol_version: "1.0.0",
    };
    const prompt: PromptRequest = {
      method: "session/prompt",
      session_id: "latest",
      text: "hi",
    };
    const delta: MessageDelta = {
      method: "event/message_delta",
      session_id: "s1",
      text: "tok",
    };
    const final: FinalAnswer = {
      method: "event/final",
      session_id: "s1",
      run_id: "run-1",
      text: "done",
    };

    expect(init.method).toBe("initialize");
    expect(prompt.text).toBe("hi");
    expect(delta.text).toBe("tok");
    expect(final.run_id).toBe("run-1");
  });
});