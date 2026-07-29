/**
 * Status / cache dialog — reads GET /status; no chat dump.
 */

import { useEffect, useState } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import { fetchStatusPayload } from "./api.ts";
import { C } from "../theme.ts";

function fmtRate(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return `${v.toFixed(1)}%`;
  if (typeof v === "string" && v.trim()) return v;
  return "暂无";
}

function fmtNum(v: unknown): string {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string" && v.trim()) return v;
  return "暂无";
}

export function DialogStatus({
  onClose,
  statusLine,
}: {
  onClose: () => void;
  statusLine: string;
}) {
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [options, setOptions] = useState<DialogSelectOption<string>[]>([]);

  useEffect(() => {
    void (async () => {
      setPhase("loading");
      const data = await fetchStatusPayload();
      if (!data) {
        setError("无法获取状态（后端离线或超时）");
        setPhase("error");
        setOptions([
          {
            id: "fallback",
            title: "本地摘要",
            description: statusLine || "offline",
            category: "状态",
            value: "fallback",
          },
        ]);
        return;
      }

      const provider = (data.provider_cache as Record<string, unknown> | undefined) || {};
      const app = (data.application_cache as Record<string, unknown> | undefined) || {};
      const precise = (app.precise as Record<string, unknown> | undefined) || {};
      const semantic = (app.semantic as Record<string, unknown> | undefined) || {};

      const rows: DialogSelectOption<string>[] = [
        {
          id: "model",
          title: "模型",
          description: String(data.model || "unknown"),
          category: "状态",
          value: "model",
        },
        {
          id: "mode",
          title: "模式",
          description: String(data.mode || "—"),
          category: "状态",
          value: "mode",
        },
        {
          id: "ctx",
          title: "上下文",
          description: `${data.context_used_k ?? 0}k / ${data.context_max_k ?? "?"}k`,
          category: "状态",
          value: "ctx",
        },
        {
          id: "p-hit",
          title: "Provider 命中 token",
          description: fmtNum(provider.hit_tokens ?? data.cache_size),
          category: "Provider 缓存",
          value: "p-hit",
        },
        {
          id: "p-rate",
          title: "Provider 命中率",
          description: fmtRate(provider.hit_rate ?? data.cache_rate),
          category: "Provider 缓存",
          value: "p-rate",
        },
        {
          id: "p-prompt",
          title: "Provider prompt tokens",
          description: fmtNum(provider.prompt_tokens),
          category: "Provider 缓存",
          value: "p-prompt",
        },
        {
          id: "a-precise",
          title: "Precise 命中率",
          description: fmtRate(precise.hit_rate),
          category: "应用缓存",
          value: "a-precise",
        },
        {
          id: "a-semantic",
          title: "Semantic 命中率",
          description: fmtRate(semantic.hit_rate),
          category: "应用缓存",
          value: "a-semantic",
        },
      ];

      setOptions(rows);
      setPhase("ready");
    })();
  }, [statusLine]);

  if (phase === "loading") {
    return (
      <box
        style={{
          flexShrink: 0,
          border: true,
          borderColor: C.borderDim,
          borderStyle: "rounded",
          paddingLeft: 1,
          paddingRight: 1,
          backgroundColor: C.bg,
        }}
      >
        <text fg={C.text} attributes={1}>
          {" 状态"}
        </text>
        <DialogLoading />
      </box>
    );
  }

  return (
    <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
      {phase === "error" ? <DialogError text={error} /> : null}
      <DialogSelect
        title="状态 / 缓存"
        options={options}
        categoryOrder={["状态", "Provider 缓存", "应用缓存"]}
        showSearch={false}
        onClose={onClose}
        onSelect={() => onClose()}
      />
    </box>
  );
}
