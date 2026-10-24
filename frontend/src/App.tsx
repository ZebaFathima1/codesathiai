import { useCallback, useEffect, useState } from 'react'
import { AuthPage } from './components/AuthPage'
import { Landing } from './components/Landing'
import { Workspace } from './components/Workspace'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { api } from './lib/api'
import type { HealthStatus } from './lib/types'

type View = 'landing' | 'workspace' | 'auth'

/** Hash routes: ``#/app`` is the workspace, ``#/login`` the auth page. */
function viewFromHash(): View {
  const hash = window.location.hash
  if (hash.startsWith('#/app')) return 'workspace'
  if (hash.startsWith('#/login')) return 'auth'
  return 'landing'
}

function Shell() {
  const { refresh } = useAuth()
  const [view, setView] = useState<View>(viewFromHash)
  const [health, setHealth] = useState<HealthStatus | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .health()
      .then((status) => {
        if (!cancelled) setHealth(status)
      })
      .catch(() => {
        if (!cancelled) setHealth(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Keep the view in step with the hash, so the back button works.
  useEffect(() => {
    const onHashChange = () => setView(viewFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const go = useCallback((next: View) => {
    const target = next === 'workspace' ? '#/app' : next === 'auth' ? '#/login' : ''
    if (window.location.hash !== target) {
      window.history.pushState(null, '', target || window.location.pathname)
    }
    setView(next)
    window.scrollTo({ top: 0 })
  }, [])

  const goToHowItWorks = useCallback(() => {
    go('landing')
    window.requestAnimationFrame(() => {
      document.getElementById('workflow')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [go])

  if (view === 'auth') {
    return (
      <AuthPage
        onBack={() => go('landing')}
        onDone={() => {
          void refresh()
          go('workspace')
        }}
      />
    )
  }

  // The workspace is reachable without an account: browsing the sample project
  // is public, and the workspace itself asks for sign-in at upload and ask.
  if (view === 'workspace') {
    return (
      <div className="h-screen">
        <Workspace health={health} onBackToLanding={() => go('landing')} onRequireAuth={() => go('auth')} />
      </div>
    )
  }

  return (
    <Landing
      onExplore={() => go('workspace')}
      onHowItWorks={goToHowItWorks}
      onSignIn={() => go('auth')}
      sarvamConfigured={health ? health.sarvam.configured : null}
    />
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
