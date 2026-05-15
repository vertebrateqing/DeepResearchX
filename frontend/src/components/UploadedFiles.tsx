/**
 * UploadedFiles — Document knowledge base panel
 *
 * A refined editorial sidebar panel for managing uploaded research documents.
 * Features per-document selection, chunking strategy control, embedding model
 * selection, and a documents-only research toggle.
 *
 * Design language: warm paper tones, hairline borders, emerald accents,
 * precise typography. Matches the DeepResearchX editorial system.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadedDocument } from '../types/api'
import { listDocuments, deleteDocument } from '../services/api'

export type ChunkingStrategy = 'recursive' | 'fixed' | 'semantic'
export type EmbeddingModel = 'BAAI/bge-large-zh-v1.5' | 'BAAI/bge-small-zh-v1.5' | 'BAAI/bge-m3'

export interface RAGSettings {
  chunkingStrategy: ChunkingStrategy
  embeddingModel: EmbeddingModel
  documentsOnly: boolean
  selectedDocIds: string[]
}

interface Props {
  sessionId: string
  settings: RAGSettings
  onSettingsChange: (settings: RAGSettings) => void
}

const CHUNKING_LABELS: Record<ChunkingStrategy, string> = {
  recursive: '递归切分',
  fixed: '固定长度',
  semantic: '语义切分',
}

const CHUNKING_DESCRIPTIONS: Record<ChunkingStrategy, string> = {
  recursive: '按段落→句子→单词逐级切分，保留自然边界',
  fixed: '按固定字符长度切分，速度最快',
  semantic: '按段落和句子语义边界切分，保留完整语义',
}

const EMBEDDING_LABELS: Record<EmbeddingModel, string> = {
  'BAAI/bge-large-zh-v1.5': 'BGE-Large (高质量)',
  'BAAI/bge-small-zh-v1.5': 'BGE-Small (快速)',
  'BAAI/bge-m3': 'BGE-M3 (多语言)',
}

export default function UploadedFiles({ sessionId, settings, onSettingsChange }: Props) {
  const [docs, setDocs] = useState<UploadedDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [open, setOpen] = useState(true)
  const [showConfig, setShowConfig] = useState(false)
  const [hoveredStrategy, setHoveredStrategy] = useState<ChunkingStrategy | null>(null)
  const prevSessionId = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      const res = await listDocuments(sessionId)
      setDocs(res.documents)
      // Auto-select newly discovered docs
      const allIds = res.documents.map((d) => d.doc_id)
      const currentSelected = new Set(settings.selectedDocIds)
      const newSelected = allIds.filter((id) => currentSelected.has(id))
      if (newSelected.length !== settings.selectedDocIds.length || allIds.length !== newSelected.length) {
        onSettingsChange({ ...settings, selectedDocIds: newSelected.length > 0 ? newSelected : allIds })
      }
    } catch (e) {
      console.error('列出文档失败:', e)
    } finally {
      setLoading(false)
    }
  }, [sessionId, settings, onSettingsChange])

  useEffect(() => {
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
          const nextSelected = settings.selectedDocIds.filter((id) => id !== docId)
          onSettingsChange({ ...settings, selectedDocIds: nextSelected })
          return next
        })
      } catch (e) {
        console.error('删除文档失败:', e)
      } finally {
        setRemovingId(null)
      }
    },
    [sessionId, settings, onSettingsChange],
  )

  const toggleDoc = (docId: string) => {
    const selected = new Set(settings.selectedDocIds)
    if (selected.has(docId)) {
      selected.delete(docId)
    } else {
      selected.add(docId)
    }
    onSettingsChange({ ...settings, selectedDocIds: Array.from(selected) })
  }

  const selectAll = () => {
    onSettingsChange({ ...settings, selectedDocIds: docs.map((d) => d.doc_id) })
  }

  const deselectAll = () => {
    onSettingsChange({ ...settings, selectedDocIds: [] })
  }

  const updateSetting = <K extends keyof RAGSettings>(key: K, value: RAGSettings[K]) => {
    onSettingsChange({ ...settings, [key]: value })
  }

  const docIcon = (ext: string) => {
    const e = ext.toLowerCase()
    if (e === '.pdf') return '📄'
    if (e === '.docx' || e === '.doc') return '📝'
    return '📃'
  }

  return (
    <div
      style={{
        padding: '16px 16px 20px',
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-sidebar)',
      }}
    >
      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'none',
          border: 'none',
          color: 'var(--text-primary)',
          fontSize: '0.82rem',
          fontWeight: 600,
          cursor: 'pointer',
          padding: 0,
          fontFamily: 'var(--font-body)',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: '0.9rem' }}>📎</span>
          文档知识库
          {docs.length > 0 && (
            <span
              style={{
                fontSize: '0.7rem',
                fontWeight: 500,
                color: 'var(--text-muted)',
                background: 'var(--bg-surface)',
                padding: '1px 6px',
                borderRadius: 10,
                border: '1px solid var(--border-subtle)',
              }}
            >
              {docs.length}
            </span>
          )}
        </span>
        <span style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', color: 'var(--text-muted)' }}>
          ▾
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 12 }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
              <span
                style={{
                  width: 14,
                  height: 14,
                  border: '2px solid var(--border-medium)',
                  borderTopColor: 'var(--accent-primary)',
                  borderRadius: '50%',
                  animation: 'spin 0.8s linear infinite',
                  display: 'inline-block',
                }}
              />
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>加载文档列表…</span>
            </div>
          )}

          {/* Documents list */}
          {docs.length > 0 && (
            <div
              style={{
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                overflow: 'hidden',
                marginBottom: 12,
              }}
            >
              {/* List header */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 10px',
                  borderBottom: '1px solid var(--border-subtle)',
                  background: 'var(--bg-surface-elevated)',
                }}
              >
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 500 }}>
                  已选 {settings.selectedDocIds.length}/{docs.length}
                </span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={selectAll}
                    style={{
                      fontSize: '0.7rem',
                      color: 'var(--accent-primary)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontWeight: 500,
                      padding: 0,
                    }}
                  >
                    全选
                  </button>
                  <button
                    onClick={deselectAll}
                    style={{
                      fontSize: '0.7rem',
                      color: 'var(--text-muted)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                    }}
                  >
                    清空
                  </button>
                </div>
              </div>

              <ul style={{ listStyle: 'none', padding: 0, margin: 0, maxHeight: 180, overflowY: 'auto' }}>
                {docs.map((d) => {
                  const checked = settings.selectedDocIds.includes(d.doc_id)
                  return (
                    <li
                      key={d.doc_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '8px 10px',
                        fontSize: '0.78rem',
                        color: checked ? 'var(--text-primary)' : 'var(--text-muted)',
                        borderBottom: '1px solid var(--border-subtle)',
                        transition: 'background 0.15s ease',
                        cursor: 'pointer',
                      }}
                      onClick={() => toggleDoc(d.doc_id)}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--bg-surface-elevated)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent'
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {}}
                        style={{
                          width: 14,
                          height: 14,
                          accentColor: 'var(--accent-primary)',
                          cursor: 'pointer',
                          flexShrink: 0,
                        }}
                      />
                      <span style={{ flexShrink: 0 }}>{docIcon(d.extension)}</span>
                      <span
                        title={d.filename}
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          flex: 1,
                          fontWeight: checked ? 500 : 400,
                        }}
                      >
                        {d.filename}
                      </span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleRemove(d.doc_id)
                        }}
                        disabled={removingId === d.doc_id}
                        title="删除"
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          fontSize: '0.75rem',
                          opacity: removingId === d.doc_id ? 0.4 : 1,
                          flexShrink: 0,
                          padding: '2px 4px',
                          borderRadius: 4,
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
                        ✕
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {!docs.length && !loading && (
            <div
              style={{
                padding: '16px 12px',
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: '0.8rem',
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-md)',
                border: '1px dashed var(--border-medium)',
              }}
            >
              <div style={{ fontSize: '1.2rem', marginBottom: 6, opacity: 0.6 }}>📎</div>
              暂无上传文档
              <div style={{ fontSize: '0.72rem', marginTop: 4, opacity: 0.7 }}>拖拽或点击上传 PDF / Word / 文本</div>
            </div>
          )}

          {/* Configuration section */}
          <div
            style={{
              background: 'var(--bg-surface)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
              overflow: 'hidden',
            }}
          >
            <button
              onClick={() => setShowConfig((v) => !v)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 12px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
                fontSize: '0.78rem',
                fontWeight: 600,
                fontFamily: 'var(--font-body)',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 5 15.4a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                检索配置
              </span>
              <span style={{ transform: showConfig ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', color: 'var(--text-muted)' }}>
                ▾
              </span>
            </button>

            {showConfig && (
              <div style={{ padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Chunking strategy */}
                <div>
                  <label
                    style={{
                      display: 'block',
                      fontSize: '0.72rem',
                      color: 'var(--text-muted)',
                      fontWeight: 600,
                      marginBottom: 6,
                      letterSpacing: '0.03em',
                      textTransform: 'uppercase',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    切分策略
                  </label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {(['recursive', 'fixed', 'semantic'] as ChunkingStrategy[]).map((s) => (
                      <label
                        key={s}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 8,
                          padding: '6px 8px',
                          borderRadius: 'var(--radius-sm)',
                          cursor: 'pointer',
                          background:
                            settings.chunkingStrategy === s
                              ? 'rgba(6, 95, 70, 0.06)'
                              : 'transparent',
                          border:
                            settings.chunkingStrategy === s
                              ? '1px solid rgba(6, 95, 70, 0.2)'
                              : '1px solid transparent',
                          transition: 'all 0.15s ease',
                        }}
                        onMouseEnter={() => setHoveredStrategy(s)}
                        onMouseLeave={() => setHoveredStrategy(null)}
                      >
                        <input
                          type="radio"
                          name="chunking"
                          checked={settings.chunkingStrategy === s}
                          onChange={() => updateSetting('chunkingStrategy', s)}
                          style={{ marginTop: 2, accentColor: 'var(--accent-primary)', flexShrink: 0 }}
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: '0.78rem',
                              fontWeight: settings.chunkingStrategy === s ? 600 : 500,
                              color:
                                settings.chunkingStrategy === s
                                  ? 'var(--accent-primary)'
                                  : 'var(--text-secondary)',
                            }}
                          >
                            {CHUNKING_LABELS[s]}
                          </div>
                          {(settings.chunkingStrategy === s || hoveredStrategy === s) && (
                            <div
                              style={{
                                fontSize: '0.7rem',
                                color: 'var(--text-muted)',
                                marginTop: 2,
                                lineHeight: 1.4,
                              }}
                            >
                              {CHUNKING_DESCRIPTIONS[s]}
                            </div>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Embedding model */}
                <div>
                  <label
                    style={{
                      display: 'block',
                      fontSize: '0.72rem',
                      color: 'var(--text-muted)',
                      fontWeight: 600,
                      marginBottom: 6,
                      letterSpacing: '0.03em',
                      textTransform: 'uppercase',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    嵌入模型
                  </label>
                  <select
                    value={settings.embeddingModel}
                    onChange={(e) => updateSetting('embeddingModel', e.target.value as EmbeddingModel)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-medium)',
                      background: 'var(--bg-surface-elevated)',
                      color: 'var(--text-primary)',
                      fontSize: '0.78rem',
                      fontFamily: 'var(--font-body)',
                      outline: 'none',
                      cursor: 'pointer',
                    }}
                  >
                    {(Object.keys(EMBEDDING_LABELS) as EmbeddingModel[]).map((m) => (
                      <option key={m} value={m}>
                        {EMBEDDING_LABELS[m]}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Documents-only toggle */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-sm)',
                    background: settings.documentsOnly
                      ? 'rgba(6, 95, 70, 0.06)'
                      : 'var(--bg-surface-elevated)',
                    border: settings.documentsOnly
                      ? '1px solid rgba(6, 95, 70, 0.2)'
                      : '1px solid var(--border-subtle)',
                    transition: 'all 0.2s ease',
                    cursor: 'pointer',
                  }}
                  onClick={() => updateSetting('documentsOnly', !settings.documentsOnly)}
                >
                  <div>
                    <div
                      style={{
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        color: settings.documentsOnly
                          ? 'var(--accent-primary)'
                          : 'var(--text-secondary)',
                      }}
                    >
                      仅从已上传文档研究
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                      {settings.documentsOnly ? '禁用联网搜索' : '联网搜索 + 文档检索'}
                    </div>
                  </div>
                  <div
                    style={{
                      width: 34,
                      height: 20,
                      borderRadius: 10,
                      background: settings.documentsOnly ? 'var(--accent-primary)' : 'var(--border-medium)',
                      position: 'relative',
                      transition: 'background 0.25s ease',
                      flexShrink: 0,
                    }}
                  >
                    <div
                      style={{
                        width: 16,
                        height: 16,
                        borderRadius: '50%',
                        background: '#fff',
                        position: 'absolute',
                        top: 2,
                        left: settings.documentsOnly ? 16 : 2,
                        transition: 'left 0.25s cubic-bezier(0.22, 1, 0.36, 1)',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.15)',
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
