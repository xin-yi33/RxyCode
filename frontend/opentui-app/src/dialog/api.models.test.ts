import { describe, expect, mock, test } from "bun:test";

type ModelsPayload = { models: { id: string; name: string }[]; active: string };

const axiosGet = mock(
  (): Promise<{ data: ModelsPayload }> =>
    Promise.resolve({ data: { models: [], active: "" } }),
);

mock.module("axios", () => ({
  default: { get: axiosGet },
}));

const { probeModels } = await import("./api.ts");

describe("probeModels", () => {
  test("network failure returns ok:false", async () => {
    axiosGet.mockImplementationOnce(() => Promise.reject(new Error("ECONNREFUSED")));
    expect(await probeModels()).toEqual({ ok: false, models: [], active: "" });
  });

  test("empty models list returns ok:true", async () => {
    axiosGet.mockImplementationOnce(() =>
      Promise.resolve({ data: { models: [], active: "" } }),
    );
    expect(await probeModels()).toEqual({ ok: true, models: [], active: "" });
  });

  test("populated models returns ok:true with data", async () => {
    axiosGet.mockImplementationOnce(() =>
      Promise.resolve({
        data: { models: [{ id: "a", name: "Model A" }], active: "a" },
      }),
    );
    expect(await probeModels()).toEqual({
      ok: true,
      models: [{ id: "a", name: "Model A" }],
      active: "a",
    });
  });
});
