/**
 * Browser-side ZIP extraction.
 *
 * Vercel caps a serverless request body at ~4.5 MB, which is smaller than a
 * typical repository archive. So the archive is unpacked here and the source
 * files are uploaded as JSON batches instead.
 *
 * The filtering rules deliberately mirror `backend/app/security.py`: the same
 * directories, extensions and secret filenames are skipped, and the same size
 * limits apply. The server re-validates everything — this pass exists to keep
 * the payload small, not to be trusted.
 */
import { unzipSync } from 'fflate'

export interface ExtractedFile {
  path: string
  content: string
}

export interface ExtractionResult {
  files: ExtractedFile[]
  totalBytes: number
  skipped: Record<string, number>
  /** Files dropped because the archive was larger than the limits allow. */
  truncated: boolean
}

export interface ExtractionLimits {
  maxFiles: number
  maxFileBytes: number
  maxTotalBytes: number
}

const IGNORED_DIRS = new Set([
  '.git', '.hg', '.svn', 'node_modules', 'bower_components', 'vendor',
  '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox',
  'venv', '.venv', 'env', 'dist', 'build', 'out', 'target', '.next', '.nuxt',
  '.cache', 'coverage', '.idea', '.vscode', '.gradle', 'site-packages',
  '.terraform', 'Pods', 'bin', 'obj',
])

const TEXT_EXTENSIONS = new Set([
  '.py', '.pyi', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx',
  '.java', '.kt', '.kts', '.c', '.h', '.cc', '.cpp', '.cxx', '.hpp', '.hh',
  '.cs', '.go', '.rb', '.php', '.rs', '.swift', '.scala', '.sh', '.bash',
  '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue', '.svelte',
  '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.properties',
  '.xml', '.md', '.markdown', '.rst', '.txt', '.sql',
])

const BINARY_EXTENSIONS = new Set([
  '.exe', '.dll', '.so', '.dylib', '.bin', '.class', '.jar', '.war', '.o',
  '.a', '.lib', '.obj', '.pdb', '.wasm', '.pyc', '.pyo',
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svgz',
  '.tiff', '.psd', '.ai', '.eps', '.pdf', '.zip', '.tar', '.gz', '.bz2',
  '.xz', '.7z', '.rar', '.mp3', '.mp4', '.mov', '.avi', '.mkv', '.wav',
  '.ogg', '.flac', '.woff', '.woff2', '.ttf', '.otf', '.eot',
  '.db', '.sqlite', '.sqlite3', '.mdb', '.dat', '.pkl', '.npy', '.npz',
  '.h5', '.pt', '.onnx', '.pem', '.key', '.p12', '.pfx', '.keystore',
  '.lock', '.map',
])

const SECRET_FILENAMES = new Set([
  '.env', '.env.local', '.env.production', 'id_rsa', 'id_dsa',
  'credentials', 'credentials.json', 'secrets.json', 'secrets.yaml',
  '.netrc', '.htpasswd',
])

const PLAIN_NAMES = new Set(['dockerfile', 'makefile', 'procfile', 'license', 'licence'])

/** Reduce a ZIP entry name to a safe relative POSIX path, or null. */
export function safePath(raw: string): string | null {
  if (!raw || raw.includes('\0')) return null
  let name = raw.replace(/\\/g, '/')
  while (name.startsWith('./')) name = name.slice(2)
  if (name.startsWith('/') || /^[a-zA-Z]:/.test(name)) return null
  const parts = name.split('/').filter((p) => p !== '' && p !== '.')
  if (parts.some((p) => p === '..')) return null
  if (parts.length === 0) return null
  return parts.join('/')
}

export function shouldSkip(path: string): string | null {
  const parts = path.split('/')
  for (const part of parts.slice(0, -1)) {
    if (IGNORED_DIRS.has(part)) return 'ignored_directory'
  }
  const base = parts[parts.length - 1].toLowerCase()
  if (SECRET_FILENAMES.has(base) || base.startsWith('.env')) return 'secret_file'
  if (base.endsWith('.min.js') || base.endsWith('.min.css')) return 'minified'

  const dot = base.lastIndexOf('.')
  const ext = dot > 0 ? base.slice(dot) : base.startsWith('.') ? base : ''
  if (BINARY_EXTENSIONS.has(ext)) return 'binary_extension'
  if (TEXT_EXTENSIONS.has(ext) || PLAIN_NAMES.has(base)) return null
  return 'unsupported_extension'
}

/** Cheap binary sniff: a NUL byte in the first block means "not text". */
function looksBinary(bytes: Uint8Array): boolean {
  const end = Math.min(bytes.length, 8000)
  for (let i = 0; i < end; i += 1) {
    if (bytes[i] === 0) return true
  }
  return false
}

export function extractZip(data: Uint8Array, limits: ExtractionLimits): ExtractionResult {
  const skipped: Record<string, number> = {}
  const note = (reason: string) => {
    skipped[reason] = (skipped[reason] ?? 0) + 1
  }

  const entries = unzipSync(data, {
    // Skip entries the archive marks as directories; we only want files.
    filter: (file) => file.size > 0,
  })

  const decoder = new TextDecoder('utf-8', { fatal: false })
  const files: ExtractedFile[] = []
  let totalBytes = 0
  let truncated = false

  for (const [rawName, bytes] of Object.entries(entries)) {
    if (files.length >= limits.maxFiles) {
      truncated = true
      break
    }
    const path = safePath(rawName)
    if (path === null) {
      note('unsafe_path')
      continue
    }
    const reason = shouldSkip(path)
    if (reason !== null) {
      note(reason)
      continue
    }
    if (bytes.byteLength > limits.maxFileBytes) {
      note('file_too_large')
      continue
    }
    if (totalBytes + bytes.byteLength > limits.maxTotalBytes) {
      note('total_too_large')
      truncated = true
      continue
    }
    if (looksBinary(bytes)) {
      note('binary_content')
      continue
    }
    files.push({ path, content: decoder.decode(bytes) })
    totalBytes += bytes.byteLength
  }

  return { files, totalBytes, skipped, truncated }
}

/** Split files into batches that respect the server's per-request budget. */
export function batchFiles(
  files: ExtractedFile[],
  maxFilesPerBatch: number,
  maxBytesPerBatch: number,
): ExtractedFile[][] {
  const batches: ExtractedFile[][] = []
  let current: ExtractedFile[] = []
  let currentBytes = 0

  for (const file of files) {
    const size = new TextEncoder().encode(file.content).length
    const wouldOverflow =
      current.length >= maxFilesPerBatch || currentBytes + size > maxBytesPerBatch
    if (current.length > 0 && wouldOverflow) {
      batches.push(current)
      current = []
      currentBytes = 0
    }
    current.push(file)
    currentBytes += size
  }
  if (current.length > 0) batches.push(current)
  return batches
}
