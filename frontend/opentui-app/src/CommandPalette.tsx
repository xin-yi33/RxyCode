/**
 * Command palette built on DialogSelect (OpenCode dialog-command pattern).
 */

import { useMemo } from "react";
import { AVAILABLE_COMMANDS, type Command } from "./commands.ts";
import { DialogSelect, type DialogSelectOption } from "./dialog/DialogSelect.tsx";

export { filterAndGroup, CATEGORY_ORDER, type DisplayRow } from "./CommandPalette.group.ts";

const ORDER = ["会话", "Agent", "记忆", "Skills", "MCP", "系统", "其他"];

export function CommandPalette({
  onSelect,
  onClose,
}: {
  query?: string;
  onQueryChange?: (q: string) => void;
  onSelect: (cmd: Command) => void;
  onClose: () => void;
  maxVisible?: number;
}) {
  const options: DialogSelectOption<Command>[] = useMemo(
    () =>
      AVAILABLE_COMMANDS.map((cmd) => ({
        id: cmd.name,
        title: cmd.name,
        description: cmd.description,
        category: cmd.category || "其他",
        value: cmd,
      })),
    [],
  );

  return (
    <DialogSelect
      title="命令"
      options={options}
      categoryOrder={ORDER}
      placeholder="搜索"
      onClose={onClose}
      onSelect={(opt) => onSelect(opt.value)}
    />
  );
}
