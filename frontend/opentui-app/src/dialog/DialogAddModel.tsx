/**
 * OpenTUI Add-model flow — OpenCode "Connect a provider" shape.
 *
 * provider (DialogSelect) → key (DialogPrompt) → discover → model (DialogSelect)
 * → optional nickname → POST /models/onboard
 *
 * Every screen is DialogSelect or DialogPrompt, so search / ↑↓ / hover / wheel /
 * block cursor / category headers / chrome all come from the shared components
 * instead of being hand-drawn here.
 *
 * Model ids are never hard-coded: presets carry provider + base URL only, and
 * ids come from POST /models/discover or from the user's own input.
 */

import { useEffect, useState } from "react";
import { DialogSelect, type DialogSelectOption } from "./DialogSelect.tsx";
import { DialogPrompt } from "./DialogPrompt.tsx";
import { DialogError, DialogLoading } from "./DialogStates.tsx";
import {
  discoverModels,
  fetchProviderPresets,
  onboardModel,
  onboardModelsBatch,
  type DiscoveredModel,
  type ProviderPreset,
} from "./api.ts";

const CUSTOM_ID = "__custom__";
const MANUAL_MODEL_ID = "__manual_model__";

type Stage =
  | "provider"
  | "custom_url"
  | "api_key"
  | "discovering"
  | "model"
  | "model_multi"
  | "manual_model"
  | "nickname"
  | "saving";

/** Build the provider list: backend presets, grouped, plus a custom escape hatch. */
export function buildProviderOptions(
  presets: ProviderPreset[],
): DialogSelectOption<string>[] {
  const options: DialogSelectOption<string>[] = presets.map((preset) => ({
    id: preset.id,
    title: preset.name,
    description: preset.base_url,
    category: preset.category || "其他",
    value: preset.id,
  }));
  options.push({
    id: CUSTOM_ID,
    title: "自定义服务商",
    description: "手动填写 API URL 与模型 ID",
    category: "其他",
    value: CUSTOM_ID,
  });
  return options;
}

/** Discovered ids for preset multi-select (no manual row). */
export function buildMultiModelOptions(
  models: DiscoveredModel[],
): DialogSelectOption<string>[] {
  return models.map((model) => ({
    id: model.id,
    title: model.id,
    description: model.owned_by || "",
    category: "可用模型",
    value: model.id,
  }));
}

/** Discovered ids become plain options; a manual-entry row stays available. */
export function buildModelOptions(
  models: DiscoveredModel[],
): DialogSelectOption<string>[] {
  const options: DialogSelectOption<string>[] = models.map((model) => ({
    id: model.id,
    title: model.id,
    description: model.owned_by || "",
    category: "可用模型",
    value: model.id,
  }));
  options.push({
    id: MANUAL_MODEL_ID,
    title: "手动输入模型 ID",
    description: "目录里没有想要的模型时使用",
    category: "操作",
    value: MANUAL_MODEL_ID,
  });
  return options;
}

export function DialogAddModel({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [stage, setStage] = useState<Stage>("provider");
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [presetsLoaded, setPresetsLoaded] = useState(false);
  const [providerName, setProviderName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [urlIsCustom, setUrlIsCustom] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [discovered, setDiscovered] = useState<DiscoveredModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      const result = await fetchProviderPresets();
      setPresets(result.presets);
      setPresetsLoaded(true);
      if (!result.ok) setError(result.error || "无法加载服务商预设");
    })();
  }, []);

  const runDiscovery = async (key: string, url: string) => {
    setStage("discovering");
    setError("");
    const result = await discoverModels({ apiKey: key, baseUrl: url });
    if (result.ok && result.models.length > 0) {
      setDiscovered(result.models);
      setStage(urlIsCustom ? "model" : "model_multi");
      return;
    }
    const code = result.errorCode ?? (result.ok ? "unsupported_catalogue" : "transport");
    setError(result.error || "查询模型失败");
    if (code === "unsupported_catalogue") {
      setDiscovered([]);
      setStage("manual_model");
      return;
    }
    if (code === "https" && urlIsCustom) {
      setStage("custom_url");
      return;
    }
    setStage("api_key");
  };

  const saveBatch = async (selectedIds: string[], highlightedId: string) => {
    setStage("saving");
    setError("");
    const activeModelId = selectedIds.includes(highlightedId) ? highlightedId : selectedIds[0];
    const result = await onboardModelsBatch({
      apiKey,
      baseUrl,
      modelIds: selectedIds,
      providerId: providerId || undefined,
      providerName: providerName || undefined,
      activeModelId,
      skipProbe: true,
    });
    if (!result.ok || result.added.length === 0) {
      setError(result.error || "批量添加失败");
      setStage("model_multi");
      return;
    }
    onDone(
      result.message ||
        `已添加 ${result.added.length} 个模型，请到 /model 查看`,
    );
    onClose();
  };

  const save = async (nickname: string) => {
    setStage("saving");
    setError("");
    const result = await onboardModel({
      providerModelId: modelId,
      apiKey,
      baseUrl,
      nickname: nickname || undefined,
    });
    if (result.action === "error" || result.detail) {
      setError(String(result.message || result.detail || "添加失败"));
      setStage("nickname");
      return;
    }
    onDone(String(result.message || `模型已添加: ${nickname || modelId}`));
    onClose();
  };

  if (stage === "provider") {
    if (!presetsLoaded) {
      return <DialogLoading text="加载服务商预设…" />;
    }
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogSelect
          title="添加模型"
          options={buildProviderOptions(presets)}
          categoryOrder={["常用", "其他"]}
          placeholder="搜索服务商"
          onClose={onClose}
          onSelect={(opt) => {
            setError("");
            if (opt.value === CUSTOM_ID) {
              setProviderName("自定义");
              setUrlIsCustom(true);
              setStage("custom_url");
              return;
            }
            const preset = presets.find((p) => p.id === opt.value);
            if (!preset) return;
            setProviderName(preset.name);
            setProviderId(preset.id);
            setBaseUrl(preset.base_url);
            setUrlIsCustom(false);
            setStage("api_key");
          }}
        />
      </box>
    );
  }

  if (stage === "custom_url") {
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogPrompt
          title="添加模型 · API URL"
          placeholder="https://api.example.com/v1"
          initial={baseUrl}
          hint="携带密钥的连接必须使用 HTTPS"
          onCancel={() => setStage("provider")}
          onSubmit={(text) => {
            const trimmed = text.trim();
            if (!trimmed) {
              setError("API URL 不能为空");
              return;
            }
            if (!/^https:\/\//i.test(trimmed)) {
              setError("API URL 必须使用 HTTPS");
              return;
            }
            setError("");
            setBaseUrl(trimmed);
            setUrlIsCustom(true);
            setStage("api_key");
          }}
        />
      </box>
    );
  }

  if (stage === "api_key") {
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogPrompt
          title={`添加模型 · ${providerName} API Key`}
          placeholder="sk-…"
          mask
          hint={`回车后向 ${baseUrl} 查询可用模型；密钥仅掩码回显`}
          onCancel={() => setStage(urlIsCustom ? "custom_url" : "provider")}
          onSubmit={(text) => {
            if (!text) {
              setError("API Key 不能为空");
              return;
            }
            setApiKey(text);
            void runDiscovery(text, baseUrl);
          }}
        />
      </box>
    );
  }

  if (stage === "discovering") {
    return <DialogLoading text={`正在向 ${providerName} 查询可用模型…`} />;
  }

  if (stage === "model_multi") {
    const modelIds = discovered.map((m) => m.id);
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogSelect
          title={`${providerName} · 选择要添加的模型`}
          options={buildMultiModelOptions(discovered)}
          categoryOrder={["可用模型"]}
          placeholder="搜索模型"
          multi
          defaultSelectedIds={modelIds}
          onClose={() => setStage("api_key")}
          onConfirm={(selectedIds, { highlightedId }) => {
            setError("");
            if (selectedIds.length === 0) {
              setError("请至少选择一个模型");
              return;
            }
            void saveBatch(selectedIds, highlightedId);
          }}
        />
      </box>
    );
  }

  if (stage === "model") {
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogSelect
          title={`${providerName} · 选择模型`}
          options={buildModelOptions(discovered)}
          categoryOrder={["可用模型", "操作"]}
          placeholder="搜索模型"
          onClose={() => setStage("api_key")}
          onSelect={(opt) => {
            setError("");
            if (opt.value === MANUAL_MODEL_ID) {
              setStage("manual_model");
              return;
            }
            setModelId(opt.value);
            setStage("nickname");
          }}
        />
      </box>
    );
  }

  if (stage === "manual_model") {
    return (
      <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
        {error ? <DialogError text={error} /> : null}
        <DialogPrompt
          title="添加模型 · 模型 ID"
          placeholder="服务商 API 期望的精确模型 ID"
          hint="例如 provider 文档中的 model 字段取值"
          onCancel={() => setStage(discovered.length > 0 ? "model" : "api_key")}
          onSubmit={(text) => {
            if (!text) {
              setError("模型 ID 不能为空");
              return;
            }
            setError("");
            setModelId(text);
            setStage("nickname");
          }}
        />
      </box>
    );
  }

  if (stage === "saving") {
    return <DialogLoading text={urlIsCustom ? "正在探测连接并保存…" : "正在批量保存模型…"} />;
  }

  return (
    <box style={{ flexShrink: 0, flexDirection: "column", width: "100%" }}>
      {error ? <DialogError text={error} /> : null}
      <DialogPrompt
        title="添加模型 · 昵称（可选）"
        placeholder={modelId}
        hint="回车跳过则使用模型 ID；保存前会先探测连接"
        onCancel={() => setStage(discovered.length > 0 ? "model" : "manual_model")}
        onSubmit={(text) => void save(text)}
      />
    </box>
  );
}
