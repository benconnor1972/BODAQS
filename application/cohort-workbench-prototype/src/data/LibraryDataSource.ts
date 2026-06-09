import type {
  LibraryRecord,
  SessionGpsPointSet,
  SessionNoteRecord,
  SessionRecord,
  SessionTrackMatchRecord,
  StudySet,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryRequest,
  TrackpointMatchQueryResults,
  TrackRecord,
} from '../domain/types'
import type { SavedSessionFilterRecord } from '../domain/sessionFilters'

export interface LibraryDataSource {
  listLibraries(): Promise<LibraryRecord[]>
  listSessions(): Promise<SessionRecord[]>
  listTracks(): Promise<TrackRecord[]>
  listStudySets(): Promise<StudySet[]>
  listSavedSessionFilters?(): Promise<SavedSessionFilterRecord[]>
  saveStudySet(studySet: StudySet): Promise<StudySet>
  saveSavedSessionFilter?(filter: SavedSessionFilterRecord): Promise<SavedSessionFilterRecord>
  deleteSavedSessionFilter?(filterId: string): Promise<void>
  saveTrack?(track: TrackRecord): Promise<TrackRecord>
  deleteTrack?(trackId: string): Promise<void>
  listTrackMatches?(studySet: StudySet): Promise<SessionTrackMatchRecord[]>
  createTrackpointMatchQuery?(request: TrackpointMatchQueryRequest): Promise<TrackpointMatchQueryRecord>
  loadTrackpointMatchQuery?(queryId: string): Promise<TrackpointMatchQueryRecord>
  loadTrackpointMatchQueryResults?(queryId: string, cursor?: string | null, limit?: number): Promise<TrackpointMatchQueryResults>
  cancelTrackpointMatchQuery?(queryId: string): Promise<TrackpointMatchQueryRecord>
  loadSessionGpsPoints?(session: SessionRecord): Promise<SessionGpsPointSet>
  loadSessionNote?(session: SessionRecord): Promise<SessionNoteRecord>
  saveSessionNote?(note: SessionNoteRecord): Promise<SessionNoteRecord>
}
