import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Markdown renderer for model output.
 *
 * `react-markdown` builds a React element tree instead of injecting HTML, so
 * raw HTML in a model reply is escaped and never executed. We deliberately do
 * not enable `rehype-raw`.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-codesathi">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: kids }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {kids}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
