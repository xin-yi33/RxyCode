import React, { useEffect, useRef, useState } from 'react';
import Banner from './Banner.js';
import { Box, Static, Text } from 'ink';
import type { Message, Mode, ToolStatus } from '../types.js';
import { MODE_COLORS } from '../types.js';
import { C } from '../theme.js';
import Markdown from './Markdown.js';

const SPINNER_FRAMES = ['\u280B', '\u2819', '\u2839', '\u2838', '\u283C', '\u2834', '\u2826', '\u2827', '\u2807', '\u280F'];

interface Props {
  messages: Message[];
  height: number;
  mode: Mode;
  expandThinking: boolean;
}

export const isFinalized = (m: Message): boolean => {
  if (m.role === 'user' || m.role === 'system') return true;
  if (m.role === 'assistant' || m.role === 'thinking') return m.done === true;
  if (m.role === 'tool') return m.toolStatus !== 'running';
  return true;
};

const MAX_STREAMING_PREVIEW_CHARS = 3000;

function tailLines(content: string, maxLines: number): string {
  const charBounded = content.length > MAX_STREAMING_PREVIEW_CHARS
    ? `... (streaming preview)\n${content.slice(-MAX_STREAMING_PREVIEW_CHARS)}`
    : content;
  const lines = charBounded.split('\n');
  if (lines.length <= maxLines) return charBounded;
  return ['... (streaming preview)', ...lines.slice(-(maxLines - 1))].join('\n');
}

const WelcomeMessage = React.memo(() => {
  return (
    <Box flexDirection="column" paddingTop={0} paddingBottom={0}>
      <Banner />
      <Box flexDirection="column" paddingLeft={2}>
        <Text color="#FFB6C1">  你好！我是 RxyCode，可以帮你分析、规划并执行各类任务</Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>代码开发</Text><Text color="#aaa"> - 编写、调试、重构代码</Text></Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>文件操作</Text><Text color="#aaa"> - 读写、检索、编辑文件</Text></Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>项目管理</Text><Text color="#aaa"> - Git、测试运行、依赖管理</Text></Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>问题排查</Text><Text color="#aaa"> - 分析错误、定位 bug、修复方案</Text></Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>研究分析</Text><Text color="#aaa"> - 检索来源、比较方案、整理结论</Text></Text>
        <Text><Text color="#666">  · </Text><Text color="#FF69B4" bold>通用任务</Text><Text color="#aaa"> - 信息整理、计划执行、多步协作</Text></Text>
        <Text color="#888">  有什么我可以帮你的？</Text>
        <Text color="#555">  快捷键: Ctrl+P 命令面板 · Ctrl+T 思考展开 · Tab 切换模式 · Esc 终止</Text>
      </Box>
    </Box>
  );
}, () => true);

// Spinner isolated into its own leaf component (gemini-cli paradigm: the
// animated GeminiRespondingSpinner is a tiny leaf so its interval re-renders
// ONLY the spinner glyph, never the surrounding content lines — the previous
// in-parent `spinnerIdx` state re-rendered the whole thinking panel every
// 80ms, one of the flicker drivers of 问题4).
const ThinkingSpinner = React.memo(function ThinkingSpinner({ done }: { done?: boolean }) {
  const [spinnerIdx, setSpinnerIdx] = useState(0);
  useEffect(() => {
    if (done) return;
    const iv = setInterval(() => setSpinnerIdx(prev => (prev + 1) % SPINNER_FRAMES.length), 80);
    return () => clearInterval(iv);
  }, [done]);
  return <Text color={C.yellow} bold>{'  '}{done ? '\u2713' : SPINNER_FRAMES[spinnerIdx]}</Text>;
});

// Cap the STREAMING thinking body to its last N lines (gemini-cli's
// availableTerminalHeight / constrainHeight paradigm): the dynamic region must
// never grow past the terminal height, otherwise Ink rewrites more rows than
// the screen holds on every frame — the root mechanism of 问题4's flicker.
// Once done, the full content is committed to <Static> and printed exactly once.
const MAX_STREAMING_THINKING_LINES = 8;
const MAX_EXPANDED_DONE_THINKING_LINES = 40;

const ThinkingMessage = React.memo(function ThinkingMessage({ content, startTime, elapsed, done, expanded, stepIndex, stepTotal }: {
  content: string; startTime: number; elapsed?: number; done?: boolean; expanded: boolean; stepIndex?: number; stepTotal?: number;
}) {
  const displayContent = content || '思考中...';
  // 问题5 修复: respect the user's toggle (Ctrl+T / /thinking) at ALL times.
  // The old `!done || expanded` force-expanded every streaming thought, so
  // turning thinking off appeared to do nothing while the run was live.
  const showExpand = expanded;
  const stepLabel = stepIndex !== undefined && stepTotal !== undefined ? ` ${stepIndex}/${stepTotal} ` : '';
  const allLines = displayContent.split('\n').filter(l => l.trim());
  let lines: string[];
  let clipped: number;
  if (done) {
    if (expanded) {
      lines = allLines.length <= MAX_EXPANDED_DONE_THINKING_LINES
        ? allLines
        : allLines.slice(-MAX_EXPANDED_DONE_THINKING_LINES);
      clipped = allLines.length - lines.length;
    } else {
      lines = [];
      clipped = 0;
    }
  } else {
    lines = allLines.slice(-MAX_STREAMING_THINKING_LINES);
    clipped = allLines.length - lines.length;
  }
  return (
    <Box flexDirection="column" paddingLeft={2} minHeight={1} marginTop={0}>
      <Box>
        <ThinkingSpinner done={done} />
        <Text color={C.yellow} bold> Thought{stepLabel}</Text>
        <Text color={C.overlay2}> (/thinking {expanded ? 'collapse' : 'expand'})</Text>
      </Box>
      {showExpand && (
        <Box paddingLeft={4} flexDirection="column" minHeight={1}>
          {clipped > 0 && <Text color={C.overlay2}>{'  '}… (+{clipped} 行)</Text>}
          {lines.map((line, i) => {
            const isErrorLine = /(?:error|fail|错误)/i.test(line);
            const isDoneLine = /(?:done|complete|success|passed)/i.test(line);
            const isStepLine = /(?:Step|step|Goal|Decompos|Execut|Validat|Synthesiz|Analyz|\d+\.)/i.test(line);
            const clr = isErrorLine ? C.accent : isDoneLine ? C.green : isStepLine ? C.yellow : C.overlay2;
            return <Text key={i} color={clr}>{'  '}{line}</Text>;
          })}
        </Box>
      )}
    </Box>
  );
}, (prev, next) => {
  if (prev.done !== next.done) return false;
  if (prev.expanded !== next.expanded) return false;
  if (prev.content !== next.content) return false;
  if (prev.elapsed !== next.elapsed) return false;
  if (prev.stepIndex !== next.stepIndex) return false;
  if (prev.stepTotal !== next.stepTotal) return false;
  if (prev.startTime !== next.startTime) return false;
  return true;
});

const ToolMessage = React.memo(function ToolMessage({ msg }: { msg: Message }) {
  const statusIcon: Record<ToolStatus, string> = { running: '\u280B', success: '\u2713', error: '\u2717', timeout: '\u23F1', cancelled: '\u2715' };
  const statusColor: Record<ToolStatus, string> = { running: C.yellow, success: C.green, error: C.accent, timeout: C.yellow, cancelled: C.overlay2 };
  const status = msg.toolStatus || 'success';
  const icon = statusIcon[status];
  const color = statusColor[status];
  const dur = msg.toolDuration !== undefined ? `  ${msg.toolDuration.toFixed(1)}s` : '';
  const exit = msg.toolExitCode !== undefined ? `  exit=${msg.toolExitCode}` : '';
  const meta = `${dur}${exit}`;
  const preview = status === 'running' ? (msg.content || '执行中...') : '';
  const allPreviewLines = msg.content ? msg.content.split('\n').filter(l => l.trim()) : [];
  const previewLines = status === 'running' ? allPreviewLines.slice(-5) : [];
  return (
    <Box flexDirection="column" paddingLeft={2} minHeight={1}>
      <Text>
        <Text color={color} bold>{'    '}{icon} {msg.toolName}</Text>
        <Text color={C.overlay2}>({msg.toolArgs})</Text>
        {status !== 'running' && <Text color={color}> [{status}]</Text>}
        {meta && <Text color={status === 'error' ? C.accent : C.overlay2}>{meta}</Text>}
      </Text>
      {previewLines.length > 0
        ? previewLines.map((line, i) => (
          <Text key={i} color={status === 'error' ? C.accent : C.overlay2}>{'       '}{line}</Text>
        ))
        : status === 'running' && <Text color={C.overlay2}>{'      '}{'\u2192'} {preview}</Text>}
    </Box>
  );
});

const UserMessage = React.memo(function UserMessage({ content, mode }: { content: string; mode: Mode }) {
  const modeColor = MODE_COLORS[mode];
  const border = '\u2588';
  const line = '\u2500'.repeat(40);
  return (
    <Box flexDirection="column" paddingLeft={1} paddingTop={0}>
      <Box><Text color={modeColor}>{'  '}{border}</Text><Text color={C.borderDim}>{line}</Text></Box>
      <Box><Text color={modeColor}>{'  '}{border}</Text><Text color={C.text}> {content}</Text></Box>
      <Box><Text color={modeColor}>{'  '}{border}</Text><Text color={C.borderDim}>{line}</Text></Box>
    </Box>
  );
});

const AssistantMessage = React.memo(function AssistantMessage({ msg, maxPreviewLines }: { msg: Message; maxPreviewLines?: number }) {
  const ts = new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour12: false });
  const content = maxPreviewLines === undefined ? (msg.content || '') : tailLines(msg.content || '', maxPreviewLines);
  return (
    <Box flexDirection="column" paddingLeft={1} paddingTop={0} paddingBottom={0}>
      <Markdown content={content} />
      <Text color={C.overlay2}>{'  '}{'\u00b7'} {ts}{msg.elapsed !== undefined ? `  ${msg.elapsed}s` : ''}</Text>
    </Box>
  );
});

const SystemMessage = React.memo(function SystemMessage({ content }: { content: string }) {
  return (
    <Box paddingLeft={2}><Text color={C.overlay2}>{'  '}{content}</Text></Box>
  );
});

function renderMessage(msg: Message, mode: Mode, expandThinking: boolean, maxAssistantPreviewLines?: number) {
  switch (msg.role) {
    case 'thinking':
      return <ThinkingMessage key={msg.id} content={msg.content} startTime={msg.timestamp} elapsed={msg.elapsed} done={msg.done} expanded={expandThinking} stepIndex={msg.stepIndex} stepTotal={msg.stepTotal} />;
    case 'tool':
      return <ToolMessage key={msg.id} msg={msg} />;
    case 'user':
      return <UserMessage key={msg.id} content={msg.content} mode={mode} />;
    case 'assistant':
      return <AssistantMessage key={msg.id} msg={msg} maxPreviewLines={maxAssistantPreviewLines} />;
    case 'system':
      return <SystemMessage key={msg.id} content={msg.content} />;
    default:
      return null;
  }
}

export default React.memo(function ChatPanel({ messages, height, mode, expandThinking }: Props) {
  const showWelcome = messages.length === 0;
  const committedIdsRef = useRef<string[]>([]);
  const staticGenerationRef = useRef(0);

  // Ink Static is append-only: once an item is printed, changing or inserting
  // anything before it is ignored. Commit only the contiguous finalized prefix,
  // keeping later assistant/tool messages dynamic while an earlier item runs.
  const committedPrefixStillPresent = committedIdsRef.current.length <= messages.length
    && committedIdsRef.current.every((id, index) => messages[index]?.id === id);
  if (!committedPrefixStillPresent) {
    committedIdsRef.current = [];
    staticGenerationRef.current += 1;
  }

  let committedCount = committedIdsRef.current.length;
  while (committedCount < messages.length && isFinalized(messages[committedCount])) {
    committedIdsRef.current.push(messages[committedCount].id);
    committedCount += 1;
  }
  const finalized = messages.slice(0, committedCount);
  const active = messages.slice(committedCount);

  // 问题3 修复 (gemini-cli content-sized frame paradigm): NO minHeight filler.
  // The old `minHeight={height}` stretched the dynamic panel to fill the
  // screen, leaving a huge blank block between the committed history (in
  // terminal scrollback above the frame) and the input box — the "消息离底部
  // 对话框太远" gap — and made new messages appear at the TOP of that panel
  // before jumping up into Static ("先下后上"). With a content-sized frame the
  // input box always sits directly under the latest message, and committed
  // history flows naturally into scrollback, exactly like gemini-cli's
  // non-alt-buffer layout.
  return (
    <Box flexDirection="column" paddingX={1}>
      {showWelcome && <WelcomeMessage />}
      <Static key={staticGenerationRef.current} items={finalized}>
        {msg => renderMessage(msg, mode, expandThinking)}
      </Static>
      {active.map(msg => renderMessage(msg, mode, expandThinking, Math.max(3, height - 6)))}
    </Box>
  );
});
