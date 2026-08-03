import { afterEach, describe, expect, mock, test } from "bun:test";

const axiosGet = mock(() =>
  Promise.resolve({
    data: {
      models: [
        {
          id: "provider/a",
          name: "provider/a",
          nickname: "Model A",
          provider_model_id: "a",
          category: "Provider",
        },
        {
          id: "provider/b",
          name: "provider/b",
          nickname: "Model B",
          provider_model_id: "b",
          category: "Provider",
        },
      ],
      active: "provider/a",
      recent: [],
    },
  }),
);

const axiosPost = mock(() =>
  Promise.resolve({
    data: { action: "model_changed", message: "Model switched: provider/b" },
  }),
);

mock.module("axios", () => ({
  default: {
    get: axiosGet,
    post: axiosPost,
    isAxiosError: (err: unknown) =>
      typeof err === "object" &&
      err !== null &&
      "isAxiosError" in err &&
      (err as { isAxiosError?: boolean }).isAxiosError === true,
  },
}));

const { fetchModels, sendCommand } = await import("./api.ts");
const { interpretModelSwitchResult, modelSwitchCommand } = await import(
  "./dialogModelFlow.ts"
);

describe("DialogModel HTTP flow", () => {
  afterEach(() => {
    axiosGet.mockClear();
    axiosPost.mockClear();
  });

  test("list → select second model → POST /command with namespaced id", async () => {
    const listed = await fetchModels();
    expect(listed.ok).toBe(true);
    expect(listed.models[1]?.id).toBe("provider/b");

    const command = modelSwitchCommand("provider/b");
    expect(command).toBe("/model provider/b");

    const result = await sendCommand(command);
    expect(axiosPost.mock.calls.length).toBe(1);
    const firstCall = axiosPost.mock.calls[0] as unknown as [string, { command: string }];
    expect(String(firstCall[0])).toContain("/command");
    expect(firstCall[1]).toEqual({ command: "/model provider/b" });

    const outcome = interpretModelSwitchResult("provider/b", result);
    expect(outcome).toEqual({
      ok: true,
      modelId: "provider/b",
      message: "Model switched: provider/b",
    });
  });

  test("http failure keeps dialog open semantics (no fake success)", async () => {
    axiosPost.mockImplementationOnce(() => Promise.reject(new Error("ECONNREFUSED")));
    const result = await sendCommand("/model provider/b");
    const outcome = interpretModelSwitchResult("provider/b", result);
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error).toBeTruthy();
    }
  });

  test("fetchModels surfaces network failure", async () => {
    axiosGet.mockImplementationOnce(() => Promise.reject(new Error("ECONNREFUSED")));
    const listed = await fetchModels();
    expect(listed.ok).toBe(false);
    expect(listed.models).toEqual([]);
    expect(listed.error).toBeTruthy();
  });
});
