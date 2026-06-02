import { cloneStudySet, slugify, uniqueId } from '../domain/studySets'
import type { SessionGpsPointSet, SessionGpsSummary, SessionRecord, StudySet, TrackRecord } from '../domain/types'
import {
  fixtureLibraries,
  fixtureSavedStudySets,
  fixtureSessions,
  fixtureTracks,
} from './fixtures'
import type { LibraryDataSource } from './LibraryDataSource'

export class FixtureLibraryDataSource implements LibraryDataSource {
  private savedStudySets = fixtureSavedStudySets.map(cloneStudySet)
  private tracks = fixtureTracks.map(cloneTrack)

  async listLibraries() {
    return fixtureLibraries.map((libraryItem) => ({ ...libraryItem }))
  }

  async listSessions() {
    return fixtureSessions.map(cloneSession)
  }

  async listTracks() {
    return this.tracks.map(cloneTrack)
  }

  async listStudySets() {
    return this.savedStudySets.map(cloneStudySet)
  }

  async saveStudySet(studySet: StudySet) {
    const displayName = studySet.displayName.trim()
    const existingIds = this.savedStudySets
      .map((savedStudySet) => savedStudySet.id)
      .filter((id): id is string => Boolean(id))
    const nextId = studySet.id ?? uniqueId(slugify(displayName), existingIds)
    const previous = this.savedStudySets.find((savedStudySet) => savedStudySet.id === nextId)
    const saved: StudySet = {
      ...cloneStudySet(studySet),
      id: nextId,
      displayName,
      revision: previous ? previous.revision + 1 : 1,
      saved: true,
      provenance: studySet.provenance || 'Created in the Library Browser prototype',
    }
    const exists = this.savedStudySets.some((savedStudySet) => savedStudySet.id === nextId)
    this.savedStudySets = exists
      ? this.savedStudySets.map((savedStudySet) => (savedStudySet.id === nextId ? saved : savedStudySet))
      : [...this.savedStudySets, saved]
    return cloneStudySet(saved)
  }

  async saveTrack(track: TrackRecord) {
    const displayName = track.name.trim()
    const existingIds = this.tracks.map((savedTrack) => savedTrack.id)
    const nextId = track.id || uniqueId(slugify(displayName), existingIds)
    const previous = this.tracks.find((savedTrack) => savedTrack.id === nextId)
    const saved: TrackRecord = {
      ...cloneTrack(track),
      id: nextId,
      name: displayName,
      revision: previous ? previous.revision + 1 : 1,
      pointCount: track.points.length,
      distanceKm: track.lengthM / 1000,
      matchSummaries: previous?.matchSummaries ?? [],
    }
    const exists = this.tracks.some((savedTrack) => savedTrack.id === nextId)
    this.tracks = exists
      ? this.tracks.map((savedTrack) => (savedTrack.id === nextId ? saved : savedTrack))
      : [...this.tracks, saved]
    return cloneTrack(saved)
  }

  async deleteTrack(trackId: string) {
    this.tracks = this.tracks.filter((track) => track.id !== trackId)
  }

  async loadSessionGpsPoints(session: SessionRecord): Promise<SessionGpsPointSet> {
    return {
      present: session.gps.length > 0,
      sourceId: session.gpsSummary.sources[0]?.sourceId ?? '',
      sourceKind: session.gpsSummary.preferredSource ?? 'unknown',
      streamName: session.gpsSummary.sources[0]?.streamName ?? '',
      samplingMode: 'fixture',
      sourcePoints: session.gpsSummary.positionPointCount,
      returnedPoints: session.gps.length,
      maxPoints: session.gps.length,
      stride: null,
      points: session.gps.map(([longitude, latitude], index) => ({
        timeS: index,
        longitude,
        latitude,
        elevationM: null,
      })),
      path: session.gps.map(([longitude, latitude]) => [longitude, latitude] as [number, number]),
      warnings: [...session.gpsSummary.warnings],
    }
  }
}

function cloneSession(session: SessionRecord): SessionRecord {
  return {
    ...session,
    qcAlerts: [...session.qcAlerts],
    signals: [...session.signals],
    gps: session.gps.map(([x, y]) => [x, y]),
    gpsSummary: cloneGpsSummary(session.gpsSummary),
  }
}

function cloneTrack(track: TrackRecord): TrackRecord {
  return {
    ...track,
    points: track.points.map(([x, y]) => [x, y]),
    trackpoints: track.trackpoints.map((trackpoint) => ({
      ...trackpoint,
      position: [trackpoint.position[0], trackpoint.position[1]] as [number, number],
      cutlineOverride: trackpoint.cutlineOverride ? { ...trackpoint.cutlineOverride } : undefined,
    })),
    matchSummaries: track.matchSummaries.map((match) => ({
      ...match,
      trackpointResults: match.trackpointResults.map((result) => ({ ...result })),
      warnings: [...match.warnings],
    })),
    source: track.source ? { ...track.source } : undefined,
  }
}

function cloneGpsSummary(summary: SessionGpsSummary): SessionGpsSummary {
  return {
    ...summary,
    sources: summary.sources.map((source) => ({ ...source })),
    warnings: [...summary.warnings],
  }
}
