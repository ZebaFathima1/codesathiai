/** Small shared helpers. */

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, i)
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-IN').format(value)
}

/** Map a file extension to a short, readable type label. */
export function fileKind(path: string): string {
  const name = path.split('/').pop() ?? path
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : ''
  const map: Record<string, string> = {
    py: 'py', ts: 'ts', tsx: 'tsx', js: 'js', jsx: 'jsx', mjs: 'js', cjs: 'js',
    java: 'java', kt: 'kt', c: 'c', h: 'h', cpp: 'cpp', cc: 'cpp', hpp: 'hpp',
    cs: 'cs', go: 'go', rb: 'rb', php: 'php', rs: 'rs', swift: 'swift',
    html: 'html', css: 'css', scss: 'scss', less: 'less', vue: 'vue', svelte: 'svelte',
    json: 'json', yaml: 'yml', yml: 'yml', toml: 'toml', ini: 'ini', cfg: 'cfg',
    xml: 'xml', md: 'md', markdown: 'md', rst: 'rst', txt: 'txt', sql: 'sql',
    sh: 'sh', bash: 'sh', env: 'env',
  }
  return map[ext] ?? (ext || 'file')
}

/** A stable accent per language so the tree reads at a glance. */
export function languageAccent(path: string): string {
  const kind = fileKind(path)
  const groups: Record<string, string> = {
    py: 'text-sky-400',
    ts: 'text-blue-400', tsx: 'text-blue-400',
    js: 'text-yellow-400', jsx: 'text-yellow-400',
    java: 'text-orange-400', kt: 'text-purple-400',
    c: 'text-slate-400', h: 'text-slate-400', cpp: 'text-slate-400', hpp: 'text-slate-400',
    go: 'text-cyan-400', rs: 'text-amber-400', rb: 'text-red-400', php: 'text-indigo-400',
    html: 'text-orange-400', css: 'text-pink-400', scss: 'text-pink-400',
    json: 'text-emerald-400', yml: 'text-emerald-400', toml: 'text-emerald-400',
    md: 'text-glow', sql: 'text-teal-400',
  }
  return groups[kind] ?? 'text-muted'
}

export function shortenPath(path: string, max = 34): string {
  if (path.length <= max) return path
  const parts = path.split('/')
  return '…/' + parts.slice(-2).join('/')
}

/** Copy text to the clipboard, falling back to a hidden textarea. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const area = document.createElement('textarea')
      area.value = text
      area.setAttribute('readonly', '')
      area.style.position = 'absolute'
      area.style.left = '-9999px'
      document.body.appendChild(area)
      area.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(area)
      return ok
    } catch {
      return false
    }
  }
}

/** Render an AskResponse as plain markdown for the copy button. */
export function answerToMarkdown(response: {
  answer: string | null
  steps: { title: string; detail: string }[]
  key_files: { path: string; symbol: string; role: string }[]
  citations: { path: string; start_line: number; end_line: number; note: string }[]
  uncertainty: string
}): string {
  const lines: string[] = []
  if (response.answer) lines.push(response.answer, '')
  if (response.steps.length) {
    lines.push('### Steps')
    response.steps.forEach((s, i) => lines.push(`${i + 1}. **${s.title}** — ${s.detail}`))
    lines.push('')
  }
  if (response.key_files.length) {
    lines.push('### Key files')
    response.key_files.forEach((f) => lines.push(`- \`${f.path}\` — ${f.role}`))
    lines.push('')
  }
  if (response.citations.length) {
    lines.push('### Evidence')
    response.citations.forEach((c) =>
      lines.push(`- \`${c.path}\` lines ${c.start_line}–${c.end_line} — ${c.note}`),
    )
    lines.push('')
  }
  if (response.uncertainty) lines.push('### Uncertainty', response.uncertainty)
  return lines.join('\n')
}
