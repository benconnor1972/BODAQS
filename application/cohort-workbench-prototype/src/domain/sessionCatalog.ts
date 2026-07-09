import { gpsSummaryLine } from './geospatial'
import type { ColumnId, LibraryRecord, SessionRecord, SortDirection } from './types'

export type ColumnGroup = {
  id: string
  label: string
  columns: ColumnId[]
}

export type ColumnPreset = {
  id: string
  label: string
  description: string
  columns: ColumnId[]
}

export const columnLabels: Record<ColumnId, string> = {
  name: 'Session',
  runName: 'Run',
  started: 'Started',
  library: 'Library',
  runId: 'Run ID',
  sessionId: 'Session ID',
  bike: 'Bike',
  rider: 'Rider',
  duration: 'Duration',
  distance: 'Distance',
  profile: 'Preprocess',
  eventSchema: 'Event schema',
  firmware: 'Firmware',
  source: 'Source',
  signals: 'Signals',
  gps: 'GPS',
  noteAction: 'Notes',
  qaAction: 'QA',
  gpsAction: 'GPS',
  signalInspectorAction: 'Inspect signals',
  metadataAction: 'Metadata',
}

export const infoActionColumns = [
  'noteAction',
  'qaAction',
  'gpsAction',
  'signalInspectorAction',
  'metadataAction',
] as const satisfies readonly ColumnId[]

export type InfoActionColumn = (typeof infoActionColumns)[number]

export const allColumns: ColumnId[] = [
  'name',
  'runName',
  'started',
  'library',
  'runId',
  'sessionId',
  'bike',
  'rider',
  'duration',
  'distance',
  'profile',
  'eventSchema',
  'firmware',
  'source',
  'signals',
  'gps',
  ...infoActionColumns,
]

export const lockedColumns: ColumnId[] = []

export const defaultColumns: ColumnId[] = normalizeColumnSelection([
  'name',
  'runName',
  'started',
  'library',
  'bike',
  'rider',
  'noteAction',
  'qaAction',
  'gpsAction',
  'signalInspectorAction',
  'metadataAction',
])

export const columnGroups: ColumnGroup[] = [
  {
    id: 'identity',
    label: 'Identity',
    columns: ['name', 'runName', 'started', 'library', 'runId', 'sessionId'],
  },
  {
    id: 'setup',
    label: 'Setup',
    columns: ['bike', 'rider', 'duration', 'distance'],
  },
  {
    id: 'processing',
    label: 'Processing',
    columns: ['profile', 'eventSchema', 'firmware'],
  },
  {
    id: 'source-signals',
    label: 'Source and signals',
    columns: ['source', 'signals', 'gps'],
  },
  {
    id: 'info',
    label: 'Info',
    columns: [...infoActionColumns],
  },
]

export const columnPresets: ColumnPreset[] = [
  {
    id: 'compact',
    label: 'Compact',
    description: 'Core browsing fields.',
    columns: ['name', 'runName', 'started', 'library'],
  },
  {
    id: 'setup',
    label: 'Setup',
    description: 'Rider, bike, and ride shape.',
    columns: ['name', 'runName', 'started', 'bike', 'rider', 'duration', 'distance'],
  },
  {
    id: 'provenance',
    label: 'Provenance',
    description: 'IDs, processing, and source context.',
    columns: ['name', 'library', 'runId', 'sessionId', 'profile', 'eventSchema', 'firmware', 'source'],
  },
  {
    id: 'signals',
    label: 'Signals',
    description: 'Signal coverage and source archive.',
    columns: ['name', 'started', 'source', 'signals', 'gps'],
  },
  {
    id: 'geospatial',
    label: 'Geospatial',
    description: 'GPS quality and source context.',
    columns: ['name', 'runName', 'started', 'distance', 'gps'],
  },
  {
    id: 'all',
    label: 'All',
    description: 'Every available catalog column.',
    columns: allColumns,
  },
]

export function normalizeColumnSelection(columns: ColumnId[]) {
  const normalized: ColumnId[] = []

  function append(columnId: ColumnId) {
    if (!allColumns.includes(columnId) || normalized.includes(columnId)) {
      return
    }
    normalized.push(columnId)
  }

  lockedColumns.forEach(append)
  columns.forEach(append)
  return normalized
}

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
    case 'runName':
      return session.runName
    case 'started':
      return formatStartedAt(session.startedAt)
    case 'library':
      return libraryName(libraries, session.libraryId)
    case 'runId':
      return session.runId
    case 'sessionId':
      return session.sessionId
    case 'bike':
      return session.bike
    case 'rider':
      return session.rider
    case 'duration':
      return `${session.durationMin.toFixed(1)} min`
    case 'distance':
      return `${session.distanceKm.toFixed(1)} km`
    case 'profile':
      return session.preprocessingProfile
    case 'eventSchema':
      return session.eventSchema
    case 'firmware':
      return session.firmware
    case 'source':
      return session.sourceArchive
    case 'signals':
      return session.signals.join(', ')
    case 'gps':
      return gpsSummaryLine(session.gpsSummary)
    case 'noteAction':
      return session.noteStatus
    case 'qaAction':
      return `${session.qcLevel} ${session.qcAlerts.length}`
    case 'gpsAction':
      return gpsSummaryLine(session.gpsSummary)
    case 'signalInspectorAction':
      return session.signals.join(', ')
    case 'metadataAction':
      return `${session.runId} ${session.sessionId} ${session.sourceArchive}`
  }
}

export function isInfoActionColumn(columnId: ColumnId): columnId is InfoActionColumn {
  return (infoActionColumns as readonly ColumnId[]).includes(columnId)
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

function formatStartedAt(value: string) {
  const trimmed = value.trim()
  if (!trimmed) {
    return ''
  }
  const timestamp = trimmed.replace('T', ' ').replace(/\+.*$/, '').replace(/Z$/, '').slice(0, 16)
  return isUtcTimestamp(trimmed) ? `${timestamp} UTC` : timestamp
}

function isUtcTimestamp(value: string) {
  return value.endsWith('Z') || value.includes('+00:00')
}
