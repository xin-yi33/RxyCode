/** layer=unit FR-SS-4 */
import { describe, expect, it } from "bun:test";
import { applySessionListKey, promoteSessionRow, type SessionListKeyState } from "./sessionListKeybind.ts";

function state(over: Partial<SessionListKeyState> = {}): SessionListKeyState {
  return { pendingDeleteId: null, selectedId: "s1", ...over };
}

describe("session list keybinds", () => {
  it("maps ctrl+r/f and ctrl+shift+f; ctrl+d is disabled", () => {
    expect(applySessionListKey({ ctrl: true, name: "r" }, state()).action).toBe("rename");
    expect(applySessionListKey({ ctrl: true, name: "d" }, state()).action).toBe("none");
    expect(applySessionListKey({ ctrl: true, name: "d" }, state({ pendingDeleteId: "s1" })).action).toBe("none");
    expect(applySessionListKey({ ctrl: true, name: "f" }, state()).action).toBe("pin");
    expect(applySessionListKey({ ctrl: true, shift: true, name: "f" }, state()).action).toBe("fork");
    expect(applySessionListKey({ name: "escape" }, state()).action).toBe("close");
  });
  it("promoteSessionRow patches title and moves the row to front", () => {
    const rows = [
      { session_id: "a", display_title: "hi", age_label: "3h" },
      { session_id: "b", display_title: "pdf", age_label: "now" },
    ];
    const next = promoteSessionRow(rows, "b", { display_title: "renamed", age_label: "now" });
    expect(next[0]).toEqual({ session_id: "b", display_title: "renamed", age_label: "now" });
    expect(next[1]?.session_id).toBe("a");
  });
  it("ctrl+d does not trash", () => {
    const once = applySessionListKey({ ctrl: true, name: "d" }, state());
    expect(once.action).not.toBe("delete-confirm");
    expect(once.action).not.toBe("delete-pending");
    expect(once.nextPendingDeleteId).toBe(null);
  });
});
