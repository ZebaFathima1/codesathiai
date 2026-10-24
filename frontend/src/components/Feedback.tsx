import { AlertTriangle, Info, XCircle } from 'lucide-react'
import type { ApiError } from '../lib/api'

interface ErrorBannerProps {
  error: { message: string; code: string; hint?: string }
  onRetry?: () => void
  onDismiss?: () => void
}

/** A consistent, readable error surface with an optional retry action. */
export function ErrorBanner({ error, onRetry, onDismiss }: ErrorBannerProps) {
  const hint = error.hint ?? hintForCode(error.code)
  return (
    <div
      role="alert"
      className="animate-fade-up rounded-xl border border-danger/40 bg-danger/10 p-3.5 text-sm"
    >
      <div className="flex items-start gap-2.5">
        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-ink">{error.message}</p>
          {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
          <p className="mt-1 font-mono text-[11px] text-muted/80">code: {error.code}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {onRetry && (
            <button type="button" onClick={onRetry} className="btn-subtle !px-2.5 !py-1 text-xs">
              Retry
            </button>
          )}
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="btn-ghost !px-2 !py-1 text-xs"
              aria-label="Dismiss error"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function hintForCode(code: string): string | undefined {
  switch (code) {
    case 'sarvam_not_configured':
      return 'Set SARVAM_API_KEY in backend/.env and restart the backend.'
    case 'network_error':
      return 'Start the backend with `python run.py` inside backend/.'
    case 'project_not_found':
      return 'The project expired or was deleted — upload it again.'
    default:
      return undefined
  }
}

/** Small inline note used for non-fatal information. */
export function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-line bg-raised p-3 text-xs text-muted">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-glow" />
      <div className="leading-relaxed">{children}</div>
    </div>
  )
}

/** Warning used when AI explanations are unavailable but browsing still works. */
export function WarnNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-xs text-ink">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
      <div className="leading-relaxed">{children}</div>
    </div>
  )
}

export function toErrorPayload(err: unknown): { message: string; code: string; hint?: string } {
  const apiError = err as ApiError
  if (apiError && typeof apiError === 'object' && 'message' in apiError && 'code' in apiError) {
    return { message: apiError.message, code: apiError.code, hint: apiError.hint }
  }
  return {
    message: err instanceof Error ? err.message : 'Something went wrong.',
    code: 'unknown_error',
  }
}
