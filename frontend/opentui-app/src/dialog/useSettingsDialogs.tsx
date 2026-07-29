/**
 * Opens OpenCode-style nested settings dialogs via DialogHost.replace / push.
 * All openable commands route here — avoid dumping list/help bodies into chat.
 */

import { useCallback, useRef } from "react";
import type { Command } from "../commands.ts";
import type { ChatMessage } from "../types.ts";
import { CommandPalette } from "../CommandPalette.tsx";
import {
  useDialog,
  DialogSession,
  DialogModel,
  DialogAddModel,
  DialogSettings,
  DialogPermission,
  DialogLanguage,
  DialogCommandList,
  DialogStatus,
  DialogMemory,
  DialogSkills,
  DialogMcp,
  DialogDoc,
} from "./index.ts";

export type SettingsDialogCallbacks = {
  pushSystem: (content: string) => void;
  setMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  fetchStatus: () => void;
  clearInput: () => void;
  statusLine: string;
  activeModel?: string;
  setPermissionMode: (mode: string) => void;
  /** Called for palette commands that are not nested-dialog routes (e.g. /clear). */
  onFallbackCommand: (cmd: Command) => void;
};

function mapLoadedMessages(raw: unknown[]): ChatMessage[] {
  return raw.map((m, i) => {
    const row = m as { role?: string; content?: string; text?: string };
    const roleRaw = row.role || "assistant";
    const role: ChatMessage["role"] =
      roleRaw === "user" ||
      roleRaw === "assistant" ||
      roleRaw === "system" ||
      roleRaw === "thinking" ||
      roleRaw === "tool"
        ? roleRaw
        : "system";
    return {
      id: `loaded-${i}-${Date.now()}`,
      role,
      content: String(row.content ?? row.text ?? ""),
      timestamp: Date.now(),
    };
  });
}

export function useSettingsDialogs(cb: SettingsDialogCallbacks) {
  const dialog = useDialog();
  const cbRef = useRef(cb);
  cbRef.current = cb;

  const close = useCallback(() => {
    dialog.clear();
    cbRef.current.clearInput();
  }, [dialog]);

  const shortMsg = useCallback((text: string) => {
    const line = text.replace(/\s+/g, " ").trim();
    cbRef.current.pushSystem(line.slice(0, 160));
  }, []);

  const openPermission = useCallback(() => {
    dialog.replace(
      <DialogPermission
        onClose={close}
        onChanged={(mode, message) => {
          cbRef.current.setPermissionMode(mode);
          shortMsg(message);
        }}
      />,
    );
  }, [dialog, close, shortMsg]);

  const openLanguage = useCallback(() => {
    dialog.replace(
      <DialogLanguage
        onClose={close}
        onChanged={(_lang, message) => shortMsg(message)}
      />,
    );
  }, [dialog, close, shortMsg]);

  const openSettings = useCallback(() => {
    dialog.replace(
      <DialogSettings
        onClose={close}
        onOpenPermission={openPermission}
        onOpenLanguage={openLanguage}
      />,
    );
  }, [dialog, close, openPermission, openLanguage]);

  const openAddModel = useCallback(() => {
    dialog.replace(
      <DialogAddModel
        onClose={close}
        onDone={(message) => {
          shortMsg(message);
          cbRef.current.fetchStatus();
        }}
      />,
    );
  }, [dialog, close, shortMsg]);

  const openModel = useCallback(() => {
    dialog.replace(
      <DialogModel
        activeModel={cbRef.current.activeModel}
        onClose={close}
        onSwitched={(modelId, message) => {
          if (modelId === "__add__") {
            openAddModel();
            return;
          }
          shortMsg(message);
          cbRef.current.fetchStatus();
        }}
      />,
    );
  }, [dialog, close, openAddModel, shortMsg]);

  const openSession = useCallback(() => {
    dialog.replace(
      <DialogSession
        onClose={close}
        onLoaded={({ messages, message }) => {
          if (messages && Array.isArray(messages) && messages.length > 0) {
            cbRef.current.setMessages(() => mapLoadedMessages(messages));
          }
          if (message) shortMsg(message);
        }}
      />,
    );
  }, [dialog, close, shortMsg]);

  const openMemory = useCallback(() => {
    dialog.replace(
      <DialogMemory onClose={close} onMessage={shortMsg} />,
    );
  }, [dialog, close, shortMsg]);

  const openSkills = useCallback(() => {
    dialog.replace(
      <DialogSkills onClose={close} onMessage={shortMsg} />,
    );
  }, [dialog, close, shortMsg]);

  const openMcp = useCallback(() => {
    dialog.replace(
      <DialogMcp onClose={close} onMessage={shortMsg} />,
    );
  }, [dialog, close, shortMsg]);

  const openList = useCallback(
    (kind: "queue" | "schedule") => {
      dialog.replace(
        <DialogCommandList
          kind={kind}
          onClose={close}
          onMessage={shortMsg}
        />,
      );
    },
    [dialog, close, shortMsg],
  );

  const openDoc = useCallback(
    (kind: "help" | "tutorial" | "quickstart" | "examples") => {
      dialog.replace(<DialogDoc kind={kind} onClose={close} />);
    },
    [dialog, close],
  );

  const openStatus = useCallback(() => {
    dialog.replace(
      <DialogStatus onClose={close} statusLine={cbRef.current.statusLine} />,
    );
  }, [dialog, close]);

  const routePaletteCommand = useCallback(
    (cmd: Command) => {
      cbRef.current.clearInput();
      const name = cmd.name;
      const action = cmd.action;

      if (name === "/settings" || action === "settings") {
        openSettings();
        return;
      }
      if (name === "/permission" || action === "permission") {
        openPermission();
        return;
      }
      if (name === "/language") {
        openLanguage();
        return;
      }
      if (name === "/session" || action === "session") {
        openSession();
        return;
      }
      if (name === "/model" || name === "/models" || action === "model") {
        openModel();
        return;
      }
      if (name === "/addmodel" || action === "addmodel") {
        openAddModel();
        return;
      }
      if (
        name === "/memory list" ||
        name === "/memory add" ||
        name === "/memory remove" ||
        name === "/memory search" ||
        action === "memory"
      ) {
        openMemory();
        return;
      }
      if (
        name === "/list-skills" ||
        name === "/addskill" ||
        name === "/find-skill" ||
        name === "/remove-skill" ||
        action === "skill"
      ) {
        openSkills();
        return;
      }
      if (
        name === "/list-mcp" ||
        name === "/addmcp" ||
        name === "/remove-mcp" ||
        action === "mcp"
      ) {
        openMcp();
        return;
      }
      if (name === "/queue" || action === "queue") {
        openList("queue");
        return;
      }
      if (name === "/schedule" || action === "schedule") {
        openList("schedule");
        return;
      }
      if (name === "/help") {
        openDoc("help");
        return;
      }
      if (name === "/tutorial") {
        openDoc("tutorial");
        return;
      }
      if (name === "/quickstart") {
        openDoc("quickstart");
        return;
      }
      if (name === "/examples") {
        openDoc("examples");
        return;
      }
      if (name === "/cache") {
        openStatus();
        return;
      }

      dialog.clear();
      cbRef.current.onFallbackCommand(cmd);
    },
    [
      dialog,
      openSettings,
      openPermission,
      openLanguage,
      openSession,
      openModel,
      openAddModel,
      openMemory,
      openSkills,
      openMcp,
      openList,
      openDoc,
      openStatus,
    ],
  );

  const openPalette = useCallback(() => {
    dialog.replace(
      <CommandPalette onClose={close} onSelect={(cmd) => routePaletteCommand(cmd)} />,
    );
  }, [dialog, close, routePaletteCommand]);

  return {
    dialogOpen: dialog.open,
    openPalette,
    openSettings,
    openPermission,
    openLanguage,
    openSession,
    openModel,
    openAddModel,
    openMemory,
    openSkills,
    openMcp,
    openHelp: () => openDoc("help"),
    openStatus,
    close,
    routePaletteCommand,
  };
}
