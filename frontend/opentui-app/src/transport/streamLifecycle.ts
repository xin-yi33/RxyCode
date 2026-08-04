/** Pure helpers for when the TUI should leave the Processing state. */

/** Clear Processing as soon as the turn's terminal stream event arrives. */
export function shouldClearStreamingOnNotify(method: string): boolean {
  return (
    method === "event/final" ||
    method === "event/done" ||
    method === "event/error"
  );
}
