import React, { useState, useEffect, useRef } from 'react';
import { Box, Text, useInput, useStdout } from 'ink';
import { C } from '../theme.js';
import { useListMouse } from '../mouse.js';
import { maxVisibleFor, modalHeight } from '../layout.js';

export interface ModalItem {
  id: string;
  label: string;
  desc?: string;
}

interface ModalProps {
  title: string;
  items: ModalItem[];
  onSelect: (index: number) => void;
  onClose: () => void;
  accentColor?: string;
  maxVisible?: number;
}

const MAX_VISIBLE_DEFAULT = 12;

export default React.memo(function Modal({
  title, items, onSelect, onClose,
  accentColor = C.primary, maxVisible = MAX_VISIBLE_DEFAULT,
}: ModalProps) {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns ?? 80;
  const termRows = stdout?.rows ?? 40;
  const innerW = Math.max(10, termWidth - 4);

  // Adapt height to the terminal so the list never overflows and the mouse
  // geometry (list flush at the bottom) stays valid.
  const mv = Math.max(4, Math.min(maxVisible, maxVisibleFor(termRows)));

  const [idx, setIdx] = useState(0);
  const idxRef = useRef(0);
  idxRef.current = idx;
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // 滚动窗口
  const half = Math.floor(mv / 2);
  let visStart = idx - half;
  if (visStart < 0) visStart = 0;
  if (visStart + mv > items.length) visStart = Math.max(0, items.length - mv);
  const visStartRef = useRef(visStart);
  visStartRef.current = visStart;

  // 鼠标：滚动 / 高光 / 点击
  useListMouse(true, {
    rows: termRows,
    listHeight: modalHeight(mv),
    offset: 3, // 边框 + 标题 + 分隔 之后是第一项
    slotCount: mv,
    resolveSlot: (slot) => {
      const gi = visStartRef.current + slot;
      return gi < itemsRef.current.length ? gi : null;
    },
    onClick: (gi) => onSelectRef.current(gi),
    onWheel: (delta) => setIdx((i) => Math.max(0, Math.min(itemsRef.current.length - 1, i + delta))),
  });

  // 键盘导航（纯 useInput，不做原始 stdin 鼠标追踪）
  useInput((ch, key) => {
    if (key.escape) { onCloseRef.current(); return; }
    if (key.upArrow) { setIdx(i => Math.max(0, i - 1)); return; }
    if (key.downArrow) { setIdx(i => Math.min(itemsRef.current.length - 1, i + 1)); return; }
    if (key.return) { onSelectRef.current(idxRef.current); return; }
  });

  // 滚动窗口（visStart 已在上方鼠标 hook 之前计算并存入 visStartRef）
  const visEnd = Math.min(items.length, visStart + mv);
  const visibleItems = items.slice(visStart, visEnd);

  const rows: Array<{ kind: 'item' | 'empty'; index?: number; item?: ModalItem }> = [];
  visibleItems.forEach((item, k) => {
    rows.push({ kind: 'item', index: visStart + k, item });
  });
  while (rows.length < mv) rows.push({ kind: 'empty' });

  const divider = '\u2500'.repeat(innerW);

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" borderStyle="round" borderColor={accentColor} paddingX={1}>
        <Box>
          <Text color={accentColor} bold>{'  '}{title}</Text>
          <Box flexGrow={1} />
          <Text color={C.overlay2}>{items.length}{' '}</Text>
        </Box>
        <Box><Text color={C.borderDim}>{divider}</Text></Box>
        {rows.map((r, i) => {
          if (r.kind === 'empty') {
            return <Box key={'e' + i}><Text>{'  '}</Text></Box>;
          }
          const sel = r.index === idx;
          return (
            <Box key={r.index} width={innerW}>
              <Text wrap="truncate" backgroundColor={sel ? C.surface1 : undefined}>
                <Text color={sel ? accentColor : C.subtext}>{sel ? ' \u276F ' : '   '}{r.item!.label}</Text>
                {r.item!.desc && <Text color={sel ? C.subtext : C.overlay2}>  {r.item!.desc}</Text>}
                <Text>{' '.repeat(innerW)}</Text>
              </Text>
            </Box>
          );
        })}
        <Box>
          <Text color={C.overlay2}>{'  \u2191\u2193 \u9009\u62E9   \u21B5 \u786E\u8BA4   esc \u5173\u95ED'}</Text>
          <Box flexGrow={1} />
          <Text color={C.overlay2}>{idx + 1}/{items.length}{' '}</Text>
        </Box>
      </Box>
    </Box>
  );
});
