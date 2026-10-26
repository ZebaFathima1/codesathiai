import { useEffect, useRef, useState } from 'react'
import {
  CornerDownLeft,
  FileCode2,
  Loader2,
  Lock,
  MessageSquareCode,
  Send,
  Sparkles,
  X,
} from 'lucide-react'
import { AnswerCard } from './AnswerCard'
import { ErrorBanner, InfoNote, WarnNote } from './Feedback'
import { Logo } from './Logo'
import type { ChatTurn, HealthStatus, LanguageCode, LanguageOption, ProjectSummary } from '../lib/types'
import { LANGUAGES } from '../lib/types'

interface ChatPanelProps {
  project: ProjectSummary | null
  health: HealthStatus | null
  turns: ChatTurn[]
  asking: boolean
  language: LanguageCode
  onLanguageChange: (code: LanguageCode) => void
  onAsk: (question: string) => void
  onRetry: (turnId: string) => void
  onOpenCitation: (c: { path: string; startLine: number; endLine: number }) => void
  onSelectEvidence: (turn: ChatTurn) => void
  onUploadClick: () => void
  onLoadSample: () => void
  onOpenSidebar?: () => void
  sessionError: { message: string; code: string; hint?: string } | null
  onDismissSessionError: () => void
  /** Asking requires an account; browsing does not. */
  signedIn: boolean
  onRequireAuth: () => void
  /** The file (or selection) an anaphoric question will be answered against. */
  focusLabel: string | null
  onClearFocus: () => void
}

const EXAMPLE_PROMPTS: { label: string; question: string; language: LanguageCode }[] = [
  { label: 'Explain the project architecture', question: 'Explain the project architecture.', language: 'en-IN' },
  { label: 'How does login work?', question: 'How does login work?', language: 'en-IN' },
  { label: 'Where is the database configured?', question: 'Where is the database configured?', language: 'en-IN' },
  { label: 'Explain this function in simple Telugu', question: 'Explain the login function in simple Telugu.', language: 'te-IN' },
]

/** Middle panel: the question box and the conversation for this session. */
export function ChatPanel({
  project,
  health,
  turns,
  asking,
  language,
  onLanguageChange,
  onAsk,
  onRetry,
  onOpenCitation,
  onSelectEvidence,
  onUploadClick,
  onLoadSample,
  onOpenSidebar,
  sessionError,
  onDismissSessionError,
  signedIn,
  onRequireAuth,
  focusLabel,
  onClearFocus,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [turns, asking])

  const submit = () => {
    const question = draft.trim()
    if (!question || asking || !project) return
    if (!signedIn) {
      onRequireAuth()
      return
    }
    onAsk(question)
    setDraft('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const sarvamReady = health?.sarvam.configured ?? false
  const activeLanguage = LANGUAGES.find((l) => l.code === language) ?? LANGUAGES[1]

  return (
    <section className="flex h-full min-h-0 flex-col bg-bg">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-3.5 py-2.5">
        {onOpenSidebar && (
          <button
            type="button"
            onClick={onOpenSidebar}
            className="btn-ghost !px-2 !py-1.5 text-xs lg:hidden"
            aria-label="Open project panel"
          >
            Files
          </button>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">
            {project ? project.name : 'Workspace'}
          </h2>
          <p className="truncate text-[11px] text-muted">
            {project
              ? `${project.stats.file_count} files · ${project.stats.total_lines} lines indexed`
              : 'Load a repository to begin'}
          </p>
        </div>

        <label className="flex items-center gap-2 text-xs text-muted">
          <span className="hidden sm:inline">Answer in</span>
          <select
            value={language}
            onChange={(e) => onLanguageChange(e.target.value as LanguageCode)}
            aria-label="Answer language"
            className="field !w-auto !py-1.5 text-xs"
          >
            {LANGUAGES.map((l: LanguageOption) => (
              <option key={l.code} value={l.code}>
                {l.label} — {l.native}
              </option>
            ))}
          </select>
        </label>
      </header>

      {sessionError && (
        <div className="p-3">
          <ErrorBanner error={sessionError} onDismiss={onDismissSessionError} />
        </div>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3.5 py-4 sm:px-5">
        {!project ? (
          <WelcomeState
            sarvamReady={sarvamReady}
            ephemeralStorage={health?.storage.ephemeral ?? false}
            onUploadClick={onUploadClick}
            onLoadSample={onLoadSample}
            signedIn={signedIn}
            onRequireAuth={onRequireAuth}
          />
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            {turns.length === 0 && (
              <div className="space-y-4">
                <div className="panel p-4">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-glow" />
                    <h3 className="text-sm font-semibold">Ask about this codebase</h3>
                  </div>
                  <p className="mt-1.5 text-sm text-muted">
                    Every answer is generated from the source files actually retrieved from your
                    repository, and each citation is checked against real file and line numbers
                    before it is shown.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {EXAMPLE_PROMPTS.map((p) => (
                      <button
                        key={p.label}
                        type="button"
                        onClick={() => {
                          onLanguageChange(p.language)
                          onAsk(p.question)
                        }}
                        disabled={asking || !sarvamReady || !signedIn}
                        className="chip transition-colors hover:border-brand/50 hover:text-ink disabled:opacity-50"
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
                {!signedIn && (
                  <SignInNote onRequireAuth={onRequireAuth} />
                )}
                {!sarvamReady && (
                  <WarnNote>
                    <strong>AI explanations are unavailable.</strong> The backend has no
                    <code className="mx-1 font-mono">SARVAM_API_KEY</code> configured. You can
                    still browse the repository and inspect files, but questions cannot be
                    answered until a key is set. {health?.sarvam.note}
                  </WarnNote>
                )}
              </div>
            )}

            {turns.map((turn) => (
              <div key={turn.id} className="space-y-3">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm border border-line bg-raised px-3.5 py-2.5">
                    <p className="whitespace-pre-wrap text-sm">{turn.question}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-wide text-muted">
                      {LANGUAGES.find((l) => l.code === turn.language)?.label}
                    </p>
                  </div>
                </div>

                {turn.status === 'pending' && (
                  <div className="panel flex items-center gap-3 p-4 text-sm text-muted">
                    <Loader2 className="h-4 w-4 animate-spin text-glow" />
                    <div>
                      <p className="font-medium text-ink">Retrieving evidence and asking Sarvam…</p>
                      <p className="mt-0.5 text-xs">
                        Selecting relevant snippets, then generating a grounded answer.
                      </p>
                    </div>
                  </div>
                )}

                {turn.status === 'error' && turn.error && (
                  <ErrorBanner error={turn.error} onRetry={() => onRetry(turn.id)} />
                )}

                {turn.status === 'done' && turn.response && (
                  <>
                    {turn.response.evidence.length > 0 && (
                      <button
                        type="button"
                        onClick={() => onSelectEvidence(turn)}
                        className="btn-ghost !px-2.5 !py-1 text-xs"
                      >
                        <MessageSquareCode className="h-3.5 w-3.5" />
                        Show {turn.response.evidence.length} retrieved snippet
                        {turn.response.evidence.length === 1 ? '' : 's'} in Evidence Explorer
                      </button>
                    )}
                    <AnswerCard
                      response={turn.response}
                      onOpenCitation={onOpenCitation}
                      onFollowup={onAsk}
                    />
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <footer className="border-t border-line bg-surface p-3">
        <div className="mx-auto max-w-3xl">
          {project && focusLabel && (
            <div className="mb-1.5 flex items-center gap-2">
              <span className="chip max-w-full gap-1.5 !border-brand/40 !bg-brand/10">
                <FileCode2 className="h-3 w-3 shrink-0 text-glow" />
                <span className="truncate font-mono text-[11px] text-ink">{focusLabel}</span>
                <button
                  type="button"
                  onClick={onClearFocus}
                  className="ml-0.5 rounded p-0.5 text-muted transition-colors hover:text-ink"
                  aria-label="Ask about the whole project instead"
                  title="Ask about the whole project instead"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            </div>
          )}
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              disabled={!project}
              placeholder={
                !project
                  ? 'Load a repository to start asking questions'
                  : !signedIn
                    ? 'Sign in to ask questions about this repository'
                    : 'Ask in English, Telugu, Hindi, Tamil — or mix them, e.g. "ee project lo login ela work avutundi?"'
              }
              aria-label="Your question"
              className="field max-h-40 min-h-[52px] flex-1 resize-y"
            />
            <button
              type="button"
              onClick={submit}
              disabled={!project || !draft.trim() || asking}
              className="btn-primary !px-3.5 !py-3"
              aria-label="Send question"
            >
              {asking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted">
            <CornerDownLeft className="h-3 w-3" />
            Enter to send · Shift+Enter for a new line · answering in {activeLanguage.label}
          </p>
        </div>
      </footer>
    </section>
  )
}

function SignInNote({ onRequireAuth }: { onRequireAuth: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-raised p-3.5 text-xs">
      <Lock className="h-4 w-4 shrink-0 text-glow" />
      <div className="min-w-0 flex-1 leading-relaxed text-muted">
        <strong className="text-ink">Sign in to ask questions.</strong> Browsing a repository is
        open to everyone; uploading one and asking about it needs an account.
      </div>
      <button type="button" onClick={onRequireAuth} className="btn-primary !px-3 !py-1.5 text-xs">
        Sign in
      </button>
    </div>
  )
}

function WelcomeState({
  sarvamReady,
  ephemeralStorage,
  onUploadClick,
  onLoadSample,
  signedIn,
  onRequireAuth,
}: {
  sarvamReady: boolean
  ephemeralStorage: boolean
  onUploadClick: () => void
  onLoadSample: () => void
  signedIn: boolean
  onRequireAuth: () => void
}) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-5 py-10 text-center">
      <Logo size="lg" withWordmark={false} />
      <div>
        <h2 className="text-xl font-bold tracking-tight">
          Understand any codebase, <span className="gradient-text">in your language</span>
        </h2>
        <p className="mx-auto mt-2 max-w-lg text-sm text-muted">
          Upload a ZIP of your source code and ask questions in English, Telugu, Hindi or Tamil.
          Every answer comes with the files and line numbers that support it.
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-2">
        <button type="button" onClick={signedIn ? onUploadClick : onRequireAuth} className="btn-primary">
          {signedIn ? 'Upload repository' : 'Sign in to upload'}
        </button>
        <button type="button" onClick={onLoadSample} className="btn-ghost">
          <Sparkles className="h-4 w-4" />
          Explore the sample project
        </button>
      </div>

      <div className="grid w-full gap-3 sm:grid-cols-3">
        {[
          { title: '1 · Upload', body: 'Drop a ZIP. Dependencies, binaries and secrets are filtered out.' },
          { title: '2 · Ask', body: 'Question in any supported language, including code-mixed.' },
          { title: '3 · Verify', body: 'Citations are re-checked against real files and lines.' },
        ].map((s) => (
          <div key={s.title} className="panel p-3.5 text-left">
            <p className="text-xs font-semibold text-glow">{s.title}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{s.body}</p>
          </div>
        ))}
      </div>

      {!sarvamReady && (
        <div className="w-full">
          <WarnNote>
            The backend is running without a Sarvam API key, so AI explanations are disabled.
            Browsing and evidence retrieval still work.
          </WarnNote>
        </div>
      )}

      {!signedIn && (
        <div className="w-full">
          <SignInNote onRequireAuth={onRequireAuth} />
        </div>
      )}

      {ephemeralStorage && (
        <div className="w-full">
          <InfoNote>
            This demo keeps accounts and uploads in temporary server storage. If
            the app has been idle, you may need to sign in or upload again — the
            sample project always reloads.
          </InfoNote>
        </div>
      )}
    </div>
  )
}
