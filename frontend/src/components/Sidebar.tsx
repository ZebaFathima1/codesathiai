import { useMemo, useState } from 'react'
import {
  Boxes,
  FileCode2,
  FolderTree,
  Loader2,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { FileTree } from './FileTree'
import { Logo } from './Logo'
import type { ProjectFiles, ProjectSummary } from '../lib/types'
import { cn, formatNumber } from '../lib/utils'

interface SidebarProps {
  project: ProjectSummary | null
  files: ProjectFiles | null
  loadingFiles: boolean
  selectedPath: string | null
  onSelectFile: (path: string) => void
  onUploadClick: () => void
  onLoadSample: () => void
  onRemoveProject: () => void
  onResetSession: () => void
  busy: boolean
  onClose?: () => void
}

/** Left panel: project identity, search, and the repository file tree. */
export function Sidebar({
  project,
  files,
  loadingFiles,
  selectedPath,
  onSelectFile,
  onUploadClick,
  onLoadSample,
  onRemoveProject,
  onResetSession,
  busy,
  onClose,
}: SidebarProps) {
  const [filter, setFilter] = useState('')

  const languages = useMemo(() => {
    if (!files) return []
    return Object.entries(files.stats.languages).slice(0, 5)
  }, [files])

  return (
    <aside className="flex h-full min-h-0 flex-col border-r border-line bg-surface">
      <header className="flex items-center justify-between gap-2 border-b border-line px-3.5 py-3">
        <Logo size="sm" />
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost !px-2 !py-1 text-xs lg:hidden"
          >
            Close
          </button>
        )}
      </header>

      <div className="space-y-2 border-b border-line p-3">
        <button type="button" onClick={onUploadClick} className="btn-primary w-full" disabled={busy}>
          <Upload className="h-4 w-4" />
          Upload repository
        </button>
        <button type="button" onClick={onLoadSample} className="btn-ghost w-full" disabled={busy}>
          <Sparkles className="h-4 w-4" />
          Load sample project
        </button>
      </div>

      {project ? (
        <>
          <div className="border-b border-line px-3.5 py-3">
            <div className="flex items-center gap-2">
              <Boxes className="h-4 w-4 shrink-0 text-glow" />
              <h2 className="truncate text-sm font-semibold" title={project.name}>
                {project.name}
              </h2>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="chip">{formatNumber(project.stats.file_count)} files</span>
              <span className="chip">{formatNumber(project.stats.total_lines)} lines</span>
              <span className="chip">{formatNumber(project.stats.symbol_count)} symbols</span>
            </div>
            {project.source === 'sample' && (
              <p className="mt-2 text-[11px] text-muted">
                Bundled sample repository — real source files, no upload needed.
              </p>
            )}
            {languages.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {languages.map(([lang, count]) => (
                  <span key={lang} className="chip">
                    {lang}
                    <span className="text-muted/70">{count}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="border-b border-line p-2.5">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search files…"
                aria-label="Search files"
                className="field !py-1.5 pl-8 text-xs"
              />
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loadingFiles ? (
              <div className="flex items-center gap-2 p-3 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Indexing repository…
              </div>
            ) : files ? (
              <FileTree
                tree={files.tree}
                selectedPath={selectedPath}
                onSelect={onSelectFile}
                filter={filter}
              />
            ) : null}
          </div>

          <footer className="space-y-1.5 border-t border-line p-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted">
              <FolderTree className="h-3.5 w-3.5" />
              {project.stats.ast_parsed_files} files parsed with Python AST
              {project.stats.regex_parsed_files > 0 &&
                `, ${project.stats.regex_parsed_files} with the regex fallback`}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onResetSession}
                className="btn-ghost flex-1 !px-2 !py-1.5 text-xs"
                disabled={busy}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset chat
              </button>
              <button
                type="button"
                onClick={onRemoveProject}
                className={cn('btn-ghost flex-1 !px-2 !py-1.5 text-xs text-danger')}
                disabled={busy}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Remove
              </button>
            </div>
          </footer>
        </>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <FileCode2 className="h-8 w-8 text-muted/50" />
          <p className="text-sm font-medium">No project loaded</p>
          <p className="text-xs text-muted">
            Upload a ZIP of your source code, or open the bundled sample to explore the workspace.
          </p>
        </div>
      )}
    </aside>
  )
}
