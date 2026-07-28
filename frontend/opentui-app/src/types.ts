export type Mode = "build" | "plan" | "compose";

export type ToolStatus = "running" | "success" | "error" | "timeout" | "cancelled";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system" | "thinking";
  content: string;
  timestamp: number;
  toolName?: string;
  toolStatus?: ToolStatus;
  done?: boolean;
  live?: boolean;
}

export interface StatusInfo {
  memory_mb?: number;
  memory_pct?: number;
  billing?: number;
  cache_size?: string;
  cache_rate?: string;
  input_tokens?: number;
  output_tokens?: number;
  context_used_k?: number;
  context_max_k?: number;
  mode?: Mode;
  model?: string;
}

export const MODE_COLORS: Record<Mode, string> = {
  build: "#FF69B4",
  plan: "#00ff7f",
  compose: "#FFB6C1",
};

export const MODE_LABELS: Record<Mode, string> = {
  build: "Build",
  plan: "Plan",
  compose: "Compose",
};

export const MODES: Mode[] = ["build", "plan", "compose"];
