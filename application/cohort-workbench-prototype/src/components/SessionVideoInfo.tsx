import { useEffect, useState } from 'react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { SessionRecord, SessionVideoAttachmentsRecord } from '../domain/types'

export function SessionVideoInfo({ session, dataSource, onOpenInspector }: {
  session: SessionRecord
  dataSource: LibraryDataSource
  onOpenInspector: () => void
}) {
  const [result, setResult] = useState<{
    session: SessionRecord
    dataSource: LibraryDataSource
    data: SessionVideoAttachmentsRecord | null
    message: string
  } | null>(null)
  const current = result?.session === session && result.dataSource === dataSource ? result : null
  const data = current?.data
  const message = current?.message ?? (dataSource.loadSessionVideoAttachments
    ? 'Loading video attachments...'
    : 'Video attachment details are unavailable from this data source.')

  useEffect(() => {
    let cancelled = false
    if (!dataSource.loadSessionVideoAttachments) return
    void dataSource.loadSessionVideoAttachments(session).then((loaded) => {
      if (!cancelled) {
        setResult({ session, dataSource, data: loaded, message: loaded.attachments.length ? '' : 'No video attached.' })
      }
    }).catch((error: unknown) => {
      if (!cancelled) setResult({ session, dataSource, data: null, message: error instanceof Error ? error.message : 'Could not load video attachments.' })
    })
    return () => { cancelled = true }
  }, [dataSource, session])

  return (
    <div>
      {message && <p className="modal-note">{message}</p>}
      {data?.attachments.map((attachment) => (
        <section className="modal-section" key={attachment.attachmentId}>
          <h3>{attachment.displayName || 'Session video'}</h3>
          <dl className="detail-list">
            <dt>Camera</dt><dd>{attachment.cameraLabel || 'Unspecified'}</dd>
            <dt>Status</dt><dd>{attachment.enabled ? 'Enabled' : 'Disabled'}</dd>
            <dt>Path</dt><dd style={{ overflowWrap: 'anywhere' }}>{attachment.workspaceRelativePath || attachment.libraryRelativePath || attachment.sessionRelativePath || attachment.path || attachment.uri || 'Unspecified'}</dd>
            <dt>Media type</dt><dd>{attachment.mediaType || 'Unspecified'}</dd>
            <dt>Video zero at session time</dt><dd>{attachment.sessionTimeAtVideoZeroS} s</dd>
          </dl>
        </section>
      ))}
      <button className="secondary-action" type="button" onClick={onOpenInspector}>Manage video in Signal Inspector</button>
    </div>
  )
}
