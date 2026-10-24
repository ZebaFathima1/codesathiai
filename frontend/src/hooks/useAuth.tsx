import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError } from '../lib/api'
import type { User } from '../lib/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  googleAvailable: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string, fullName: string) => Promise<void>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
  /** True when the backend rejected the last call for want of a session. */
  sessionExpired: boolean
  clearSessionExpired: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * Session state for the whole app.
 *
 * The session itself lives in an httpOnly cookie, so the browser cannot read
 * it — this provider simply asks the backend who is signed in, and re-asks
 * whenever a request comes back 401.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [googleAvailable, setGoogleAvailable] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const status = await api.me()
      setUser(status.user)
      setGoogleAvailable(status.googleAvailable)
    } catch {
      // A backend that is unreachable is not the same as being signed out, but
      // there is nothing useful to show for it here either.
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password))
    setSessionExpired(false)
  }, [])

  const signUp = useCallback(async (email: string, password: string, fullName: string) => {
    setUser(await api.signup(email, password, fullName))
    setSessionExpired(false)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      googleAvailable,
      signIn,
      signUp,
      signOut,
      refresh,
      sessionExpired,
      clearSessionExpired: () => setSessionExpired(false),
    }),
    [user, loading, googleAvailable, signIn, signUp, signOut, refresh, sessionExpired],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an AuthProvider')
  }
  return context
}

/** Turn an unknown error into a message plus an optional hint. */
export function describeError(err: unknown): { message: string; code: string; hint?: string } {
  const apiError = err as ApiError
  if (apiError && typeof apiError === 'object' && 'message' in apiError && 'code' in apiError) {
    return { message: apiError.message, code: apiError.code, hint: apiError.hint }
  }
  return {
    message: err instanceof Error ? err.message : 'Something went wrong.',
    code: 'unknown_error',
  }
}
