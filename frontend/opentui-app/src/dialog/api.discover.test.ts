import { describe, expect, mock, test } from "bun:test";

const axiosPost = mock(() => Promise.resolve({ data: { models: [] } }));

function axiosError(detail: unknown) {
  const err = new Error("Request failed") as Error & {
    isAxiosError: boolean;
    response: { data: { detail: unknown } };
  };
  err.isAxiosError = true;
  err.response = { data: { detail } };
  return err;
}

mock.module("axios", () => ({
  default: {
    post: axiosPost,
    isAxiosError: (err: unknown) =>
      Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
  },
  isAxiosError: (err: unknown) =>
    Boolean(err && typeof err === "object" && (err as { isAxiosError?: boolean }).isAxiosError),
}));

const { discoverModels } = await import("./api.ts");

describe("discoverModels", () => {
  test("maps structured 400 detail to errorCode", async () => {
    axiosPost.mockImplementationOnce(() =>
      Promise.reject(
        axiosError({
          message: "Model discovery failed: 认证失败",
          error_code: "auth",
        }),
      ),
    );

    const result = await discoverModels({
      apiKey: "sk",
      baseUrl: "https://example.com/v1",
    });

    expect(result.ok).toBe(false);
    expect(result.errorCode).toBe("auth");
    expect(result.error).toContain("认证失败");
  });

  test("treats legacy string detail as transport", async () => {
    axiosPost.mockImplementationOnce(() =>
      Promise.reject(axiosError("Model discovery failed: boom")),
    );

    const result = await discoverModels({
      apiKey: "sk",
      baseUrl: "https://example.com/v1",
    });

    expect(result.ok).toBe(false);
    expect(result.errorCode).toBe("transport");
    expect(result.error).toContain("boom");
  });
});
