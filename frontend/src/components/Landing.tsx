import {
  ArrowRight,
  BadgeCheck,
  Boxes,
  FileSearch,
  Languages,
  Lock,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Terminal,
} from 'lucide-react'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'
import { LANGUAGES } from '../lib/types'

interface LandingProps {
  onExplore: () => void
  onHowItWorks: () => void
  onSignIn: () => void
  sarvamConfigured: boolean | null
}

/**
 * Landing page.
 *
 * The product preview below shows a real question, a real answer shape, and a
 * real citation format — it is a labelled illustration of the output format,
 * not a fabricated user testimonial or a fake statistic.
 */
export function Landing({ onExplore, onHowItWorks, onSignIn, sarvamConfigured }: LandingProps) {
  return (
    <div className="min-h-full bg-bg">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <Logo />
          <nav className="ml-auto hidden items-center gap-1 md:flex">
            <a href="#features" className="btn-ghost !border-transparent text-sm">
              Features
            </a>
            <a href="#workflow" className="btn-ghost !border-transparent text-sm">
              How it works
            </a>
            <a href="#languages" className="btn-ghost !border-transparent text-sm">
              Languages
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-2 md:ml-0">
            <ThemeToggle />
            <UserMenu onSignIn={onSignIn} />
            <button type="button" onClick={onExplore} className="btn-primary hidden sm:inline-flex">
              Explore Your Codebase
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="grid-bg border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
          <div className="mx-auto max-w-3xl text-center">
            <span className="chip mx-auto">
              <Sparkles className="h-3 w-3 text-glow" />
              Built with Sarvam AI · sarvam-105b
            </span>

            <h1 className="mt-5 text-4xl font-extrabold leading-[1.1] tracking-tight sm:text-6xl">
              Understand Code.
              <br />
              <span className="gradient-text">In Your Language.</span>
            </h1>

            <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-muted sm:text-lg">
              CodeSathi AI explains unfamiliar software projects to Indian students and beginner
              developers in Telugu, English, Hindi or Tamil — and shows the exact files,
              functions and line numbers behind every answer.
            </p>

            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <button type="button" onClick={onExplore} className="btn-primary !px-5 !py-2.5">
                Explore Your Codebase
                <ArrowRight className="h-4 w-4" />
              </button>
              <button type="button" onClick={onHowItWorks} className="btn-ghost !px-5 !py-2.5">
                See How It Works
              </button>
            </div>

            <p className="mt-4 text-xs text-muted">
              Browse the bundled sample project with no account. An account is needed only to
              upload your own repository and ask questions about it.
            </p>

            {sarvamConfigured === false && (
              <p className="mx-auto mt-6 max-w-xl rounded-xl border border-warn/40 bg-warn/10 p-3 text-xs text-ink">
                This instance is running without a Sarvam API key. You can explore the sample
                repository and browse code, but AI explanations require the backend to be
                configured with <code className="font-mono">SARVAM_API_KEY</code>.
              </p>
            )}
          </div>

          {/* Product preview — output format illustration */}
          <div className="mx-auto mt-14 max-w-4xl">
            <div className="panel overflow-hidden shadow-soft">
              <div className="flex items-center gap-2 border-b border-line bg-raised px-4 py-2.5">
                <span className="h-2.5 w-2.5 rounded-full bg-danger/70" />
                <span className="h-2.5 w-2.5 rounded-full bg-warn/70" />
                <span className="h-2.5 w-2.5 rounded-full bg-success/70" />
                <span className="ml-2 font-mono text-[11px] text-muted">
                  CodeSathi AI — ShopEasy API (sample project)
                </span>
              </div>

              <div className="grid gap-0 sm:grid-cols-[minmax(0,1fr)_300px]">
                <div className="border-line p-4 sm:border-r">
                  <p className="mb-2 font-mono text-[11px] uppercase tracking-wide text-muted">
                    Question · Telugu (code-mixed)
                  </p>
                  <p className="rounded-xl bg-raised px-3 py-2 text-sm">
                    Ee project lo login process ela work avutundi?
                  </p>

                  <p className="mb-2 mt-4 font-mono text-[11px] uppercase tracking-wide text-muted">
                    Answer · తెలుగు
                  </p>
                  <p className="text-sm leading-relaxed">
                    లాగిన్ అభ్యర్థన <code className="font-mono text-glow">POST /api/auth/login</code>{' '}
                    కి వస్తుంది. ముందుగా ఇమెయిల్‌తో యూజర్‌ను వెతుకుతుంది, ఆ తర్వాత{' '}
                    <code className="font-mono text-glow">check_password()</code> తో పాస్‌వర్డ్
                    హాష్‌ను సరిపోలుస్తుంది. విజయవంతమైతే{' '}
                    <code className="font-mono text-glow">generate_token()</code> ఒక JWT ను
                    జారీ చేస్తుంది.
                  </p>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <span className="chip">
                      <BadgeCheck className="h-3 w-3 text-success" />
                      2 verified citations
                    </span>
                    <span className="chip">
                      <ShieldCheck className="h-3 w-3" />
                      Grounded in retrieved code
                    </span>
                  </div>
                </div>

                <div className="bg-raised/40 p-4">
                  <p className="mb-2 font-mono text-[11px] uppercase tracking-wide text-muted">
                    Evidence
                  </p>
                  <div className="space-y-2">
                    {[
                      { path: 'auth/login.py', range: '39–61', symbol: 'login()' },
                      { path: 'auth/login.py', range: '22–36', symbol: 'generate_token()' },
                    ].map((c) => (
                      <div key={c.path + c.range} className="rounded-xl border border-line bg-surface p-2.5">
                        <code className="block font-mono text-[11px] text-glow">{c.path}</code>
                        <p className="mt-0.5 text-[10px] text-muted">
                          lines {c.range} · {c.symbol}
                        </p>
                        <pre className="mt-1.5 overflow-hidden rounded-lg bg-code/70 p-1.5 font-mono text-[10px] text-ink/85">
{`def login():`}
                        </pre>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 text-[10px] leading-relaxed text-muted">
                    Illustration of the output format. In the running app these values come from
                    your repository and the live Sarvam response.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Built for understanding, not guessing
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            The hard part of explaining code is not writing prose — it is being right about which
            file, which function and which line. CodeSathi treats that as the core problem.
          </p>

          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                icon: ScanSearch,
                title: 'Evidence first',
                body: 'Your question is matched against an index of real files and symbols. Only the most relevant snippets are sent to the model — never the whole repository.',
              },
              {
                icon: ShieldCheck,
                title: 'Citations that are checked',
                body: 'Every citation the model returns is re-validated against the current project: the file must exist and the line range must be real, or it is flagged as unverified.',
              },
              {
                icon: Languages,
                title: 'Your language, your script',
                body: 'Ask in Telugu, English, Hindi or Tamil — or mix them. Code identifiers, file paths and keywords stay unchanged; only the explanation is translated.',
              },
              {
                icon: Boxes,
                title: 'Real indexing',
                body: 'Python is parsed with its own AST for exact function, class and route locations. Other languages use a conservative scanner that never over-claims.',
              },
              {
                icon: FileSearch,
                title: 'A workspace, not a chat box',
                body: 'A file tree, a conversation, and an evidence explorer side by side. Click a citation and land on the exact lines.',
              },
              {
                icon: Lock,
                title: 'Safe by default',
                body: 'Uploads are size- and count-bounded, path traversal and symlinks are refused, secrets and binaries are skipped, and uploaded code is never executed. Accounts use PBKDF2-hashed passwords and server-side sessions.',
              },
            ].map((f) => (
              <div key={f.title} className="panel p-5">
                <f.icon className="h-5 w-5 text-glow" />
                <h3 className="mt-3 text-sm font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Workflow */}
      <section id="workflow" className="border-b border-line bg-surface/50">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">How it works</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            Four steps, all of them inspectable.
          </p>

          <ol className="mt-8 grid gap-4 md:grid-cols-4">
            {[
              {
                n: '01',
                title: 'Upload a ZIP',
                body: 'The archive is validated and extracted safely. Dependencies, build output, binaries and secret files are dropped.',
              },
              {
                n: '02',
                title: 'Index the source',
                body: 'Files are indexed with exact line numbers. Python functions, classes, imports and routes are extracted with the AST.',
              },
              {
                n: '03',
                title: 'Retrieve evidence',
                body: 'Your question selects the most relevant snippets within a fixed context budget. You can see exactly which ones were chosen.',
              },
              {
                n: '04',
                title: 'Explain & verify',
                body: 'Sarvam writes the explanation in your language; the backend validates every citation before showing it as evidence.',
              },
            ].map((s) => (
              <li key={s.n} className="panel p-5">
                <span className="font-mono text-xs font-bold text-glow">{s.n}</span>
                <h3 className="mt-2 text-sm font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Languages */}
      <section id="languages" className="border-b border-line">
        <div className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Supported languages</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            Answer language is selectable per question, so you can ask in English and read in
            Telugu, or switch mid-session. Availability follows the Sarvam model&apos;s own
            language coverage.
          </p>

          <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {LANGUAGES.map((l) => (
              <div key={l.code} className="panel flex items-center justify-between p-4">
                <div>
                  <p className="text-sm font-semibold">{l.label}</p>
                  <p className="text-xs text-muted">{l.native}</p>
                </div>
                <span className="chip font-mono">{l.code}</span>
              </div>
            ))}
          </div>

          <div className="panel mt-4 p-4 text-xs leading-relaxed text-muted">
            <Terminal className="mb-2 h-4 w-4 text-glow" />
            Code-mixed questions work too. The retriever understands romanised Indic question
            words — for example <span className="font-mono text-ink">login ela work avutundi</span>{' '}
            is mapped onto the English concepts that actually appear in source code.
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-4 py-16">
        <div className="panel grid-bg p-8 text-center sm:p-12">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Open a repository and ask your first question
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-muted">
            Try the bundled sample project — a small Flask service with real login, database and
            routing code — without uploading anything.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <button type="button" onClick={onExplore} className="btn-primary !px-5 !py-2.5">
              Explore Your Codebase
              <ArrowRight className="h-4 w-4" />
            </button>
            <button type="button" onClick={onHowItWorks} className="btn-ghost !px-5 !py-2.5">
              See How It Works
            </button>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-muted sm:flex-row">
          <Logo size="sm" />
          <p>
            A hackathon project built with Sarvam AI · explanations are AI-generated and citations
            are validated against your own repository.
          </p>
        </div>
      </footer>
    </div>
  )
}
