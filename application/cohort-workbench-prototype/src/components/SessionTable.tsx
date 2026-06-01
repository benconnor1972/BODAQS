import { AlertTriangle, FileText, Info } from 'lucide-react'
import { columnLabels, getColumnText } from '../domain/sessionCatalog'
import { candidateId } from '../domain/studySets'
import type {
  ColumnId,
  LibraryRecord,
  SessionInspectionTab,
  SessionRecord,
  SortDirection,
} from '../domain/types'
import { IconButton } from './Common'
import { NoteBadge, QcBadge } from './StatusBadges'

export function SessionTable({
  sessions: tableSessions,
  libraries,
  visibleColumns,
  selectedIds,
  primaryId,
  sortColumn,
  sortDirection,
  onSort,
  onToggle,
  onSelectSingle,
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
  onToggle: (session: SessionRecord) => void
  onSelectSingle: (session: SessionRecord) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
}) {
  return (
    <div className="table-shell">
      <table className="session-table">
        <thead>
          <tr>
            <th className="select-col">Sel</th>
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
            return (
              <tr
                className={[isSelected ? 'selected' : '', primaryId === id ? 'primary-row' : ''].join(' ')}
                key={id}
                onClick={() => onSelectSingle(session)}
              >
                <td className="select-col" onClick={(event) => event.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggle(session)}
                    aria-label={`Select ${session.name}`}
                  />
                </td>
                {visibleColumns.map((columnId) => (
                  <td key={columnId}>{renderSessionCell(session, columnId, libraries)}</td>
                ))}
                <td className="icon-cluster" onClick={(event) => event.stopPropagation()}>
                  <IconButton label="View note" onClick={() => onInspect(session, 'note')} icon={<FileText size={15} />} />
                  <IconButton label="View QC" onClick={() => onInspect(session, 'qc')} icon={<AlertTriangle size={15} />} />
                  <IconButton label="View metadata" onClick={() => onInspect(session, 'metadata')} icon={<Info size={15} />} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function renderSessionCell(session: SessionRecord, columnId: ColumnId, libraries: LibraryRecord[]) {
  if (columnId === 'note') {
    return <NoteBadge status={session.noteStatus} />
  }
  if (columnId === 'qc') {
    return <QcBadge session={session} />
  }
  return getColumnText(session, columnId, libraries)
}
