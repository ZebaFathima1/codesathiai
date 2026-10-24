import { useEffect, useRef, useState } from 'react'
import { LogOut, User as UserIcon } from 'lucide-react'
import { useAuth } from '../hooks/useAuth'

/** Signed-in avatar with a small account menu. */
export function UserMenu({ onSignIn }: { onSignIn: () => void }) {
  const { user, loading, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocumentClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocumentClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocumentClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (loading) {
    return <span className="h-8 w-8 animate-pulse rounded-full bg-raised" aria-hidden="true" />
  }

  if (!user) {
    return (
      <button type="button" onClick={onSignIn} className="btn-primary !px-3.5 !py-2 text-sm">
        Sign in
      </button>
    )
  }

  const initial = (user.full_name || user.email).trim().charAt(0).toUpperCase()

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full border border-line bg-raised py-1 pl-1 pr-3 transition-colors hover:border-brand/50"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
      >
        {user.avatar_url ? (
          <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full" referrerPolicy="no-referrer" />
        ) : (
          <span
            className="grid h-7 w-7 place-items-center rounded-full text-xs font-bold text-white"
            style={{ backgroundImage: 'linear-gradient(135deg, rgb(var(--c-brand)), rgb(var(--c-brand-2)))' }}
          >
            {initial || <UserIcon className="h-3.5 w-3.5" />}
          </span>
        )}
        <span className="hidden max-w-[10rem] truncate text-xs font-medium sm:inline">
          {user.full_name || user.email}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="panel animate-fade-up absolute right-0 z-50 mt-2 w-64 p-2 shadow-soft"
        >
          <div className="border-b border-line px-2.5 py-2">
            <p className="truncate text-sm font-semibold">{user.full_name || 'Signed in'}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
            <span className="chip mt-2">
              {user.provider === 'google' ? 'Google account' : 'Email account'}
            </span>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              void signOut()
            }}
            className="mt-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-danger transition-colors hover:bg-raised"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
