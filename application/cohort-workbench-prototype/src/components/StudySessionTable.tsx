import type { KeyboardEvent, MouseEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { columnLabels, getColumnText, isInfoActionColumn } from '../domain/sessionCatalog'
import { sessionByRef, sessionRefId } from '../domain/studySets'
import type {
  ColumnId,
  LibraryRecord,
  SessionInspectionTab,
  SessionRecord,
  StudySet,
} from '../domain/types'
import { IconButton } from './Common'
import type { SessionSelectionGesture } from './SessionTable'
import {
  SessionInfoButtons,
  sessionInfoActionForColumn,
  type SessionInfoAction,
} from './SessionInfoButtons'

export function StudySessionTable({
  studySet,
  libraries,
  sessions,
  visibleColumns,
  selectedStudySessionIds,
  primaryStudySessionId,
  onSelect,
  onRemove,
  onInspect,
}: {
  studySet: StudySet
  libraries: LibraryRecord[]
  sessions: SessionRecord[]
  visibleColumns: ColumnId[]
  selectedStudySessionIds: string[]
  primaryStudySessionId: string | null
  onSelect: (refId: string, gesture: SessionSelectionGesture) => void
  onRemove: (refId: string) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
}) {
  const inheritedColumns = visibleColumns.filter((columnId) => columnId !== 'name' && !isInfoActionColumn(columnId))
  const inheritedInfoActions = visibleColumns
    .map(sessionInfoActionForColumn)
    .filter((action): action is SessionInfoAction => Boolean(action))
  const emptyColSpan = inheritedColumns.length + 3

  return (
    <>
      <div className="table-shell study-table-shell">
        <table className="session-table study-session-table">
          <thead>
            <tr>
              <th>Name</th>
              {inheritedColumns.map((columnId) => (
                <th key={columnId}>{columnLabels[columnId]}</th>
              ))}
              <th>Groupings</th>
              <th className="info-action-heading">
                <span title="Session actions" />
              </th>
            </tr>
          </thead>
          <tbody>
            {studySet.sessions.length === 0 && (
              <tr>
                <td className="empty-cell" colSpan={emptyColSpan}>
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
              const isSelected = selectedStudySessionIds.includes(refId)
              const isPrimary = primaryStudySessionId === refId
              return (
                <tr
                  aria-current={isPrimary ? 'true' : undefined}
                  aria-selected={isSelected}
                  className={['session-row', isSelected ? 'selected' : '', isPrimary ? 'primary-row' : ''].join(' ')}
                  key={refId}
                  onClick={(event) => onSelect(refId, mouseGesture(event))}
                  onKeyDown={(event) => handleRowKeyDown(event, refId, onSelect)}
                  tabIndex={0}
                >
                  <td>{sessionRef.label}</td>
                  {inheritedColumns.map((columnId) => (
                    <td key={columnId}>{session ? getColumnText(session, columnId, libraries) : '-'}</td>
                  ))}
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
                  <td
                    className="icon-cluster info-action-cell session-info-action-cell"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <div className="row-action-strip">
                      {session && inheritedInfoActions.length > 0 && (
                        <span className="row-info-action-group">
                          <SessionInfoButtons session={session} onInspect={onInspect} actions={inheritedInfoActions} />
                        </span>
                      )}
                      <IconButton label="Remove session" onClick={() => onRemove(refId)} icon={<Trash2 size={15} />} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function mouseGesture(event: MouseEvent<HTMLTableRowElement>): SessionSelectionGesture {
  return {
    extendRange: event.shiftKey,
    toggle: event.ctrlKey || event.metaKey,
  }
}

function handleRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
  refId: string,
  onSelect: (refId: string, gesture: SessionSelectionGesture) => void,
) {
  if (event.key === 'Enter') {
    event.preventDefault()
    onSelect(refId, { extendRange: event.shiftKey, toggle: event.ctrlKey || event.metaKey })
  }
  if (event.key === ' ') {
    event.preventDefault()
    onSelect(refId, { extendRange: event.shiftKey, toggle: true })
  }
}
