import { FileSearch, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { CodeViewer } from './CodeViewer'
import type { EvidenceSnippet, FileContent, Selection } from '../lib/types'
import { cn } from '../lib/utils'

interface EvidencePanelProps {
  evidence: EvidenceSnippet[]
  selectedSnippetId: string | null
  onSelectSnippet: (snippet: EvidenceSnippet) => void
  file: FileContent | null
  loadingFile: boolean
  selection: Selection | null
  fileError: { message: string; code: string; hint?: string } | null
  onCloseFile: () => void
}

/**
 * Right panel: what was retrieved, and the actual source it points at.
 *
 * The panel separates two things that are easy to conflate: the snippets the
 * model was *given* (evidence), and the file contents the user is reading.
 */
export function EvidencePanel({
  evidence,
  selectedSnippetId,
  onSelectSnippet,
  file,
  loadingFile,
  selection,
  fileError,
  onCloseFile,
}: EvidencePanelProps) {
  const [tab, setTab] = useState<'evidence' | 'code'>('evidence')

  const openCodeTab = (snippet: EvidenceSnippet) => {
    onSelectSnippet(snippet)
    setTab('code')
  }

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-line bg-surface">
      <header className="border-b border-line">
        <div className="flex items-center gap-1 p-2.5">
          <button
            type="button"
            onClick={() => setTab('evidence')}
            className={cn(
              'flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors',
              tab === 'evidence' ? 'bg-brand/20 text-ink ring-1 ring-brand/40' : 'text-muted hover:bg-raised',
            )}
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Evidence
            <span className="text-muted/70">{evidence.length}</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('code')}
            className={cn(
              'flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors',
              tab === 'code' ? 'bg-brand/20 text-ink ring-1 ring-brand/40' : 'text-muted hover:bg-raised',
            )}
          >
            <FileSearch className="h-3.5 w-3.5" />
            Code
          </button>
        </div>
      </header>

      {tab === 'evidence' ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
          {evidence.length === 0 ? (
            <EmptyEvidence />
          ) : (
            <ul className="space-y-2">
              {evidence.map((snippet, index) => (
                <li key={snippet.citation_id}>
                  <button
                    type="button"
                    onClick={() => openCodeTab(snippet)}
                    aria-current={selectedSnippetId === snippet.citation_id ? 'true' : undefined}
                    className={cn(
                      'w-full rounded-xl border p-3 text-left transition-colors',
                      selectedSnippetId === snippet.citation_id
                        ? 'border-brand/60 bg-brand/10'
                        : 'border-line bg-raised hover:border-brand/40',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md bg-brand/25 text-[10px] font-bold text-glow">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <code className="block truncate font-mono text-[11px] text-glow">
                          {snippet.path}
                        </code>
                        <p className="mt-0.5 text-[11px] text-muted">
                          lines {snippet.start_line}–{snippet.end_line} · score{' '}
                          {snippet.score.toFixed(1)}
                        </p>
                      </div>
                    </div>

                    {snippet.symbol && (
                      <p className="mt-1.5 font-mono text-[11px] text-ink/80">{snippet.symbol}()</p>
                    )}

                    <p className="mt-1.5 text-[11px] italic text-muted">{snippet.reason}</p>

                    <pre className="mt-2 max-h-32 overflow-hidden whitespace-pre-wrap rounded-lg bg-code/70 p-2 font-mono text-[10.5px] leading-relaxed text-ink/85">
                      {snippet.code.split('\n').slice(0, 8).join('\n')}
                    </pre>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {file ? (
            <>
              <div className="flex items-center gap-2 border-b border-line px-3 py-2">
                <div className="min-w-0 flex-1">
                  <code className="block truncate font-mono text-[11px] text-glow" title={file.path}>
                    {file.path}
                  </code>
                  <p className="text-[10px] text-muted">
                    {file.language} · {file.line_count} lines ·{' '}
                    {file.parser === 'ast'
                      ? 'Python AST'
                      : file.parser === 'regex'
                        ? 'regex fallback'
                        : 'plain text'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={onCloseFile}
                  className="btn-ghost !px-2 !py-1 text-[11px]"
                >
                  Close
                </button>
              </div>

              {selection && selection.path === file.path && (
                <div className="flex items-center gap-1.5 border-b border-line bg-brand/10 px-3 py-1.5 text-[11px] text-glow">
                  <ShieldCheck className="h-3 w-3" />
                  Showing cited lines {selection.startLine}–{selection.endLine}
                </div>
              )}

              <div className="min-h-0 flex-1">
                {loadingFile ? (
                  <div className="grid h-full place-items-center text-xs text-muted">
                    Loading file…
                  </div>
                ) : (
                  <CodeViewer
                    lines={file.lines}
                    symbols={file.symbols}
                    showSymbols
                    highlight={
                      selection && selection.path === file.path
                        ? { start: selection.startLine, end: selection.endLine, nonce: selection.nonce }
                        : null
                    }
                  />
                )}
              </div>
            </>
          ) : (
            <div className="grid flex-1 place-items-center p-6 text-center">
              {fileError ? (
                <div className="text-sm">
                  <p className="font-semibold text-danger">{fileError.message}</p>
                  {fileError.hint && <p className="mt-1 text-xs text-muted">{fileError.hint}</p>}
                </div>
              ) : (
                <div className="space-y-2">
                  <FileSearch className="mx-auto h-7 w-7 text-muted/50" />
                  <p className="text-sm font-medium">No file open</p>
                  <p className="text-xs text-muted">
                    Pick a file in the project tree, or click a citation in an answer to jump
                    straight to the cited lines.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </aside>
  )
}

function EmptyEvidence() {
  return (
    <div className="grid h-full place-items-center p-6 text-center">
      <div className="space-y-2">
        <ShieldCheck className="mx-auto h-7 w-7 text-muted/50" />
        <p className="text-sm font-medium">No evidence yet</p>
        <p className="text-xs text-muted">
          Ask a question and the snippets selected for the answer will appear here — each with
          its real file path and line range.
        </p>
      </div>
    </div>
  )
}
