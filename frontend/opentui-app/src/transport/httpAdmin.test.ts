import { describe, expect, mock, test } from "bun:test";

const axiosPost = mock(() =>
  Promise.resolve({ data: { action: "model_changed", message: "ok" } }),
);

mock.module("axios", () => ({
  default: {
    post: axiosPost,
    isAxiosError: (err: unknown) =>
      typeof err === "object" &&
      err !== null &&
      "isAxiosError" in err &&
      (err as { isAxiosError?: boolean }).isAxiosError === true,
  },
}));

const { httpSendCommand } = await import("./httpAdmin.ts");

describe("httpSendCommand", () => {
  test("network failure returns structured error", async () => {
    axiosPost.mockImplementationOnce(() => {
      const err = new Error("connect ECONNREFUSED") as Error & {
        isAxiosError: boolean;
        code: string;
      };
      err.isAxiosError = true;
      err.code = "ECONNREFUSED";
      return Promise.reject(err);
    });
    expect(await httpSendCommand("/model x")).toEqual({
      ok: false,
      error: "无法连接 API 服务",
    });
  });

  test("server action=error normalizes to ok=false", async () => {
    axiosPost.mockImplementationOnce(() =>
      Promise.resolve({
        data: { action: "error", message: "Model not found: x" },
      }),
    );
    expect(await httpSendCommand("/model x")).toEqual({
      ok: false,
      action: "error",
      message: "Model not found: x",
      error: "Model not found: x",
    });
  });
});
