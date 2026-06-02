import type {
  LibraryRecord,
  SessionGpsPointSet,
  SessionRecord,
  SessionTrackMatchRecord,
  StudySet,
  TrackRecord,
} from '../domain/types'

export interface LibraryDataSource {
  listLibraries(): Promise<LibraryRecord[]>
  listSessions(): Promise<SessionRecord[]>
  listTracks(): Promise<TrackRecord[]>
  listStudySets(): Promise<StudySet[]>
  saveStudySet(studySet: StudySet): Promise<StudySet>
  saveTrack?(track: TrackRecord): Promise<TrackRecord>
  deleteTrack?(trackId: string): Promise<void>
  listTrackMatches?(studySet: StudySet): Promise<SessionTrackMatchRecord[]>
  loadSessionGpsPoints?(session: SessionRecord): Promise<SessionGpsPointSet>
}
