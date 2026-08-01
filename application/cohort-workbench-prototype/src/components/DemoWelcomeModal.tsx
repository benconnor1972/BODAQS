import { ExternalLink, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

const BODAQS_YOUTUBE_URL = 'https://www.youtube.com/@BODAQS'

export function DemoWelcomeModal({ onClose }: { onClose: (suppressFutureSessions: boolean) => void }) {
  const [suppressFutureSessions, setSuppressFutureSessions] = useState(false)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose(suppressFutureSessions)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, suppressFutureSessions])

  return (
    <div className="demo-welcome-backdrop" role="presentation" onMouseDown={() => onClose(suppressFutureSessions)}>
      <section
        aria-labelledby="demo-welcome-title"
        aria-modal="true"
        className="demo-welcome-modal"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="demo-welcome-header">
          <div>
            <p className="demo-welcome-kicker">BODAQS DEMO</p>
            <h2 id="demo-welcome-title">Welcome to the BODAQS Workbench</h2>
          </div>
          <button
            aria-label="Close welcome"
            className="icon-button"
            onClick={() => onClose(suppressFutureSessions)}
            ref={closeButtonRef}
            type="button"
          >
            <X size={18} />
          </button>
        </header>
        <div className="demo-welcome-content">
          <p>
            This read-only demonstration lets you explore processed mountain-bike session data without a logger or
            local installation. Browse the library, build a temporary Study Set, and open the analysis views.
          </p>
          <p>
            Changes you make in the Workbench are local to this browser session and do not alter the demonstration
            library.
          </p>
          <section aria-label="BODAQS videos" className="demo-welcome-videos">
            <h3>Videos and walkthroughs</h3>
            <a className="demo-welcome-video" href={BODAQS_YOUTUBE_URL} rel="noreferrer" target="_blank">
              <span>
                <strong>BODAQS on YouTube</strong>
                <small>Watch the latest Workbench walkthroughs and installation guidance.</small>
              </span>
              <ExternalLink aria-hidden="true" size={16} />
            </a>
          </section>
          <section className="demo-welcome-desktop-note">
            <p>
              You can also install the BODAQS Desktop package - this is <em>not required</em> to try this demo.
            </p>
          </section>
          <label className="demo-welcome-preference">
            <input
              checked={suppressFutureSessions}
              onChange={(event) => setSuppressFutureSessions(event.target.checked)}
              type="checkbox"
            />
            Don&apos;t show this again on this device
          </label>
          <div className="demo-welcome-actions">
            <button className="primary-button" onClick={() => onClose(suppressFutureSessions)} type="button">
              Explore the demo
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
