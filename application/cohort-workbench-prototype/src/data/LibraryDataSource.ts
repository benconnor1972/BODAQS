import type {
  AnalysisAdequacyResult,
  AnalysisViewRecord,
  LibraryRecord,
  LocalVideoFileSelection,
  SessionGpsPointSet,
  SessionBookmarkRecord,
  SessionNoteRecord,
  SessionRecord,
  SessionVideoAttachmentsRecord,
  SessionTrackMatchRecord,
  SignalQueryRequest,
  SignalQueryResponse,
  StudySessionRef,
  StudySet,
  TableQueryRequest,
  TableQueryResponse,
  TimeseriesWindowRequest,
  TimeseriesWindowResponse,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryRequest,
  TrackpointMatchQueryResults,
  TrackRecord,
} from '../domain/types'
import type { SavedSessionFilterRecord } from '../domain/sessionFilters'

export type WorkbenchBootstrapData = {
  libraries: LibraryRecord[]
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  studySets: StudySet[]
  savedFilters: SavedSessionFilterRecord[]
  timings?: Record<string, unknown>
}

export type CatalogRevision = {
  libraryId: string
  revision: number
}

export type SignalSetDefinition = {
  id: string
  displayName: string
  description: string
  defaultSelectionSetId?: string
  defaultExclusionRules?: Array<Record<string, unknown>>
  rules: Array<Record<string, unknown>>
}

export type SessionNoteSaveResult =
  | { ok: true; note: SessionNoteRecord }
  | { ok: false; sessionRef: StudySessionRef; message: string }

export interface LibraryDataSource {
  listLibraries(): Promise<LibraryRecord[]>
  refreshLibrary?(libraryId: string): Promise<LibraryRecord | void>
  loadWorkbenchBootstrap?(): Promise<WorkbenchBootstrapData>
  listCatalogRevisions?(): Promise<CatalogRevision[]>
  loadSignalSets?(): Promise<SignalSetDefinition[]>
  listSessions(libraries?: LibraryRecord[]): Promise<SessionRecord[]>
  listTracks(): Promise<TrackRecord[]>
  listStudySets(): Promise<StudySet[]>
  loadStudySet?(studySetId: string): Promise<StudySet>
  listAnalysisViews?(): Promise<AnalysisViewRecord[]>
  evaluateAnalysisAdequacy?(viewId: string, studySet: StudySet): Promise<AnalysisAdequacyResult>
  listSavedSessionFilters?(): Promise<SavedSessionFilterRecord[]>
  saveStudySet(studySet: StudySet): Promise<StudySet>
  deleteStudySet?(studySetId: string): Promise<void>
  deleteSession?(
    session: SessionRecord,
    options?: { cleanupMemberships?: boolean },
  ): Promise<Record<string, unknown>>
  renameSession?(session: SessionRecord, name: string): Promise<SessionRecord>
  saveSavedSessionFilter?(filter: SavedSessionFilterRecord): Promise<SavedSessionFilterRecord>
  deleteSavedSessionFilter?(filterId: string): Promise<void>
  saveTrack?(track: TrackRecord): Promise<TrackRecord>
  deleteTrack?(trackId: string): Promise<void>
  listTrackMatches?(studySet: StudySet): Promise<SessionTrackMatchRecord[]>
  createTrackpointMatchQuery?(request: TrackpointMatchQueryRequest): Promise<TrackpointMatchQueryRecord>
  loadTrackpointMatchQuery?(queryId: string): Promise<TrackpointMatchQueryRecord>
  loadTrackpointMatchQueryResults?(queryId: string, cursor?: string | null, limit?: number): Promise<TrackpointMatchQueryResults>
  cancelTrackpointMatchQuery?(queryId: string): Promise<TrackpointMatchQueryRecord>
  loadSessionGpsPoints?(session: SessionRecord, sourceId?: string | null): Promise<SessionGpsPointSet>
  loadSessionNote?(session: SessionRecord): Promise<SessionNoteRecord>
  saveSessionNote?(note: SessionNoteRecord): Promise<SessionNoteRecord>
  saveSessionNotes?(notes: SessionNoteRecord[]): Promise<SessionNoteSaveResult[]>
  loadSessionVideoAttachments?(session: SessionRecord): Promise<SessionVideoAttachmentsRecord>
  saveSessionVideoAttachments?(attachments: SessionVideoAttachmentsRecord): Promise<SessionVideoAttachmentsRecord>
  sessionVideoStreamUrl?(session: SessionRecord, attachmentId: string): string
  selectLocalVideoFile?(): Promise<LocalVideoFileSelection>
  listSessionBookmarks(session: SessionRecord): Promise<SessionBookmarkRecord[]>
  saveSessionBookmark(bookmark: SessionBookmarkRecord): Promise<SessionBookmarkRecord>
  deleteSessionBookmark(bookmarkId: string): Promise<void>
  loadTimeseriesWindow(libraryId: string, request: TimeseriesWindowRequest): Promise<TimeseriesWindowResponse>
  querySignals(libraryId: string, request: SignalQueryRequest): Promise<SignalQueryResponse>
  queryEvents(libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse>
  queryMetrics(libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse>
}
