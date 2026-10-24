import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, PanelRight } from 'lucide-react'
import { ChatPanel } from './ChatPanel'
import { EvidencePanel } from './EvidencePanel'
import { Logo } from './Logo'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import { UploadDialog } from './UploadDialog'
import { UserMenu } from './UserMenu'
import { api } from '../lib/api'
import { describeError, useAuth } from '../hooks/useAuth'
import type {
  ChatTurn,
  EvidenceSnippet,
  FileContent,
  HealthStatus,
  LanguageCode,
  ProjectFiles,
  ProjectSummary,
  Selection,
} from '../lib/types'
import type { ExtractionResult } from '../lib/zip'
import { cn } from '../lib/utils'

interface WorkspaceProps {
  health: HealthStatus | null
  onBackToLanding: () => void
  onRequireAuth: () => void
}

type Pane = 'files' | 'chat' | 'evidence'

/** The three-panel application workspace. */
export function Workspace({ health, onBackToLanding, onRequireAuth }: WorkspaceProps) {
  const { user } = useAuth()

  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [files, setFiles] = useState<ProjectFiles | null>(null)
  const [loadingFiles, setLoadingFiles] = useState(false)

  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<FileContent | null>(null)
  const [loadingFile, setLoadingFile] = useState(false)
  const [fileError, setFileError] = useState<{ message: string; code: string; hint?: string } | null>(null)

  const [selection, setSelection] = useState<Selection | null>(null)
  const [evidence, setEvidence] = useState<EvidenceSnippet[]>([])
  const [selectedSnippetId, setSelectedSnippetId] = useState<string | null>(null)

  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [asking, setAsking] = useState(false)
  const [language, setLanguage] = useState<LanguageCode>('en-IN')
  const [sessionError, setSessionError] = useState<{ message: string; code: string; hint?: string } | null>(null)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pane, setPane] = useState<Pane>('chat')

  const fileRequestId = useRef(0)

  /* ---------------------------------------------------------------- load */
  const applyProject = useCallback(async (summary: ProjectSummary) => {
    setProject(summary)
    setTurns([])
    setEvidence([])
    setSelectedSnippetId(null)
    setSelection(null)
    setFileContent(null)
    setSelectedPath(null)
    setSessionError(null)
    setFileError(null)
    setLoadingFiles(true)
    try {
      const tree = await api.projectFiles(summary.project_id)
      setFiles(tree)
      const preferred =
        tree.files.find((f) => /(^|\/)(app|main|index)\.(py|js|ts|tsx|jsx)$/.test(f.path)) ??
        tree.files.find((f) => f.path.toLowerCase().endsWith('readme.md')) ??
        tree.files[0]
      if (preferred) setSelectedPath(preferred.path)
    } catch (err) {
      setSessionError(describeError(err))
    } finally {
      setLoadingFiles(false)
    }
  }, [])

  const loadSample = useCallback(async () => {
    setBusy(true)
    setSessionError(null)
    try {
      await applyProject(await api.loadSample())
      setPane('chat')
    } catch (err) {
      setSessionError(describeError(err))
    } finally {
      setBusy(false)
    }
  }, [applyProject])

  const upload = useCallback(
    async (
      name: string,
      result: ExtractionResult,
      onProgress: (percent: number, detail: string) => void,
    ) => {
      if (!user) {
        onRequireAuth()
        throw new Error('Sign in to upload a repository.')
      }
      const summary = await api.uploadRepository(
        name,
        result.files,
        {
          maxFilesPerBatch: 120,
          maxBytesPerBatch: Math.max(
            512 * 1024,
            Math.min(health?.storage.upload_batch_bytes ?? 3 * 1024 * 1024, 3 * 1024 * 1024),
          ),
        },
        (progress) => onProgress(progress.percent, progress.detail),
      )
      await applyProject(summary)
      setPane('chat')
      return summary
    },
    [applyProject, health, onRequireAuth, user],
  )

  /* --------------------------------------------------------------- files */
  const openFile = useCallback(
    async (path: string, highlight?: { start: number; end: number }) => {
      if (!project) return
      const requestId = ++fileRequestId.current
      setSelectedPath(path)
      setLoadingFile(true)
      setFileError(null)
      try {
        const content = await api.fileContent(project.project_id, path)
        if (requestId !== fileRequestId.current) return
        setFileContent(content)
        if (highlight) {
          setSelection({ path, startLine: highlight.start, endLine: highlight.end, nonce: Date.now() })
        }
      } catch (err) {
        if (requestId !== fileRequestId.current) return
        setFileContent(null)
        setFileError(describeError(err))
      } finally {
        if (requestId === fileRequestId.current) setLoadingFile(false)
      }
    },
    [project],
  )

  const handleTreeSelect = useCallback(
    (path: string) => {
      setSelection(null)
      void openFile(path)
      setPane('chat')
    },
    [openFile],
  )

  const handleOpenCitation = useCallback(
    (c: { path: string; startLine: number; endLine: number }) => {
      void openFile(c.path, { start: c.startLine, end: c.endLine })
      setPane('evidence')
    },
    [openFile],
  )

  /* ---------------------------------------------------------------- ask */
  const runAsk = useCallback(
    async (question: string, existingTurnId?: string) => {
      if (!project) return
      if (!user) {
        onRequireAuth()
        return
      }
      setSessionError(null)

      const history = turns
        .filter((t) => t.status === 'done' && t.response)
        .flatMap((t) => [
          { role: 'user', content: t.question },
          { role: 'assistant', content: t.response?.answer ?? '' },
        ])
        .filter((m) => m.content)

      const turnId = existingTurnId ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

      setTurns((prev) =>
        existingTurnId
          ? prev.map((t) =>
              t.id === existingTurnId ? { ...t, status: 'pending' as const, error: undefined } : t,
            )
          : [...prev, { id: turnId, question, language, status: 'pending' as const }],
      )
      setAsking(true)

      try {
        const response = await api.ask(project.project_id, question, language, history)
        setTurns((prev) =>
          prev.map((t) => (t.id === turnId ? { ...t, status: 'done' as const, response } : t)),
        )
        setEvidence(response.evidence)
        setSelectedSnippetId(response.evidence[0]?.citation_id ?? null)
      } catch (err) {
        const payload = describeError(err)
        setTurns((prev) =>
          prev.map((t) => (t.id === turnId ? { ...t, status: 'error' as const, error: payload } : t)),
        )
        // A 401 mid-session means the cookie expired or was revoked.
        if (payload.code === 'not_authenticated') onRequireAuth()
      } finally {
        setAsking(false)
      }
    },
    [project, turns, language, user, onRequireAuth],
  )

  const retryTurn = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId)
      if (turn) void runAsk(turn.question, turnId)
    },
    [turns, runAsk],
  )

  /* ------------------------------------------------------------ project */
  const removeProject = useCallback(async () => {
    if (!project) return
    setBusy(true)
    try {
      if (project.source !== 'sample') {
        await api.deleteProject(project.project_id)
      }
    } catch {
      /* removal is best-effort; local state is cleared regardless */
    } finally {
      setProject(null)
      setFiles(null)
      setTurns([])
      setEvidence([])
      setFileContent(null)
      setSelectedPath(null)
      setSelection(null)
      setBusy(false)
    }
  }, [project])

  const resetSession = useCallback(() => {
    setTurns([])
    setEvidence([])
    setSelectedSnippetId(null)
    setSessionError(null)
  }, [])

  /* keep the selected snippet in sync with the open file */
  useEffect(() => {
    if (!selectedPath) return
    const match = evidence.find((e) => e.path === selectedPath)
    setSelectedSnippetId(match?.citation_id ?? null)
  }, [selectedPath, evidence])

  /* a different account must not inherit the previous account's project */
  useEffect(() => {
    setProject(null)
    setFiles(null)
    setTurns([])
    setEvidence([])
    setFileContent(null)
    setSelectedPath(null)
    setSelection(null)
  }, [user?.id])

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-line bg-surface px-3.5 py-2">
        <button type="button" onClick={onBackToLanding} className="btn-ghost !px-2 !py-1.5"
                aria-label="Back to home" title="Back to home">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Logo size="sm" />
        <div className="ml-auto flex items-center gap-2">
          {health && (
            <span className={cn('chip hidden sm:inline-flex',
                                health.sarvam.configured ? '!text-success' : '!text-warn')}
                  title={health.sarvam.note}>
              <span className={cn('h-1.5 w-1.5 rounded-full',
                                  health.sarvam.configured ? 'bg-success' : 'bg-warn')} />
              {health.sarvam.configured ? `Sarvam · ${health.sarvam.model}` : 'Sarvam not configured'}
            </span>
          )}
          <button type="button" onClick={() => setPane(pane === 'evidence' ? 'chat' : 'evidence')}
                  className="btn-ghost !px-2 !py-1.5 xl:hidden" aria-label="Toggle evidence panel">
            <PanelRight className="h-4 w-4" />
          </button>
          <ThemeToggle />
          <UserMenu onSignIn={onRequireAuth} />
        </div>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[276px_minmax(0,1fr)] xl:grid-cols-[276px_minmax(0,1fr)_400px]">
        <div className={cn('min-h-0', pane === 'files' ? 'block' : 'hidden', 'lg:block')}>
          <Sidebar
            project={project}
            files={files}
            loadingFiles={loadingFiles}
            selectedPath={selectedPath}
            onSelectFile={handleTreeSelect}
            onUploadClick={() => setUploadOpen(true)}
            onLoadSample={loadSample}
            onRemoveProject={removeProject}
            onResetSession={resetSession}
            busy={busy}
            onClose={() => setPane('chat')}
          />
        </div>

        <div className={cn('min-h-0', pane === 'chat' ? 'block' : 'hidden', 'lg:block')}>
          <ChatPanel
            project={project}
            health={health}
            turns={turns}
            asking={asking}
            language={language}
            onLanguageChange={setLanguage}
            onAsk={(q) => void runAsk(q)}
            onRetry={retryTurn}
            onOpenCitation={handleOpenCitation}
            onSelectEvidence={(turn) => {
              if (!turn.response) return
              setEvidence(turn.response.evidence)
              setSelectedSnippetId(turn.response.evidence[0]?.citation_id ?? null)
              setPane('evidence')
            }}
            onUploadClick={() => setUploadOpen(true)}
            onLoadSample={loadSample}
            onOpenSidebar={() => setPane('files')}
            sessionError={sessionError}
            onDismissSessionError={() => setSessionError(null)}
            signedIn={Boolean(user)}
            onRequireAuth={onRequireAuth}
          />
        </div>

        <div className={cn('min-h-0', pane === 'evidence' ? 'block' : 'hidden', 'xl:block')}>
          <EvidencePanel
            evidence={evidence}
            selectedSnippetId={selectedSnippetId}
            onSelectSnippet={(snippet) => {
              setSelectedSnippetId(snippet.citation_id)
              void openFile(snippet.path, { start: snippet.start_line, end: snippet.end_line })
            }}
            file={fileContent}
            loadingFile={loadingFile}
            selection={selection}
            fileError={fileError}
            onCloseFile={() => {
              setFileContent(null)
              setSelectedPath(null)
              setSelection(null)
            }}
          />
        </div>
      </div>

      <nav className="flex items-center justify-around border-t border-line bg-surface py-1.5 lg:hidden">
        {(['files', 'chat', 'evidence'] as Pane[]).map((p) => (
          <button key={p} type="button" onClick={() => setPane(p)}
                  className={cn('flex-1 py-1.5 text-xs font-semibold capitalize transition-colors',
                                pane === p ? 'text-glow' : 'text-muted')}>
            {p}
            {p === 'evidence' && evidence.length > 0 && (
              <span className="ml-1 text-muted/70">{evidence.length}</span>
            )}
          </button>
        ))}
      </nav>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUpload={upload}
        signedIn={Boolean(user)}
        onRequireAuth={onRequireAuth}
        limits={{
          maxFiles: health?.limits.max_archive_files ?? 1500,
          maxFileBytes: health?.limits.max_file_bytes ?? 1_500_000,
          maxTotalBytes: health?.storage.max_stored_bytes ?? 12 * 1024 * 1024,
        }}
      />
    </div>
  )
}
