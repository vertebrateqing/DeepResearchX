interface AnalysisProgressProps {
  stage: string
  progress?: number
}

const STAGE_PROGRESS: Record<string, number> = {
  intent: 5,
  outline: 15,
  chapters: 50,
  integration: 80,
  export: 95,
}

export default function AnalysisProgress({ stage, progress }: AnalysisProgressProps) {
  const displayProgress =
    progress !== undefined ? progress : (STAGE_PROGRESS[stage] ?? 10)

  return (
    <div style={{ marginBottom: 12 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontSize: '0.72rem',
            fontWeight: 600,
            color: 'var(--accent-primary)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {displayProgress}%
        </span>
      </div>
      <div
        style={{
          width: '100%',
          height: 3,
          background: 'var(--border-subtle)',
          borderRadius: 2,
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
