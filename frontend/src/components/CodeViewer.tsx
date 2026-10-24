import { useEffect, useMemo, useRef } from 'react'
import type { CodeLine, SymbolInfo } from '../lib/types'
import { cn } from '../lib/utils'

interface CodeViewerProps {
  lines: CodeLine[]
  /** Inclusive line range to emphasise (a clicked citation). */
  highlight?: { start: number; end: number; nonce: number } | null
  symbols?: SymbolInfo[]
  /** Show the file's symbol outline above the code. */
  showSymbols?: boolean
  emptyMessage?: string
}

/**
 * Read-only code viewer with exact line numbers.
 *
 * Line numbers come straight from the backend index, so a citation of
 * "auth/login.py:39-61" always lands on the same lines the model was shown.
 */
export function CodeViewer({
  lines,
  highlight,
  symbols = [],
  showSymbols = false,
  emptyMessage = 'No file selected.',
}: CodeViewerProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!highlight || !scrollRef.current) return
    const target = scrollRef.current.querySelector<HTMLElement>(
      `[data-line="${highlight.start}"]`,
    )
    if (target) {
      target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [highlight?.nonce, highlight?.start])

  const gutterWidth = useMemo(
    () => String(lines.length ? lines[lines.length - 1].number : 1).length,
    [lines],
  )

  if (!lines.length) {
    return (
      <div className="grid h-full place-items-center p-6 text-sm text-muted">{emptyMessage}</div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {showSymbols && symbols.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-line p-2.5">
          {symbols.slice(0, 24).map((s) => (
            <span key={`${s.name}-${s.start_line}`} className="chip font-mono">
              <span className="text-glow">{s.kind === 'class' ? 'C' : s.kind === 'method' ? 'M' : 'ƒ'}</span>
              {s.name}
              <span className="text-muted/70">:{s.start_line}</span>
            </span>
          ))}
        </div>
      )}

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto font-mono text-[12.5px] leading-[1.65]"
      >
        {/* A flex row per line wraps long code cleanly; a table would let the
            content column push the layout wider than the panel. */}
        <div className="min-w-full">
          {lines.map((line) => {
            const inRange =
              highlight && line.number >= highlight.start && line.number <= highlight.end
            const isStart = highlight && line.number === highlight.start
            return (
              <div
                key={line.number}
                data-line={line.number}
                className={cn(
                  'flex items-start',
                  inRange && 'bg-brand/15',
                  isStart && 'border-l-2 border-glow',
                )}
              >
                <span
                  className={cn(
                    'shrink-0 select-none whitespace-nowrap py-px pr-2 pl-3 text-right tabular-nums',
                    inRange ? 'text-glow' : 'text-muted/60',
                  )}
                  style={{ width: `${gutterWidth + 2}ch` }}
                >
                  {line.number}
                </span>
                <span className="min-w-0 flex-1 whitespace-pre-wrap [overflow-wrap:anywhere] py-px pr-3 text-ink/95">
                  {line.text || '\u00A0'}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
