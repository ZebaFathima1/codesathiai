/**
 * Typed client for the CodeSathi AI backend.
 *
 * The Sarvam API key lives only on the server, so the browser talks to
 * `/api/*` exclusively. Every request sends the session cookie
 * (`credentials: 'include'`) — that is how the app knows who is signed in.
 * Errors are normalised into `ApiError` so components can show the backend's
 * own human-readable message and error code.
 */
import type {
  AskResponse,
  AuthStatus,
  FileContent,
  HealthStatus,
  LanguageCode,
  ProjectFiles,
  ProjectSummary,
  User,
} from './types'
import type { ExtractedFile } from './zip'
import { batchFiles } from './zip'

const BASE = '/api'

export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown>

  constructor(message: string, code: string, status: number, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }

  /** True when the request failed only because nobody is signed in. */
  get isAuthError(): boolean {
    return this.status === 401
  }

  /** A short, actionable suggestion shown under the error message. */
  get hint(): string | undefined {
    switch (this.code) {
      case 'not_authenticated':
        return 'Sign in to continue.'
      case 'sarvam_not_configured':
        return 'Add SARVAM_API_KEY to the backend environment and restart the server.'
      case 'sarvam_auth_failed':
        return 'Check that the API key is valid and has access to sarvam-105b.'
      case 'sarvam_rate_limited':
      case 'rate_limited':
        return 'Wait a few seconds and retry.'
      case 'sarvam_quota_exhausted':
        return 'Top up the Sarvam account or switch to a key with remaining quota.'
      case 'sarvam_timeout':
        return 'Retry, or ask a narrower question.'
      case 'project_not_found':
        return 'It may have expired or belong to another account — upload it again.'
      case 'project_too_large':
      case 'total_too_large':
        return 'Try a smaller repository, or exclude dependencies and build output.'
      case 'google_not_configured':
        return 'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the deployment.'
      default:
        return undefined
    }
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      credentials: 'include',
      ...init,
    })
  } catch {
    throw new ApiError(
      'Cannot reach the CodeSathi backend. Is it running?',
      'network_error',
      0,
    )
  }

  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }

  if (!response.ok) {
    const payload = (body ?? {}) as {
      error?: string
      code?: string
      details?: Record<string, unknown>
    }
    throw new ApiError(
      payload.error || `Request failed (${response.status}).`,
      payload.code || 'request_failed',
      response.status,
      payload.details,
    )
  }

  return body as T
}

export interface UploadProgress {
  phase: 'extracting' | 'uploading' | 'indexing' | 'done'
  percent: number
  detail: string
}

export const api = {
  health(): Promise<HealthStatus> {
    return request<HealthStatus>('/health')
  },

  /* ---------------------------------------------------------------- auth */
  me(): Promise<AuthStatus> {
    return request<{ user: User | null; google_available: boolean }>('/auth/me').then((r) => ({
      user: r.user,
      googleAvailable: r.google_available,
    }))
  },

  signup(email: string, password: string, fullName: string): Promise<User> {
    return request<User>('/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, full_name: fullName }),
    })
  },

  login(email: string, password: string): Promise<User> {
    return request<User>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  },

  logout(): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>('/auth/logout', { method: 'POST' })
  },

  /** Full-page navigation: the API sets the state cookie and redirects back. */
  googleSignInUrl(): string {
    return `${BASE}/auth/google/start`
  },

  /* ------------------------------------------------------------ projects */
  listProjects(): Promise<ProjectSummary[]> {
    return request<{ projects: ProjectSummary[] }>('/projects').then((r) => r.projects)
  },

  loadSample(): Promise<ProjectSummary> {
    return request<ProjectSummary>('/projects/sample', { method: 'POST' })
  },

  /**
   * Upload an unpacked repository as JSON batches.
   *
   * The first batch creates the project; the rest are appended; a final call
   * builds the index. This keeps every request inside Vercel's ~4.5 MB body
   * limit while still supporting repositories far larger than that.
   */
  async uploadRepository(
    name: string,
    files: ExtractedFile[],
    limits: { maxFilesPerBatch: number; maxBytesPerBatch: number },
    onProgress?: (progress: UploadProgress) => void,
  ): Promise<ProjectSummary> {
    const batches = batchFiles(files, limits.maxFilesPerBatch, limits.maxBytesPerBatch)
    if (batches.length === 0) {
      throw new ApiError('That archive contained no indexable source files.',
                         'no_source_files', 400)
    }

    const report = (phase: UploadProgress['phase'], percent: number, detail: string) =>
      onProgress?.({ phase, percent, detail })

    report('uploading', 0, `Sending ${files.length} files…`)

    let project = await request<ProjectSummary>('/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, files: batches[0] }),
    })

    for (let i = 1; i < batches.length; i += 1) {
      await request(`/projects/${project.project_id}/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: batches[i] }),
      })
      report('uploading', Math.round((i / batches.length) * 100),
             `Sent batch ${i + 1} of ${batches.length}`)
    }

    // Only a project created with files is already finished.
    if (project.status === 'uploading') {
      report('indexing', 100, 'Indexing source files…')
      project = await request<ProjectSummary>(`/projects/${project.project_id}/finalize`, {
        method: 'POST',
      })
    }

    report('done', 100, 'Ready')
    return project
  },

  projectFiles(projectId: string): Promise<ProjectFiles> {
    return request<ProjectFiles>(`/projects/${projectId}/files`)
  },

  fileContent(projectId: string, path: string, start?: number, end?: number): Promise<FileContent> {
    const params = new URLSearchParams({ path })
    if (start) params.set('start', String(start))
    if (end) params.set('end', String(end))
    return request<FileContent>(`/projects/${projectId}/file?${params.toString()}`)
  },

  ask(
    projectId: string,
    question: string,
    language: LanguageCode,
    history: { role: string; content: string }[],
  ): Promise<AskResponse> {
    return request<AskResponse>(`/projects/${projectId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, language, history }),
    })
  },

  deleteProject(projectId: string): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`/projects/${projectId}`, { method: 'DELETE' })
  },
}
