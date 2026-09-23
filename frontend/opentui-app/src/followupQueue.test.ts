import { describe, expect, test } from "bun:test";
import {
  enqueueFollowup,
  FOLLOWUP_LIMIT,
  previewFollowup,
  putBackFollowup,
  removeFollowup,
  takeFollowupById,
  takeNextFollowup,
} from "./followupQueue.ts";

describe("followupQueue", () => {
  test("enqueues trimmed text FIFO and ignores blanks", () => {
    let queue = enqueueFollowup([], "  first  ", "plan");
    queue = enqueueFollowup(queue, "second", "build");
    queue = enqueueFollowup(queue, "   ", "compose");
    expect(queue.map((row) => row.text)).toEqual(["first", "second"]);
    expect(queue.map((row) => row.mode)).toEqual(["plan", "build"]);
    expect(queue[0]?.id).toBeTruthy();
    const first = takeNextFollowup(queue);
    expect(first.item?.text).toBe("first");
    expect(first.remaining.map((row) => row.text)).toEqual(["second"]);
  });

  test("caps at FOLLOWUP_LIMIT", () => {
    let queue = enqueueFollowup([], "item-0", "build");
    for (let i = 1; i < FOLLOWUP_LIMIT + 3; i++) {
      queue = enqueueFollowup(queue, `item-${i}`, "build");
    }
    expect(queue).toHaveLength(FOLLOWUP_LIMIT);
    expect(queue[0]?.text).toBe("item-0");
    expect(queue.at(-1)?.text).toBe(`item-${FOLLOWUP_LIMIT - 1}`);
  });

  test("takeFollowupById pulls one item for send now / edit", () => {
    const seeded = enqueueFollowup(enqueueFollowup([], "first", "plan"), "second", "compose");
    const taken = takeFollowupById(seeded, seeded[1]!.id);
    expect(taken.item?.text).toBe("second");
    expect(taken.remaining.map((row) => row.text)).toEqual(["first"]);
  });

  test("removeFollowup deletes without sending", () => {
    const seeded = enqueueFollowup(enqueueFollowup([], "keep", "build"), "drop", "plan");
    const next = removeFollowup(seeded, seeded[1]!.id);
    expect(next.map((row) => row.text)).toEqual(["keep"]);
  });

  test("putBackFollowup restores a draft in front so a second edit keeps the first", () => {
    const first = enqueueFollowup([], "one", "build")[0]!;
    const second = enqueueFollowup([first], "two", "plan");
    const taken = takeFollowupById(second, first.id);
    const restored = putBackFollowup(taken.remaining, { ...first, text: "one edited" });
    expect(restored.map((row) => row.text)).toEqual(["one edited", "two"]);
    expect(restored[0]?.mode).toBe("build");
  });

  test("stamps the enqueue-time mode for later drain", () => {
    const queue = enqueueFollowup([], "queued in plan", "plan");
    expect(queue[0]?.mode).toBe("plan");
    const taken = takeNextFollowup(queue);
    expect(taken.item?.mode).toBe("plan");
  });

  test("previewFollowup collapses whitespace and truncates", () => {
    expect(previewFollowup("  hello   world  ")).toBe("hello world");
    expect(previewFollowup("abcdefghij", 6)).toBe("abcde…");
  });
});
