import { AlertTriangle, Check, Copy, FileCode2, HelpCircle, Link2, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Markdown } from './Markdown'
import type { AskResponse, Citation } from '../lib/types'
import { answerToMarkdown, cn, copyText } from '../lib/utils'

interface AnswerCardProps {
  response: AskResponse
  onOpenCitation: (citation: { path: string; startLine: number; endLine: number }) => void
  onFollowup: (question: string) => void
}

/** Renders one evidence-backed answer, clearly separating model text from source. */
export function AnswerCard({ response, onOpenCitation, onFollowup }: AnswerCardProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const ok = await copyText(answerToMarkdown(response))
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    }
  }

  const openCitation = (c: Citation) =>
    onOpenCitation({ path: c.path, startLine: c.start_line, endLine: c.end_line })

  return (
    <article className="animate-fade-up space-y-3">
      {/* Direct answer — or, when nothing could be grounded, a way forward */}
      {response.sarvam_called ? (
        <div className="panel p-4">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="chip">
              <FileCode2 className="h-3 w-3" />
              AI interpretation
            </span>
            <button
              type="button"
              onClick={handleCopy}
              className="btn-ghost !px-2 !py-1 text-xs"
              aria-label="Copy answer"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>

          {response.answer ? (
            <Markdown>{response.answer}</Markdown>
          ) : (
            <p className="text-sm text-muted">
              The model returned no readable answer for this question.
            </p>
          )}
        </div>
      ) : (
        <NoEvidenceCard response={response} onFollowup={onFollowup} />
      )}

      {/* Steps */}
      {response.steps.length > 0 && (
        <section className="panel p-4">
          <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-muted">
            Step by step
          </h4>
          <ol className="space-y-2.5">
            {response.steps.map((step, i) => (
              <li key={`${step.title}-${i}`} className="flex gap-3">
                <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand/25 text-[11px] font-bold text-glow">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  {step.title && <p className="text-sm font-semibold">{step.title}</p>}
                  <p className={cn('text-sm leading-relaxed text-muted', step.title && 'mt-0.5')}>
                    {step.detail}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Key files */}
      {response.key_files.length > 0 && (
        <section className="panel p-4">
          <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-muted">
            Relevant files &amp; functions
          </h4>
          <ul className="space-y-1.5">
            {response.key_files.map((file, i) => (
              <li
                key={`${file.path}-${i}`}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg bg-raised px-2.5 py-2 text-xs"
              >
                <code className="font-mono text-glow">{file.path}</code>
                {file.symbol && <code className="font-mono text-ink">{file.symbol}()</code>}
                <span className="text-muted">{file.role}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Verified citations — only meaningful once the model was actually
          called. When it was not, NoEvidenceCard above already explains why. */}
      {response.sarvam_called && (
      <section className="panel p-4">
        <h4 className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
          <ShieldAlert className="h-3.5 w-3.5 text-success" />
          Verified source evidence
          <span className="font-normal normal-case text-muted/70">
            ({response.citations.length})
          </span>
        </h4>

        {response.citations.length === 0 ? (
          <p className="text-xs text-muted">
            No citation in this answer could be verified against the repository, so none is
            shown as evidence. Treat the explanation above as an interpretation only.
          </p>
        ) : (
          <ul className="space-y-2">
            {response.citations.map((c) => (
              <li key={c.citation_id}>
                <button
                  type="button"
                  onClick={() => openCitation(c)}
                  className="w-full rounded-xl border border-line bg-raised p-3 text-left transition-colors hover:border-brand/50 hover:bg-brand/10"
                >
                  <div className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                    <code className="truncate font-mono text-xs text-glow">{c.path}</code>
                    <span className="ml-auto shrink-0 text-[11px] text-muted">
                      L{c.start_line}–{c.end_line}
                    </span>
                  </div>
                  {c.quote && (
                    <pre className="mt-2 max-h-24 overflow-hidden whitespace-pre-wrap rounded-lg bg-code/60 p-2 font-mono text-[11px] leading-relaxed text-ink/90">
                      {c.quote}
                    </pre>
                  )}
                  {c.note && <p className="mt-1.5 text-[11px] text-muted">{c.note}</p>}
                  <span className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-glow">
                    <Link2 className="h-3 w-3" />
                    Open in code viewer
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      )}

      {/* Rejected citations — shown for honesty, never as evidence */}
      {response.rejected_citations.length > 0 && (
        <section className="panel border-danger/40 p-4">
          <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-danger">
            <AlertTriangle className="h-3.5 w-3.5" />
            Unverified citations discarded
          </h4>
          <p className="mb-2 text-[11px] text-muted">
            The model referenced these, but they do not match this repository. They are not
            shown as evidence.
          </p>
          <ul className="space-y-1.5">
            {response.rejected_citations.map((c) => (
              <li key={c.citation_id} className="rounded-lg bg-raised px-2.5 py-2 text-[11px]">
                <code className="font-mono text-ink">
                  {c.path}:{c.start_line}-{c.end_line}
                </code>
                <span className="ml-2 text-muted">{c.rejection_reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Uncertainty — already stated by NoEvidenceCard when nothing was sent */}
      {response.sarvam_called && response.uncertainty && (
        <section className="rounded-xl border border-warn/40 bg-warn/10 p-3.5">
          <h4 className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-warn">
            <HelpCircle className="h-3.5 w-3.5" />
            Uncertainty / missing evidence
          </h4>
          <p className="text-xs leading-relaxed text-ink">{response.uncertainty}</p>
        </section>
      )}

      {/* Provenance footer */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11px] text-muted">
        <span>
          Model: <span className="font-mono text-ink/80">{response.model ?? 'not called'}</span>
        </span>
        <span>
          Evidence: <span className="font-mono text-ink/80">{response.evidence.length}</span> snippet
          {response.evidence.length === 1 ? '' : 's'}
        </span>
        {response.usage?.total_tokens != null && (
          <span>
            Tokens: <span className="font-mono text-ink/80">{response.usage.total_tokens}</span>
          </span>
        )}
        <span className={cn('font-medium', response.structured ? 'text-success' : 'text-warn')}>
          {!response.sarvam_called
            ? 'Not sent to the model'
            : response.structured
              ? 'Structured output verified'
              : 'Unstructured output'}
        </span>
      </div>

      {/* Follow-ups */}
      {response.followups.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {response.followups.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onFollowup(q)}
              className="chip transition-colors hover:border-brand/50 hover:text-ink"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </article>
  )
}

/**
 * Shown when the question could not be grounded in any code.
 *
 * An empty "AI interpretation" panel reads like a model failure, but in this
 * state nothing was sent to the model at all — the wording named no symbol.
 * Saying that plainly, and offering clickable starting points taken from the
 * repository's own symbols, is more useful than a dead end.
 */
function NoEvidenceCard({
  response,
  onFollowup,
}: {
  response: AskResponse
  onFollowup: (question: string) => void
}) {
  const suggestions = response.suggestions ?? []

  return (
    <section className="panel border-warn/40 p-4">
      <div className="flex items-center gap-2">
        <HelpCircle className="h-4 w-4 text-warn" />
        <h4 className="text-sm font-semibold">I need something more specific</h4>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">
        {response.uncertainty || 'That question did not match any code in this project.'}
      </p>

      {suggestions.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            Ask about something in this project
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s.question}
                type="button"
                onClick={() => onFollowup(s.question)}
                className="chip transition-colors hover:border-brand/50 hover:text-ink"
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
