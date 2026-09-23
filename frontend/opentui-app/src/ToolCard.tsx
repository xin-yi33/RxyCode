import { useEffect, useState } from "react";
import { ElapsedTimer } from "./lib/elapsedTimer.ts";
import {
  applyToolExpandedOverride,
  EDIT_PREVIEW_LINES,
  getToolFullResult,
  previewLimitForFamily,
  toggleToolExpanded,
  toggleToolFullResult,
} from "./lib/toolCardDisplay.ts";
import {
  buildEditDiff,
  classifyTool,
  diffCounts,
  fileLabel,
  genericSummary,
  groupDiffHunks,
  isPlanMdPath,
  parseToolArgs,
  readTargets,
  selectDiffPreview,
  selectLinePreview,
  toolCommand,
  type DiffLine,
} from "./lib/toolDisplay.ts";
import { padToWidth, wrapContentLines } from "./layout.ts";
import { C } from "./theme.ts";
import type { ChatMessage } from "./types.ts";

function useToolElapsed(startedAt: number, endedAt: number | undefined, running: boolean): string {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [running]);
  return new ElapsedTimer(startedAt).format(running ? now : endedAt ?? now);
}

function DiffHunk({
  kind,
  lines,
  width,
  startNo = 1,
}: {
  kind: DiffLine["kind"];
  lines: DiffLine[];
  width: number;
  startNo?: number;
}) {
  if (kind === "ctx") {
    return (
      <box style={{ flexDirection: "column", width: "100%" }}>
        {lines.map((line, i) => (
          <text key={i} fg={C.subtext} selectable>
            {padToWidth(`  ${line.text}`, width)}
          </text>
        ))}
      </box>
    );
  }
  const bg = kind === "add" ? C.diffAddBg : C.diffDelBg;
  const fg = kind === "add" ? C.green : C.red;
  const mark = kind === "add" ? "+" : "-";
  const numW = Math.max(2, String(startNo + lines.length - 1).length);
  return (
    <box style={{ flexDirection: "column", width: "100%", backgroundColor: bg }}>
      {lines.map((line, i) => {
        const no = String(startNo + i).padStart(numW, " ");
        return (
          <text key={i} fg={fg} bg={bg} selectable>
            {padToWidth(`${no} ${mark} ${line.text}`, width)}
          </text>
        );
      })}
    </box>
  );
}

function ClipHint({
  expanded,
  clipped,
  onToggle,
}: {
  expanded: boolean;
  clipped: number;
  onToggle: () => void;
}) {
  const label = expanded
    ? clipped > 0
      ? `  ...v  (+${clipped} 行)`
      : "  ...v"
    : clipped > 0
      ? `  ...>  (+${clipped} 行)`
      : "  ...>";
  return (
    <box onMouseDown={onToggle}>
      <text fg={C.subtext} selectable={false}>
        {label}
      </text>
    </box>
  );
}

export function ToolCard({
  msg,
  wrapW,
  ctrlHeldRef,
  onChanged,
}: {
  msg: ChatMessage;
  wrapW: number;
  ctrlHeldRef: { current: boolean };
  onChanged: () => void;
}) {
  const resolved = applyToolExpandedOverride(msg);
  const st = resolved.toolStatus || "running";
  const running = st === "running";
  const ok = st === "success";
  const icon = running ? "…" : ok ? "✓" : "✗";
  const name = resolved.toolName || "tool";
  const family = classifyTool(name);
  const args = parseToolArgs(resolved.toolArgs);
  const command = toolCommand(args);
  const elapsed = useToolElapsed(resolved.timestamp, resolved.endedAt, running);
  const headerColor = running ? C.subtext : ok ? C.green : C.yellow;
  const expanded = running ? true : resolved.toolExpanded !== false;
  const fullResult = getToolFullResult(resolved.id);

  useEffect(() => {
  }, [resolved.id, name, family, st, running, expanded, fullResult, resolved.toolArgs, resolved.content]);

  const onHeaderDown = () => {
    if (running) return;
    if (ctrlHeldRef.current) {
      toggleToolFullResult(resolved.id, fullResult);
    } else {
      toggleToolExpanded(resolved.id, expanded);
    }
    onChanged();
  };

  const onTailDown = () => {
    if (running) return;
    toggleToolFullResult(resolved.id, fullResult);
    onChanged();
  };

  const body =
    running || !expanded ? null : (
      <ToolBody
        msg={resolved}
        family={family}
        args={args}
        command={command}
        wrapW={wrapW}
        fullResult={fullResult}
        onToggleTail={onTailDown}
      />
    );

  return (
    <box style={{ width: "100%", paddingLeft: 1, paddingRight: 1, flexDirection: "column" }}>
      <box onMouseDown={onHeaderDown}>
        <text selectable={false}>
          <span fg={headerColor}>
            {`  ${icon} >_ ${name} [${st}] ：`}
          </span>
          <span fg={C.subtext}>{elapsed}</span>
          <span fg={C.subtext}>{expanded ? "  ...v" : "  ...>"}</span>
        </text>
      </box>
      {running && family === "bash" && command ? (
        <text fg={C.text} selectable>
          {`$ ${command}`}
        </text>
      ) : null}
      {body}
    </box>
  );
}

function ToolBody({
  msg,
  family,
  args,
  command,
  wrapW,
  fullResult,
  onToggleTail,
}: {
  msg: ChatMessage;
  family: ReturnType<typeof classifyTool>;
  args: Record<string, unknown>;
  command: string;
  wrapW: number;
  fullResult: boolean;
  onToggleTail: () => void;
}) {
  const name = msg.toolName || "tool";
  const result = msg.content || "";
  const width = Math.max(8, wrapW - 4);

  if (family === "edit") {
    const diff = buildEditDiff(name, args);
    const counts = diffCounts(diff);
    const preview = fullResult
      ? { lines: diff.filter((l) => l.kind !== "ctx"), clipped: 0 }
      : selectDiffPreview(diff, EDIT_PREVIEW_LINES);
    const hunks = groupDiffHunks(preview.lines);
    const filePath = String(args.filePath || args.file_path || args.path || name);
    const label = fileLabel(filePath);
    const planFile = isPlanMdPath(filePath);
    const verb = (name.toLowerCase().includes("write") || name.toLowerCase().includes("create"))
      ? "Wrote"
      : "Edited";
    const canClip = !planFile && diff.filter((l) => l.kind !== "ctx").length > EDIT_PREVIEW_LINES;
    const shownHunks = planFile
      ? groupDiffHunks(diff.filter((l) => l.kind !== "ctx"))
      : hunks;
    let lineNo = 1;
    return (
      <box style={{ flexDirection: "column", width: "100%" }}>
        <text selectable>
          <span fg={C.subtext}>{`  ${verb} ${label} `}</span>
          <span fg={C.green}>{`+${counts.added}`}</span>
          <span fg={C.subtext}>{" "}</span>
          <span fg={C.red}>{`-${counts.removed}`}</span>
        </text>
        {shownHunks.map((hunk, i) => {
          const node = (
            <DiffHunk key={i} kind={hunk.kind} lines={hunk.lines} width={width} startNo={lineNo} />
          );
          lineNo += hunk.lines.length;
          return node;
        })}
        {canClip ? (
          <ClipHint expanded={fullResult} clipped={preview.clipped} onToggle={onToggleTail} />
        ) : null}
        {result && /\[error/i.test(result) ? (
          <text fg={C.yellow} selectable>
            {result}
          </text>
        ) : null}
      </box>
    );
  }

  if (family === "read") {
    const targets = readTargets(name, args, result);
    return (
      <box style={{ flexDirection: "column", width: "100%" }}>
        {targets.map((target, i) => (
          <text key={i} fg={C.subtext} selectable>
            {`  read: ${target}`}
          </text>
        ))}
        {targets.length === 0 ? (
          <text fg={C.subtext} selectable>
            {"  read:"}
          </text>
        ) : null}
        {/\[error/i.test(result) ? (
          <text fg={C.yellow} selectable>
            {result}
          </text>
        ) : null}
      </box>
    );
  }

  const summary = family === "bash" ? "" : genericSummary(name, args);
  const rawLines = wrapContentLines(result, width);
  const limit = previewLimitForFamily(family);
  const preview = fullResult ? { lines: rawLines, clipped: 0 } : selectLinePreview(rawLines, limit);
  const canClip = rawLines.length > limit;

  return (
    <box style={{ flexDirection: "column", width: "100%" }}>
      {family === "bash" && command ? (
        <text fg={C.text} selectable>
          {`$ ${command}`}
        </text>
      ) : null}
      {summary ? (
        <text fg={C.subtext} selectable>
          {`  ${summary}`}
        </text>
      ) : null}
      {preview.lines.map((line, i) => (
        <text key={i} fg={C.subtext} selectable>
          {line}
        </text>
      ))}
      {canClip ? (
        <ClipHint expanded={fullResult} clipped={preview.clipped} onToggle={onToggleTail} />
      ) : null}
    </box>
  );
}
