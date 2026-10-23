// W9-F1/F2: ApiError code -> 中文文案. One module so auth pages, the
// composer, and future surfaces stay consistent.
import { ApiError } from "./client"

const CODE_TEXT: Record<string, string> = {
  INVALID_CREDENTIALS: "邮箱或密码错误",
  INVALID_INPUT: "输入内容有误",
  EMAIL_TAKEN: "该邮箱已注册",
  INVITE_INVALID: "邀请码无效或已用完",
  REGISTRATION_CLOSED: "暂未开放注册",
  RATE_LIMITED: "尝试过于频繁，请稍后再试",
  UNAUTHORIZED: "请先登录",
  FORBIDDEN: "没有权限执行此操作",
  SESSION_NOT_FOUND: "会话不存在",
  RUN_ACTIVE: "该会话已有任务在运行",
  REQUEST_CONFLICT: "请求与已提交的任务冲突",
  APPROVAL_STALE: "审批状态已变化，请刷新后重试",
  QUESTION_STALE: "问题已被处理",
  RUN_NOT_FOUND: "任务不存在",
  RUN_TERMINAL: "任务已结束",
  AUTH_PROVIDER_NOT_CONFIGURED: "该登录方式暂未配置",
  CURSOR_EXPIRED: "事件游标已过期，请刷新",
  RESET_INVALID: "重置链接无效或已过期，请重新发起",
  MODEL_NOT_FOUND: "模型不存在或已移除",
  MODEL_UNAVAILABLE: "该模型当前不可用（连接已变更）",
  BYOK_REQUIRED: "请先配置自己的 API Key",
  BYOK_UNAVAILABLE: "模型服务暂不可用",
  INVALID_BASE_URL: "接口地址无效（需 HTTPS 公网地址）",
  BILLABLE_TEST_NOT_CONFIRMED: "请先确认计费测试",
  CONNECTION_NOT_FOUND: "连接不存在",
  DEVICE_IN_USE: "该账号正在另一台设备上使用",
  UNAVAILABLE: "服务暂不可用",
}

const QUOTA_REASON_TEXT: Record<string, string> = {
  concurrency: "你已有任务在运行",
  queue: "排队人数已满，请稍后再试",
  task: "今日任务数已用完",
  token: "您没有额度了",
  upstream: "您没有额度了",
}

export function apiErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "QUOTA_EXCEEDED") {
      return QUOTA_REASON_TEXT[error.detail] ?? "额度不足"
    }
    return CODE_TEXT[error.code] ?? `请求失败（${error.code}）`
  }
  return "无法连接服务器"
}

// PRD §10：失败文案保留 request/error code 便于对账 —— “文案（CODE）”。
export function errorWithCode(error: unknown): string {
  if (error instanceof ApiError) {
    return `${apiErrorText(error)}（${error.code}）`
  }
  return apiErrorText(error)
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

export function isNetworkError(error: unknown): boolean {
  return !(error instanceof ApiError)
}
