/**
 * OpenTUI ScrollBox probe (U2) — style-frozen pink brand not required here.
 * Validates Bun + @opentui can create a renderer with a scrollbox.
 * Run: bun run scripts/opentui-probe.ts
 *
 * Preferred dual-entry probe (React 19 isolated package):
 *   cd frontend/opentui-app && bun run probe
 */
import { createCliRenderer, Box, Text, ScrollBox } from "@opentui/core"

const renderer = await createCliRenderer({
  exitOnCtrlC: true,
  useAlternateScreen: true,
})

const scroll = ScrollBox(
  {
    flexGrow: 1,
    stickyScroll: true,
    borderStyle: "rounded",
  },
  ...Array.from({ length: 80 }, (_, i) =>
    Text({
      content: `probe-line-${i} RxyCode OpenTUI scrollbox`,
      fg: i === 0 ? "#FFB6C1" : "#FF69B4",
    }),
  ),
)

renderer.root.add(
  Box(
    { flexDirection: "column", width: "100%", height: "100%" },
    Text({ content: "RxyCode OpenTUI probe — Ctrl+C exit", fg: "#FFB6C1" }),
    scroll,
  ),
)

console.error("opentui-probe: renderer started (scrollbox with 80 lines)")
