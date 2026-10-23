export type ClipboardAttachment = {
  path: string;
  name?: string;
};

export const MAX_CLIPBOARD_ATTACHMENTS = 10;
export const MAX_CLIPBOARD_PATH_LENGTH = 4_096;
const MAX_CLIPBOARD_NAME_LENGTH = 512;

/** Strict all-or-none metadata sanitizer shared by helper results and replay. */
export function validateClipboardAttachments(value: unknown): ClipboardAttachment[] {
  if (!Array.isArray(value) || value.length > MAX_CLIPBOARD_ATTACHMENTS) {
    throw new Error(`附件列表必须是最多 ${MAX_CLIPBOARD_ATTACHMENTS} 项的数组`);
  }
  const attachments: ClipboardAttachment[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      throw new Error("剪贴板 helper 返回了无效附件项");
    }
    const item = raw as Record<string, unknown>;
    if (
      typeof item.path !== "string" ||
      !item.path.trim() ||
      item.path.length > MAX_CLIPBOARD_PATH_LENGTH ||
      item.path.includes("\0")
    ) {
      throw new Error("剪贴板 helper 返回了无效或过长的附件路径");
    }
    if (item.name !== undefined && item.name !== null && (typeof item.name !== "string" || item.name.length > MAX_CLIPBOARD_NAME_LENGTH)) {
      throw new Error("剪贴板 helper 返回了无效或过长的附件名称");
    }
    attachments.push({
      path: item.path,
      ...(typeof item.name === "string" && item.name.trim() ? { name: item.name } : {}),
    });
  }
  return attachments;
}
