import type { ColumnId, LibraryRecord, SessionRecord, SortDirection } from './types'

export const columnLabels: Record<ColumnId, string> = {
  name: 'Name',
  date: 'Date',
  library: 'Library',
  bike: 'Bike',
  rider: 'Rider',
  duration: 'Duration',
  distance: 'Distance',
  note: 'Note',
  qc: 'QC',
  profile: 'Profile',
}

export const defaultColumns: ColumnId[] = [
  'name',
  'date',
  'library',
  'bike',
  'rider',
  'note',
  'qc',
]

export function libraryName(libraries: LibraryRecord[], libraryId: string) {
  return libraries.find((libraryItem) => libraryItem.id === libraryId)?.name ?? libraryId
}

export function getColumnText(
  session: SessionRecord,
  columnId: ColumnId,
  libraries: LibraryRecord[],
) {
  switch (columnId) {
    case 'name':
      return session.name
    case 'date':
      return session.date
    case 'library':
      return libraryName(libraries, session.libraryId)
    case 'bike':
      return session.bike
    case 'rider':
      return session.rider
    case 'duration':
      return `${session.durationMin.toFixed(1)} min`
    case 'distance':
      return `${session.distanceKm.toFixed(1)} km`
    case 'note':
      return session.noteStatus
    case 'qc':
      return session.qcLevel
    case 'profile':
      return session.preprocessingProfile
  }
}

export function sortSessions(
  input: SessionRecord[],
  columnId: ColumnId,
  direction: SortDirection,
  libraries: LibraryRecord[],
) {
  const directionFactor = direction === 'asc' ? 1 : -1
  return [...input].sort((a, b) => {
    const aValue = getColumnText(a, columnId, libraries)
    const bValue = getColumnText(b, columnId, libraries)
    return String(aValue).localeCompare(String(bValue), undefined, { numeric: true }) * directionFactor
  })
}

export function matchesSearch(
  session: SessionRecord,
  text: string,
  visibleColumns: ColumnId[],
  libraries: LibraryRecord[],
) {
  const query = text.trim().toLowerCase()
  if (!query) {
    return true
  }
  return visibleColumns.some((columnId) =>
    getColumnText(session, columnId, libraries).toLowerCase().includes(query),
  )
}
