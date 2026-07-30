/**
 * OpenTUI command catalog — copied from Ink frontend/src/types.ts AVAILABLE_COMMANDS
 * (do NOT import frontend/src at runtime — dual React versions).
 * Plus `/model` which the API supports but Ink palette listed as `__model` action.
 */

export interface Command {
  name: string;
  description: string;
  args?: string;
  category?: string;
  action?: string;
  keywords?: string;
}

export const AVAILABLE_COMMANDS: Command[] = [
  { name: "/session", description: "会话管理（查看/加载）", category: "会话", action: "session" },
  { name: "/save-chat", description: "保存当前对话", category: "会话" },
  { name: "/clear", description: "清除对话上下文", category: "会话", keywords: "new session 清除" },
  { name: "/model", description: "切换模型", args: "[name]", category: "Agent", action: "model", keywords: "switch model 模型" },
  { name: "/models", description: "列出所有模型", category: "Agent", action: "model" },
  { name: "/addmodel", description: "添加新模型", args: "", category: "Agent", action: "addmodel" },
  { name: "/plan", description: "进入规划模式", category: "Agent", keywords: "mode 模式" },
  { name: "/build", description: "进入构建模式", category: "Agent", keywords: "mode 模式" },
  { name: "/compose", description: "进入编排模式", category: "Agent", keywords: "mode 模式" },
  { name: "/thinking", description: "展开/折叠思考过程", category: "Agent", keywords: "think reason" },
  { name: "/memory add", description: "添加记忆", args: "<text>", category: "记忆" },
  { name: "/memory list", description: "列出所有记忆", category: "记忆", action: "memory" },
  { name: "/memory remove", description: "删除记忆", args: "<id>", category: "记忆" },
  { name: "/memory search", description: "搜索记忆", args: "<query>", category: "记忆" },
  { name: "/find-skill", description: "搜索并下载 skill", args: "<name>", category: "Skills" },
  { name: "/addskill", description: "从 URL 或名称安装 skill", args: "<name|url>", category: "Skills" },
  { name: "/list-skills", description: "列出已安装的 skills", category: "Skills", action: "skill" },
  { name: "/remove-skill", description: "删除已安装的 skill", args: "<name>", category: "Skills" },
  { name: "/addmcp", description: "添加 MCP 服务", args: "<name> <command> [args...]", category: "MCP" },
  { name: "/list-mcp", description: "列出已配置的 MCP 服务", category: "MCP", action: "mcp" },
  { name: "/remove-mcp", description: "删除 MCP 服务", args: "<name>", category: "MCP" },
  { name: "/queue", description: "任务队列", category: "系统", action: "queue" },
  { name: "/queue add", description: "添加任务", args: "<prompt>", category: "系统" },
  { name: "/cache", description: "缓存统计", category: "系统" },
  { name: "/language", description: "切换界面语言", args: "zh|en", category: "系统" },
  { name: "/settings", description: "打开设置窗口", category: "系统", action: "settings", keywords: "设置 权限" },
  { name: "/permission", description: "权限设置（三档审批）", args: "[confirm_all|auto_edit|full_auto]", category: "系统", action: "permission", keywords: "safety 安全 权限" },
  { name: "/schedule", description: "定时任务管理", category: "系统", action: "schedule" },
  { name: "/tutorial", description: "交互式教程", category: "系统", keywords: "help 帮助" },
  { name: "/quickstart", description: "快速入门指南", category: "系统", keywords: "help 帮助" },
  { name: "/examples", description: "使用示例", category: "系统", keywords: "help 帮助" },
  { name: "/help", description: "显示帮助信息", category: "系统", keywords: "help 帮助" },
];

/** Local-only commands handled without POST /command. */
export const LOCAL_COMMAND_NAMES = new Set([
  "/clear",
  "/build",
  "/plan",
  "/compose",
  "/thinking",
  "/help",
  "/settings",
]);

export function isSlashCommand(text: string): boolean {
  const trimmed = text.trim();
  return trimmed.startsWith("/") && /^\/[a-zA-Z]/.test(trimmed);
}

export function filterCommands(query: string, limit = 8): Command[] {
  const q = query.trim().toLowerCase();
  const needle = q.startsWith("/") ? q : `/${q}`;
  const scored = AVAILABLE_COMMANDS.map((cmd) => {
    const blob = `${cmd.name} ${cmd.description} ${cmd.keywords ?? ""}`.toLowerCase();
    const name = cmd.name.toLowerCase();
    let score = 0;
    if (!q || q === "/") score = 1;
    else if (name.startsWith(needle)) score = 3;
    else if (name.includes(needle) || blob.includes(q.replace(/^\//, ""))) score = 2;
    return { cmd, score };
  }).filter((x) => x.score > 0);
  scored.sort((a, b) => b.score - a.score || a.cmd.name.localeCompare(b.cmd.name));
  return scored.slice(0, limit).map((x) => x.cmd);
}
