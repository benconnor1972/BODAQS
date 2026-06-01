import type { NoteStatus, SessionRecord } from '../domain/types'

export function NoteBadge({ status }: { status: NoteStatus }) {
  const label = status === 'finished' ? 'finished' : status === 'draft' ? 'draft' : 'none'
  return <span className={`pill note-${status}`}>{label}</span>
}

export function QcBadge({ session }: { session: SessionRecord }) {
  const label = session.qcLevel === 'ok' ? 'clear' : `${session.qcAlerts.length} ${session.qcLevel}`
  return <span className={`pill qc-${session.qcLevel}`}>{label}</span>
}
