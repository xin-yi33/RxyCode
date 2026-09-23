import { useEffect, useMemo, useRef, useState } from "react";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import type { ScrollBoxRenderable } from "@opentui/core";
import { C } from "./theme.ts";
import { createScrollAcceleration, SCROLLBAR_TRACK } from "./scroll.ts";
import { clampPlanScroll, planViewportLines, type PlanDoc } from "./planDoc.ts";
import { PLAN_ACTIONS, type PlanAction } from "./planActions.ts";
import { looksLikeMarkdown, MarkdownView } from "./Markdown.tsx";

export type { PlanDoc };
export { parsePlanDoc, planViewportLines, clampPlanScroll } from "./planDoc.ts";

function isUpKey(key: { name?: string; ctrl?: boolean }): boolean {
  return key.name === "up" || key.name === "arrowup" || Boolean(key.ctrl && key.name === "p");
}

function isDownKey(key: { name?: string; ctrl?: boolean }): boolean {
  return key.name === "down" || key.name === "arrowdown" || Boolean(key.ctrl && key.name === "n");
}

export function PlanPane(props: {
  doc: PlanDoc;
  focused: boolean;
  captureEsc: boolean;
  borderColor: string;
  fill?: boolean;
  selectedLine: number;
  onSelectLine: (index: number) => void;
  onFocus: () => void;
  onBlur: () => void;
  onClose: () => void;
  onAction: (action: PlanAction) => void;
}) {
  const { height: termRows } = useTerminalDimensions();
  const viewport = planViewportLines(termRows || 24, Boolean(props.fill));
  const scrollAccel = useMemo(() => createScrollAcceleration(), []);
  const lines = useMemo(() => props.doc.body.split(/\r?\n/), [props.doc.body]);
  const [scroll, setScroll] = useState(0);
  const [hoveredAction, setHoveredAction] = useState<PlanAction | null>(null);
  const scrollRef = useRef<ScrollBoxRenderable>(null);
  const offsetRef = useRef(0);
  const linesRef = useRef(lines);
  const viewportRef = useRef(viewport);
  linesRef.current = lines;
  viewportRef.current = viewport;

  useEffect(() => {
    offsetRef.current = 0;
    setScroll(0);
    try {
      if (scrollRef.current) scrollRef.current.scrollTop = 0;
    } catch {
      // ignore
    }
  }, [props.doc.body]);

  const applyScroll = (next: number) => {
    const clamped = clampPlanScroll(next, linesRef.current.length, viewportRef.current);
    offsetRef.current = clamped;
    setScroll(clamped);
    try {
      const box = scrollRef.current;
      if (box) box.scrollTop = clamped;
    } catch {
      // ignore
    }
  };

  useKeyboard((key) => {
    if (!props.focused) return;
    if ((key.name === "escape" || key.name === "esc") && props.captureEsc) {
      key.preventDefault?.();
      props.onClose();
      return;
    }
    const page = Math.max(1, viewportRef.current - 1);
    if (key.name === "pageup" || key.name === "home") {
      key.preventDefault?.();
      applyScroll(key.name === "home" ? 0 : offsetRef.current - page);
      return;
    }
    if (key.name === "pagedown" || key.name === "end") {
      key.preventDefault?.();
      applyScroll(
        key.name === "end" ? linesRef.current.length : offsetRef.current + page,
      );
      return;
    }
    if (isUpKey(key)) {
      key.preventDefault?.();
      applyScroll(offsetRef.current - 1);
      return;
    }
    if (isDownKey(key)) {
      key.preventDefault?.();
      applyScroll(offsetRef.current + 1);
    }
  });

  const safeScroll = clampPlanScroll(scroll, lines.length, viewport);
  const shown = `${safeScroll + 1}-${Math.min(safeScroll + viewport, lines.length)}/${lines.length}`;

  return (
    <box
      style={{
        flexGrow: props.fill ? 1 : 0,
        flexShrink: props.fill ? 1 : 0,
        flexDirection: "column",
        width: "100%",
        border: true,
        borderColor: props.borderColor,
        borderStyle: "rounded",
        paddingLeft: 1,
        paddingRight: 1,
        backgroundColor: C.surface0,
      }}
      onMouseDown={() => props.onFocus()}
    >
      <box style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}>
        <text fg={props.borderColor} attributes={1}>
          {" plan.md "}
        </text>
        <text fg={C.text} attributes={1}>
          {props.doc.title}
        </text>
        <box style={{ flexGrow: 1, height: 1 }} />
        <text fg={C.overlay2}>
          {props.focused ? `↑↓/j k ${shown} ` : `点击查阅 · 滚轮/↑↓ ${shown} `}
        </text>
      </box>
      <scrollbox
        ref={scrollRef}
        stickyScroll={false}
        stickyStart="top"
        scrollAcceleration={scrollAccel}
        style={{
          rootOptions: {
            flexGrow: props.fill ? 1 : 0,
            flexShrink: props.fill ? 1 : 0,
            height: viewport,
            border: false,
            backgroundColor: C.surface0,
          },
          viewportOptions: { flexGrow: 1, backgroundColor: C.surface0 },
          contentOptions: { backgroundColor: C.surface0 },
          verticalScrollbarOptions: {
            showArrows: false,
            paddingLeft: 1,
            trackOptions: {
              foregroundColor: SCROLLBAR_TRACK.foregroundColor,
              backgroundColor: SCROLLBAR_TRACK.backgroundColor,
            },
          },
        }}
      >
        <MarkdownView content={props.doc.body} backgroundColor={C.surface0} />
      </scrollbox>
      <box
        style={{ flexDirection: "row", width: "100%", height: 1, flexShrink: 0 }}
        onMouseOut={() => setHoveredAction(null)}
      >
        {PLAN_ACTIONS.map((row, i) => {
          const hot = hoveredAction === row.id;
          return (
            <box
              key={row.id}
              onMouseDown={() => props.onAction(row.id)}
              onMouseOver={() => {
                setHoveredAction(row.id);
              }}
              onMouseMove={() => setHoveredAction(row.id)}
            >
              <text bg={hot ? C.surface1 : C.surface0}>
                {i > 0 ? <span fg={C.overlay2}>{" | "}</span> : <span>{" "}</span>}
                <span fg={hot ? C.yellow : C.yellow} attributes={1}>
                  {row.key}
                </span>
                <span fg={hot ? C.text : C.subtext}>{` ${row.label} `}</span>
              </text>
            </box>
          );
        })}
      </box>
    </box>
  );
}
