/**
 * App 组件 —— 主应用容器
 *
 * 布局：左右分栏
 * - 左侧边栏：会话列表（新建对话、历史记录）
 * - 右侧主区域：消息流 + 底部输入框
 *
 * 支持多轮对话：通过 session_id 让后端恢复会话上下文。
 */

import { useState, useRef, useCallback, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createAnalysisStream } from './services/api'
import type { StreamEvent, Conversation, Message, SourceItem } from './types/api'
import AnalysisProgress from './components/AnalysisProgress'
import SourceCards from './components/SourceCards'

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function generateSessionId(): string {
  return `sess_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}_${Date.now().toString(36)}`
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function truncate(str: string, len: number): string {
  return str.length > len ? str.slice(0, len) + '...' : str
}

// ---------------------------------------------------------------------------
// 组件
// ---------------------------------------------------------------------------

export default function App() {
  // ========================================================================
  // 状态
  // ========================================================================

  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const saved = localStorage.getItem('fdr_conversations')
    return saved ? JSON.parse(saved) : []
  })

  const [currentId, setCurrentId] = useState<string | null>(() => {
    const saved = localStorage.getItem('fdr_current_id')
    return saved || null
  })

  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const streamRef = useRef<ReturnType<typeof createAnalysisStream> | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const currentConversation = conversations.find((c) => c.id === currentId)

  // ========================================================================
  // 持久化到 localStorage
  // ========================================================================

  useEffect(() => {
    localStorage.setItem('fdr_conversations', JSON.stringify(conversations))
  }, [conversations])

  useEffect(() => {
    if (currentId) localStorage.setItem('fdr_current_id', currentId)
  }, [currentId])

  // ========================================================================
  // 自动滚动到底部
  // ========================================================================

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [currentConversation?.messages])

  // ========================================================================
  // 新建对话
  // ========================================================================

  const createNewConversation = useCallback(() => {
    const newConv: Conversation = {
      id: generateId(),
      title: '新对话',
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      sessionId: generateSessionId(),
    }
    setConversations((prev) => [newConv, ...prev])
    setCurrentId(newConv.id)
    setInput('')
    // 移动端自动收起侧边栏
    if (window.innerWidth < 768) setSidebarOpen(false)
  }, [])

  // ========================================================================
  // 删除对话
  // ========================================================================

  const deleteConversation = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setConversations((prev) => prev.filter((c) => c.id !== id))
    if (currentId === id) {
      const remaining = conversations.filter((c) => c.id !== id)
      setCurrentId(remaining.length > 0 ? remaining[0].id : null)
    }
  }, [currentId, conversations])

  // ========================================================================
  // 发送消息
  // ========================================================================

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return

    // 确保有当前会话
    let convId = currentId
    let sessionId = currentConversation?.sessionId

    if (!convId) {
      const newConv: Conversation = {
        id: generateId(),
        title: truncate(trimmed, 20),
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        sessionId: generateSessionId(),
      }
      setConversations((prev) => [newConv, ...prev])
      setCurrentId(newConv.id)
      convId = newConv.id
      sessionId = newConv.sessionId
    }

    // 添加用户消息
    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content: trimmed,
      status: 'done',
      createdAt: new Date().toISOString(),
      sessionId,
    }

    // 添加 AI 占位消息（pending 状态）
    const assistantMsg: Message = {
      id: generateId(),
      role: 'assistant',
      content: '',
      status: 'pending',
      createdAt: new Date().toISOString(),
      sessionId,
      stage: 'intent',
      progress: 5,
      sources: [],
    }

    const targetId = convId

    setConversations((prev) =>
      prev.map((c) =>
        c.id === targetId
          ? {
              ...c,
              title: c.messages.length === 0 ? truncate(trimmed, 20) : c.title,
              messages: [...c.messages, userMsg, assistantMsg],
              updatedAt: new Date().toISOString(),
            }
          : c,
      ),
    )

    setInput('')
    setIsStreaming(true)

    // 关闭之前的连接
    if (streamRef.current) {
      streamRef.current.close()
    }

    // 创建 SSE 连接
    const stream = createAnalysisStream(trimmed, sessionId)
    streamRef.current = stream

    let assistantContent = ''

    // 辅助函数：更新当前 assistant 消息的属性
    const updateAssistantMsg = (updates: Partial<Message>) => {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === targetId
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === assistantMsg.id ? { ...m, ...updates } : m,
                ),
              }
            : c,
        ),
      )
    }

    stream.onEvent((event: StreamEvent) => {
      switch (event.event) {
        case 'connected':
          break

        case 'status':
          updateAssistantMsg({
            status: 'streaming',
            thinking: event.data.message || '',
            stage: event.data.stage || 'intent',
            progress: event.data.progress,
          })
          break

        case 'thinking':
          updateAssistantMsg({ thinking: event.data.message || '' })
          break

        case 'tool_call':
          updateAssistantMsg({
            thinking: `调用 ${event.data.tool || '工具'}...`,
          })
          break

        case 'content':
          assistantContent += event.data.text || ''
          updateAssistantMsg({ content: assistantContent, status: 'streaming' })
          break

        case 'sources': {
          const newSource: SourceItem = {
            title: event.data.title || '未命名来源',
            url: event.data.url || '',
            chapter: event.data.chapter,
          }
          setConversations((prev) =>
            prev.map((c) =>
              c.id === targetId
                ? {
                    ...c,
                    messages: c.messages.map((m) =>
                      m.id === assistantMsg.id
                        ? { ...m, sources: [...(m.sources || []), newSource] }
                        : m,
                    ),
                  }
                : c,
            ),
          )
          break
        }

        case 'error':
          updateAssistantMsg({
            status: 'error',
            error: event.data.message || '分析出错',
          })
          setIsStreaming(false)
          if (streamRef.current) {
            streamRef.current.close()
            streamRef.current = null
          }
          break

        case 'complete':
          updateAssistantMsg({
            content: assistantContent,
            status: 'done',
          })
          setIsStreaming(false)
          if (streamRef.current) {
            streamRef.current.close()
            streamRef.current = null
          }
          break
      }
    })

    stream.onError(() => {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === targetId
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === assistantMsg.id
                    ? {
                        ...m,
                        status: 'error',
                        error: '连接后端服务失败，请检查后端是否运行',
                        thinking: assistantThinking,
                      }
                    : m,
                ),
              }
            : c,
        ),
      )
      setIsStreaming(false)
    })
  }, [input, isStreaming, currentId, currentConversation])

  // ========================================================================
  // 键盘快捷键：Enter 发送，Shift+Enter 换行
  // ========================================================================

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // ========================================================================
  // 渲染
  // ========================================================================

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: 'var(--bg-base)',
        fontFamily: 'var(--font-body)',
        overflow: 'hidden',
      }}
    >
      {/* =====================================================================
          左侧边栏
         ===================================================================== */}
      <aside
        style={{
          width: sidebarOpen ? 260 : 0,
          minWidth: sidebarOpen ? 260 : 0,
          background: 'var(--bg-sidebar)',
          borderRight: '1px solid var(--border-subtle)',
          display: 'flex',
          flexDirection: 'column',
          transition: 'width 0.3s ease, min-width 0.3s ease',
          overflow: 'hidden',
        }}
      >
        {/* 顶部：Logo + 新建按钮 */}
        <div
          style={{
            padding: '20px 16px 12px',
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 12,
            }}
          >
            <h1
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: '1.35rem',
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              DeepResearch
            </h1>
          </div>
          <button
            onClick={createNewConversation}
            style={{
              width: '100%',
              padding: '10px 14px',
              borderRadius: 'var(--radius-md)',
              border: '1.5px solid var(--border-medium)',
              background: 'var(--bg-surface)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-body)',
              fontSize: '0.9rem',
              fontWeight: 500,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent-primary)'
              e.currentTarget.style.background = 'var(--bg-surface-elevated)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border-medium)'
              e.currentTarget.style.background = 'var(--bg-surface)'
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            新建对话
          </button>
        </div>

        {/* 会话列表 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '8px 10px',
          }}
        >
          {conversations.length === 0 && (
            <p
              style={{
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: '0.85rem',
                padding: '20px 10px',
              }}
            >
              暂无历史对话
            </p>
          )}
          {conversations.map((conv) => {
            const isActive = conv.id === currentId
            return (
              <div
                key={conv.id}
                onClick={() => {
                  setCurrentId(conv.id)
                  if (window.innerWidth < 768) setSidebarOpen(false)
                }}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  marginBottom: 4,
                  background: isActive ? 'var(--bg-surface)' : 'transparent',
                  border: isActive ? '1px solid var(--border-medium)' : '1px solid transparent',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'var(--bg-surface-elevated)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent'
                  }
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 8,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.85rem',
                        fontWeight: isActive ? 600 : 500,
                        color: 'var(--text-primary)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {conv.title}
                    </p>
                    <p
                      style={{
                        margin: '2px 0 0',
                        fontSize: '0.75rem',
                        color: 'var(--text-tertiary)',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {conv.messages.length} 条消息 · {new Date(conv.updatedAt).toLocaleDateString('zh-CN')}
                    </p>
                  </div>
                  <button
                    onClick={(e) => deleteConversation(conv.id, e)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      padding: 4,
                      borderRadius: 4,
                      opacity: 0,
                      transition: 'opacity 0.15s ease',
                      flexShrink: 0,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = '#ef4444'
                      e.currentTarget.style.background = '#fef2f2'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = 'var(--text-muted)'
                      e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </aside>

      {/* =====================================================================
          右侧主区域
         ===================================================================== */}
      <main
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
          position: 'relative',
        }}
      >
        {/* 顶部工具栏 */}
        <header
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 20px',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-surface)',
            flexShrink: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                padding: 6,
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <span
              style={{
                fontSize: '0.9rem',
                color: 'var(--text-secondary)',
                fontWeight: 500,
              }}
            >
              {currentConversation?.title || 'Financial DeepResearch'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: isStreaming ? 'var(--accent-secondary)' : 'var(--accent-primary)',
                transition: 'background 0.3s ease',
              }}
            />
            <span
              style={{
                fontSize: '0.8rem',
                color: 'var(--text-tertiary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {isStreaming ? '分析中' : '就绪'}
            </span>
          </div>
        </header>

        {/* 消息流区域 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px 0',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {!currentConversation || currentConversation.messages.length === 0 ? (
            /* 空状态 */
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 40,
                animation: 'fade-in 0.6s ease forwards',
              }}
            >
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: 'var(--radius-lg)',
                  background: 'var(--bg-surface)',
                  border: '1.5px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: 24,
                  boxShadow: 'var(--shadow-sm)',
                }}
              >
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent-primary)" strokeWidth="1.5">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <h2
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: '1.75rem',
                  fontWeight: 700,
                  color: 'var(--text-primary)',
                  margin: '0 0 8px',
                  letterSpacing: '-0.02em',
                }}
              >
                Financial DeepResearch
              </h2>
              <p
                style={{
                  color: 'var(--text-secondary)',
                  fontSize: '0.95rem',
                  maxWidth: 420,
                  textAlign: 'center',
                  lineHeight: 1.7,
                  margin: '0 0 32px',
                }}
              >
                基于多智能体架构的深度 A 股投资分析系统。
                输入股票代码或投资问题，AI 将为您生成专业级研究报告。
              </p>
              <div
                style={{
                  display: 'flex',
                  gap: 10,
                  flexWrap: 'wrap',
                  justifyContent: 'center',
                }}
              >
                {[
                  '贵州茅台值得长期持有吗？',
                  '分析 300750 宁德时代',
                  '半导体板块近期走势如何？',
                ].map((example) => (
                  <button
                    key={example}
                    onClick={() => {
                      setInput(example)
                      textareaRef.current?.focus()
                    }}
                    style={{
                      padding: '10px 16px',
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--border-subtle)',
                      background: 'var(--bg-surface)',
                      color: 'var(--text-secondary)',
                      fontSize: '0.85rem',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      fontFamily: 'var(--font-body)',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = 'var(--accent-primary)'
                      e.currentTarget.style.color = 'var(--accent-primary)'
                      e.currentTarget.style.background = 'var(--bg-surface-elevated)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = 'var(--border-subtle)'
                      e.currentTarget.style.color = 'var(--text-secondary)'
                      e.currentTarget.style.background = 'var(--bg-surface)'
                    }}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* 消息列表 */
            <div style={{ maxWidth: 800, width: '100%', margin: '0 auto', padding: '0 20px' }}>
              {currentConversation.messages.map((msg, index) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLast={index === currentConversation.messages.length - 1}
                />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* 底部输入框 */}
        <div
          style={{
            padding: '16px 20px 20px',
            background: 'var(--bg-surface)',
            borderTop: '1px solid var(--border-subtle)',
            flexShrink: 0,
          }}
        >
          <div
            style={{
              maxWidth: 800,
              margin: '0 auto',
              position: 'relative',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-end',
                gap: 10,
                border: '1.5px solid var(--border-medium)',
                borderRadius: 'var(--radius-lg)',
                padding: '12px 14px',
                background: 'var(--bg-surface-elevated)',
                transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
              }}
              className="input-container"
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  isStreaming
                    ? 'AI 正在分析，请稍候...'
                    : '输入投资分析问题，例如：腾讯最近值得买入吗？'
                }
                disabled={isStreaming}
                rows={Math.min(5, input.split('\n').length + 1)}
                style={{
                  flex: 1,
                  border: 'none',
                  outline: 'none',
                  background: 'transparent',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-body)',
                  fontSize: '0.95rem',
                  lineHeight: 1.6,
                  resize: 'none',
                  maxHeight: 160,
                  minHeight: 24,
                  padding: 0,
                }}
              />
              <button
                onClick={handleSubmit}
                disabled={isStreaming || !input.trim()}
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 'var(--radius-md)',
                  border: 'none',
                  background:
                    isStreaming || !input.trim()
                      ? 'var(--border-subtle)'
                      : 'var(--accent-primary)',
                  color:
                    isStreaming || !input.trim()
                      ? 'var(--text-muted)'
                      : '#fff',
                  cursor:
                    isStreaming || !input.trim() ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  transition: 'all 0.2s ease',
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
            <p
              style={{
                textAlign: 'center',
                fontSize: '0.75rem',
                color: 'var(--text-muted)',
                marginTop: 10,
                fontFamily: 'var(--font-mono)',
              }}
            >
              数据仅供参考，不构成投资建议 · Shift+Enter 换行
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// MessageBubble 组件
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  isLast,
}: {
  message: Message
  isLast: boolean
}) {
  const isUser = message.role === 'user'
  const [showThinking, setShowThinking] = useState(false)

  return (
    <div
      className="animate-message-enter"
      style={{
        display: 'flex',
        gap: 12,
        marginBottom: 24,
        justifyContent: isUser ? 'flex-end' : 'flex-start',
      }}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 'var(--radius-md)',
            background: 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            marginTop: 4,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
      )}

      {/* 消息内容 */}
      <div
        style={{
          maxWidth: '85%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: isUser ? 'flex-end' : 'flex-start',
        }}
      >
        {/* 气泡 */}
        <div
          style={{
            padding: isUser ? '12px 16px' : '0',
            borderRadius: isUser
              ? 'var(--radius-lg) var(--radius-lg) 4px var(--radius-lg)'
              : '0',
            background: isUser
              ? 'var(--accent-primary)'
              : 'transparent',
            color: isUser
              ? '#fff'
              : 'var(--text-primary)',
            fontSize: '0.95rem',
            lineHeight: 1.65,
            boxShadow: isUser ? 'var(--shadow-sm)' : 'none',
          }}
        >
          {isUser ? (
            <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span>
          ) : message.status === 'pending' || message.status === 'streaming' ? (
            /* 加载中 — 显示进度条和来源卡片 */
            <div
              style={{
                padding: '16px',
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                width: '100%',
              }}
            >
              <AnalysisProgress
                stage={message.stage || 'intent'}
                progress={message.progress}
              />
              <SourceCards sources={message.sources || []} />
              {message.content && (
                <div
                  style={{
                    marginTop: 12,
                    paddingTop: 12,
                    borderTop: '1px solid var(--border-subtle)',
                  }}
                >
                  <div className="report-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          ) : message.status === 'error' ? (
            /* 错误状态 */
            <div
              style={{
                padding: '12px 16px',
                background: '#fef2f2',
                borderRadius: 'var(--radius-md)',
                border: '1px solid #fecaca',
                color: '#b91c1c',
                fontSize: '0.9rem',
              }}
            >
              <strong>出错了：</strong>
              {message.error || '未知错误'}
            </div>
          ) : (
            /* 正常 Markdown 内容 */
            <div className="report-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content || '（无内容）'}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* 思考过程（可折叠） */}
        {!isUser && message.thinking && message.status !== 'pending' && (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => setShowThinking(!showThinking)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-tertiary)',
                fontSize: '0.8rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                fontFamily: 'var(--font-mono)',
                padding: '4px 8px',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                style={{
                  transform: showThinking ? 'rotate(90deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s ease',
                }}
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
              思考过程
            </button>
            {showThinking && (
              <div
                style={{
                  marginTop: 6,
                  padding: '10px 14px',
                  background: 'var(--bg-surface-elevated)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.8rem',
                  color: 'var(--text-tertiary)',
                  fontFamily: 'var(--font-mono)',
                  lineHeight: 1.5,
                  border: '1px solid var(--border-subtle)',
                }}
              >
                {message.thinking}
              </div>
            )}
          </div>
        )}

        {/* 数据来源卡片 */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <SourceCards sources={message.sources} />
        )}

        {/* 时间戳 */}
        <span
          style={{
            fontSize: '0.7rem',
            color: 'var(--text-muted)',
            marginTop: 4,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {formatTime(message.createdAt)}
        </span>
      </div>

      {/* 用户头像 */}
      {isUser && (
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 'var(--radius-md)',
            background: 'var(--accent-secondary-soft)',
            border: '1.5px solid var(--accent-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            marginTop: 4,
          }}
        >
          <span
            style={{
              fontSize: '0.85rem',
              fontWeight: 600,
              color: 'var(--accent-secondary)',
            }}
          >
            我
          </span>
        </div>
      )}
    </div>
  )
}
