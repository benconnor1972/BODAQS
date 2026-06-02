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

export type StudySessionRef = {
  libraryId: string
  sessionKey: string
  runId: string
  sessionId: string
  label: string
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
  revision: number
  pointCount: number
  distanceKm: number
  lengthM: number
  points: Array<[number, number]>
  defaultPolicyId: string
  trackpoints: TrackpointRecord[]
  matchSummaries: SessionTrackMatchRecord[]
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
