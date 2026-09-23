import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  applyTokenUsageToStatus,
  parseStdioAdminCommand,
  shouldRestartStdioSessionOnModelSwitch,
  statusFromModelsList,
  statusModelLabel,
} from "./stdioCommands.ts";

describe("stdio admin commands", () => {
  test("/model is handled locally instead of HTTP + session restart", () => {
    expect(parseStdioAdminCommand("/model deepseek/deepseek-v4-flash")).toEqual({
      kind: "model",
      modelId: "deepseek/deepseek-v4-flash",
    });
    expect(shouldRestartStdioSessionOnModelSwitch()).toBe(false);
  });

  test("/thinking stays local", () => {
    expect(parseStdioAdminCommand("/thinking")).toEqual({ kind: "thinking" });
  });

  test("other slash commands still go through HTTP admin", () => {
    expect(parseStdioAdminCommand("/status")).toEqual({
      kind: "http",
      command: "/status",
    });
  });

  test("status bar uses persisted active model before the worker starts", () => {
    const status = statusFromModelsList({
      active: "deepseek/deepseek-v4-flash",
      models: [
        {
          id: "deepseek/deepseek-v4-flash",
          name: "deepseek-v4-flash",
          nickname: "deepseek-v4-flash",
          active: true,
        },
      ],
    });
    expect(status.model).toBe("deepseek-v4-flash");
  });

  test("copies context_window into context_max_k and keeps prior usage", () => {
    const status = statusFromModelsList(
      {
        active: "m1",
        models: [{ id: "m1", name: "m1", context_window: 131072, active: true }],
      },
      { context_used_k: 2.4, cache_size: "800", cache_rate: "12.5%" },
    );
    expect(status.context_max_k).toBe(131);
    expect(status.context_used_k).toBe(2.4);
    expect(status.cache_size).toBe("800");
    expect(status.cache_rate).toBe("12.5%");
  });

  test("copies persisted effort into the status chip", () => {
    const status = statusFromModelsList({
      active: "deepseek/deepseek-v4-flash",
      effort: "max",
      models: [
        {
          id: "deepseek/deepseek-v4-flash",
          name: "deepseek-v4-flash",
          nickname: "deepseek-flash",
          active: true,
          effort_options: ["low", "high", "max"],
        },
      ],
    });
    expect(status.model).toBe("deepseek-flash");
    expect(status.effort).toBe("max");
  });

  test("duplicate nicknames include the endpoint host on the status chip", () => {
    const listed = {
      active: "custom-api-arc-bench-com/kimi-k3",
      models: [
        {
          id: "opencode-go/kimi-k3",
          name: "kimi-k3",
          nickname: "kimi-k3",
          category: "OpenCode Go",
          base_url: "https://opencode.ai/zen/go/v1",
        },
        {
          id: "custom-api-arc-bench-com/kimi-k3",
          name: "kimi-k3",
          nickname: "kimi-k3",
          category: "api.arc-bench.com",
          base_url: "https://api.arc-bench.com/v1",
          active: true,
        },
      ],
    };
    expect(statusModelLabel(listed)).toBe("kimi-k3 · api.arc-bench.com");
    expect(statusFromModelsList(listed).model).toBe("kimi-k3 · api.arc-bench.com");
  });
});

describe("applyTokenUsageToStatus", () => {
  test("fills context and cache from a reported token_usage event", () => {
    const status = applyTokenUsageToStatus(
      { model: "deepseek-v4-flash", context_max_k: 256 },
      {
        input_tokens: 1200,
        output_tokens: 300,
        cache_hit_tokens: 800,
        cache_hit_rate: 66.7,
        context_used: 1500,
        reporting_status: "reported",
      },
    );
    expect(status.context_used_k).toBe(1.5);
    expect(status.cache_size).toBe("800");
    expect(status.cache_rate).toBe("66.7%");
    expect(status.model).toBe("deepseek-v4-flash");
  });

  test("does not treat cached billing input as occupancy", () => {
    const status = applyTokenUsageToStatus(
      { model: "m", context_used_k: 23.4, context_max_k: 1049 },
      {
        input_tokens: 208248,
        output_tokens: 1729,
        cache_hit_tokens: 205696,
        cache_hit_rate: 98.8,
        reporting_status: "reported",
      },
    );
    expect(status.context_used_k).toBe(23.4);
    expect(status.cache_size).toBe("205.7K");
    expect(status.cache_rate).toBe("98.8%");
  });

  test("billing-only payload does not invent occupancy", () => {
    const status = applyTokenUsageToStatus(
      { model: "m", context_max_k: 1049 },
      {
        input_tokens: 3703115,
        output_tokens: 16935,
        cache_hit_tokens: 3656832,
        cache_hit_rate: 98.8,
        reporting_status: "reported",
      },
    );
    expect(status.context_used_k ?? 0).toBe(0);
    expect(status.cache_size).toBe("3.66M");
    expect(status.cache_rate).toBe("98.8%");
  });

  test("prefers context_used window occupancy over last-turn delta", () => {
    const status = applyTokenUsageToStatus(
      { model: "m", context_used_k: 2.4, context_max_k: 256 },
      {
        input_tokens: 800,
        output_tokens: 200,
        context_used: 58600,
        reporting_status: "reported",
      },
    );
    expect(status.context_used_k).toBe(58.6);
  });

  test("ignores not_reported payloads so zeros do not wipe a live bar", () => {
    const previous = {
      model: "m",
      context_used_k: 2.4,
      cache_size: "800",
      cache_rate: "12.5%",
    };
    expect(
      applyTokenUsageToStatus(previous, {
        reporting_status: "not_reported",
        input_tokens: null,
        output_tokens: null,
        cache_hit_tokens: null,
      }),
    ).toEqual(previous);
  });
});

describe("stdio transport model switch regression", () => {
  test("does not shut down the live worker after /model", () => {
    const src = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "stdioTransport.ts"),
      "utf8",
    );
    expect(src).not.toMatch(/model_changed[\s\S]{0,400}sharedSession\.shutdown/);
  });

  test("interrupt clears Processing before waiting for session/interrupt", () => {
    const src = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "stdioTransport.ts"),
      "utf8",
    );
    const interrupt = src.slice(src.indexOf("async interrupt()"));
    const streamingIdx = interrupt.indexOf("onStreaming(false)");
    const rpcIdx = interrupt.indexOf("session/interrupt");
    expect(streamingIdx).toBeGreaterThanOrEqual(0);
    expect(rpcIdx).toBeGreaterThan(streamingIdx);
  });

  test("stdio fetchStatus does not fall back to HTTP /status", () => {
    const src = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "stdioTransport.ts"),
      "utf8",
    );
    const fetchStatus = src.slice(src.lastIndexOf("async fetchStatus("));
    expect(fetchStatus).not.toMatch(/httpFetchStatus/);
    expect(src).toMatch(/raceWithAbort/);
  });

  test("stdio warms on open and acks the first keystroke immediately", () => {
    const transport = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "stdioTransport.ts"),
      "utf8",
    );
    const index = readFileSync(
      path.join(path.dirname(fileURLToPath(import.meta.url)), "../index.tsx"),
      "utf8",
    );
    expect(transport).toMatch(/DEFAULT_INIT_TIMEOUT_MS = 60_000/);
    expect(transport).toMatch(/startStdioWarmOnOpen/);
    expect(transport).toMatch(/收到，正在回复/);
    expect(index).toMatch(/startStdioWarmOnOpen/);
    expect(index).toMatch(/writeDisableAllMotion/);
    expect(index).toMatch(/writeDisableMouseTracking/);
    expect(index).not.toMatch(/enableMouseMovement:\s*true/);
  });
});
