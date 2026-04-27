/**
 * 分析进度条组件
 *
 * 显示5个分析阶段的视觉进度，配合当前 stage 高亮对应步骤。
 */

interface AnalysisProgressProps {
  stage: string
  progress?: number
}

const STAGES = [
  { key: 'intent', label: '理解问题', description: '解析投资意图' },
  { key: 'outline', label: '规划结构', description: '生成报告大纲' },
  { key: 'chapters', label: '并行分析', description: '多章节深度研究' },
  { key: 'integration', label: '整合审校', description: '合并与质量审核' },
  { key: 'export', label: '生成报告', description: '输出最终报告' },
]

export default function AnalysisProgress({ stage, progress }: AnalysisProgressProps) {
  const currentIndex = STAGES.findIndex((s) => s.key === stage)
  const activeIndex = currentIndex >= 0 ? currentIndex : 0
  const displayProgress = progress !== undefined ? progress : Math.round(((activeIndex + 0.5) / STAGES.length) * 100)

  return (
    <div
      style={{
        padding: '14px 16px',
        background: 'var(--bg-surface-elevated)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
        marginBottom: 12,
      }}
    >
      {/* 步骤条 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          marginBottom: 10,
        }}
      >
        {STAGES.map((s, i) => {
          const isActive = i === activeIndex
          const isCompleted = i < activeIndex
          const isPending = i > activeIndex

          return (
            <div key={s.key} style={{ display: 'flex', alignItems: 'center', flex: 1, gap: 4 }}>
              {/* 步骤圆圈 */}
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.7rem',
                  fontWeight: 700,
                  flexShrink: 0,
                  transition: 'all 0.3s ease',
                  background: isCompleted
                    ? 'var(--accent-primary)'
                    : isActive
                      ? 'var(--accent-primary)'
                      : 'var(--bg-surface)',
                  color: isCompleted || isActive ? '#fff' : 'var(--text-muted)',
                  border:
                    isPending
                      ? '1.5px solid var(--border-medium)'
                      : '1.5px solid var(--accent-primary)',
                  boxShadow: isActive ? '0 0 0 3px var(--accent-primary-soft)' : 'none',
                }}
              >
                {isCompleted ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>

              {/* 连接线 */}
              {i < STAGES.length - 1 && (
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    borderRadius: 1,
                    background: isCompleted ? 'var(--accent-primary)' : 'var(--border-subtle)',
                    transition: 'background 0.3s ease',
                  }}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* 步骤标签 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        {STAGES.map((s, i) => (
          <div
            key={s.key}
            style={{
              flex: 1,
              textAlign: i === 0 ? 'left' : i === STAGES.length - 1 ? 'right' : 'center',
            }}
          >
            <span
              style={{
                fontSize: '0.7rem',
                fontWeight: i === activeIndex ? 600 : 400,
                color: i <= activeIndex ? 'var(--text-primary)' : 'var(--text-muted)',
                transition: 'color 0.3s ease',
              }}
            >
              {s.label}
            </span>
          </div>
        ))}
      </div>

      {/* 当前阶段描述 + 进度百分比 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
          }}
        >
          {STAGES[activeIndex]?.description || '分析中...'}
        </span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            color: 'var(--accent-primary)',
            fontFamily: 'var(--font-mono)',
            minWidth: 36,
            textAlign: 'right',
          }}
        >
          {displayProgress}%
        </span>
      </div>

      {/* 进度条 */}
      <div
        style={{
          width: '100%',
          height: 4,
          background: 'var(--border-subtle)',
          borderRadius: 2,
          marginTop: 8,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${displayProgress}%`,
            height: '100%',
            background: 'var(--accent-primary)',
            borderRadius: 2,
            transition: 'width 0.5s ease',
          }}
        />
      </div>
    </div>
  )
}
