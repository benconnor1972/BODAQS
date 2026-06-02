import { gpsQualityLabel } from '../domain/geospatial'
import type { NoteStatus, SessionGpsSummary, SessionRecord } from '../domain/types'

export function NoteBadge({ status }: { status: NoteStatus }) {
  const label = status === 'edited' ? 'edited' : status
  return <span className={`pill note-${status}`}>{label}</span>
}

export function QcBadge({ session }: { session: SessionRecord }) {
  const label = session.qcLevel === 'ok' ? 'clear' : `${session.qcAlerts.length} ${session.qcLevel}`
  return <span className={`pill qc-${session.qcLevel}`}>{label}</span>
}

export function GpsBadge({ summary }: { summary: SessionGpsSummary }) {
  return <span className={`pill gps-${summary.quality}`}>{gpsQualityLabel(summary.quality)}</span>
}
