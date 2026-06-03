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

export type SessionFilterPredicate =
  | {
      op: 'and' | 'or'
      children: SessionFilterPredicate[]
    }
  | {
      field: SessionFilterField
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

export function applySavedSessionFilters(sessions: SessionRecord[], filters: SavedSessionFilterRecord[]) {
  if (filters.length === 0) {
    return sessions
  }
  return sessions.filter((session) => filters.every((filter) => sessionMatchesPredicate(session, filter.predicate)))
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
    default:
      return category
  }
}

function sessionMatchesPredicate(session: SessionRecord, predicate: SessionFilterPredicate): boolean {
  if ('children' in predicate) {
    if (predicate.op === 'and') {
      return predicate.children.every((child) => sessionMatchesPredicate(session, child))
    }
    return predicate.children.some((child) => sessionMatchesPredicate(session, child))
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
        session.gpsSummary.preferredSource ?? '',
        ...session.gpsSummary.sources.map((source) => source.kind),
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
  }
}

function normalized(value: unknown) {
  return String(value ?? '').trim().toLowerCase()
}
