import type { KeyboardEvent, MouseEvent } from 'react'
import { columnLabels, getColumnText } from '../domain/sessionCatalog'
import { candidateId } from '../domain/studySets'
import type {
  ColumnId,
  LibraryRecord,
  SessionInspectionTab,
  SessionRecord,
  SortDirection,
} from '../domain/types'
import { SessionInfoButtons } from './SessionInfoButtons'

export type SessionSelectionGesture = {
  extendRange: boolean
  toggle: boolean
}

export function SessionTable({
  sessions: tableSessions,
  libraries,
  visibleColumns,
  selectedIds,
  primaryId,
  sortColumn,
  sortDirection,
  onSort,
  onSelect,
  onInspect,
}: {
  sessions: SessionRecord[]
  libraries: LibraryRecord[]
  visibleColumns: ColumnId[]
  selectedIds: string[]
  primaryId: string | null
  sortColumn: ColumnId
  sortDirection: SortDirection
  onSort: (columnId: ColumnId) => void
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
}) {
  return (
    <>
      <p className="selection-hint">
        Click a row to select it. Ctrl/Cmd-click toggles rows; Shift-click selects a range. The last selected row is primary.
      </p>
      <div className="table-shell">
        <table className="session-table" aria-label="Candidate sessions">
          <thead>
            <tr>
              {visibleColumns.map((columnId) => (
                <th key={columnId}>
                  <button className="sort-button" onClick={() => onSort(columnId)}>
                    {columnLabels[columnId]}
                    {sortColumn === columnId && <span>{sortDirection === 'asc' ? 'up' : 'down'}</span>}
                  </button>
                </th>
              ))}
              <th>Info</th>
            </tr>
          </thead>
          <tbody>
            {tableSessions.map((session) => {
              const id = candidateId(session)
              const isSelected = selectedIds.includes(id)
              const isPrimary = primaryId === id
              return (
                <tr
                  aria-current={isPrimary ? 'true' : undefined}
                  aria-selected={isSelected}
                  className={[
                    'session-row',
                    isSelected ? 'selected' : '',
                    isPrimary ? 'primary-row' : '',
                  ].join(' ')}
                  key={id}
                  onClick={(event) => onSelect(session, mouseGesture(event))}
                  onKeyDown={(event) => handleRowKeyDown(event, session, onSelect)}
                  tabIndex={0}
                >
                  {visibleColumns.map((columnId) => (
                    <td key={columnId}>{renderSessionCell(session, columnId, libraries)}</td>
                  ))}
                  <td className="icon-cluster" onClick={(event) => event.stopPropagation()}>
                    <SessionInfoButtons session={session} onInspect={onInspect} />
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

function renderSessionCell(session: SessionRecord, columnId: ColumnId, libraries: LibraryRecord[]) {
  return getColumnText(session, columnId, libraries)
}

function mouseGesture(event: MouseEvent<HTMLTableRowElement>): SessionSelectionGesture {
  return {
    extendRange: event.shiftKey,
    toggle: event.ctrlKey || event.metaKey,
  }
}

function handleRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
  session: SessionRecord,
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void,
) {
  if (event.key === 'Enter') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: event.ctrlKey || event.metaKey })
  }
  if (event.key === ' ') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: true })
  }
}
