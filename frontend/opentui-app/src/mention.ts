/** Parse a leading `@agent_id` mention from a user input line.
 *
 * Phase B C8: the frontend only extracts the mention; permission/session
 * creation stays on the backend (`agent/invoke`). Returns null when the
 * input does not start with a valid mention.
 */
export interface MentionParse {
  agentId: string;
  prompt: string;
}

export function parseMention(input: string): MentionParse | null {
  const m = input.match(/^\s*@([a-z0-9_-]+)\s*([\s\S]*)$/);
  if (!m) return null;
  return { agentId: m[1], prompt: m[2].trim() };
}
