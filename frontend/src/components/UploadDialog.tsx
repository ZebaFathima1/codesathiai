import { useCallback, useRef, useState } from 'react'
import { AlertCircle, FileArchive, FileCode2, Loader2, UploadCloud, X } from 'lucide-react'
import type { ProjectSummary } from '../lib/types'
import type { ExtractionResult } from '../lib/zip'
import { extractZip } from '../lib/zip'
import { cn, formatBytes, formatNumber } from '../lib/utils'
import { describeError } from '../hooks/useAuth'

interface UploadDialogProps {
  open: boolean
  onClose: () => void
  onUpload: (
    name: string,
    result: ExtractionResult,
    onProgress: (percent: number, detail: string) => void,
  ) => Promise<ProjectSummary>
  limits: { maxFiles: number; maxFileBytes: number; maxTotalBytes: number }
  /** Called when the user is not signed in and tries to upload. */
  onRequireAuth: () => void
  signedIn: boolean
}

const ACCEPTED = '.zip,application/zip,application/x-zip-compressed'

/**
 * Upload dialog.
 *
 * The archive is unpacked in the browser: Vercel caps a serverless request
 * body at ~4.5 MB, so sending the ZIP itself would fail for any real project.
 * The extracted files are uploaded as JSON batches instead.
 */
export function UploadDialog({
  open,
  onClose,
  onUpload,
  limits,
  onRequireAuth,
  signedIn,
}: UploadDialogProps) {
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [phase, setPhase] = useState<'idle' | 'extracting' | 'uploading' | 'done'>('idle')
  const [percent, setPercent] = useState(0)
  const [detail, setDetail] = useState('')
  const [preview, setPreview] = useState<ExtractionResult | null>(null)
  const [error, setError] = useState<{ message: string; code: string; hint?: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const busy = phase === 'extracting' || phase === 'uploading'

  const reset = useCallback(() => {
    setFile(null)
    setName('')
    setPhase('idle')
    setPercent(0)
    setDetail('')
    setPreview(null)
    setError(null)
    setDragging(false)
  }, [])

  const close = () => {
    if (busy) return
    reset()
    onClose()
  }

  const choose = async (candidate: File) => {
    setError(null)
    setPreview(null)

    if (!candidate.name.toLowerCase().endsWith('.zip')) {
      setError({ message: 'Only .zip archives are supported.', code: 'client_validation' })
      return
    }
    if (candidate.size === 0) {
      setError({ message: 'That file is empty.', code: 'client_validation' })
      return
    }

    setFile(candidate)
    if (!name) setName(candidate.name.replace(/\.zip$/i, ''))
    setPhase('extracting')
    setPercent(0)
    setDetail('Reading the archive…')

    try {
      const bytes = new Uint8Array(await candidate.arrayBuffer())
      const result = extractZip(bytes, limits)
      if (result.files.length === 0) {
        setPhase('idle')
        setError({
          message: 'No indexable source files were found in that archive.',
          code: 'no_source_files',
          hint: 'Dependencies, build output, binaries and secret files are skipped by design.',
        })
        return
      }
      setPreview(result)
      setPhase('idle')
      setDetail(`${result.files.length} source files ready (${formatBytes(result.totalBytes)})`)
    } catch (err) {
      setPhase('idle')
      setError({
        message: 'That archive could not be read. Is it a valid ZIP file?',
        code: 'bad_zip',
        hint: describeError(err).message,
      })
    }
  }

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const dropped = event.dataTransfer.files?.[0]
    if (dropped) void choose(dropped)
  }

  const submit = async () => {
    if (!file || !preview) return
    if (!signedIn) {
      onRequireAuth()
      return
    }
    setPhase('uploading')
    setPercent(0)
    setError(null)
    try {
      await onUpload(name, preview, (value, message) => {
        setPercent(value)
        setDetail(message)
      })
      setPhase('done')
      reset()
      onClose()
    } catch (err) {
      setPhase('idle')
      setError(describeError(err))
    }
  }

  if (!open) return null

  const skipped = preview
    ? Object.entries(preview.skipped).sort((a, b) => b[1] - a[1]).slice(0, 4)
    : []

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Upload repository"
      onKeyDown={(e) => e.key === 'Escape' && close()}
    >
      <div className="panel w-full max-w-lg animate-fade-up p-5 shadow-soft">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Upload a repository</h2>
            <p className="mt-0.5 text-xs text-muted">
              ZIP your project folder. It is unpacked in your browser — dependencies, build output,
              binaries and secret files are skipped before anything is sent.
            </p>
          </div>
          <button type="button" onClick={close} disabled={busy} className="btn-ghost !px-2 !py-1.5"
                  aria-label="Close upload dialog">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={cn(
            'rounded-2xl border-2 border-dashed p-6 text-center transition-colors',
            dragging ? 'border-brand bg-brand/10' : 'border-line bg-raised',
          )}
        >
          <UploadCloud className={cn('mx-auto h-8 w-8', dragging ? 'text-glow' : 'text-muted')} />
          <p className="mt-2 text-sm font-medium">{file ? file.name : 'Drag a .zip here'}</p>
          <p className="mt-1 text-xs text-muted">
            {file ? formatBytes(file.size) : 'or browse — unpacked locally, nothing is uploaded yet'}
          </p>

          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED}
            className="sr-only"
            onChange={(e) => {
              const chosen = e.target.files?.[0]
              if (chosen) void choose(chosen)
              e.target.value = ''
            }}
          />

          <button type="button" onClick={() => inputRef.current?.click()} className="btn-ghost mt-3"
                  disabled={busy}>
            <FileArchive className="h-4 w-4" />
            Browse files
          </button>
        </div>

        {preview && (
          <div className="mt-4 rounded-xl border border-line bg-raised p-3 text-xs">
            <div className="flex items-center gap-2">
              <FileCode2 className="h-3.5 w-3.5 text-glow" />
              <span className="font-semibold">
                {formatNumber(preview.files.length)} source files ·{' '}
                {formatBytes(preview.totalBytes)}
              </span>
            </div>
            {skipped.length > 0 && (
              <p className="mt-1.5 text-muted">
                Skipped: {skipped.map(([reason, count]) => `${count} ${reason.replace(/_/g, ' ')}`).join(', ')}
              </p>
            )}
            {preview.truncated && (
              <p className="mt-1.5 text-warn">
                Some files were left out because the repository is larger than the limits allow.
              </p>
            )}
          </div>
        )}

        <label className="mt-4 block">
          <span className="mb-1 block text-xs font-medium text-muted">Project name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120}
                 placeholder="my-project" className="field" disabled={busy} />
        </label>

        {busy && (
          <div className="mt-4">
            <div className="mb-1.5 flex justify-between text-xs text-muted">
              <span>{detail || 'Working…'}</span>
              <span>{percent}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-raised">
              <div
                className="h-full rounded-full transition-all duration-200"
                style={{
                  width: `${percent}%`,
                  backgroundImage: 'linear-gradient(90deg, rgb(var(--c-brand)), rgb(var(--c-brand-2)))',
                }}
              />
            </div>
          </div>
        )}

        {!busy && detail && !preview && (
          <p className="mt-3 text-xs text-muted">{detail}</p>
        )}

        {error && (
          <div role="alert" className="mt-4 flex items-start gap-2 rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
            <div>
              <p className="font-semibold">{error.message}</p>
              {error.hint && <p className="mt-0.5 text-muted">{error.hint}</p>}
            </div>
          </div>
        )}

        {!signedIn && (
          <p className="mt-4 rounded-xl border border-warn/40 bg-warn/10 p-3 text-xs">
            You need an account to upload a repository. Browsing the sample project stays open.
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={close} className="btn-ghost" disabled={busy}>
            Cancel
          </button>
          <button type="button" onClick={submit} className="btn-primary"
                  disabled={!preview || busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
            {signedIn ? (busy ? 'Uploading…' : 'Upload & index') : 'Sign in to upload'}
          </button>
        </div>
      </div>
    </div>
  )
}
