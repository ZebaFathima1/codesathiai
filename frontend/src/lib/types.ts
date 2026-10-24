/** Shared types mirroring the backend API contract. */

export type LanguageCode = 'te-IN' | 'en-IN' | 'hi-IN' | 'ta-IN'

export interface LanguageOption {
  code: LanguageCode
  label: string
  native: string
}

export const LANGUAGES: LanguageOption[] = [
  { code: 'te-IN', label: 'Telugu', native: 'తెలుగు' },
  { code: 'en-IN', label: 'English', native: 'English' },
  { code: 'hi-IN', label: 'Hindi', native: 'हिन्दी' },
  { code: 'ta-IN', label: 'Tamil', native: 'தமிழ்' },
]

export interface HealthStatus {
  status: string
  service: string
  version: string
  sarvam: {
    configured: boolean
    model: string
    note: string
  }
  auth: {
    password_signup: boolean
    google: boolean
  }
  storage: {
    backend: string
    max_stored_bytes: number
    upload_batch_bytes: number
  }
  limits: {
    max_archive_files: number
    max_file_bytes: number
  }
  languages: Record<string, string>
}

export interface User {
  id: string
  email: string
  full_name: string
  provider: 'password' | 'google'
  avatar_url: string | null
  created_at: string | null
}

export interface AuthStatus {
  user: User | null
  googleAvailable: boolean
}

export interface ProjectStats {
  file_count: number
  total_lines: number
  languages: Record<string, number>
  symbol_count: number
  ast_parsed_files: number
  regex_parsed_files: number
}

export interface ProjectSummary {
  project_id: string
  name: string
  source: 'upload' | 'sample'
  /** "uploading" while batches are still arriving, then "ready". */
  status: 'uploading' | 'ready'
  created_at: number | null
  stats: ProjectStats | Record<string, never>
  skipped_entries?: number
  skip_reasons?: Record<string, number>
  stored_files?: number
}

export interface SymbolInfo {
  name: string
  kind: string
  start_line: number
  end_line: number
  signature: string
  docstring: string
}

export interface FileSummary {
  path: string
  language: string
  line_count: number
  parser: 'ast' | 'regex' | 'none'
  symbols: SymbolInfo[]
}

export interface TreeNode {
  name: string
  path: string
  type: 'dir' | 'file'
  language?: string
  line_count?: number
  children?: TreeNode[]
}

export interface ProjectFiles {
  project_id: string
  name: string
  tree: TreeNode
  stats: ProjectStats
  files: FileSummary[]
}

export interface CodeLine {
  number: number
  text: string
}

export interface FileContent {
  path: string
  language: string
  parser: string
  line_count: number
  start_line: number
  end_line: number
  symbols: SymbolInfo[]
  lines: CodeLine[]
}

export interface Citation {
  citation_id: string
  path: string
  start_line: number
  end_line: number
  quote: string
  note: string
  verified: boolean
  rejection_reason?: string
}

export interface EvidenceSnippet {
  citation_id: string
  path: string
  start_line: number
  end_line: number
  code: string
  score: number
  reason: string
  language: string
  symbol: string | null
}

export interface AnswerStep {
  title: string
  detail: string
}

export interface KeyFile {
  path: string
  symbol: string
  role: string
}

export interface AskResponse {
  project_id: string
  question: string
  language: string
  answer: string | null
  steps: AnswerStep[]
  key_files: KeyFile[]
  citations: Citation[]
  rejected_citations: Citation[]
  uncertainty: string
  followups: string[]
  evidence: EvidenceSnippet[]
  retrieval_terms: string[]
  model: string | null
  usage: { total_tokens?: number | null } | null
  structured: boolean
  sarvam_called: boolean
}

export interface ChatTurn {
  id: string
  question: string
  language: LanguageCode
  status: 'pending' | 'done' | 'error'
  response?: AskResponse
  error?: { message: string; code: string; hint?: string }
}

/** A citation the user clicked, to be opened in the code viewer. */
export interface Selection {
  path: string
  startLine: number
  endLine: number
  nonce: number
}
