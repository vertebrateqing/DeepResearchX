/**
 * API 服务层
 *
 * 负责前端和后端之间的所有通信。
 * 核心功能：通过 SSE (Server-Sent Events) 连接后端，实时接收分析数据。
 */

import type { StreamEvent } from '../types/api'

/** 后端 API 的基础地址 */
const API_BASE_URL = 'http://localhost:8000/api'

// ---------------------------------------------------------------------------
// SSE 连接管理
// ---------------------------------------------------------------------------

/**
 * 创建分析任务的 SSE 流式连接
 *
 * @param query 用户的查询
 * @param sessionId 可选，已有会话 ID（多轮对话时传递）
 * @param model 可选，指定 LLM 模型
 */
export function createAnalysisStream(query: string, sessionId?: string, model?: string) {
  const params = new URLSearchParams()
  params.append('query', query)
  if (sessionId) {
    params.append('session_id', sessionId)
  }
  if (model) {
    params.append('model', model)
  }

  const url = `${API_BASE_URL}/analyze/stream?${params.toString()}`
  const eventSource = new EventSource(url)

  let eventCallback: ((event: StreamEvent) => void) | null = null
  let errorCallback: ((error: Event) => void) | null = null

  const eventTypes: StreamEvent['event'][] = [
    'connected', 'status', 'progress', 'thinking', 'tool_call',
    'tool_result', 'chapter', 'content', 'chart', 'sources',
    'error', 'complete',
  ]

  eventTypes.forEach((eventType) => {
    eventSource.addEventListener(eventType, (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        const event: StreamEvent = {
          event: eventType,
          data,
          timestamp: new Date().toISOString(),
        }
        if (eventCallback) {
          eventCallback(event)
        }
      } catch (err) {
        console.error(`解析 ${eventType} 事件失败:`, err)
      }
    })
  })

  eventSource.onerror = (error) => {
    console.error('SSE 连接错误:', error)
    if (errorCallback) {
      errorCallback(error)
    }
  }

  return {
    onEvent(callback: (event: StreamEvent) => void) {
      eventCallback = callback
    },
    onError(callback: (error: Event) => void) {
      errorCallback = callback
    },
    close() {
      eventSource.close()
    },
  }
}
