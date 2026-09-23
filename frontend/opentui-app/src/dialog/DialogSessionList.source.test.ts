/** layer=module FR-SS-4 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "bun:test";

describe("DialogSessionList data source", () => {
  it("does not call sendCommand /session or /load-chat", () => {
    const body = readFileSync(resolve(__dirname, "DialogSessionList.tsx"), "utf8");
    expect(body).not.toContain('sendCommand("/session")');
    expect(body).not.toContain("/load-chat");
    expect(body).toContain("sessions/list");
    expect(body).toContain("SESSION_RENAME_SUCCESS");
    expect(body).toContain("footerHintItems");
  });

  it("session-list footer keys are plain white text, not orange chips", () => {
    const select = readFileSync(resolve(__dirname, "DialogSelect.tsx"), "utf8");
    const footerBlock = select.slice(select.indexOf("footerHintItems?.length"));
    expect(footerBlock).toContain("{item.label}");
    expect(footerBlock).toContain("{item.keys}");
    expect(footerBlock).toContain("fg={C.text}");
    expect(footerBlock).not.toMatch(/item\.keys[\s\S]{0,80}SELECT_BG/);
  });
  it("rename prompt hides the native caret off-screen", () => {
    const prompt = readFileSync(resolve(__dirname, "DialogPrompt.tsx"), "utf8");
    expect(prompt).toContain("left: -10000");
    expect(prompt).not.toContain("left: 0");
  });
  it("keeps esc close", () => {
    expect(bodyIncludesEsc()).toBe(true);
  });
});

function bodyIncludesEsc(): boolean {
  const body = readFileSync(resolve(__dirname, "DialogSessionList.tsx"), "utf8");
  return body.includes("onClose") && body.includes("escape");
}
