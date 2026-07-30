import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { Box, Text, useInput, useStdout, type Key } from 'ink';
import CursorInput, { handleCursorInputKey } from './CursorInput.js';
import type { Mode, Command } from '../types.js';
import { MODE_COLORS, AVAILABLE_COMMANDS } from '../types.js';
import { C } from '../theme.js';
import { useListMouse, useMouseManager } from '../mouse.js';
import { maxVisibleFor, paletteHeight, numInputLines, caretOffsetFromClick, caretVisualPosition, cursorRowsFromFrameEnd } from '../layout.js';
import { installCursorAnchor, uninstallCursorAnchor, setCursorAnchor } from '../terminalCursor.js';

export const paletteTopRow = (termRows: number): number => termRows - paletteHeight(termRows) + 1;

export default React.memo(function InputBox({
  mode, onSubmit, onCycleMode, onCommand, isStreaming, onCancel,
  showCommandPalette, onToggleCommandPalette, onCommandPaletteSelect,
}: {
  mode: Mode;
  onSubmit: (text: string) => void;
  onCycleMode: () => void;
  onCommand: (cmd: string) => void;
  isStreaming: boolean;
  onCancel: () => void;
  showCommandPalette: boolean;
  onToggleCommandPalette: () => void;
  onCommandPaletteSelect: (cmd: string) => void;
}) {
  const [input, setInput] = useState('');
  const [showCommands, setShowCommands] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [paletteIdx, setPaletteIdx] = useState(0);
  const [paletteSearch, setPaletteSearch] = useState('');
  const [cursorOffset, setCursorOffset] = useState(0);

  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  const termRows = stdout?.rows ?? 40;
  const innerW = Math.max(10, termWidth - 4);
  const borderColor = useMemo(() => MODE_COLORS[mode], [mode]);

  // Position the terminal's native (thin, blinking) cursor at the input line.
  //
  // Frame-synchronized anchor (问题1/2 根修, paradigm adapted from
  // google-gemini/gemini-cli, Apache-2.0 — see terminalCursor.ts):
  //   - No setTimeout: the old deferred write raced against frames triggered by
  //     OTHER components (spinner ticks, status polls). Any frame Ink flushed
  //     without re-running this effect left the caret at the frame end — right
  //     after the StatusBar "设置" text (问题1).
  //   - No absolute rows: the caret is expressed as "rows UP from the frame
  //     end" (`cursorRowsFromFrameEnd`), which stays correct even when the
  //     frame is shorter than the terminal, and fixes the off-by-one that put
  //     the caret one row above the text (问题2).
  //   - `installCursorAnchor` wraps process.stdout.write so the caret is
  //     re-asserted synchronously after EVERY frame — race-free by design.
  //
  // The cursor COLUMN must be computed from the DISPLAY width of the text
  // before the caret (string-width, UAX #11 + emoji): CJK / fullwidth glyphs
  // occupy 2 cells, so a naive `5 + cursorOffset` would land mid-glyph.
  //
  // IMPORTANT: operate on the REAL `process.stdout`, not the `useStdout()`
  // instance — in tests (ink-testing-library) the latter is a virtual buffer
  // and `installCursorAnchor` is a no-op for non-TTY streams.
  useEffect(() => {
    installCursorAnchor(process.stdout);
    return () => uninstallCursorAnchor();
  }, []);

  useEffect(() => {
    const out = process.stdout;
    if (!out.isTTY) return;
    // Hide the caret while the run is streaming (input not editable) and while
    // the command palette owns the screen — mirrors opencode's "hide cursor
    // while generating" so the caret never garbles the `ESC 取消` text.
    if (showCommandPalette || isStreaming) {
      setCursorAnchor(out, null);
      return;
    }
    const startCell = 4; // 0-based: first input char cell = column 5
    const wrapW = Math.max(10, termWidth - 6); // inner box width minus `> ` prefix
    const caret = caretVisualPosition(input, cursorOffset, wrapW);
    const numTextLines = numInputLines(input, wrapW);
    setCursorAnchor(out, {
      rowsUp: cursorRowsFromFrameEnd(numTextLines, caret.lineIndex),
      column: startCell + caret.column + 1, // 1-based
    });
  }, [showCommandPalette, isStreaming, showCommands, cursorOffset, termWidth, termRows, input]);

  // Bug 4: click anywhere inside the input text area moves the native caret to
  // the clicked character — mirroring opencode / claude-code. The box geometry
  // used here is IDENTICAL to the one in the cursor-positioning effect above
  // (shared via layout.ts helpers), so the click math can never disagree with
  // where the caret actually lands. Clicks outside the text block (header,
  // border, StatusBar, or the chat area above) are ignored.
  const mouseMgr = useMouseManager();
  const clickGeoRef = useRef({ input, showCommands, showCommandPalette, isStreaming, termWidth, termRows });
  clickGeoRef.current = { input, showCommands, showCommandPalette, isStreaming, termWidth, termRows };
  useEffect(() => {
    const unsub = mouseMgr.subscribe((e) => {
      const g = clickGeoRef.current;
      if (g.showCommandPalette || g.isStreaming) return; // not editable
      if (e.wheel !== 0 || !e.click) return; // plain left clicks only
      const commandsAbove = g.showCommands ? 4 + Math.min(8, AVAILABLE_COMMANDS.length) : 0;
      const off = caretOffsetFromClick(e.x, e.y, g.input, g.termWidth, g.termRows, commandsAbove);
      if (off >= 0) setCursorOffset(off);
    });
    return unsub;
  }, [mouseMgr]);

  const filteredCommands = useMemo(() => AVAILABLE_COMMANDS, []);

  const paletteFiltered = useMemo(() => {
    const q = paletteSearch.trim().toLowerCase();
    if (!q) return AVAILABLE_COMMANDS;
    return AVAILABLE_COMMANDS.filter(c => {
      const hay = (c.name + ' ' + c.description + ' ' + (c.keywords || '') + ' ' + (c.category || '')).toLowerCase();
      return q.split(/\s+/).every(tok => hay.includes(tok));
    });
  }, [paletteSearch]);

  const paletteGroups = useMemo(() => {
    if (paletteSearch.trim()) return [{ cat: '', items: paletteFiltered }];
    const map = new Map<string, Command[]>();
    for (const cmd of paletteFiltered) {
      const cat = cmd.category || 'Other';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(cmd);
    }
    return Array.from(map.entries()).map(([cat, items]) => ({ cat, items }));
  }, [paletteFiltered, paletteSearch]);

  const paletteFlat = useMemo(() => {
    if (paletteSearch.trim()) return paletteFiltered;
    return paletteGroups.flatMap(g => g.items);
  }, [paletteGroups, paletteFiltered, paletteSearch]);

  const paletteFlatRef = useRef(paletteFlat);
  paletteFlatRef.current = paletteFlat;
  const paletteSlotRef = useRef<(number | null)[]>([]);
  const onPaletteSelectRef = useRef(onCommandPaletteSelect);
  onPaletteSelectRef.current = onCommandPaletteSelect;

  useListMouse(showCommandPalette, {
    rows: termRows,
    listHeight: paletteHeight(termRows),
    offset: 4,
    slotCount: maxVisibleFor(termRows),
    resolveSlot: (slot) => paletteSlotRef.current[slot] ?? null,
    onClick: (gi) => {
      const cmd = paletteFlatRef.current[gi];
      if (cmd) {
        try {
          onPaletteSelectRef.current(cmd.action ? ('__action:' + cmd.action) : cmd.name);
        } catch { /* ignore */ }
      }
    },
    onWheel: (delta) => setPaletteIdx((i) => Math.max(0, Math.min(paletteFlatRef.current.length - 1, i + delta))),
  });

  const inputHandlerRef = useRef<(input: string, key: Key) => void>(() => {});
  inputHandlerRef.current = (ch, key) => {
    const isCtrl = key.ctrl;
    const chLower = ch ? ch.toLowerCase() : '';
    const code = ch ? ch.charCodeAt(0) : -1;

    if (isCtrl && (chLower === 'p' || code === 16)) {
      if (!showCommandPalette) {
        setPaletteSearch('');
        setPaletteIdx(0);
      }
      onToggleCommandPalette();
      return;
    }

    if ((isCtrl && chLower === 'c') || code === 3) { if (isStreaming) onCancel(); return; }
    if (key.tab) { onCycleMode(); return; }

    if (showCommandPalette) {
      if (key.escape) {
        setPaletteSearch(''); setPaletteIdx(0); onToggleCommandPalette();
        return;
      }
      if (key.upArrow) { setPaletteIdx(i => Math.max(0, i - 1)); return; }
      if (key.downArrow) { setPaletteIdx(i => Math.min(paletteFlat.length - 1, i + 1)); return; }
      if (key.backspace || key.delete) {
        setPaletteSearch(s => s.slice(0, -1));
        setPaletteIdx(0);
        return;
      }
      if (key.return) {
        const cmd = paletteFlat[paletteIdx];
        if (cmd) {
          try {
            onCommandPaletteSelect(cmd.action ? ('__action:' + cmd.action) : cmd.name);
          } catch { /* ignore */ }
        }
        return;
      }
      if (ch && !key.ctrl && !key.meta && ch.length === 1 && ch >= ' ') {
        setPaletteSearch(s => s + ch);
        setPaletteIdx(0);
        return;
      }
      return;
    }

    if (key.escape) {
      if (showCommands) { setShowCommands(false); setSelectedIdx(0); setInput(''); }
      else if (isStreaming) { onCancel(); }
      return;
    }

    if (showCommands) {
      if (key.upArrow) { setSelectedIdx(i => Math.max(0, i - 1)); return; }
      if (key.downArrow) { setSelectedIdx(i => Math.min(filteredCommands.length - 1, i + 1)); return; }
    }

    handleCursorInputKey(ch, key, input, cursorOffset, handleInputChange, handleSubmit);
  };

  const stableInputHandler = useCallback((input: string, key: Key) => {
    inputHandlerRef.current(input, key);
  }, []);
  useInput(stableInputHandler);

  const handleInputChange = useCallback((value: string, offset: number) => {
    setInput(value);
    setCursorOffset(offset);
    if (showCommandPalette) {
      setPaletteSearch(value);
      setPaletteIdx(0);
      return;
    }
    if (value.startsWith('/') && value.length > 0) { setShowCommands(true); setSelectedIdx(0); }
    else { setShowCommands(false); }
  }, [showCommandPalette]);

  const handleSubmit = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    if (trimmed.startsWith('/')) { onCommand(trimmed); }
    else { onSubmit(trimmed); }
    setInput(''); setCursorOffset(0); setShowCommands(false);
  }, [onSubmit, onCommand]);

  // === Command palette rendering ===
  if (showCommandPalette) {
    const maxVisible = maxVisibleFor(termRows);

    // Build display rows with category headers
    interface RowDef { kind: 'header' | 'item' | 'empty'; category?: string; label?: string; desc?: string; globalIndex?: number; }
    const allRows: RowDef[] = [];
    const flatToDisplay: number[] = [];
    if (paletteSearch.trim()) {
      paletteFlat.forEach((cmd, gi) => {
        flatToDisplay[gi] = allRows.length;
        allRows.push({ kind: 'item', globalIndex: gi, label: cmd.name + (cmd.args ? ' ' + cmd.args : ''), desc: cmd.description });
      });
    } else {
      paletteGroups.forEach(group => {
        allRows.push({ kind: 'header', category: group.cat });
        group.items.forEach(cmd => {
          const gi = paletteFlat.indexOf(cmd);
          if (gi >= 0) {
            flatToDisplay[gi] = allRows.length;
            allRows.push({ kind: 'item', globalIndex: gi, label: cmd.name + (cmd.args ? ' ' + cmd.args : ''), desc: cmd.description });
          }
        });
      });
    }

    const currentDisplayIdx = flatToDisplay[paletteIdx] ?? 0;
    const half = Math.floor(maxVisible / 2);
    let visStart = currentDisplayIdx - half;
    if (visStart < 0) visStart = 0;
    if (visStart + maxVisible > allRows.length) {
      visStart = Math.max(0, allRows.length - maxVisible);
    }
    const visEnd = Math.min(allRows.length, visStart + maxVisible);
    const rows: RowDef[] = allRows.slice(visStart, visEnd);
    while (rows.length < maxVisible) rows.push({ kind: 'empty' });

    paletteSlotRef.current = rows.map(r => (r.kind === 'item' ? (r.globalIndex ?? null) : null));

    const divider = '\u2500'.repeat(innerW);

    const renderItems = rows.map((r, idx) => {
      if (r.kind === 'empty') {
        return (<Box key={'e' + idx}><Text>{'  '}</Text></Box>);
      }
      if (r.kind === 'header') {
        return (
          <Box key={'h' + idx} width={innerW}>
            <Text color={C.overlay2} bold dimColor>{'  '}{r.category}</Text>
          </Box>
        );
      }
      const sel = r.globalIndex === paletteIdx;
      return (
        <Box key={r.globalIndex} width={innerW}>
          <Text wrap="truncate" backgroundColor={sel ? C.surface1 : undefined}>
            <Text color={sel ? C.primary : C.subtext}>{sel ? ' \u276F ' : '   '}{r.label}</Text>
            <Text color={sel ? C.subtext : C.overlay2}>  {r.desc}</Text>
            <Text>{' '.repeat(innerW)}</Text>
          </Text>
        </Box>
      );
    });

    return (
      <Box flexDirection="column">
        <Box flexDirection="column" borderStyle="round" borderColor={C.border} paddingX={1}>
          <Box>
            <Text color={C.primary} bold>{'  \u547D\u4EE4\u9762\u677F'}</Text>
            <Box flexGrow={1} />
            <Text color={C.overlay2}>{paletteFlat.length}/{AVAILABLE_COMMANDS.length}</Text>
          </Box>
          <Box>
            <Text color={C.primary}>{' \u276F '}</Text>
            <Text color={paletteSearch ? C.text : C.overlay2}>{paletteSearch || '\u641C\u7D22\u547D\u4EE4\u2026'}</Text>
          </Box>
          <Box><Text color={C.borderDim}>{divider}</Text></Box>
          {renderItems}
          <Box>
            <Text color={C.overlay2}>{'  \u2191\u2193 \u9009\u62E9   \u21B5 \u786E\u8BA4   esc \u5173\u95ED'}</Text>
            <Box flexGrow={1} />
            <Text color={C.overlay2}>{paletteIdx + 1}/{paletteFlat.length}</Text>
          </Box>
        </Box>
      </Box>
    );
  }

  // === Normal input box rendering ===
  return (
    <Box flexDirection="column">
      {showCommands && filteredCommands.length > 0 && (
        <Box flexDirection="column" borderStyle="round" borderColor={C.borderDim} paddingX={1} marginBottom={1}>
          <Text color={C.yellow} bold>{'  '}Commands</Text>
          {filteredCommands.slice(0, 8).map((cmd, i) => {
            const arrow = i === selectedIdx ? '\u276F' : ' ';
            const color = i === selectedIdx ? C.primary : C.subtext;
            const argsPart = cmd.args ? (' ' + cmd.args) : '';
            return (
              <Box key={cmd.name} width={innerW}>
                <Text wrap="truncate" backgroundColor={i === selectedIdx ? C.surface1 : undefined}>
                  <Text color={color}>{'  '}{arrow} {cmd.name}{argsPart}</Text>
                  <Text color={C.overlay2}> - {cmd.description}</Text>
                  <Text>{' '.repeat(innerW)}</Text>
                </Text>
              </Box>
            );
          })}
        </Box>
      )}
      <Box flexDirection="column" borderStyle="round" borderColor={borderColor} paddingX={1}>
        <Box>
          <Text color={borderColor} bold> {mode} </Text>
          <Text color={C.overlay2}>{'\u00B7'} </Text>
          <Text color={C.mauve}>{isStreaming ? 'Processing...' : 'Ready'}</Text>
        </Box>
        <Box>
          <Text color={borderColor} bold>{'>'} </Text>
          <Box flexGrow={1}>
            <CursorInput
              value={input}
              cursorOffset={cursorOffset}
              onChange={handleInputChange}
              onSubmit={handleSubmit}
              isActive={false}
              placeholder={isStreaming ? '处理中...' : '\u8F93\u5165\u6307\u4EE4\u6216\u9700\u6C42...'}
            />
          </Box>
          {isStreaming && (<Text color={C.yellow}>{' ESC 取消'}</Text>)}
        </Box>
      </Box>
    </Box>
  );
});
