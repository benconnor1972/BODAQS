import type { SessionRecord } from './types'

export type SessionFilterField =
  | 'bike'
  | 'event.schema'
  | 'firmware'
  | 'gps.present'
  | 'gps.quality'
  | 'gps.source'
  | 'note.status'
  | 'preprocessing.profile'
  | 'qc.level'
  | 'rider'
  | 'signals'
  | 'source.archive'
  | 'trackpoint.crossing'

export type TrackpointCrossingFilterValue = {
  track_id?: string
  trackId?: string
  trackpoint_id?: string
  trackpointId?: string
  trackpoint_ids?: string[]
  trackpointIds?: string[]
  match_mode?: 'any' | 'all' | 'min_count'
  matchMode?: 'any' | 'all' | 'min_count'
  tolerance_m?: number
  toleranceM?: number
  min_count?: number
  minCount?: number
}

export type TrackpointCrossingSpec = {
  key: string
  trackId: string
  trackpointIds: string[]
  matchMode: 'any' | 'all' | 'min_count'
  toleranceM: number
  minCount?: number
  libraryIds: string[]
}

export type SessionFilterPredicate =
  | {
      op: 'and' | 'or'
      children: SessionFilterPredicate[]
    }
  | {
      field: 'trackpoint.crossing'
      op: 'matches'
      value: TrackpointCrossingFilterValue
    }
  | {
      field: Exclude<SessionFilterField, 'trackpoint.crossing'>
      op: 'contains' | 'eq' | 'in' | 'present'
      value?: boolean | string | string[]
    }

export type SavedSessionFilterRecord = {
  id: string
  displayName: string
  description: string
  category: string
  origin: 'prototype_saved' | 'api_saved'
  revision: number
  predicate: SessionFilterPredicate
}

export const prototypeSavedSessionFilters: SavedSessionFilterRecord[] = [
  {
    id: 'ben-rides',
    displayName: "Ben's rides",
    description: 'Prototype saved filter matching rider fields that contain Ben.',
    category: 'people',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'rider', op: 'contains', value: 'ben' },
  },
  {
    id: 'notes-edited',
    displayName: 'Edited notes',
    description: 'Sessions with reviewed or edited notes.',
    category: 'notes-qc',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'note.status', op: 'eq', value: 'edited' },
  },
  {
    id: 'notes-need-review',
    displayName: 'Notes need review',
    description: 'Sessions with missing or draft notes.',
    category: 'notes-qc',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'note.status', op: 'in', value: ['missing', 'draft'] },
  },
  {
    id: 'qc-no-alerts',
    displayName: 'No QC alerts',
    description: 'Sessions with no QC alert-level metadata.',
    category: 'notes-qc',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'qc.level', op: 'in', value: ['ok', 'warning'] },
  },
  {
    id: 'qc-clean',
    displayName: 'QC clean',
    description: 'Sessions with an OK QC level.',
    category: 'notes-qc',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'qc.level', op: 'eq', value: 'ok' },
  },
  {
    id: 'has-usable-gps',
    displayName: 'Usable GPS',
    description: 'Sessions with usable GPS coverage.',
    category: 'gps',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'gps.quality', op: 'eq', value: 'usable' },
  },
  {
    id: 'has-any-gps',
    displayName: 'Any GPS',
    description: 'Sessions with any GPS source present.',
    category: 'gps',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'gps.present', op: 'present', value: true },
  },
  {
    id: 'gps-fit-enriched',
    displayName: 'FIT-enriched GPS',
    description: 'Sessions using FIT enrichment as a GPS source.',
    category: 'gps',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'gps.source', op: 'eq', value: 'fit_enrichment' },
  },
  {
    id: 'gps-logger-sensor',
    displayName: 'Logger GPS sensor',
    description: 'Sessions using logger-sensor GPS.',
    category: 'gps',
    origin: 'prototype_saved',
    revision: 0,
    predicate: { field: 'gps.source', op: 'eq', value: 'logger_sensor' },
  },
  {
    id: 'has-accelerometer',
    displayName: 'Accelerometer data',
    description: 'Sessions with accelerometer or IMU signal names.',
    category: 'data',
    origin: 'prototype_saved',
    revision: 0,
    predicate: {
      op: 'or',
      children: [
        { field: 'signals', op: 'contains', value: 'accel' },
        { field: 'signals', op: 'contains', value: 'accelerometer' },
        { field: 'signals', op: 'contains', value: 'imu' },
      ],
    },
  },
  {
    id: 'has-suspension',
    displayName: 'Suspension signals',
    description: 'Sessions with front or rear suspension signal names.',
    category: 'data',
    origin: 'prototype_saved',
    revision: 0,
    predicate: {
      op: 'or',
      children: [
        { field: 'signals', op: 'contains', value: 'front' },
        { field: 'signals', op: 'contains', value: 'rear' },
        { field: 'signals', op: 'contains', value: 'suspension' },
      ],
    },
  },
]

export function applySavedSessionFilters(
  sessions: SessionRecord[],
  filters: SavedSessionFilterRecord[],
  options: {
    trackpointCrossingMatches?: Record<string, string[]>
    pendingTrackpointCrossingKeys?: Set<string>
    libraryIds?: string[]
  } = {},
) {
  if (filters.length === 0) {
    return sessions
  }
  return sessions.filter((session) => filters.every((filter) => sessionMatchesPredicate(session, filter.predicate, options)))
}

export function trackpointCrossingSpecsForFilters(
  filters: SavedSessionFilterRecord[],
  libraryIds: string[],
): TrackpointCrossingSpec[] {
  const specs = new Map<string, TrackpointCrossingSpec>()
  for (const filter of filters) {
    for (const predicate of trackpointCrossingPredicates(filter.predicate)) {
      const spec = trackpointCrossingSpecFromValue(predicate.value, libraryIds)
      if (spec) {
        specs.set(spec.key, spec)
      }
    }
  }
  return Array.from(specs.values()).sort((a, b) => a.key.localeCompare(b.key))
}

export function savedFilterCategoryLabel(category: string) {
  switch (category) {
    case 'data':
      return 'Data coverage'
    case 'gps':
      return 'GPS'
    case 'notes-qc':
      return 'Notes and QC'
    case 'people':
      return 'People'
    case 'processing':
      return 'Processing'
    case 'custom':
      return 'Custom'
    default:
      return category
  }
}

function sessionMatchesPredicate(
  session: SessionRecord,
  predicate: SessionFilterPredicate,
  options: {
    trackpointCrossingMatches?: Record<string, string[]>
    pendingTrackpointCrossingKeys?: Set<string>
    libraryIds?: string[]
  },
): boolean {
  if ('children' in predicate) {
    if (predicate.op === 'and') {
      return predicate.children.every((child) => sessionMatchesPredicate(session, child, options))
    }
    return predicate.children.some((child) => sessionMatchesPredicate(session, child, options))
  }

  if (predicate.field === 'trackpoint.crossing') {
    const spec = trackpointCrossingSpecFromValue(predicate.value, options.libraryIds ?? [])
    if (!spec) {
      return false
    }
    if (options.pendingTrackpointCrossingKeys?.has(spec.key)) {
      return true
    }
    const matchedRefs = options.trackpointCrossingMatches?.[spec.key]
    if (!matchedRefs) {
      return true
    }
    return matchedRefs.includes(sessionFilterSessionRefId(session))
  }

  const values = fieldValues(session, predicate.field)
  if (predicate.op === 'present') {
    if (typeof predicate.value === 'boolean') {
      return values.some((value) => Boolean(value)) === predicate.value
    }
    return values.some((value) => Boolean(String(value).trim()))
  }
  if (predicate.op === 'eq') {
    return values.some((value) => normalized(value) === normalized(predicate.value))
  }
  if (predicate.op === 'in') {
    const expected = Array.isArray(predicate.value) ? predicate.value.map(normalized) : [normalized(predicate.value)]
    return values.some((value) => expected.includes(normalized(value)))
  }
  if (predicate.op === 'contains') {
    const expected = normalized(predicate.value)
    return values.some((value) => normalized(value).includes(expected))
  }
  return false
}

function fieldValues(session: SessionRecord, field: SessionFilterField): Array<boolean | string> {
  switch (field) {
    case 'bike':
      return [session.bike]
    case 'event.schema':
      return [session.eventSchema]
    case 'firmware':
      return [session.firmware]
    case 'gps.present':
      return [session.gpsSummary.present]
    case 'gps.quality':
      return [session.gpsSummary.quality]
    case 'gps.source':
      return [
        session.gpsSummary.preferredSourceId ?? '',
        session.gpsSummary.preferredSourceKind ?? '',
        ...session.gpsSummary.sources.map((source) => source.kind),
        ...session.gpsSummary.sources.map((source) => source.sourceId),
        ...session.gpsSummary.sources.map((source) => source.streamName),
      ]
    case 'note.status':
      return [session.noteStatus]
    case 'preprocessing.profile':
      return [session.preprocessingProfile]
    case 'qc.level':
      return [session.qcLevel]
    case 'rider':
      return [session.rider]
    case 'signals':
      return session.signals
    case 'source.archive':
      return [session.sourceArchive]
    case 'trackpoint.crossing':
      return []
  }
}

function normalized(value: unknown) {
  return String(value ?? '').trim().toLowerCase()
}

function trackpointCrossingPredicates(predicate: SessionFilterPredicate): Array<Extract<SessionFilterPredicate, { field: 'trackpoint.crossing' }>> {
  if ('children' in predicate) {
    return predicate.children.flatMap(trackpointCrossingPredicates)
  }
  return predicate.field === 'trackpoint.crossing' ? [predicate] : []
}

function trackpointCrossingSpecFromValue(
  value: TrackpointCrossingFilterValue,
  libraryIds: string[],
): TrackpointCrossingSpec | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const trackId = textValue(value.track_id ?? value.trackId)
  const rawTrackpointIds =
    value.trackpoint_ids ?? value.trackpointIds ?? (value.trackpoint_id ?? value.trackpointId ? [value.trackpoint_id ?? value.trackpointId] : [])
  const trackpointIds = Array.from(new Set((rawTrackpointIds ?? []).map(textValue).filter(Boolean))).sort()
  if (!trackId || trackpointIds.length === 0) {
    return null
  }
  const matchMode = matchModeValue(value.match_mode ?? value.matchMode)
  const toleranceM = numberValue(value.tolerance_m ?? value.toleranceM, 5)
  const minCount = matchMode === 'min_count' ? numberValue(value.min_count ?? value.minCount, trackpointIds.length) : undefined
  const scopedLibraryIds = Array.from(new Set(libraryIds.map(textValue).filter(Boolean))).sort()
  const key = JSON.stringify({
    field: 'trackpoint.crossing',
    trackId,
    trackpointIds,
    matchMode,
    toleranceM,
    minCount,
    libraryIds: scopedLibraryIds,
  })
  return {
    key,
    trackId,
    trackpointIds,
    matchMode,
    toleranceM,
    minCount,
    libraryIds: scopedLibraryIds,
  }
}

function sessionFilterSessionRefId(session: SessionRecord) {
  return `${session.libraryId}|||${session.sessionKey}`
}

function textValue(value: unknown) {
  return String(value ?? '').trim()
}

function numberValue(value: unknown, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function matchModeValue(value: unknown): 'any' | 'all' | 'min_count' {
  if (value === 'any' || value === 'min_count') {
    return value
  }
  return 'all'
}
