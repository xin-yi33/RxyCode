import { describe, expect, test } from "bun:test";
import { applyStreamEvent, settleActiveMessages, type StreamReduceState } from "./streamReducer.ts";

function base(): StreamReduceState {
  return {
    messages: [
      {
        id: "t1",
        role: "thinking",
        content: "…",
        timestamp: 1,
        live: true,
        done: false,
      },
    ],
    thinkingId: "t1",
    assistantId: "a1",
    acc: "",
    assistantCreated: false,
    reasoningAcc: "",
    hasReasoning: false,
  };
}

const nid = (s: string) => `id-${s}`;

describe("applyStreamEvent thinking timing", () => {
  test("first token checkmarks the current Thought so body follows it", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "reasoning", text: "plan A" }, nid);
    s = applyStreamEvent(s, { type: "token", text: "hello" }, nid);
    const thinking = s.messages.find((m) => m.id === "t1")!;
    expect(thinking.done).toBe(true);
    expect(thinking.live).toBe(false);
    expect(s.messages.some((m) => m.role === "assistant")).toBe(true);
    expect(s.messages.map((m) => m.role)).toEqual(["thinking", "assistant"]);
  });

  test("reasoning after a tool opens a new Thought slice", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "reasoning", text: "before" }, nid);
    s = applyStreamEvent(s, { type: "tool_call", name: "bash", args: "dir" }, nid);
    s = applyStreamEvent(s, { type: "tool_result", name: "bash", result: "ok" }, nid);
    s = applyStreamEvent(s, { type: "reasoning", text: "after tool" }, nid);
    const first = s.messages.find((m) => m.id === "t1")!;
    const later = s.messages.filter((m) => m.role === "thinking");
    expect(first.content).toBe("before");
    expect(first.done).toBe(true);
    expect(first.content).not.toContain("after tool");
    expect(later).toHaveLength(2);
    expect(later[1]?.content).toBe("after tool");
    expect(later[1]?.done).toBe(false);
    expect(s.messages.map((m) => (m.role === "tool" ? `tool:${m.toolName}` : m.role))).toEqual([
      "thinking",
      "tool:bash",
      "thinking",
    ]);
  });

  test("reasoning chunks concatenate without inserted newlines", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "reasoning", text: "counter" }, nid);
    s = applyStreamEvent(s, { type: "reasoning", text: ".py" }, nid);
    s = applyStreamEvent(s, { type: "reasoning", text: " doesn't" }, nid);
    const thinking = s.messages.find((m) => m.id === "t1")!;
    expect(thinking.content).toBe("counter.py doesn't");
    expect(thinking.content).not.toContain("\n");
  });

  test("liveness placeholders do not become the thinking chain", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "reasoning", text: "思考中..." }, nid);
    expect(s.hasReasoning).toBe(false);
    expect(s.messages.find((m) => m.id === "t1")?.content).toBe("…");
    s = applyStreamEvent(s, { type: "reasoning", text: "先决定要不要搜" }, nid);
    expect(s.hasReasoning).toBe(true);
    expect(s.messages.find((m) => m.id === "t1")?.content).toBe("先决定要不要搜");
  });

  test("final.thinking fills an empty Thought when no stream chain arrived", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "final", text: "done", thinking: "先写文件再跑一遍" }, nid);
    const thinking = s.messages.find((m) => m.id === "t1")!;
    expect(thinking.content).toBe("先写文件再跑一遍");
    expect(thinking.done).toBe(true);
    expect(s.hasReasoning).toBe(true);
  });

  test("final marks thinking done", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "reasoning", text: "x" }, nid);
    s = applyStreamEvent(s, { type: "token", text: "y" }, nid);
    s = applyStreamEvent(s, { type: "final", text: "y done" }, nid);
    const thinking = s.messages.find((m) => m.id === "t1")!;
    expect(thinking.done).toBe(true);
    expect(thinking.live).toBe(false);
  });

  test("settleActiveMessages finishes assistant and tools", () => {
    const settled = settleActiveMessages([
      { id: "t1", role: "thinking", content: "x", timestamp: 1, done: false, live: true },
      { id: "a1", role: "assistant", content: "hi", timestamp: 1, done: false },
      { id: "tool", role: "tool", content: "", timestamp: 1, toolName: "bash", toolStatus: "running" },
    ]);
    expect(settled.find((m) => m.id === "t1")!.done).toBe(true);
    expect(settled.find((m) => m.id === "a1")!.done).toBe(true);
    expect(settled.find((m) => m.id === "tool")!.toolStatus).toBe("cancelled");
  });

  test("tokens after a tool open a new assistant segment", () => {
    let s = base();
    s = applyStreamEvent(s, { type: "token", text: "先查官网" }, nid);
    s = applyStreamEvent(s, { type: "tool_call", name: "websearch", args: "gz sha" }, nid);
    s = applyStreamEvent(s, { type: "tool_result", name: "websearch", result: "ok" }, nid);
    s = applyStreamEvent(s, { type: "token", text: "再打开携程" }, nid);
    s = applyStreamEvent(s, { type: "final", text: "先查官网再打开携程完整总结" }, nid);
    const roles = s.messages.map((m) => (m.role === "tool" ? `tool:${m.toolName}` : m.role));
    expect(roles).toEqual(["thinking", "assistant", "tool:websearch", "assistant"]);
    const assistants = s.messages.filter((m) => m.role === "assistant");
    expect(assistants[0]?.content).toBe("先查官网");
    expect(assistants[1]?.content).toBe("再打开携程");
  });

  test("tool_call keeps args after result so edit/bash can render", () => {
    let s = base();
    s = applyStreamEvent(
      s,
      {
        type: "tool_call",
        name: "edit",
        args: { filePath: "a.py", oldString: "x", newString: "y" },
      },
      nid,
    );
    const running = s.messages.find((m) => m.role === "tool");
    expect(running?.toolStatus).toBe("running");
    expect(running?.content).toBe("");
    expect(running?.toolArgs).toContain("oldString");
    expect(running?.toolExpanded).toBe(true);
    s = applyStreamEvent(s, { type: "tool_result", name: "edit", result: "ok" }, nid);
    const done = s.messages.find((m) => m.role === "tool");
    expect(done?.toolStatus).toBe("success");
    expect(done?.content).toBe("ok");
    expect(done?.toolArgs).toContain("newString");
    expect(done?.endedAt).toBeGreaterThan(0);
    expect(done?.toolExpanded).toBe(true);
  });

  test("tool_result matches call_id so a later vision end does not close read", () => {
    let s = base();
    s = applyStreamEvent(
      s,
      { type: "tool_call", name: "read", call_id: "r1", args: { filePath: "a.css" } },
      nid,
    );
    s = applyStreamEvent(
      s,
      { type: "tool_call", name: "vision", call_id: "v1", args: { filePath: "a.jpg" } },
      nid,
    );
    s = applyStreamEvent(
      s,
      { type: "tool_result", name: "", call_id: "v1", result: "image ok" },
      nid,
    );
    const read = s.messages.find((m) => m.toolName === "read");
    const vision = s.messages.find((m) => m.toolName === "vision");
    expect(vision?.toolStatus).toBe("success");
    expect(vision?.content).toBe("image ok");
    expect(read?.toolStatus).toBe("running");
  });

  test("question tool_call shows the prompt instead of raw JSON", () => {
    const next = applyStreamEvent(
      base(),
      {
        type: "tool_call",
        name: "question",
        args: {
          questions: [{ question: "哪个环节慢？", header: "确认问题" }],
        },
      },
      nid,
    );
    const tool = next.messages.find((m) => m.role === "tool");
    expect(tool?.toolName).toBe("question");
    expect(tool?.content).toBe("确认问题: 哪个环节慢？");
    expect(tool?.content).not.toContain("questions");
  });

  test("stage separator progress stays out of the chat stream (2026-09-23 P1b)", () => {
    // 阶段分隔线不再渲染成主聊流里的 system 消息（仪式条取消）；
    // 阶段信息只走状态行。
    const next = applyStreamEvent(
      base(),
      { type: "progress", text: "──────── plan · architect ────────" },
      nid,
    );
    const sep = next.messages.find((m) => m.role === "system");
    expect(sep).toBeUndefined();
  });
});

describe("intermediate (子代理中间输出) 不进主聊流（2026-09-23 P0/P1b）", () => {
  // base() 预置一条 thinking 消息；断言只看「没有新增 assistant/system 消息」。
  test("intermediate token does not append to messages", () => {
    const before = base().messages.length;
    const next = applyStreamEvent(
      base(),
      { type: "token", text: "子代理的中间文本", intermediate: true },
      nid,
    );
    expect(next.messages).toHaveLength(before);
    expect(next.acc).toBe("");
    expect(next.assistantCreated).toBe(false);
  });

  test("intermediate reasoning does not open a thought slice", () => {
    const before = base().messages.length;
    const next = applyStreamEvent(
      base(),
      { type: "reasoning", thinking: "子代理的思维链内容", intermediate: true },
      nid,
    );
    expect(next.messages).toHaveLength(before);
    expect(next.hasReasoning).toBe(false);
    expect(next.reasoningAcc).toBe("");
  });

  test("main-agent token/reasoning without the flag still renders", () => {
    let next = applyStreamEvent(base(), { type: "token", text: "主代理" }, nid);
    const assistant = next.messages.find((m) => m.role === "assistant");
    expect(assistant?.content).toBe("主代理");
    next = applyStreamEvent(next, { type: "reasoning", thinking: "主代理思维链内容推理" }, nid);
    expect(next.hasReasoning).toBe(true);
  });
});
