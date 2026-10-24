import { useState } from 'react'
import { ArrowLeft, Loader2, Lock, Mail, ShieldCheck, User as UserIcon } from 'lucide-react'
import { Logo } from './Logo'
import { describeError, useAuth } from '../hooks/useAuth'
import { api } from '../lib/api'
import { cn } from '../lib/utils'

interface AuthPageProps {
  onDone: () => void
  onBack: () => void
  /** Pre-select the sign-up tab, e.g. when arriving from "create an account". */
  initialMode?: Mode
}

type Mode = 'signin' | 'signup'

/** Full-page sign in / sign up. */
export function AuthPage({ onDone, onBack, initialMode = 'signin' }: AuthPageProps) {
  const { signIn, signUp, googleAvailable } = useAuth()
  const [mode, setMode] = useState<Mode>(initialMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; code: string; hint?: string } | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') {
        await signIn(email.trim(), password)
      } else {
        await signUp(email.trim(), password, fullName.trim())
      }
      onDone()
    } catch (err) {
      setError(describeError(err))
      setBusy(false)
    }
  }

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
  }

  return (
    <div className="grid-bg flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-4">
        <button type="button" onClick={onBack} className="btn-ghost !px-2 !py-1.5" aria-label="Back">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Logo />
      </header>

      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 pb-16">
        <div className="panel animate-fade-up p-6 shadow-soft sm:p-7">
          <div className="mb-5 flex rounded-xl border border-line bg-raised p-1">
            {(['signin', 'signup'] as Mode[]).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => switchMode(option)}
                aria-pressed={mode === option}
                className={cn(
                  'flex-1 rounded-lg py-2 text-sm font-semibold transition-colors',
                  mode === option ? 'bg-brand/25 text-ink ring-1 ring-brand/40' : 'text-muted hover:text-ink',
                )}
              >
                {option === 'signin' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <h1 className="text-lg font-bold tracking-tight">
            {mode === 'signin' ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {mode === 'signin'
              ? 'Sign in to upload a repository and ask questions about it.'
              : 'An account is needed to upload repositories and ask questions. Browsing the sample project stays open to everyone.'}
          </p>

          <form onSubmit={submit} className="mt-5 space-y-3.5">
            {mode === 'signup' && (
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Name</span>
                <div className="relative">
                  <UserIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    autoComplete="name"
                    placeholder="Your name"
                    className="field pl-9"
                    disabled={busy}
                  />
                </div>
              </label>
            )}

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Email</span>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                  placeholder="you@example.com"
                  className="field pl-9"
                  disabled={busy}
                />
              </div>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Password</span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                  placeholder={mode === 'signup' ? 'At least 8 characters' : 'Your password'}
                  className="field pl-9"
                  disabled={busy}
                />
              </div>
            </label>

            {error && (
              <div role="alert" className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs">
                <p className="font-semibold text-ink">{error.message}</p>
                {error.hint && <p className="mt-1 text-muted">{error.hint}</p>}
              </div>
            )}

            <button type="submit" className="btn-primary w-full !py-2.5" disabled={busy}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          </form>

          {googleAvailable && (
            <>
              <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wide text-muted">
                <span className="h-px flex-1 bg-line" />
                or
                <span className="h-px flex-1 bg-line" />
              </div>
              <a href={api.googleSignInUrl()} className="btn-ghost w-full !py-2.5">
                <GoogleMark />
                Continue with Google
              </a>
            </>
          )}

          <p className="mt-5 flex items-start gap-2 text-[11px] leading-relaxed text-muted">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-glow" />
            Passwords are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations). Sessions are stored
            server-side and the cookie is httpOnly.
          </p>
        </div>
      </main>
    </div>
  )
}

/** Inline Google mark, so no external asset is needed. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.4a5.5 5.5 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.6-5.2 3.6-8.8Z" />
      <path fill="#34A853" d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3c-1.1.7-2.4 1.2-4 1.2a7 7 0 0 1-6.6-4.8H1.4v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.4 14.5a7.2 7.2 0 0 1 0-4.6V6.8H1.4a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.4 6.8l4 3.1A7 7 0 0 1 12 4.8Z" />
    </svg>
  )
}
