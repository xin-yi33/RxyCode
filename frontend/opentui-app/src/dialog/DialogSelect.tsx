/**
 * DialogSelect — OpenCode dialog-select.tsx port for OpenTUI React.
 *
 * - keyboard vs mouse inputMode: hover only moves selection in mouse mode
 * - wheel scrolls the scrollbox viewport (does NOT change selected)
 * - filter change forces keyboard mode (prevents synthetic hover snap-back)
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useKeyboard, usePaste, useTerminalDimensions } from "@opentui/react";
import type { InputRenderable, ScrollBoxRenderable } from "@opentui/core";
import { C } from "../theme.ts";
import { stringWidth } from "../layout.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "../scroll.ts";
import { CATEGORY_FG, SELECT_BG, SELECT_FG } from "./colors.ts";

export type DialogSelectOption<T = string> = {
  id: string;
  title: string;
  description?: string;
  footer?: string;
  category?: string;
  value: T;
  disabled?: boolean;
};

export type DisplayRow<T> =
  | { kind: "header"; category: string; key: string }
  | { kind: "item"; option: DialogSelectOption<T>; flatIndex: number; key: string };

/** Pure gate — exported for unit tests (clear→build snap-back fix). */
export function shouldApplyMouseHover(inputMode: "keyboard" | "mouse"): boolean {
  return inputMode === "mouse";
}

const NAV_KEY_NAMES = new Set([
  "up",
  "down",
  "left",
  "right",
  "return",
  "linefeed",
  "escape",
  "tab",
  "backspace",
  "delete",
  "home",
  "end",
  "pageup",
  "pagedown",
]);

/**
 * Extract printable search text (and optional Enter) from a key event.
 * ConPTY/PTY often delivers bursts like "model" or "model\\r" as one event.
 */
export function textFromKeyEvent(key: {
  name?: string;
  raw?: string;
  ctrl?: boolean;
  meta?: boolean;
}): { text: string; submit: boolean } | null {
  if (key.ctrl || key.meta) return null;
  const name = key.name || "";
  if (name === "return" || name === "linefeed") return { text: "", submit: true };
  if (NAV_KEY_NAMES.has(name) && name !== "space") return null;
  const raw = key.raw ?? "";
  if (!raw) {
    if (name.length === 1) return { text: name === "space" ? " " : name, submit: false };
    return null;
  }
  let text = "";
  let submit = false;
  for (const ch of raw) {
    if (ch === "\r" || ch === "\n") {
      submit = true;
      break;
    }
    if (ch >= " ") text += ch;
  }
  if (!text && !submit) return null;
  return { text, submit };
}

export function buildSelectRows<T>(
  options: DialogSelectOption<T>[],
  filter: string,
  categoryOrder?: string[],
): { flat: DialogSelectOption<T>[]; rows: DisplayRow<T>[] } {
  const q = filter.trim().toLowerCase();
  const scored = options
    .filter((o) => !o.disabled)
    .map((option) => {
      if (!q) return { option, score: 1 };
      const title = option.title.toLowerCase();
      const blob = `${option.title} ${option.description ?? ""} ${option.category ?? ""} ${option.footer ?? ""}`.toLowerCase();
      const qSlash = q.startsWith("/") ? q : `/${q}`;
      let score = 0;
      // Prefer exact / prefix matches so "model" ranks /model above /addmodel
      if (title === q || title === qSlash) score = 5;
      else if (title.startsWith(qSlash) || title.startsWith(q)) score = 4;
      else if (title.includes(qSlash) || new RegExp(`(^|[\\s/_-])${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(title))
        score = 3;
      else if (blob.includes(q)) score = 2;
      return { option, score };
    })
    .filter((x) => x.score > 0);

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (categoryOrder) {
      const ca = categoryOrder.indexOf(a.option.category || "");
      const cb = categoryOrder.indexOf(b.option.category || "");
      if (ca !== cb) return (ca < 0 ? 99 : ca) - (cb < 0 ? 99 : cb);
    }
    return a.option.title.localeCompare(b.option.title);
  });

  const flat = scored.map((x) => x.option);
  const rows: DisplayRow<T>[] = [];

  if (q) {
    flat.forEach((option, flatIndex) => {
      rows.push({ kind: "item", option, flatIndex, key: `i-${option.id}` });
    });
    return { flat, rows };
  }

  const groups = new Map<string, DialogSelectOption<T>[]>();
  for (const option of flat) {
    const cat = option.category || "";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat)!.push(option);
  }

  const order = categoryOrder?.length
    ? [...categoryOrder, ...[...groups.keys()].filter((c) => !categoryOrder.includes(c))]
    : [...groups.keys()];

  let flatIndex = 0;
  const seen = new Set<string>();
  for (const cat of order) {
    if (seen.has(cat)) continue;
    seen.add(cat);
    const items = groups.get(cat);
    if (!items?.length) continue;
    if (cat) rows.push({ kind: "header", category: cat, key: `h-${cat}` });
    for (const option of items) {
      rows.push({ kind: "item", option, flatIndex, key: `i-${option.id}` });
      flatIndex += 1;
    }
  }
  return { flat, rows };
}

function truncateToWidth(text: string, maxW: number): string {
  if (maxW <= 0) return "";
  if (stringWidth(text) <= maxW) return text;
  let out = "";
  let w = 0;
  for (const ch of text) {
    const cw = stringWidth(ch);
    if (w + cw + 1 > maxW) break;
    out += ch;
    w += cw;
  }
  return out + "…";
}

function padEndWidth(text: string, width: number): string {
  const w = stringWidth(text);
  if (w >= width) return truncateToWidth(text, width);
  return text + " ".repeat(width - w);
}

function RowShell({
  children,
  bg,
  onMouseDown,
  onMouseOver,
  onMouseUp,
  onMouseMove,
}: {
  children: ReactNode;
  bg?: string;
  onMouseDown?: () => void;
  onMouseOver?: () => void;
  onMouseUp?: () => void;
  onMouseMove?: () => void;
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
      onMouseMove={onMouseMove}
    >
      {children}
    </box>
  );
}

export function DialogSelect<T>({
  title,
  options,
  categoryOrder,
  placeholder = "搜索",
  currentId,
  onSelect,
  onClose,
  maxVisible,
  showSearch = true,
  footerHint = " ↑↓选择  ↵确认  滚轮滚动  指针定位",
}: {
  title: string;
  options: DialogSelectOption<T>[];
  categoryOrder?: string[];
  placeholder?: string;
  currentId?: string;
  onSelect: (option: DialogSelectOption<T>) => void;
  onClose: () => void;
  maxVisible?: number;
  showSearch?: boolean;
  footerHint?: string;
}) {
  const { height: termRows, width: termCols } = useTerminalDimensions();
  const cols = termCols || 80;
  const innerW = Math.max(28, cols - 6);
  const mv = Math.max(
    6,
    Math.min(maxVisible ?? 14, Math.max(6, Math.floor((termRows || 24) / 2) - 4)),
  );

  const [filter, setFilter] = useState("");
  const [idx, setIdx] = useState(0);
  const [inputMode, setInputMode] = useState<"keyboard" | "mouse">("keyboard");
  const inputModeRef = useRef<"keyboard" | "mouse">("keyboard");
  inputModeRef.current = inputMode;
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const focusRef = useRef<InputRenderable>(null);
  const scrollAccel = useMemo(() => createScrollAcceleration(), []);

  const { flat, rows } = useMemo(
    () => buildSelectRows(options, showSearch ? filter : "", categoryOrder),
    [options, filter, categoryOrder, showSearch],
  );

  // Keep a focused input so ConPTY/OpenTUI continues delivering key/paste events
  // after the main App textarea is unmounted while the dialog is open.
  useEffect(() => {
    try {
      focusRef.current?.focus();
    } catch {
      // ignore
    }
  }, []);

  // OpenCode: filter change forces keyboard mode (layout shift under cursor)
  useEffect(() => {
    setInputMode("keyboard");
    setIdx(0);
  }, [filter]);

  const safeIdx = flat.length === 0 ? 0 : Math.min(Math.max(0, idx), flat.length - 1);

  const selectedDisplayIdx = useMemo(() => {
    const i = rows.findIndex((r) => r.kind === "item" && r.flatIndex === safeIdx);
    return i < 0 ? 0 : i;
  }, [rows, safeIdx]);

  const scrollSelectedIntoView = (center: boolean) => {
    const box = scrollRef.current;
    if (!box) return;
    try {
      const vh = Math.max(1, Number(box.height) || mv);
      const y = selectedDisplayIdx;
      if (center) {
        box.scrollTop = Math.max(0, y - Math.floor(vh / 2));
      } else {
        const top = Number(box.scrollTop) || 0;
        if (y >= top + vh) box.scrollTop = y - vh + 1;
        if (y < top) box.scrollTop = y;
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    scrollSelectedIntoView(inputMode === "keyboard");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safeIdx, selectedDisplayIdx]);

  const move = (delta: number) => {
    if (flat.length === 0) return;
    setInputMode("keyboard");
    setIdx((i) => {
      let n = i + delta;
      if (n < 0) n = flat.length - 1;
      if (n >= flat.length) n = 0;
      return n;
    });
  };

  const moveTo = (flatIndex: number) => {
    if (flatIndex < 0 || flatIndex >= flat.length) return;
    setIdx(flatIndex);
  };

  const confirm = (flatIndex = safeIdx) => {
    const opt = flat[flatIndex];
    if (opt) onSelect(opt);
  };

  const applyFilterText = (text: string) => {
    if (!showSearch || !text) return;
    setFilter((f) => {
      const next = f + text;
      try {
        if (focusRef.current) focusRef.current.value = next;
      } catch {
        // ignore
      }
      return next;
    });
  };

  const confirmWithFilter = (nextFilter: string) => {
    const { flat: nextFlat } = buildSelectRows(options, showSearch ? nextFilter : "", categoryOrder);
    const opt = nextFlat[0];
    if (opt) onSelect(opt);
  };

  usePaste((event) => {
    if (!showSearch) return;
    let text = "";
    try {
      text = new TextDecoder().decode(event.bytes).replace(/[\r\n]/g, "");
    } catch {
      return;
    }
    if (!text) return;
    try {
      event.preventDefault?.();
    } catch {
      // ignore
    }
    setInputMode("keyboard");
    applyFilterText(text);
  });

  useKeyboard((key) => {
    setInputMode("keyboard");
    if (key.name === "escape") {
      key.preventDefault?.();
      onClose();
      return;
    }
    if (key.name === "up" || (key.ctrl && key.name === "p")) {
      key.preventDefault?.();
      move(-1);
      return;
    }
    if (key.name === "down" || (key.ctrl && key.name === "n")) {
      key.preventDefault?.();
      move(1);
      return;
    }
    if (key.name === "pageup") {
      key.preventDefault?.();
      move(-(mv - 1 || 1));
      return;
    }
    if (key.name === "pagedown") {
      key.preventDefault?.();
      move(mv - 1 || 1);
      return;
    }
    if (key.name === "return" || key.name === "linefeed") {
      key.preventDefault?.();
      confirm();
      return;
    }
    if (!showSearch) return;
    if (key.name === "backspace" || key.name === "delete") {
      key.preventDefault?.();
      setFilter((f) => {
        const next = f.slice(0, -1);
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
    if (parsed.text || parsed.submit) {
      key.preventDefault?.();
    }
    if (parsed.text && parsed.submit) {
      const next = filter + parsed.text;
      setFilter(next);
      try {
        if (focusRef.current) focusRef.current.value = next;
      } catch {
        // ignore
      }
      confirmWithFilter(next);
      return;
    }
    if (parsed.text) {
      applyFilterText(parsed.text);
    }
    if (parsed.submit) {
      confirm();
    }
  });

  const nameCol = Math.min(
    28,
    Math.max(14, ...flat.map((o) => stringWidth(o.title) + 4), 14),
  );

  const searchShown = filter.length > 0 ? filter : placeholder;
  const listHeight = Math.min(mv, Math.max(rows.length, 1));

  return (
    <box
      style={{
        flexShrink: 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: C.borderDim,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.bg,
      }}
      onMouseMove={() => setInputMode("mouse")}
    >
      <RowShell>
        <text fg={C.text} attributes={1}>
          {" "}
          {title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>esc </text>
      </RowShell>

      {showSearch ? (
        <RowShell>
          <text fg={SELECT_FG} bg={SELECT_BG}>
            {searchShown.slice(0, 1) || " "}
          </text>
          <text fg={filter.length > 0 ? C.text : C.overlay2}>{searchShown.slice(1)}</text>
          <box style={{ flexGrow: 1, height: 1 }} />
          <text fg={C.overlay2}>
            {flat.length}/{options.length}{" "}
          </text>
        </RowShell>
      ) : null}
      {/* Off-layout focus sink: keeps ConPTY/key delivery alive; must not paint glyphs */}
      <input
        ref={focusRef}
        focused
        onInput={(v) => {
          if (!showSearch) return;
          setInputMode("keyboard");
          setFilter(String(v ?? ""));
        }}
        onSubmit={() => confirm()}
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

      <scrollbox
        ref={scrollRef}
        stickyScroll={false}
        stickyStart="top"
        scrollAcceleration={scrollAccel}
        style={{
          rootOptions: {
            flexShrink: 0,
            height: listHeight,
            maxHeight: mv,
            border: false,
            backgroundColor: C.bg,
          },
          viewportOptions: { flexGrow: 1, backgroundColor: C.bg },
          contentOptions: { backgroundColor: C.bg },
          verticalScrollbarOptions: {
            showArrows: false,
            trackOptions: {
              foregroundColor: SCROLLBAR_TRACK.foregroundColor,
              backgroundColor: SCROLLBAR_TRACK.backgroundColor,
            },
          },
        }}
      >
        {rows.map((row) => {
          if (row.kind === "header") {
            return (
              <RowShell key={row.key}>
                <text fg={CATEGORY_FG}>
                  {"  "}
                  {row.category}
                </text>
              </RowShell>
            );
          }

          const sel = row.flatIndex === safeIdx;
          const isCurrent = currentId != null && row.option.id === currentId;
          const prefix = sel ? " ❯ " : isCurrent ? " ● " : "   ";
          const namePart = padEndWidth(prefix + row.option.title, nameCol);
          const right = row.option.footer || row.option.description || "";
          const descPart = padEndWidth(right, Math.max(0, innerW - nameCol));

          return (
            <RowShell
              key={row.key}
              bg={sel ? SELECT_BG : C.bg}
              onMouseMove={() => setInputMode("mouse")}
              onMouseOver={() => {
                if (!shouldApplyMouseHover(inputModeRef.current)) return;
                moveTo(row.flatIndex);
              }}
              onMouseDown={() => {
                setInputMode("mouse");
                moveTo(row.flatIndex);
              }}
              onMouseUp={() => {
                setInputMode("mouse");
                moveTo(row.flatIndex);
                confirm(row.flatIndex);
              }}
            >
              <text fg={sel ? SELECT_FG : C.text}>{namePart}</text>
              <text fg={sel ? SELECT_FG : C.overlay2}>{descPart}</text>
            </RowShell>
          );
        })}
      </scrollbox>

      <RowShell>
        <text fg={C.overlay2}>{footerHint}</text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>
          {flat.length ? safeIdx + 1 : 0}/{flat.length}{" "}
        </text>
      </RowShell>
    </box>
  );
}
