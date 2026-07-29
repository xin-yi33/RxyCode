/**
 * OpenTUI Add-model wizard — port of Ink AddModelWizard (4 steps → POST /models/onboard).
 */

import { useEffect, useRef, useState } from "react";
import { useKeyboard } from "@opentui/react";
import type { InputRenderable } from "@opentui/core";
import { C } from "../theme.ts";
import { SELECT_BG, SELECT_FG } from "./colors.ts";
import { onboardModel } from "./api.ts";
import { textFromKeyEvent } from "./DialogSelect.tsx";

type Step = "provider_model_id" | "api_key" | "api_url" | "nickname";

const STEPS: Step[] = ["provider_model_id", "api_key", "api_url", "nickname"];

const META: Record<
  Step,
  { title: string; placeholder: string; hint: string; field: keyof Data; label: string }
> = {
  provider_model_id: {
    title: "[1/4] Provider model ID",
    placeholder: "e.g. deepseek-chat",
    hint: "Provider API 期望的精确模型 ID",
    field: "providerModelId",
    label: "Provider ID",
  },
  api_key: {
    title: "[2/4] API Key",
    placeholder: "sk-...",
    hint: "密钥本地仅回显掩码",
    field: "apiKey",
    label: "Key",
  },
  api_url: {
    title: "[3/4] API URL",
    placeholder: "https://api.deepseek.com",
    hint: "携带密钥的连接必须使用 HTTPS",
    field: "apiUrl",
    label: "URL",
  },
  nickname: {
    title: "[4/4] 昵称（可选）",
    placeholder: "留空则等于模型名",
    hint: "回车跳过",
    field: "nickname",
    label: "昵称",
  },
};

type Data = {
  providerModelId: string;
  apiKey: string;
  apiUrl: string;
  nickname: string;
};

function mask(step: Step, v: string): string {
  if (step === "api_key") return v.length > 8 ? `${v.slice(0, 4)}...${v.slice(-4)}` : "****";
  return v;
}

export function DialogAddModel({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [stepIdx, setStepIdx] = useState(0);
  const [data, setData] = useState<Data>({
    providerModelId: "",
    apiKey: "",
    apiUrl: "",
    nickname: "",
  });
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const focusRef = useRef<InputRenderable>(null);

  const step = STEPS[stepIdx]!;
  const meta = META[step];

  useEffect(() => {
    try {
      focusRef.current?.focus();
      if (focusRef.current) focusRef.current.value = "";
    } catch {
      // ignore
    }
  }, [stepIdx]);

  const commitStep = async (text: string) => {
    const nextData = { ...data, [meta.field]: text.trim() };
    setData(nextData);
    setDraft("");
    setError("");

    if (stepIdx < STEPS.length - 1) {
      setStepIdx((i) => i + 1);
      return;
    }

    setBusy(true);
    const result = await onboardModel({
      providerModelId: nextData.providerModelId,
      apiKey: nextData.apiKey,
      baseUrl: nextData.apiUrl,
      nickname: nextData.nickname || undefined,
    });
    setBusy(false);
    if (result.action === "error" || result.detail) {
      setError(String(result.message || result.detail || "添加失败"));
      return;
    }
    onDone(String(result.message || `模型已添加: ${nextData.nickname || nextData.providerModelId}`));
    onClose();
  };

  useKeyboard((key) => {
    if (busy) return;
    if (key.name === "escape") {
      key.preventDefault?.();
      onClose();
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      void commitStep(draft);
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
      void commitStep(draft + (parsed.text || ""));
    }
  });

  const collected = STEPS.slice(0, stepIdx).map((s) => ({
    step: s,
    value: data[META[s].field],
  }));

  const shown = step === "api_key" ? "*".repeat(draft.length) : draft;

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: C.primary,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "row", width: "100%", height: 1 }}>
        <text fg={C.primary} attributes={1}>
          {" 添加模型"}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </box>
      {collected.map((c) => (
        <box key={c.step} style={{ height: 1, width: "100%" }}>
          <text fg={C.green}>
            {"  ✓ "}
            {META[c.step].label}: {mask(c.step, c.value)}
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
          {meta.title}
        </text>
      </box>
      <box style={{ flexDirection: "row", height: 1, width: "100%" }}>
        <text fg={C.primary}>{"> "}</text>
        <text fg={SELECT_FG} bg={draft ? undefined : SELECT_BG}>
          {(shown || meta.placeholder).slice(0, 1) || " "}
        </text>
        <text fg={draft ? C.text : C.overlay2}>
          {shown ? shown.slice(1) : meta.placeholder.slice(1)}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <input
          ref={focusRef}
          focused
          onInput={(v) => setDraft(String(v ?? ""))}
          onSubmit={() => {
            if (!busy) void commitStep(draft);
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
          {busy ? "探测连接中…" : meta.hint}
        </text>
      </box>
    </box>
  );
}
