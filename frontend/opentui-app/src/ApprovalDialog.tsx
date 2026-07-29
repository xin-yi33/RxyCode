import { useState } from "react";
import { useKeyboard } from "@opentui/react";
import { C } from "./theme.ts";

export type ApprovalDecision = "approved" | "rejected" | "always_allow_level";

export interface ApprovalInfo {
  approvalId: string;
  tool: string;
  risk: string;
  args: string;
}

const OPTIONS: Array<{ key: string; label: string; decision: ApprovalDecision }> = [
  { key: "a", label: "Approve (允许本次)", decision: "approved" },
  { key: "r", label: "Reject (拒绝)", decision: "rejected" },
  { key: "l", label: "Always allow this level (本会话同级别放行)", decision: "always_allow_level" },
];

const RISK_COLOR: Record<string, string> = {
  READ: C.green,
  WRITE: C.yellow,
  DANGER: C.accent,
};

export function ApprovalDialog({
  approval,
  onDecision,
}: {
  approval: ApprovalInfo;
  onDecision: (decision: ApprovalDecision) => void;
}) {
  const [idx, setIdx] = useState(0);
  const riskColor = RISK_COLOR[approval.risk] || C.yellow;
  const argsPreview =
    approval.args.length > 200 ? `${approval.args.slice(0, 200)}...` : approval.args;

  useKeyboard((key) => {
    if (key.name === "up") {
      setIdx((i) => Math.max(0, i - 1));
      return;
    }
    if (key.name === "down") {
      setIdx((i) => Math.min(OPTIONS.length - 1, i + 1));
      return;
    }
    if (key.name === "return") {
      onDecision(OPTIONS[idx].decision);
      return;
    }
    const lower = (key.name || "").toLowerCase();
    const hit = OPTIONS.find((o) => o.key === lower);
    if (hit) onDecision(hit.decision);
  });

  return (
    <box
      style={{
        flexShrink: 0,
        border: true,
        borderColor: riskColor,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
    >
      <box style={{ flexDirection: "column", width: "100%", backgroundColor: C.bg }}>
        <box style={{ flexDirection: "row", width: "100%" }}>
          <text fg={riskColor} attributes={1}>
            {"  Safety Approval"}
          </text>
          <box style={{ flexGrow: 1 }} />
          <text fg={riskColor} attributes={1}>
            {approval.risk}
            {" "}
          </text>
        </box>
        <text fg={C.overlay2}>{"─".repeat(40)}</text>
        <text fg={C.subtext}>
          {"  Tool: "}
          <span fg={C.text} attributes={1}>
            {approval.tool}
          </span>
        </text>
        <text fg={C.overlay2}>{`  Args: ${argsPreview}`}</text>
        <text fg={C.overlay2}>{"─".repeat(40)}</text>
        {OPTIONS.map((o, i) => {
          const sel = i === idx;
          return (
            <box
              key={o.key}
              style={{ width: "100%", backgroundColor: sel ? C.surface1 : C.bg }}
              onMouseDown={() => onDecision(o.decision)}
            >
              <text fg={sel ? riskColor : C.subtext}>
                {sel ? " ❯ " : "   "}
                {`[${o.key}] ${o.label}`}
              </text>
            </box>
          );
        })}
        <text fg={C.overlay2}>{"  ↑↓ 选择   ↵ 确认   a/r/l 快捷   鼠标点击"}</text>
      </box>
    </box>
  );
}
