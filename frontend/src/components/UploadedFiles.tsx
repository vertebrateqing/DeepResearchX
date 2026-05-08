/**
 * UploadedFiles 组件
 *
 * 在侧边栏展示当前会话的上传文档列表。
 * 支持刷新、删除，并提示用户可在分析时引用这些文档。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadedDocument } from '../types/api'
import { listDocuments, deleteDocument } from '../services/api'

interface Props {
  sessionId: string
  /**
   * 当文档列表发生增删时回调，通知父级更新已选中的 documentIds。
   */
  onDocumentsChange?: (docs: UploadedDocument[]) => void
}

export default function UploadedFiles({ sessionId, onDocumentsChange }: Props) {
  const [docs, setDocs] = useState<UploadedDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [open, setOpen] = useState(true)
  const prevSessionId = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      const res = await listDocuments(sessionId)
      setDocs(res.documents)
      if (onDocumentsChange) {
        onDocumentsChange(res.documents)
      }
    } catch (e) {
      console.error('列出文档失败:', e)
    } finally {
      setLoading(false)
    }
  }, [sessionId, onDocumentsChange])

  useEffect(() => {
    // 每次 sessionId 改变时重新拉取
    if (sessionId && sessionId !== prevSessionId.current) {
      prevSessionId.current = sessionId
      refresh()
    }
  }, [sessionId, refresh])

  const handleRemove = useCallback(
    async (docId: string) => {
      setRemovingId(docId)
      try {
        await deleteDocument(docId, sessionId)
        setDocs((prev) => {
          const next = prev.filter((d) => d.doc_id !== docId)
          if (onDocumentsChange) {
            onDocumentsChange(next)
          }
          return next
        })
      } catch (e) {
        console.error('删除文档失败:', e)
      } finally {
        setRemovingId(null)
      }
    },
    [sessionId, onDocumentsChange],
  )

  if (!docs.length && !loading) {
    return null
  }

  return (
    <div
      style={{
        padding: '16px 20px',
        borderTop: '1px solid var(--border-subtle)',
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'none',
          border: 'none',
          color: 'var(--text-secondary)',
          fontSize: '0.82rem',
          fontWeight: 600,
          cursor: 'pointer',
          padding: 0,
        }}
      >
        <span>
          📎 文档 ({docs.length})
        </span>
        <span style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
          ▾
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 8 }}>
          {loading && <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>加载中…</p>}
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {docs.map((d) => (
              <li
                key={d.doc_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: '0.78rem',
                  color: 'var(--text-secondary)',
                }}
              >
                <span
                  title={d.filename}
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                  }}
                >
                  {d.filename}
                </span>
                <button
                  onClick={() => handleRemove(d.doc_id)}
                  disabled={removingId === d.doc_id}
                  title="删除"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '0.78rem',
                    opacity: removingId === d.doc_id ? 0.4 : 1,
                  }}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 8 }}>
            发送消息时自动引用所有已上传文档。
          </p>
        </div>
      )}
    </div>
  )
}
