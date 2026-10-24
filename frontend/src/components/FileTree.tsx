import { useState } from 'react'
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen } from 'lucide-react'
import type { TreeNode } from '../lib/types'
import { cn, languageAccent } from '../lib/utils'

interface FileTreeProps {
  tree: TreeNode
  selectedPath: string | null
  onSelect: (path: string) => void
  /** When set, only nodes matching this filter are shown. */
  filter?: string
}

/** Collapsible repository tree with file-type accents. */
export function FileTree({ tree, selectedPath, onSelect, filter = '' }: FileTreeProps) {
  const needle = filter.trim().toLowerCase()

  return (
    <ul role="tree" className="space-y-0.5 text-sm">
      {(tree.children ?? []).map((node) => (
        <TreeItem
          key={node.path}
          node={node}
          depth={0}
          selectedPath={selectedPath}
          onSelect={onSelect}
          needle={needle}
        />
      ))}
    </ul>
  )
}

interface TreeItemProps {
  node: TreeNode
  depth: number
  selectedPath: string | null
  onSelect: (path: string) => void
  needle: string
}

function TreeItem({ node, depth, selectedPath, onSelect, needle }: TreeItemProps) {
  const matches = (n: TreeNode): boolean => {
    if (!needle) return true
    if (n.type === 'file') return n.path.toLowerCase().includes(needle)
    return (n.children ?? []).some(matches)
  }

  if (!matches(node)) return null

  const [open, setOpen] = useState(depth < 2)
  const pad = { paddingLeft: `${depth * 12 + 6}px` }

  if (node.type === 'dir') {
    const children = (node.children ?? []).filter(matches)
    return (
      <li role="treeitem" aria-expanded={open}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-muted transition-colors hover:bg-raised hover:text-ink"
          style={pad}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
          {open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-glow" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-glow" />
          )}
          <span className="truncate font-medium">{node.name}</span>
        </button>
        {open && (
          <ul role="group" className="space-y-0.5">
            {children.map((child) => (
              <TreeItem
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedPath={selectedPath}
                onSelect={onSelect}
                needle={needle}
              />
            ))}
          </ul>
        )}
      </li>
    )
  }

  const active = selectedPath === node.path
  return (
    <li role="treeitem">
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        aria-current={active ? 'true' : undefined}
        className={cn(
          'flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left transition-colors',
          active
            ? 'bg-brand/20 text-ink ring-1 ring-brand/40'
            : 'text-muted hover:bg-raised hover:text-ink',
        )}
        style={pad}
        title={node.path}
      >
        <FileCode2 className={cn('h-3.5 w-3.5 shrink-0', languageAccent(node.path))} />
        <span className="truncate">{node.name}</span>
      </button>
    </li>
  )
}
