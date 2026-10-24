import { useState } from "react";
import { useKeyboard } from "@opentui/react";
import { C } from "./theme.ts";
import { textFromKeyEvent } from "./dialog/DialogSelect.tsx";
import type { QuestionInfo, QuestionReply } from "./questionInfo.ts";

export type { QuestionInfo, QuestionReply } from "./questionInfo.ts";

const ACCENT = C.teal;

export function QuestionDialog({
  question,
  onResponse,
}: {
  question: QuestionInfo;
  onResponse: (reply: QuestionReply) => void;
}) {
  const [idx, setIdx] = useState(0);
  const [draft, setDraft] = useState("");
  const hasOptions = question.options.length > 0;
  const last = Math.max(0, question.options.length - 1);

  useKeyboard((key) => {
    if (key.name === "escape") {
      key.preventDefault?.();
      onResponse({ cancelled: true });
      return;
    }
    if (hasOptions) {
      if (key.name === "up") {
        setIdx((i) => Math.max(0, i - 1));
        return;
      }
      if (key.name === "down") {
        setIdx((i) => Math.min(last, i + 1));
        return;
      }
      if (key.name === "return" || key.name === "linefeed") {
        const selected = question.options[idx];
        if (selected) onResponse({ answer: selected.value });
        return;
      }
      const raw = (key.name || key.raw || "").trim();
      const number = Number.parseInt(raw, 10);
      if (Number.isInteger(number) && number >= 1 && number <= question.options.length) {
        onResponse({ answer: question.options[number - 1].value });
      }
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      onResponse({ answer: draft.trim() });
      return;
    }
    if (key.name === "backspace" || key.name === "delete") {
      key.preventDefault?.();
      setDraft((d) => d.slice(0, -1));
      return;
    }
    const parsed = textFromKeyEvent(key);
    if (!parsed?.text) return;
    key.preventDefault?.();
    setDraft((d) => d + parsed.text);
  });

  return (
    <box
      style={{
        flexShrink: 0,
        border: true,
        borderColor: ACCENT,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
        <box style={{ flexDirection: "row", width: "100%" }}>
          <text fg={ACCENT} attributes={1}>
            {"  "}
            {question.header || "Question"}
          </text>
          <box style={{ flexGrow: 1 }} />
          <text fg={C.overlay2}>esc 取消</text>
        </box>
        <text fg={C.overlay2}>{"─".repeat(40)}</text>
        <text fg={C.text}>{`  ${question.question}`}</text>
        {hasOptions ? (
          question.options.map((option, i) => {
            const sel = i === idx;
            return (
              <box
                key={`${option.value}-${i}`}
                style={{ width: "100%", backgroundColor: sel ? C.surface1 : C.bg }}
                onMouseDown={() => onResponse({ answer: option.value })}
              >
                <text fg={sel ? ACCENT : C.subtext} attributes={sel ? 1 : 0}>
                  {sel ? " ❯ " : "   "}
                  {`${i + 1}. ${option.label}`}
                </text>
              </box>
            );
          })
        ) : (
          <text fg={C.text}>
            {"  > "}
            <span fg={draft ? C.text : C.overlay2}>{draft || "输入回答"}</span>
          </text>
        )}
        <text fg={C.overlay2}>
          {hasOptions ? "  ↑↓ 选择   ↵ 确认   数字键快捷   Esc 取消" : "  ↵ 确认   Esc 取消"}
        </text>
      </box>
    </box>
  );
}
