import { getColumnText } from './sessionCatalog'
import type { ColumnId, LibraryRecord, SessionRecord } from './types'

export type TableColumnFilter = {
  columnId: ColumnId
  values: string[]
}

export function applyTableColumnFilters(
  sessions: SessionRecord[],
  filters: TableColumnFilter[],
  libraries: LibraryRecord[],
) {
  const activeFilters = filters.filter((filter) => filter.values.length > 0)
  if (activeFilters.length === 0) {
    return sessions
  }

  return sessions.filter((session) =>
    activeFilters.every((filter) => {
      const acceptedValues = new Set(filter.values.map(normalized))
      return tableFilterValues(session, filter.columnId, libraries).some((value) => acceptedValues.has(normalized(value)))
    }),
  )
}

export function tableColumnFilterOptions(
  sessions: SessionRecord[],
  columnId: ColumnId,
  libraries: LibraryRecord[],
) {
  return uniqueStrings(sessions.flatMap((session) => tableFilterValues(session, columnId, libraries)))
}

export function tableFilterLabel(
  columnId: ColumnId,
  libraries: LibraryRecord[],
  value: string,
) {
  if (columnId !== 'library') {
    return value
  }
  return libraries.find((libraryItem) => libraryItem.id === value)?.name ?? value
}

function tableFilterValues(session: SessionRecord, columnId: ColumnId, libraries: LibraryRecord[]) {
  if (columnId === 'signals') {
    return session.signals
  }
  if (columnId === 'library') {
    return [session.libraryId]
  }
  return [getColumnText(session, columnId, libraries)]
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true }),
  )
}

function normalized(value: string) {
  return value.trim().toLowerCase()
}
