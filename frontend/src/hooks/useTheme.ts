import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'codesathi-theme'

function initialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  // Dark is the product's default. Only an explicit user choice overrides it,
  // so the workspace looks the same for everyone on first load.
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' ? 'light' : 'dark'
}

/** Theme state, persisted and applied to <html data-theme>. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* storage may be unavailable in private mode — the theme still applies */
    }
  }, [theme])

  const toggle = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), [])
  return { theme, setTheme, toggle }
}
