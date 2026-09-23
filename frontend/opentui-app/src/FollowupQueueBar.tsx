import { C } from "./theme.ts";
import { MODE_COLORS, MODE_LABELS } from "./types.ts";
import { previewFollowup, type FollowupItem } from "./followupQueue.ts";

export function FollowupQueueBar(props: {
  items: readonly FollowupItem[];
  onSendNow: (id: string) => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (props.items.length === 0) return null;
  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.surface0,
        maxHeight: 8,
      }}
    >
      <text fg={C.yellow} attributes={1}>
        {`  队列 ${props.items.length}  · 立即发送=当前工具结束后插入本回合（不中断） · 编辑 · 删除`}
      </text>
      {props.items.map((item, i) => (
        <box key={item.id} style={{ flexDirection: "row", width: "100%" }}>
          <text fg={MODE_COLORS[item.mode] || C.text}>
            {`  ${i + 1}.[${MODE_LABELS[item.mode] || item.mode}] `}
          </text>
          <text fg={C.text}>{`${previewFollowup(item.text, 36)}  `}</text>
          <box onMouseDown={() => props.onSendNow(item.id)}>
            <text fg={C.green}>{"[立即发送]"}</text>
          </box>
          <box onMouseDown={() => props.onEdit(item.id)}>
            <text fg={C.teal}>{" [编辑]"}</text>
          </box>
          <box onMouseDown={() => props.onDelete(item.id)}>
            <text fg={C.red}>{" [删除]"}</text>
          </box>
        </box>
      ))}
    </box>
  );
}
