/**
 * 数据来源卡片组件
 *
 * 以水平滚动卡片形式展示搜索到的数据来源，可点击跳转，支持折叠。
 */

import { useState } from 'react'
import type { SourceItem } from '../types/api'

interface SourceCardsProps {
  sources: SourceItem[]
}

export default function SourceCards({ sources }: SourceCardsProps) {
  const [collapsed, setCollapsed] = useState(false)

  if (!sources || sources.length === 0) return null

  const uniqueSources = sources.filter(
    (s, i, arr) => arr.findIndex((t) => t.url === s.url) === i
  )

  return (
    <div
      style={{
        marginTop: 10,
        background: 'var(--bg-surface-elevated)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
        overflow: 'hidden',
      }}
    >
      {/* 头部：标题 + 数量 + 折叠按钮 */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--text-secondary)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
            }}
          >
            数据来源
          </span>
          <span
            style={{
              fontSize: '0.7rem',
              padding: '2px 8px',
              background: 'var(--accent-primary-soft)',
              color: 'var(--accent-primary)',
              borderRadius: 10,
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {uniqueSources.length} 个来源
          </span>
        </div>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          style={{
            transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
            flexShrink: 0,
          }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* 卡片列表 */}
      {!collapsed && (
        <div
          style={{
            display: 'flex',
            gap: 10,
            padding: '0 14px 14px',
            overflowX: 'auto',
            scrollbarWidth: 'thin',
            scrollbarColor: 'var(--border-medium) transparent',
          }}
        >
          {uniqueSources.map((source, i) => (
            <a
              key={`${source.url}-${i}`}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                flexShrink: 0,
                width: 220,
                padding: '12px 14px',
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                textDecoration: 'none',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                transition: 'all 0.2s ease',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent-primary)'
                e.currentTarget.style.boxShadow = 'var(--shadow-sm)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-subtle)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              <span
                style={{
                  fontSize: '0.8rem',
                  fontWeight: 500,
                  color: 'var(--text-primary)',
                  lineHeight: 1.4,
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  wordBreak: 'break-word',
                }}
              >
                {source.title || '未命名来源'}
              </span>
              <span
                style={{
                  fontSize: '0.7rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {(() => {
                  try {
                    return new URL(source.url).hostname
                  } catch {
                    return source.url
                  }
                })()}
              </span>
              {source.chapter && (
                <span
                  style={{
                    fontSize: '0.65rem',
                    color: 'var(--accent-primary)',
                    fontWeight: 500,
                  }}
                >
                  {source.chapter}
                </span>
              )}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
