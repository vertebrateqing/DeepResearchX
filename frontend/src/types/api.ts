/**
 * TypeScript 类型定义文件
 *
 * 定义前端和后端之间的数据契约，以及前端内部使用的类型。
 */

// ---------------------------------------------------------------------------
// SSE 流式事件类型
// ---------------------------------------------------------------------------

export type StreamEventType =
  | 'connected'
  | 'status'
  | 'progress'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'chapter'
  | 'content'
  | 'chart'
  | 'sources'
  | 'error'
  | 'complete'
  | 'clarification'

export interface StreamEvent {
  event: StreamEventType
  data: Record<string, any>
  timestamp: string
}

// ---------------------------------------------------------------------------
// API 请求/响应类型
// ---------------------------------------------------------------------------

export interface AnalyzeRequest {
  query: string
  model?: string
  session_id?: string
}

export interface TaskResponse {
  task_id: string
  status: 'created' | 'queued'
  message: string
}

export interface TaskStatusResponse {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress?: number
  result?: Record<string, any>
  error?: string
  created_at: string
  updated_at?: string
}

// ---------------------------------------------------------------------------
// 对话消息类型
// ---------------------------------------------------------------------------

/**
 * 单条消息的角色
 * - 'user': 用户发送的消息
 * - 'assistant': AI 回复的消息
 */
export type MessageRole = 'user' | 'assistant'

/**
 * 消息状态
 * - 'pending': 等待 AI 回复
 * - 'streaming': 正在流式接收内容
 * - 'done': 已完成
 * - 'error': 出错
 */
export type MessageStatus = 'pending' | 'streaming' | 'done' | 'error'

/**
 * 单条消息
 */
export interface Message {
  /** 消息唯一 ID */
  id: string
  /** 消息角色 */
  role: MessageRole
  /** 消息内容（Markdown 格式） */
  content: string
  /** 消息状态 */
  status: MessageStatus
  /** 创建时间 */
  createdAt: string
  /** 关联的会话 ID */
  sessionId?: string
  /** 错误信息（仅 error 状态） */
  error?: string
  /** 数据来源（仅 assistant 消息） */
  sources?: SourceItem[]
  /** 思考过程（仅 assistant 消息，可选展示） */
  thinking?: string
  /** 当前分析阶段（仅 assistant 消息，流式时更新） */
  stage?: string
  /** 当前进度 0-100（仅 assistant 消息，流式时更新） */
  progress?: number
  /** 意图澄清数据（当后端需要用户确认 enriched_query 时） */
  clarification?: {
    question: string
    enrichedQuery: string
  }
}

/** 数据来源项 */
export interface SourceItem {
  title: string
  url: string
  chapter?: string
}

// ---------------------------------------------------------------------------
// 会话类型
// ---------------------------------------------------------------------------

/**
 * 一个完整的对话会话
 */
export interface Conversation {
  /** 会话唯一 ID */
  id: string
  /** 会话标题（取第一条用户消息的摘要） */
  title: string
  /** 会话中的所有消息 */
  messages: Message[]
  /** 创建时间 */
  createdAt: string
  /** 最后更新时间 */
  updatedAt: string
  /** 后端 session_id（用于多轮对话恢复上下文） */
  sessionId?: string
}
