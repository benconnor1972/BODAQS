export type NoteStatus = 'missing' | 'draft' | 'edited'
export type QcLevel = 'ok' | 'warning' | 'alert'
export type SortDirection = 'asc' | 'desc'
export type SessionInspectionTab = 'note' | 'qc' | 'gps' | 'metadata'
export type StudySetModalMode = 'view' | 'analyze'
export type GpsQuality = 'absent' | 'limited' | 'usable' | 'invalid'
export type GpsSourceKind = 'logger_sensor' | 'fit_enrichment' | 'imported_route' | 'unknown'
export type GpsTimebase = 'uniform' | 'intermittent' | 'unknown'
export type TrackMatchStatus = 'matched' | 'partial' | 'no_gps' | 'no_overlap' | 'ambiguous' | 'failed'
export type TrackDirection = 'positive' | 'reverse' | 'unknown'

export type SessionGpsSourceSummary = {
  sourceId: string
  kind: GpsSourceKind
  streamName: string
  timebase: GpsTimebase
  pointCount: number
  nominalSampleRateHz: number | null
  medianGapS: number | null
  maxGapS: number | null
  gapCountOverThreshold?: number
  gapThresholdS?: number
}

export type SessionGpsSummary = {
  present: boolean
  preferredSource: GpsSourceKind | null
  sources: SessionGpsSourceSummary[]
  sessionDurationS: number
  timeCoverageRatio: number
  positionPointCount: number
  quality: GpsQuality
  warnings: string[]
}

export type SessionGpsPoint = {
  timeS: number | null
  longitude: number
  latitude: number
  elevationM: number | null
}

export type SessionGpsPointSet = {
  present: boolean
  sourceId: string
  sourceKind: GpsSourceKind
  streamName: string
  samplingMode: string
  sourcePoints: number
  returnedPoints: number
  maxPoints: number
  stride: number | null
  points: SessionGpsPoint[]
  path: Array<[number, number]>
  warnings: string[]
}

export type LibraryRecord = {
  id: string
  name: string
  path: string
  sessionCount: number
}

export type SessionRecord = {
  libraryId: string
  runId: string
  runName: string
  sessionId: string
  sessionKey: string
  name: string
  startedAt: string
  bike: string
  rider: string
  durationMin: number
  distanceKm: number
  noteStatus: NoteStatus
  qcLevel: QcLevel
  qcAlerts: string[]
  preprocessingProfile: string
  firmware: string
  eventSchema: string
  sourceArchive: string
  signals: string[]
  gps: Array<[number, number]>
  gpsSummary: SessionGpsSummary
}

export type SessionNoteValue = string | number | boolean | string[] | null

export type SessionNoteFieldType = 'string' | 'text' | 'int' | 'float' | 'bool' | 'enum' | 'multi_enum' | 'date'

export type StudySessionRef = {
  libraryId: string
  sessionKey: string
  runId: string
  sessionId: string
  label: string
}

export type SessionNoteRecord = {
  sessionRef: StudySessionRef
  present: boolean
  title: string
  templateId: string
  templateVersion: string
  templateStatus: 'ok' | 'missing'
  templateError: string
  fields: SessionNoteFieldDef[]
  customFieldSection: string
  values: Record<string, SessionNoteValue>
  customValues: Record<string, SessionNoteValue>
  freeTextNotes: string
  draft: boolean
  createdAtUtc: string
  updatedAtUtc: string
}

export type SessionNoteFieldDef = {
  fieldId: string
  label: string
  fieldType: SessionNoteFieldType
  section: string
  required: boolean
  default: SessionNoteValue
  unit: string
  helpText: string
  enumOptions: string[]
}

export type TrackpointMatchMode = 'any' | 'all' | 'min_count'
export type TrackpointMatchQueryStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'

export type TrackpointMatchQueryRequest = {
  trackId: string
  trackpointIds: string[]
  matchMode: TrackpointMatchMode
  toleranceM: number
  minCount?: number
  scope?: {
    libraryIds?: string[]
    sessionRefs?: StudySessionRef[]
  }
  persist?: boolean
}

export type TrackpointMatchQueryRecord = {
  queryId: string
  status: TrackpointMatchQueryStatus
  trackId: string
  trackRevision: number
  trackpointIds: string[]
  matchMode: TrackpointMatchMode
  toleranceM: number
  candidateSessionCount: number
  processedSessionCount: number
  matchedSessionCount: number
  failedSessionCount: number
  error: string
}

export type TrackpointMatchQueryResult = {
  sessionRef: StudySessionRef
  trackMatchId: string
  matchedTrackpointIds: string[]
  missingTrackpointIds: string[]
  quality: string
}

export type TrackpointMatchQueryResults = {
  queryId: string
  resultCount: number
  returnedCount: number
  nextCursor: string | null
  results: TrackpointMatchQueryResult[]
}

export type StudyGrouping = {
  id: string
  name: string
  color: string
  sessionRefs: string[]
}

export type TrackRecord = {
  id: string
  name: string
  description?: string
  revision: number
  pointCount: number
  distanceKm: number
  lengthM: number
  points: Array<[number, number]>
  defaultPolicyId: string
  trackpoints: TrackpointRecord[]
  matchSummaries: SessionTrackMatchRecord[]
  source?: {
    kind: string
    libraryId?: string
    sessionRefId?: string
    sessionKey?: string
    runId?: string
    sessionId?: string
  }
}

export type TrackpointRecord = {
  id: string
  name: string
  stationM: number
  position: [number, number]
  cutlineOverride?: {
    leftLengthM?: number
    rightLengthM?: number
    angleDegFromPathNormal?: number
  }
}

export type GeospatialPolicyRecord = {
  id: string
  name: string
  defaultCutlineLeftLengthM: number
  defaultCutlineRightLengthM: number
  maxPointDistanceM: number
  reverseDirectionPolicy: 'reject' | 'allow_and_report' | 'infer_direction'
}

export type SessionTrackMatchRecord = {
  trackId: string
  sessionRefId: string
  status: TrackMatchStatus
  direction: TrackDirection
  coverageRatio: number
  matchedGpsPointCount: number
  trackpointResults: Array<{
    trackpointId: string
    crossed: boolean
    crossingTimeS: number | null
    minDistanceM: number | null
    quality: 'good' | 'approximate' | 'ambiguous' | 'missing'
  }>
  warnings: string[]
}

export type StudySet = {
  id: string | null
  displayName: string
  revision: number
  saved: boolean
  sessions: StudySessionRef[]
  groupings: StudyGrouping[]
  trackIds: string[]
  provenance: string
}

export type ColumnId =
  | 'name'
  | 'runName'
  | 'started'
  | 'library'
  | 'runId'
  | 'sessionId'
  | 'bike'
  | 'rider'
  | 'duration'
  | 'distance'
  | 'profile'
  | 'eventSchema'
  | 'firmware'
  | 'source'
  | 'signals'
  | 'gps'

export type ModalState =
  | { kind: 'session'; tab: SessionInspectionTab; session: SessionRecord }
  | { kind: 'track'; track: TrackRecord }
  | { kind: 'study-set'; studySet: StudySet; mode: StudySetModalMode }
  | null
