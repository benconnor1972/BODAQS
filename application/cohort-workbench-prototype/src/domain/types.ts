export type NoteStatus = 'missing' | 'draft' | 'edited'
export type QcLevel = 'ok' | 'warning' | 'alert'
export type SortDirection = 'asc' | 'desc'
export type SessionInspectionTab = 'note' | 'qc' | 'metadata'
export type StudySetModalMode = 'view' | 'analyze'

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
  pointCount: number
  distanceKm: number
  points: Array<[number, number]>
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

export type ModalState =
  | { kind: 'session'; tab: SessionInspectionTab; session: SessionRecord }
  | { kind: 'track'; track: TrackRecord }
  | { kind: 'study-set'; studySet: StudySet; mode: StudySetModalMode }
  | null
