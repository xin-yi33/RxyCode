import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import type { ChatMessage } from "../types.ts";

type StatusAxiosConfig = { signal?: AbortSignal };

let statusPayload: unknown = { capabilities: { prompt_attachments: true } };
let statusBehavior: ((config?: StatusAxiosConfig) => Promise<{ data: unknown }>) | null = null;
let statusCalls = 0;
let statusSignal: AbortSignal | undefined;
const axiosGet = mock(async (_url: string, config?: StatusAxiosConfig) => {
  statusCalls += 1;
  statusSignal = config?.signal;
  if (statusBehavior) return statusBehavior(config);
  return { data: statusPayload };
});

mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: mock(async () => ({ data: {} })),
    isAxiosError: () => false,
  },
}));

const { httpTransport } = await import("./httpTransport.ts");

const originalFetch = globalThis.fetch;
const originalFetchStatus = httpTransport.fetchStatus;
let streamCalls = 0;
let messages: ChatMessage[] = [];

function doneResponse(): Response {
  return new Response('data: {"type":"done"}\n\n', {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function callbacks() {
  return {
    onMessages: (updater: (previous: ChatMessage[]) => ChatMessage[]) => {
      messages = updater(messages);
    },
    onStreaming: () => {},
    onStatus: () => {},
  };
}

function setSuccessfulChatFetch(): void {
  globalThis.fetch = (async () => {
    streamCalls += 1;
    return doneResponse();
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  statusPayload = { capabilities: { prompt_attachments: true } };
  statusBehavior = null;
  statusCalls = 0;
  statusSignal = undefined;
  streamCalls = 0;
  messages = [];
  axiosGet.mockClear();
  httpTransport.fetchStatus = async () => {};
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  httpTransport.fetchStatus = originalFetchStatus;
});

describe("HTTP clipboard attachment fallback", () => {
  test("accepts an advertised capability and sends metadata through the existing stream request", async () => {
    let capturedBody: Record<string, unknown> | undefined;
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      streamCalls += 1;
      capturedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return doneResponse();
    }) as unknown as typeof fetch;

    await httpTransport.sendChatMessage(
      "inspect",
      "build",
      callbacks(),
      undefined,
      undefined,
      [{ path: "C:\\fixtures\\diagram.png", name: "diagram.png" }],
    );

    expect(statusCalls).toBe(1);
    expect(streamCalls).toBe(1);
    expect(capturedBody).toEqual({
      message: "inspect",
      mode: "build",
      attachments: [{ path: "C:\\fixtures\\diagram.png", name: "diagram.png" }],
    });
    expect(messages.find((message) => message.role === "user")?.attachments).toEqual([
      { path: "C:\\fixtures\\diagram.png", name: "diagram.png" },
    ]);
  });

  test("rejects missing, false, and offline status capabilities before creating a message or stream", async () => {
    for (const response of [
      {},
      { capabilities: {} },
      { capabilities: { prompt_attachments: false } },
      null,
    ]) {
      statusPayload = response;
      await expect(httpTransport.sendChatMessage(
        "inspect",
        "build",
        callbacks(),
        undefined,
        undefined,
        [{ path: "C:\\fixtures\\diagram.png" }],
      )).rejects.toThrow(/prompt_attachments/);
      expect(messages).toEqual([]);
      expect(streamCalls).toBe(0);
    }
    expect(statusCalls).toBe(4);
  });

  test("ordinary turns do not make the attachment capability status request", async () => {
    setSuccessfulChatFetch();

    await httpTransport.sendChatMessage("plain turn", "build", callbacks());

    expect(statusCalls).toBe(0);
    expect(streamCalls).toBe(1);
    expect(messages.find((message) => message.role === "user")?.content).toBe("plain turn");
  });

  test("aborting capability preflight is propagated and prevents chat submission", async () => {
    let notifyStatusStarted!: () => void;
    const statusStarted = new Promise<void>((resolve) => { notifyStatusStarted = resolve; });
    statusBehavior = (config) => new Promise((_resolve, reject) => {
      notifyStatusStarted();
      config?.signal?.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
    });
    const controller = new AbortController();
    const pending = httpTransport.sendChatMessage(
      "inspect",
      "build",
      callbacks(),
      controller.signal,
      undefined,
      [{ path: "C:\\fixtures\\diagram.png" }],
    );
    await statusStarted;
    controller.abort();

    await expect(pending).rejects.toHaveProperty("name", "AbortError");
    expect(statusSignal).toBe(controller.signal);
    expect(streamCalls).toBe(0);
    expect(messages).toEqual([]);
  });

  test("bubbles stream admission rejection without retrying the attachment request", async () => {
    globalThis.fetch = (async () => {
      streamCalls += 1;
      return new Response(
        'data: {"type":"error","message":"unsupported-vision: no vision model"}\n\n' +
          'data: {"type":"done"}\n\n',
        {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        },
      );
    }) as unknown as typeof fetch;

    await expect(httpTransport.sendChatMessage(
      "inspect",
      "build",
      callbacks(),
      undefined,
      undefined,
      [{ path: "C:\\fixtures\\diagram.png", name: "diagram.png" }],
    )).rejects.toThrow(/unsupported-vision/);
    expect(streamCalls).toBe(1);
    expect(messages.find((message) => message.role === "user")?.attachments).toEqual([
      { path: "C:\\fixtures\\diagram.png", name: "diagram.png" },
    ]);
  });
});
