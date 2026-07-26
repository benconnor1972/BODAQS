export type NoteStatus = 'missing' | 'draft' | 'edited'
export type QcLevel = 'ok' | 'warning' | 'alert'
export type SortDirection = 'asc' | 'desc'
export type SessionInspectionTab = 'note' | 'qc' | 'gps' | 'signals' | 'metadata'
export type StudySetModalMode = 'view' | 'analyze'
export type GpsQuality = 'absent' | 'limited' | 'usable' | 'invalid'
export type GpsSourceKind = 'logger_sensor' | 'fit_enrichment' | 'imported_route' | 'unknown'
export type GpsTimebase = 'uniform' | 'intermittent' | 'unknown'
export type TrackMatchStatus = 'matched' | 'partial' | 'no_gps' | 'no_overlap' | 'ambiguous' | 'failed'
export type TrackDirection = 'positive' | 'reverse' | 'unknown'
export type SignalRole = 'front' | 'rear' | 'unknown'
export type GeoPosition = [number, number] | [number, number, number]

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
  qualityColumns?: Record<string, string>
  routeReconstruction?: Record<string, unknown>
  validCoverageRatio?: number | null
  freshCoverageRatio?: number | null
  dedupeMethod?: string | null
  cachedAsyncSnapshots?: boolean | null
}

export type SessionGpsSummary = {
  present: boolean
  preferredSourceId: string | null
  preferredSourceKind: GpsSourceKind | null
  sourceSelectionMethod: string
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
  sourceSelectionMethod?: string
  sourcePolicy?: Record<string, unknown>
  routeReconstruction?: Record<string, unknown>
  points: SessionGpsPoint[]
  path: GeoPosition[]
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
  sessionLabel?: string
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
  availableSignals?: SessionSignalSummary[]
  gps: Array<[number, number]>
  gpsSummary: SessionGpsSummary
}

export type SessionSignalSummary = {
  signalId: string
  column: string
  displayName: string
  end: string
  domain: string
  quantity: string
  unit: string
  processingRole: string
  kind: string
  sensor: string
  motionSourceId?: string
  origin: string
  derivation?: Record<string, unknown>
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
  exactSessionCount: number
  skippedSessionCount: number
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
  points: GeoPosition[]
  defaultPolicyId: string
  trackpoints: TrackpointRecord[]
  segmentAliases?: TrackSegmentAliasRecord[]
  matchSummaries: SessionTrackMatchRecord[]
  source?: {
    kind: string
    libraryId?: string
    sessionRefId?: string
    sessionKey?: string
    runId?: string
    sessionId?: string
    gpsSourceId?: string
    gpsSourceKind?: GpsSourceKind
    gpsStreamName?: string
    gpsSourceSelectionMethod?: string
  }
}

export type TrackSegmentAliasRecord = {
  fromTrackpointId: string
  toTrackpointId: string
  name: string
}

export type TrackpointRecord = {
  id: string
  name: string
  stationM: number
  position: GeoPosition
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

export type AnalysisAdequacyStatus = 'ready' | 'warning' | 'partial' | 'blocked' | 'unknown'
export type AnalysisRequirementTier = 'required' | 'recommended' | 'optional'

export type AnalysisRequirementRecord = {
  requirementId: string
  label: string
  tier: AnalysisRequirementTier
  description: string
}

export type AnalysisViewRecord = {
  id: string
  displayName: string
  category: string
  description: string
  route: string
  adequacyPolicy: string
  requirements: Record<string, AnalysisRequirementRecord[]>
}

export type AnalysisAdequacyMessage = {
  level: 'info' | 'warning' | 'error'
  code: string
  message: string
  sessionRef?: StudySessionRef
  detail?: Record<string, unknown>
}

export type AnalysisAdequacySessionResult = {
  sessionRef: StudySessionRef
  status: AnalysisAdequacyStatus
  summary: string
  requiredPassed: boolean
  recommendedMissing: string[]
  optionalMissing: string[]
  units?: Record<string, unknown>
}

export type AnalysisAdequacyResult = {
  viewId: string
  displayName: string
  status: AnalysisAdequacyStatus
  policy: string
  summary: string
  totalSessionCount: number
  usableSessionCount: number
  blockedSessionCount: number
  messages: AnalysisAdequacyMessage[]
  sessionResults: AnalysisAdequacySessionResult[]
}

export type SignalQuerySignalRequest = {
  role: string
  selector?: Record<string, unknown>
  column?: string
}

export type SignalQueryRequest = {
  sessions: StudySessionRef[]
  signals: SignalQuerySignalRequest[]
}

export type SignalQuerySignal = {
  role: string
  signalId: string
  column: string
  displayName: string
  end: string
  domain: string
  quantity: string
  unit: string
  processingRole: string
  kind: string
  sensor: string
  motionSourceId?: string
  origin: string
  derivation?: Record<string, unknown>
  values: Array<number | null>
}

export type SignalQuerySession = {
  sessionRef: StudySessionRef
  time: {
    column: string
    unit: string
    values: Array<number | null>
  } | null
  sampling: {
    mode: string
    sourcePoints: number
    returnedPoints: number
    distributionCorrect: boolean
  }
  signals: SignalQuerySignal[]
}

export type SignalQueryResponse = {
  sessions: SignalQuerySession[]
  warnings: Array<Record<string, unknown>>
}

export type TimeseriesWindowSignalRequest = {
  selector?: Record<string, unknown>
  column?: string
}

export type TimeseriesWindowRequest = {
  session: StudySessionRef
  signals: TimeseriesWindowSignalRequest[]
  window?: {
    startS?: number | null
    endS?: number | null
  }
  resolution?: {
    targetPoints?: number
  }
  includeEvents?: boolean
  includeMarks?: boolean
}

export type TimeseriesWindowSignal = SessionSignalSummary & {
  values: Array<number | null>
}

export type TimeseriesWindowEvent = {
  eventId: string
  eventType: string
  displayName: string
  startS: number | null
  endS: number | null
  peakTimeS: number | null
  end: string
  metrics?: Record<string, unknown>
}

export type TimeseriesWindowMark = {
  markId: string
  timeS: number
  displayName: string
  column: string
}

export type TimeseriesWindowResponse = {
  sessionRef: StudySessionRef
  window: {
    requestedStartS: number | null
    requestedEndS: number | null
    returnedStartS: number | null
    returnedEndS: number | null
  }
  sampling: {
    mode: string
    sourcePoints: number
    returnedPoints: number
    targetPoints: number
  }
  time: {
    column: string
    unit: string
    values: Array<number | null>
  }
  signals: TimeseriesWindowSignal[]
  events: TimeseriesWindowEvent[]
  marks: TimeseriesWindowMark[]
  warnings: string[]
}

export type SessionBookmarkRecord = {
  id: string
  revision: number
  title: string
  description: string
  sessionRef: StudySessionRef
  window: {
    startS: number
    endS: number
  }
  viewState: {
    signalInspector?: {
      signalColumns: string[]
      showMarks: boolean
    }
    [key: string]: unknown
  }
  tags: string[]
  private: boolean
  createdAtUtc: string
  updatedAtUtc: string
}

export type TableQueryRequest = {
  sessions: StudySessionRef[]
  eventTypes?: string[]
}

export type TableQueryRow = {
  sessionRef: StudySessionRef
  setId: string
  rowIndex: number
  eventType: string
  signalRole: SignalRole
  fields: Record<string, unknown>
}

export type TableQueryResponse = {
  rowKind: 'event' | 'metric'
  rowCount: number
  rows: TableQueryRow[]
  warnings: Array<Record<string, unknown>>
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
  | 'noteAction'
  | 'qaAction'
  | 'gpsAction'
  | 'signalInspectorAction'
  | 'metadataAction'

export type ModalState =
  | { kind: 'session'; tab: SessionInspectionTab; session: SessionRecord }
  | { kind: 'signal-inspector'; session: SessionRecord; initialWindow?: { startS: number; endS: number } | null }
  | { kind: 'track'; track: TrackRecord }
  | { kind: 'analysis-launcher'; studySet: StudySet }
  | { kind: 'study-set'; studySet: StudySet; mode: StudySetModalMode }
  | null
