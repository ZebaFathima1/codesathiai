import { Code2 } from 'lucide-react'
import { cn } from '../lib/utils'

interface LogoProps {
  size?: 'sm' | 'md' | 'lg'
  withWordmark?: boolean
  className?: string
}

/** CodeSathi AI mark: a gradient tile with a code glyph. */
export function Logo({ size = 'md', withWordmark = true, className }: LogoProps) {
  const box = size === 'lg' ? 'h-11 w-11' : size === 'sm' ? 'h-7 w-7' : 'h-9 w-9'
  const icon = size === 'lg' ? 'h-6 w-6' : size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'
  const text = size === 'lg' ? 'text-xl' : size === 'sm' ? 'text-sm' : 'text-base'

  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span
        aria-hidden="true"
        className={cn(
          'grid place-items-center rounded-xl text-white shadow-glow',
          box,
        )}
        style={{
          backgroundImage:
            'linear-gradient(135deg, rgb(var(--c-brand)), rgb(var(--c-brand-2)))',
        }}
      >
        <Code2 className={icon} strokeWidth={2.4} />
      </span>
      {withWordmark && (
        <span className={cn('font-bold tracking-tight', text)}>
          CodeSathi<span className="gradient-text"> AI</span>
        </span>
      )}
    </span>
  )
}
