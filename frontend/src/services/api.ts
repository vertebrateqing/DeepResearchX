/**
 * API 服务层
 *
 * 负责前端和后端之间的所有通信。
 * 核心功能：通过 SSE (Server-Sent Events) 连接后端，实时接收分析数据。
 */

import type {
  DocumentDeleteResponse,
  DocumentListResponse,
  DocumentUploadResponse,
  StreamEvent,
} from '../types/api'

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
 * @param confirmedQuery 可选，用户在意图澄清卡片中确认的最终 prompt
 * @param documentIds 可选，限定研究只引用这些已上传文档
 */
export function createAnalysisStream(
  query: string,
  sessionId?: string,
  model?: string,
  confirmedQuery?: string,
  documentIds?: string[],
  documentsOnly?: boolean,
) {
  const params = new URLSearchParams()
  params.append('query', query)
  if (sessionId) {
    params.append('session_id', sessionId)
  }
  if (model) {
    params.append('model', model)
  }
  if (confirmedQuery) {
    params.append('confirmed_query', confirmedQuery)
  }
  if (documentIds && documentIds.length > 0) {
    documentIds.forEach((id) => params.append('document_ids', id))
  }
  if (documentsOnly) {
    params.append('documents_only', 'true')
  }

  const url = `${API_BASE_URL}/analyze/stream?${params.toString()}`
  const eventSource = new EventSource(url)

  let eventCallback: ((event: StreamEvent) => void) | null = null
  let errorCallback: ((error: Event) => void) | null = null
  // Track whether stream ended normally — suppress onerror after terminal events
  let completedNormally = false

  const TERMINAL_EVENTS = new Set<StreamEvent['event']>(['complete', 'error', 'clarification'])

  const eventTypes: StreamEvent['event'][] = [
    'connected', 'status', 'progress', 'thinking', 'tool_call',
    'tool_result', 'chapter', 'content', 'chart', 'sources',
    'error', 'complete', 'clarification',
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
        // Close EventSource on terminal events to prevent auto-reconnect
        if (TERMINAL_EVENTS.has(eventType)) {
          completedNormally = true
          eventSource.close()
        }
      } catch (err) {
        console.error(`解析 ${eventType} 事件失败:`, err)
      }
    })
  })

  eventSource.onerror = (error) => {
    // EventSource fires onerror on normal server-side close too — ignore if we
    // already received a terminal event (complete / clarification / error)
    if (completedNormally) return
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
      completedNormally = true
      eventSource.close()
    },
  }
}

// ---------------------------------------------------------------------------
// 文档上传 / RAG 管理
// ---------------------------------------------------------------------------

export async function uploadDocuments(
  files: File[],
  sessionId: string,
  chunkingStrategy = 'recursive',
  embeddingModel = '',
): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append('session_id', sessionId)
  formData.append('chunking_strategy', chunkingStrategy)
  if (embeddingModel) {
    formData.append('embedding_model', embeddingModel)
  }
  files.forEach((f) => formData.append('files', f))

  const res = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`上传失败 (${res.status}): ${text}`)
  }
  return res.json()
}

export async function listDocuments(sessionId: string): Promise<DocumentListResponse> {
  const res = await fetch(`${API_BASE_URL}/documents?session_id=${encodeURIComponent(sessionId)}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`查询失败 (${res.status}): ${text}`)
  }
  return res.json()
}

export async function deleteDocument(
  docId: string,
  sessionId: string,
): Promise<DocumentDeleteResponse> {
  const res = await fetch(
    `${API_BASE_URL}/documents/${encodeURIComponent(docId)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`删除失败 (${res.status}): ${text}`)
  }
  return res.json()
}
