export type NoteStatus = 'finished' | 'draft' | 'none'
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
  sessionId: string
  sessionKey: string
  name: string
  date: string
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
  libraryId: string
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
  | 'date'
  | 'library'
  | 'bike'
  | 'rider'
  | 'duration'
  | 'distance'
  | 'note'
  | 'qc'
  | 'profile'

export type ModalState =
  | { kind: 'session'; tab: SessionInspectionTab; session: SessionRecord }
  | { kind: 'track'; track: TrackRecord }
  | { kind: 'study-set'; studySet: StudySet; mode: StudySetModalMode }
  | null
