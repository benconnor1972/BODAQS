import { ExternalLink, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

const WALKTHROUGH_VIDEOS = [
  {
    title: 'BODAQS Workbench: first analysis',
    description: 'Explore the demo library and simple suspension metrics.',
    href: 'https://youtu.be/HjcBr6v1-Ec?si=DsW_EbhhPCR1otQ2',
  },
  {
    title: 'BODAQS Workbench: the Signal Inspector',
    description: 'In detail with the underlying data, including video synchronisation. Walkthrough video coming soon.',
    href: null,
  },
  {
    title: 'BODAQS Workbench: Tracks and lap timing',
    description: 'Setting up tracks, segments and timing comparisons. Walkthrough video coming soon.',
    href: null,
  },
]

const DESKTOP_INSTALL_VIDEO = {
  title: 'Download and install BODAQS Desktop',
  href: 'https://youtu.be/V4gr8XfFBcc?si=XJwLHi5YHer0pZt-',
}

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
          <section aria-label="Walkthrough videos" className="demo-welcome-videos">
            <h3>Walkthrough videos</h3>
            {WALKTHROUGH_VIDEOS.map((video) =>
              video.href ? (
                <a className="demo-welcome-video" href={video.href} key={video.title} rel="noreferrer" target="_blank">
                  <span>
                    <strong>{video.title}</strong>
                    <small>{video.description}</small>
                  </span>
                  <ExternalLink aria-hidden="true" size={16} />
                </a>
              ) : (
                <div className="demo-welcome-video pending" key={video.title}>
                  <span>
                    <strong>{video.title}</strong>
                    <small>{video.description}</small>
                  </span>
                </div>
              ),
            )}
          </section>
          <section className="demo-welcome-desktop-note">
            <p>
              You can also install the BODAQS Desktop package - this is <em>not required</em> to try this demo.
            </p>
            <a className="demo-welcome-video" href={DESKTOP_INSTALL_VIDEO.href} rel="noreferrer" target="_blank">
              <span>
                <strong>{DESKTOP_INSTALL_VIDEO.title}</strong>
              </span>
              <ExternalLink aria-hidden="true" size={16} />
            </a>
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
