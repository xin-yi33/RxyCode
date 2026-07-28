import { C } from './theme.js';

export type Mode = 'build' | 'plan' | 'compose';

export type ToolStatus = 'running' | 'success' | 'error' | 'timeout' | 'cancelled';

export interface Message {
  version?: number;
  id: string;
  role: 'user' | 'assistant' | 'tool' | 'system' | 'thinking';
  content: string;
  timestamp: number;
  runId?: string;
  toolName?: string;
  toolArgs?: string;
  elapsed?: number;
  done?: boolean;
  // Tool execution metadata (P2-2: error transparency, P2-3: progress feedback)
  toolStatus?: ToolStatus;
  toolDuration?: number; // seconds
  toolExitCode?: number;
  toolStdout?: string; // full output preserved for rendering and export
  toolError?: string;
  // Step progress for thinking messages (P2-3)
  stepIndex?: number;
  stepTotal?: number;
  // Thinking panel is currently streaming reasoning -> render even if not done
  live?: boolean;
}

export interface StatusInfo {
  memory_mb: number;
  memory_pct: number;
  billing: number;
  cache_size: string;
  cache_rate: string;
  input_tokens: number;
  output_tokens: number;
  context_used_k?: number;
  context_max_k?: number;
  mode: Mode;
  model: string;
  language?: string;
}

export interface Command {
  name: string;
  description: string;
  args?: string;
  category?: string;
  action?: string;     // non-slash action: 'model', 'session', 'exit', etc.
  keywords?: string;   // extra search keywords
}

export const AVAILABLE_COMMANDS: Command[] = [
  // Session
  { name: '/session', description: '会话管理（查看/加载）', category: '会话', action: 'session' },
  { name: '/save-chat', description: '保存当前对话', category: '会话' },
  { name: '/clear', description: '清除对话上下文', category: '会话', keywords: 'new session 清除' },
  // Agent
  { name: '__model', description: '切换模型（可视化选择）', category: 'Agent', action: 'model', keywords: 'switch model 模型切换' },
  { name: '/addmodel', description: '添加新模型', args: '', category: 'Agent' },
  { name: '/models', description: '列出所有模型', category: 'Agent' },
  { name: '/plan', description: '进入规划模式', category: 'Agent', keywords: 'mode 模式' },
  { name: '/build', description: '进入构建模式', category: 'Agent', keywords: 'mode 模式' },
  { name: '/compose', description: '进入编排模式', category: 'Agent', keywords: 'mode 模式' },
  { name: '/thinking', description: '展开/折叠思考过程', category: 'Agent', keywords: 'think reason' },
  // Memory
  { name: '/memory add', description: '添加记忆', args: '<text>', category: '记忆' },
  { name: '/memory list', description: '列出所有记忆', category: '记忆', action: 'memory' },
  { name: '/memory remove', description: '删除记忆', args: '<id>', category: '记忆' },
  { name: '/memory search', description: '搜索记忆', args: '<query>', category: '记忆' },
  // Skills
  { name: '/find-skill', description: '搜索并下载 skill', args: '<name>', category: 'Skills' },
  { name: '/addskill', description: '从 URL 或名称安装 skill', args: '<name|url>', category: 'Skills' },
  { name: '/list-skills', description: '列出已安装的 skills', category: 'Skills', action: 'skill' },
  { name: '/remove-skill', description: '删除已安装的 skill', args: '<name>', category: 'Skills' },
  // MCP
  { name: '/addmcp', description: '添加 MCP 服务', args: '<name> <command> [args...]', category: 'MCP' },
  { name: '/list-mcp', description: '列出已配置的 MCP 服务', category: 'MCP', action: 'mcp' },
  { name: '/remove-mcp', description: '删除 MCP 服务', args: '<name>', category: 'MCP' },
  // System
  { name: '/queue', description: '任务队列', category: '系统', action: 'queue' },
  { name: '/queue add', description: '添加任务', args: '<prompt>', category: '系统' },
  { name: '/cache', description: '缓存统计', category: '系统' },
  { name: '/language', description: '切换界面语言', args: 'zh|en', category: '系统' },
  { name: '/schedule', description: '定时任务管理', category: '系统', action: 'schedule' },
  { name: '/tutorial', description: '交互式教程', category: '系统', keywords: 'help 帮助' },
  { name: '/quickstart', description: '快速入门指南', category: '系统', keywords: 'help 帮助' },
  { name: '/examples', description: '使用示例', category: '系统', keywords: 'help 帮助' },
  { name: '/help', description: '显示帮助信息', category: '系统', keywords: 'help 帮助' },
  { name: '__exit', description: '退出', category: '系统', action: 'exit', keywords: 'quit exit 退出' },
];

export const MODE_COLORS: Record<Mode, string> = {
  build: C.primary, // #FF69B4 hot pink border (classic UI)
  plan: C.green,
  compose: C.mauve,
};

export const MODE_LABELS: Record<Mode, string> = {
  build: 'Build',
  plan: 'Plan',
  compose: 'Compose',
};
