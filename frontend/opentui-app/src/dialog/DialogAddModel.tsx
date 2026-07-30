/**
* OpenTUI Add-model wizard — OpenCode Connect-provider state machine.
*
*   阶段          非自定义                                          自定义
*   provider      DialogSelect over PROVIDER_PRESETS                  (含 "+ 自定义")
*   api_url       文本输入（preset 预填，可改）                        文本输入（必填）
*   api_key       文本输入（掩码）                                    文本输入
*   loading       自动 GET {base}/models 探针                         —
*   select        DialogSelect over discover 返回的 model id          —
*   custom_id     —                                                  文本输入
*   nickname      文本输入（可空）                                    文本输入
*   submit        POST /models/onboard                                POST /models/onboard
*
* 注：model id 不再写死在 preset；只能来自后端 discover 探针或用户自定义手填。
*/

import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import { C } from "../theme.ts";
import { SELECT_BG, SELECT_FG } from "./colors.ts";
import { discoverProviderModels, onboardModel } from "./api.ts";
import { DialogSelect, type DialogSelectOption, textFromKeyEvent } from "./DialogSelect.tsx";

type Phase =
  | "provider"
  | "api_url"
  | "api_key"
  | "loading"
  | "select"
  | "custom_id"
  | "nickname"
  | "submit";

type ProviderPreset = {
  id: string;
  name: string;
  baseUrl: string;
  category?: "常用" | "其他";
};

type ProviderPick = ProviderPreset | "__custom__";

const PROVIDER_PRESETS: ProviderPreset[] = [
  { id: "openai", name: "OpenAI", baseUrl: "https://api.openai.com/v1", category: "常用" },
  { id: "azure-openai", name: "Azure OpenAI", baseUrl: "https://{resource-name}.openai.azure.com/openai/v1", category: "其他" },
  { id: "anthropic", name: "Anthropic Claude", baseUrl: "https://api.anthropic.com/v1", category: "常用" },
  { id: "gemini", name: "Google Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/", category: "常用" },
  { id: "deepseek", name: "DeepSeek", baseUrl: "https://api.deepseek.com", category: "常用" },
  { id: "volcengine", name: "火山方舟", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", category: "其他" },
  { id: "qwen", name: "阿里云百炼", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", category: "常用" },
  { id: "hunyuan", name: "腾讯混元", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", category: "其他" },
  { id: "zhipu", name: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", category: "其他" },
  { id: "moonshot", name: "Kimi / Moonshot", baseUrl: "https://api.moonshot.cn/v1", category: "其他" },
];

const PROVIDER_OPTIONS: DialogSelectOption<ProviderPick>[] = [
  ...PROVIDER_PRESETS.map((p) => ({
    id: p.id,
    title: p.name,
    description: p.baseUrl,
    footer: p.id,
    category: p.category ?? "其他",
    value: p as ProviderPick,
  })),
  {
    id: "__custom__",
    title: "+ 自定义",
    description: "手填 model id / URL / Key（无 GET /models 探针）",
    category: "操作",
    value: "__custom__" as ProviderPick,
  },
];

const PHASES_NON_CUSTOM: Phase[] = ["provider", "api_url", "api_key", "loading", "select", "nickname"];
const PHASES_CUSTOM: Phase[] = ["provider", "api_url", "api_key", "custom_id", "nickname"];
const INPUT_PHASES: Phase[] = ["api_url", "api_key", "custom_id", "nickname"];

type Data = {
  apiUrl: string;
  apiKey: string;
  providerModelId: string;
  nickname: string;
};

type PhaseMeta = {
  label: string;
  placeholder: string;
  hint: string;
  field: keyof Data | null;
  masked: boolean;
};

function getPhaseMeta(p: Phase): PhaseMeta {
  switch (p) {
    case "api_url":
      return { label: "URL", placeholder: "https://api.deepseek.com", hint: "携带密钥的连接必须使用 HTTPS", field: "apiUrl", masked: false };
    case "api_key":
      return { label: "Key", placeholder: "sk-...", hint: "密钥本地仅回显掩码", field: "apiKey", masked: true };
    case "custom_id":
      return { label: "Model ID", placeholder: "model id（如 deepseek-chat）", hint: "由 provider 直接给出的精确 model id", field: "providerModelId", masked: false };
    case "nickname":
      return { label: "昵称", placeholder: "留空则等于模型名", hint: "回车跳过", field: "nickname", masked: false };
    default:
      return { label: "", placeholder: "", hint: "", field: null, masked: false };
  }
}

function maskKey(s: string): string {
  if (s.length <= 8) return "****";
  return `${s.slice(0, 4)}...${s.slice(-4)}`;
}

function shellStyle() {
  return {
    flexShrink: 0 as const,
    flexDirection: "column" as const,
    width: "100%" as const,
    border: true as const,
    borderColor: C.primary,
    borderStyle: "rounded" as const,
    paddingLeft: 1 as const,
    paddingRight: 1 as const,
    backgroundColor: C.bg,
  };
}

export function DialogAddModel({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [phase, setPhase] = useState<Phase>("provider");
  const [customMode, setCustomMode] = useState(false);
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [data, setData] = useState<Data>({
    apiUrl: "",
    apiKey: "",
    providerModelId: "",
    nickname: "",
  });
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const focusRef = useRef<InputRenderable>(null);

  const flowPhases = customMode ? PHASES_CUSTOM : PHASES_NON_CUSTOM;
  const flowIdx = flowPhases.indexOf(phase);

  // 进入文本输入阶段时聚焦 + 清空 draft
  useEffect(() => {
    try {
      focusRef.current?.focus();
      if (focusRef.current) focusRef.current.value = "";
      setDraft("");
    } catch {
      // ignore
    }
  }, [phase]);

  // 自动副作用：loading 触发 discover；submit 触发 onboard
  useEffect(() => {
    if (phase === "loading") {
      void runDiscover();
    } else if (phase === "submit") {
      void runOnboard();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  async function runDiscover() {
    setError("");
    setBusy(true);
    const r = await discoverProviderModels({ baseUrl: data.apiUrl, apiKey: data.apiKey });
    setBusy(false);
    if (!r.ok || r.models.length === 0) {
      setError(r.error || "未发现任何模型，请检查 URL 与 Key");
      setPhase("api_key");
      return;
    }
    setDiscovered(r.models);
    setPhase("select");
  }

  async function runOnboard() {
    setBusy(true);
    const r = (await onboardModel({
      providerModelId: data.providerModelId,
      apiKey: data.apiKey,
      baseUrl: data.apiUrl,
      nickname: data.nickname || undefined,
    })) as Record<string, unknown>;
    setBusy(false);
    const detail = typeof r.detail === "string" ? r.detail : null;
    if (r.action === "error" || detail) {
      setError(String(r.message || detail || "添加失败"));
      setPhase("nickname");
      return;
    }
    onDone(String(r.message || `模型已添加: ${data.nickname || data.providerModelId}`));
    onClose();
  }

  function submitTextStep(text: string) {
    const meta = getPhaseMeta(phase);
    if (!meta.field) return;
    const trimmed = text.trim();
    const nextData = { ...data, [meta.field]: trimmed };
    setData(nextData);
    setError("");

    if (phase === "api_url") {
      setPhase("api_key");
    } else if (phase === "api_key") {
      setPhase(customMode ? "custom_id" : "loading");
    } else if (phase === "custom_id") {
      setPhase("nickname");
    } else if (phase === "nickname") {
      setPhase("submit");
    }
  }

  useKeyboard((key) => {
    // provider / select 由 DialogSelect 接管；loading / submit 阻塞输入
    if (phase === "provider" || phase === "select") return;
    if (phase === "loading" || phase === "submit") {
      if (key.name === "escape") {
        key.preventDefault?.();
        onClose();
      }
      return;
    }
    if (busy) return;
    if (key.name === "escape") {
      key.preventDefault?.();
      onClose();
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      void submitTextStep(draft);
      return;
    }
    if (key.name === "backspace" || key.name === "delete") {
      key.preventDefault?.();
      setDraft((d) => {
        const next = d.slice(0, -1);
        try {
          if (focusRef.current) focusRef.current.value = next;
        } catch {
          // ignore
        }
        return next;
      });
      return;
    }
    const parsed = textFromKeyEvent(key);
    if (!parsed) return;
    if (parsed.text) {
      key.preventDefault?.();
      setDraft((d) => {
        const next = d + parsed.text;
        try {
          if (focusRef.current) focusRef.current.value = next;
        } catch {
          // ignore
        }
        return next;
      });
    }
    if (parsed.submit) {
      key.preventDefault?.();
      void submitTextStep(draft + (parsed.text || ""));
    }
  });

  // ============================================================
  // 渲染分支
  // ============================================================

  // 阶段 1：选 provider（含 "+ 自定义"）
  if (phase === "provider") {
    return (
      <DialogSelect<ProviderPick>
        title="添加模型"
        placeholder="搜索服务商"
        options={PROVIDER_OPTIONS}
        categoryOrder={["常用", "其他", "操作"]}
        maxVisible={10}
        onSelect={(opt) => {
          if (opt.value === "__custom__") {
            setCustomMode(true);
            setData({ apiUrl: "", apiKey: "", providerModelId: "", nickname: "" });
          } else {
            const preset = opt.value as ProviderPreset;
            setCustomMode(false);
            setData({ apiUrl: preset.baseUrl, apiKey: "", providerModelId: "", nickname: "" });
          }
          setPhase("api_url");
        }}
        onClose={onClose}
      />
    );
  }

  // 阶段 select：选已发现模型
  if (phase === "select") {
    const opts: DialogSelectOption<string>[] = discovered.map((id) => ({
      id,
      title: id,
      description: id,
      category: "可用模型",
      value: id,
    }));
    return (
      <DialogSelect<string>
        title="选择模型"
        placeholder="搜索探针返回的模型"
        options={opts}
        categoryOrder={["可用模型"]}
        maxVisible={10}
        onSelect={(opt) => {
          setData((d) => ({ ...d, providerModelId: opt.value }));
          setPhase("nickname");
        }}
        onClose={onClose}
      />
    );
  }

  // 阶段 loading / submit：状态视图
  if (phase === "loading" || phase === "submit") {
    const status = phase === "loading" ? "⠋ 探测可用模型…" : "⠋ 保存并接入中…";
    const title = phase === "loading" ? "Discovering" : "Saving";
    return (
      <box style={shellStyle()}>
        <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
          <text fg={C.primary} attributes={1}>
            {" 添加模型"}
          </text>
          <box style={{ flexGrow: 1, height: 1 }} />
          <text fg={C.overlay2}>esc </text>
        </box>
        <box style={{ height: 1, width: "100%" }}>
          <text fg={C.mauve} attributes={1}>{`  ${status}`}</text>
        </box>
        <box style={{ height: 1, width: "100%" }}>
          <text fg={C.overlay2}>{`  ${title}`}</text>
        </box>
        {error ? (
          <box style={{ height: 1, width: "100%" }}>
            <text fg={C.yellow}>{"  ⚠ "}{error}</text>
          </box>
        ) : null}
      </box>
    );
  }

  // ============================================================
  // 文本输入阶段（api_url / api_key / custom_id / nickname）
  // ============================================================
  const meta = getPhaseMeta(phase);
  const storedValue = meta.field ? (data[meta.field] as string) : "";
  const liveValue = draft.length > 0 ? draft : storedValue;
  const shownValue = meta.masked && liveValue ? maskKey(liveValue) : liveValue;

  const collected = INPUT_PHASES.filter(
    (p) =>
      flowPhases.indexOf(p) >= 0 &&
      flowPhases.indexOf(p) < (flowIdx >= 0 ? flowIdx : flowPhases.length),
  ).map((p) => {
    const m = getPhaseMeta(p);
    const value = m.field ? (data[m.field] as string) : "";
    return {
      phase: p,
      label: m.label,
      value: m.masked ? maskKey(value) : value,
    };
  });

  const totalShown = flowPhases.length;

  return (
    <box style={shellStyle()}>
      <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
        <text fg={C.primary} attributes={1}>
          {" 添加模型"}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </box>
      {collected.map((c) => (
        <box key={c.phase} style={{ height: 1, width: "100%" }}>
          <text fg={C.green}>
            {"  ✓ "}
            {c.label}: {c.value}
          </text>
        </box>
      ))}
      {error ? (
        <box style={{ height: 1, width: "100%" }}>
          <text fg={C.yellow}>{"  ⚠ "}{error}</text>
        </box>
      ) : null}
      <box style={{ height: 1, width: "100%" }}>
        <text fg={C.yellow} attributes={1}>
          {"  "}
          {`[${flowIdx + 1}/${totalShown}] ${meta.label}`}
        </text>
      </box>
      <box style={{ flexDirection: "row", height: 1, width: "100%" }}>
        <text fg={C.primary}>{"> "}</text>
        <text fg={SELECT_FG} bg={liveValue ? undefined : SELECT_BG}>
          {(shownValue || meta.placeholder).slice(0, 1) || " "}
        </text>
        <text fg={liveValue ? C.text : C.overlay2}>
          {shownValue ? shownValue.slice(1) : meta.placeholder.slice(1)}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <input
          ref={focusRef}
          focused
          onInput={(v) => setDraft(String(v ?? ""))}
          onSubmit={() => {
            if (!busy) void submitTextStep(draft);
          }}
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 0,
            height: 0,
            flexShrink: 0,
            backgroundColor: C.bg,
          }}
        />
      </box>
      <box style={{ height: 1, width: "100%" }}>
        <text fg={C.overlay2}>
          {"  "}
          {busy ? "处理中…" : meta.hint}
        </text>
      </box>
    </box>
  );
}
