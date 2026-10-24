import { useMemo, useState, type ReactNode } from "react";
import { useKeyboard } from "@opentui/react";
import type { MouseEvent as OtuiMouseEvent } from "@opentui/core";
import { C } from "./theme.ts";

export interface ModalItem {
  id: string;
  label: string;
  desc?: string;
}

const MAX_VISIBLE_DEFAULT = 12;
const SELECT_BG = "#FF8C00";
const SELECT_FG = "#000000";

function Row({
  children,
  bg,
  onMouseDown,
  onMouseOver,
  onMouseUp,
  onMouseScroll,
}: {
  children: ReactNode;
  bg?: string;
  onMouseDown?: () => void;
  onMouseOver?: () => void;
  onMouseUp?: () => void;
  onMouseScroll?: (ev: OtuiMouseEvent) => void;
}) {
  return (
    <box
      style={{
        flexDirection: "row",
        width: "100%",
        height: 1,
        flexShrink: 0,
        backgroundColor: bg || C.bg,
      }}
      onMouseDown={onMouseDown}
      onMouseOver={onMouseOver}
      onMouseUp={onMouseUp}
      onMouseScroll={onMouseScroll}
    >
      {children}
    </box>
  );
}

export function Modal({
  title,
  items,
  onSelect,
  onClose,
  accentColor = C.primary,
  maxVisible = MAX_VISIBLE_DEFAULT,
}: {
  title: string;
  items: ModalItem[];
  onSelect: (index: number) => void;
  onClose: () => void;
  accentColor?: string;
  maxVisible?: number;
}) {
  const [idx, setIdx] = useState(0);
  const mv = Math.max(4, Math.min(maxVisible, items.length || 4));
  const half = Math.floor(mv / 2);
  let visStart = idx - half;
  if (visStart < 0) visStart = 0;
  if (visStart + mv > items.length) visStart = Math.max(0, items.length - mv);
  const visible = items.slice(visStart, visStart + mv);

  const move = (delta: number) => {
    setIdx((i) => {
      let n = i + delta;
      if (n < 0) n = 0;
      if (n >= items.length) n = Math.max(0, items.length - 1);
      return n;
    });
  };

  const onScroll = (ev: OtuiMouseEvent) => {
    const dir = ev.scroll?.direction;
    if (dir === "up") move(-(mv - 1 || 1));
    else if (dir === "down") move(mv - 1 || 1);
  };

  useKeyboard((key) => {
    if (key.name === "escape") {
      key.preventDefault?.();
      onClose();
      return;
    }
    if (key.name === "up") {
      move(-1);
      return;
    }
    if (key.name === "down") {
      move(1);
      return;
    }
    if (key.name === "pageup") {
      move(-(mv - 1 || 1));
      return;
    }
    if (key.name === "pagedown") {
      move(mv - 1 || 1);
      return;
    }
    if (key.name === "return") {
      if (items[idx]) onSelect(idx);
    }
  });

  return (
    <box
      style={{
        flexShrink: 0,
        border: true,
        borderColor: accentColor,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
      onMouseScroll={onScroll}
    >
      <Row>
        <text fg={C.text} attributes={1}>
          {"  "}
          {title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </Row>
      {visible.map((item, k) => {
        const gi = visStart + k;
        const sel = gi === idx;
        return (
          <Row
            key={item.id}
            bg={sel ? SELECT_BG : C.bg}
            onMouseOver={() => setIdx(gi)}
            onMouseDown={() => setIdx(gi)}
            onMouseUp={() => onSelect(gi)}
            onMouseScroll={onScroll}
          >
            <text fg={sel ? SELECT_FG : C.text}>
              {sel ? " ❯ " : "   "}
              {item.label}
            </text>
            {item.desc ? (
              <text fg={sel ? SELECT_FG : C.overlay2}>{`  ${item.desc}`}</text>
            ) : null}
          </Row>
        );
      })}
      <Row>
        <text fg={C.overlay2}>{" ↑↓选择  ↵确认  滚轮翻页  指针定位"}</text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>
          {items.length ? idx + 1 : 0}/{items.length}{" "}
        </text>
      </Row>
    </box>
  );
}

export function SettingsModal({
  onPermission,
  onClose,
}: {
  onPermission: () => void;
  onClose: () => void;
}) {
  const items: ModalItem[] = useMemo(
    () => [
      {
        id: "permission",
        label: "权限设置",
        desc: "三档安全审批：全确认 / 写代码免批 / 全自动",
      },
    ],
    [],
  );
  return (
    <Modal
      title="设置"
      items={items}
      accentColor={C.primary}
      onClose={onClose}
      onSelect={(i) => {
        if (items[i]?.id === "permission") onPermission();
      }}
    />
  );
}

export const PERMISSION_ITEMS: ModalItem[] = [
  {
    id: "confirm_all",
    label: "confirm_all",
    desc: "任何写/系统指令都要同意（默认）",
  },
  {
    id: "auto_edit",
    label: "auto_edit",
    desc: "写代码免批；bash/git 等系统指令仍要同意",
  },
  {
    id: "full_auto",
    label: "full_auto",
    desc: "所有指令自动同意",
  },
];
