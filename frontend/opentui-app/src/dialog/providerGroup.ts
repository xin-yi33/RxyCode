/**
 * Infer OpenCode-style provider group from a base URL.
 * Known preset hosts map to their display name; unknown -> other.
 */

export type InferredProvider = { id: string; name: string };

const HOST_GROUPS: Array<{ match: RegExp; id: string; name: string }> = [
  { match: /deepseek\.com$/i, id: "deepseek", name: "DeepSeek" },
  { match: /moonshot\.(cn|ai)$/i, id: "moonshot", name: "Moonshot Kimi" },
  { match: /dashscope\.aliyuncs\.com$/i, id: "dashscope", name: "阿里云百炼 / 通义千问" },
  { match: /volces\.com$/i, id: "volces_ark", name: "火山方舟 Ark" },
  { match: /bigmodel\.cn$/i, id: "zhipu", name: "智谱 GLM" },
  { match: /siliconflow\.(cn|com)$/i, id: "siliconflow", name: "SiliconFlow 硅基流动" },
  { match: /openai\.com$/i, id: "openai", name: "OpenAI" },
  { match: /openrouter\.ai$/i, id: "openrouter", name: "OpenRouter" },
  { match: /groq\.com$/i, id: "groq", name: "Groq" },
  { match: /together\.(xyz|ai)$/i, id: "together", name: "Together AI" },
  { match: /opencode\.ai$/i, id: "opencode-go", name: "OpenCode Go" },
];

export function inferProviderFromUrl(baseUrl: string): InferredProvider {
  try {
    const host = new URL(baseUrl.trim()).hostname.replace(/^www\./i, "");
    for (const row of HOST_GROUPS) {
      if (row.match.test(host)) {
        return { id: row.id, name: row.name };
      }
    }
  } catch {
    // ignore parse errors
  }
  return { id: "custom", name: "其他" };
}
