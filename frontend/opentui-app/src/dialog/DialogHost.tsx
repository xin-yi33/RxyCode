/**
 * DialogHost — OpenCode-style dialog stack (replace / push / pop / clear).
 * Only the top node is mounted (avoids stacked useKeyboard handlers).
 * ESC policy is owned by each dialog; Host just stores the stack.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type DialogNode = ReactNode;

type DialogContextValue = {
  open: boolean;
  depth: number;
  content: DialogNode | null;
  /** Replace entire stack with a single node (legacy-compatible). */
  replace: (node: DialogNode) => void;
  /** Push a child layer (confirm / sub-wizard). */
  push: (node: DialogNode) => void;
  /** Pop one layer; empty stack clears. */
  pop: () => void;
  clear: () => void;
};

const DialogContext = createContext<DialogContextValue | null>(null);

/** Pure stack helpers — exported for unit tests. */
export function stackReplace(_stack: DialogNode[], node: DialogNode): DialogNode[] {
  return [node];
}

export function stackPush(stack: DialogNode[], node: DialogNode): DialogNode[] {
  return [...stack, node];
}

export function stackPop(stack: DialogNode[]): DialogNode[] {
  if (stack.length <= 1) return [];
  return stack.slice(0, -1);
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<DialogNode[]>([]);

  const replace = useCallback((node: DialogNode) => {
    setStack(stackReplace([], node));
  }, []);

  const push = useCallback((node: DialogNode) => {
    setStack((s) => stackPush(s, node));
  }, []);

  const pop = useCallback(() => {
    setStack((s) => stackPop(s));
  }, []);

  const clear = useCallback(() => {
    setStack([]);
  }, []);

  const content = stack.length > 0 ? stack[stack.length - 1]! : null;

  const value = useMemo(
    () => ({
      open: stack.length > 0,
      depth: stack.length,
      content,
      replace,
      push,
      pop,
      clear,
    }),
    [stack, content, replace, push, pop, clear],
  );

  return <DialogContext.Provider value={value}>{children}</DialogContext.Provider>;
}

export function useDialog(): DialogContextValue {
  const ctx = useContext(DialogContext);
  if (!ctx) {
    throw new Error("useDialog must be used within DialogProvider");
  }
  return ctx;
}

/** Renders only the top dialog — unmounts lower layers (keyboard isolation). */
export function DialogOutlet() {
  const { content } = useDialog();
  if (!content) return null;
  return (
    <box style={{ flexShrink: 0, width: "100%", flexDirection: "column" }}>{content}</box>
  );
}
