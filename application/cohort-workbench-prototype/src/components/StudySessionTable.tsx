import { AlertTriangle, FileText, Trash2 } from 'lucide-react'
import { sessionByRef, sessionRefId } from '../domain/studySets'
import type { SessionInspectionTab, SessionRecord, StudySet } from '../domain/types'
import { IconButton } from './Common'
import { NoteBadge, QcBadge } from './StatusBadges'

export function StudySessionTable({
  studySet,
  sessions,
  selectedStudySessionIds,
  onToggle,
  onRemove,
  onInspect,
}: {
  studySet: StudySet
  sessions: SessionRecord[]
  selectedStudySessionIds: string[]
  onToggle: (refId: string) => void
  onRemove: (refId: string) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
}) {
  return (
    <div className="table-shell study-table-shell">
      <table className="session-table study-session-table">
        <thead>
          <tr>
            <th className="select-col">Use</th>
            <th>Name</th>
            <th>Date</th>
            <th>Bike</th>
            <th>Rider</th>
            <th>Note</th>
            <th>QC</th>
            <th>Groupings</th>
            <th>Controls</th>
          </tr>
        </thead>
        <tbody>
          {studySet.sessions.length === 0 && (
            <tr>
              <td className="empty-cell" colSpan={9}>
                No sessions in the current Study Set.
              </td>
            </tr>
          )}
          {studySet.sessions.map((sessionRef) => {
            const refId = sessionRefId(sessionRef)
            const session = sessionByRef(sessionRef, sessions)
            const groupingMatches = studySet.groupings.filter((grouping) =>
              grouping.sessionRefs.includes(refId),
            )
            return (
              <tr key={refId}>
                <td className="select-col">
                  <input
                    type="checkbox"
                    checked={selectedStudySessionIds.includes(refId)}
                    onChange={() => onToggle(refId)}
                    aria-label={`Select ${sessionRef.label} for grouping`}
                  />
                </td>
                <td>{sessionRef.label}</td>
                <td>{session?.date ?? '-'}</td>
                <td>{session?.bike ?? '-'}</td>
                <td>{session?.rider ?? '-'}</td>
                <td>{session ? <NoteBadge status={session.noteStatus} /> : '-'}</td>
                <td>{session ? <QcBadge session={session} /> : '-'}</td>
                <td>
                  <div className="badge-row">
                    {groupingMatches.length === 0 && <span className="subtle">none</span>}
                    {groupingMatches.map((grouping) => (
                      <span className="mini-group" style={{ borderColor: grouping.color }} key={grouping.id}>
                        {grouping.name}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="icon-cluster">
                  {session && (
                    <>
                      <IconButton label="View note" onClick={() => onInspect(session, 'note')} icon={<FileText size={15} />} />
                      <IconButton label="View QC" onClick={() => onInspect(session, 'qc')} icon={<AlertTriangle size={15} />} />
                    </>
                  )}
                  <IconButton label="Remove session" onClick={() => onRemove(refId)} icon={<Trash2 size={15} />} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
