import { cloneStudySet, sessionRefId, sessionToStudyRef, slugify, uniqueId } from '../domain/studySets'
import {
  prototypeSavedSessionFilters,
  type SavedSessionFilterRecord,
  type SessionFilterPredicate,
} from '../domain/sessionFilters'
import type {
  SessionGpsPointSet,
  SessionGpsSummary,
  SessionRecord,
  StudySet,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryRequest,
  TrackpointMatchQueryResult,
  TrackpointMatchQueryResults,
  TrackRecord,
} from '../domain/types'
import {
  fixtureLibraries,
  fixtureSavedStudySets,
  fixtureSessions,
  fixtureTracks,
} from './fixtures'
import type { LibraryDataSource } from './LibraryDataSource'

export class FixtureLibraryDataSource implements LibraryDataSource {
  private savedStudySets = fixtureSavedStudySets.map(cloneStudySet)
  private savedFilters = prototypeSavedSessionFilters.map(cloneSavedFilter)
  private trackpointQueries = new Map<string, { query: TrackpointMatchQueryRecord; results: TrackpointMatchQueryResult[] }>()
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

  async listSavedSessionFilters() {
    return this.savedFilters.map(cloneSavedFilter)
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

  async saveSavedSessionFilter(filter: SavedSessionFilterRecord) {
    const displayName = filter.displayName.trim()
    const existingIds = this.savedFilters.map((savedFilter) => savedFilter.id)
    const nextId = filter.origin === 'api_saved' && filter.id ? filter.id : uniqueId(slugify(displayName), existingIds)
    const previous = this.savedFilters.find((savedFilter) => savedFilter.id === nextId)
    const saved: SavedSessionFilterRecord = {
      ...cloneSavedFilter(filter),
      id: nextId,
      displayName,
      origin: 'api_saved',
      revision: previous ? previous.revision + 1 : 1,
    }
    const exists = this.savedFilters.some((savedFilter) => savedFilter.id === nextId)
    this.savedFilters = exists
      ? this.savedFilters.map((savedFilter) => (savedFilter.id === nextId ? saved : savedFilter))
      : [...this.savedFilters, saved]
    return cloneSavedFilter(saved)
  }

  async deleteSavedSessionFilter(filterId: string) {
    this.savedFilters = this.savedFilters.filter((filter) => filter.id !== filterId)
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

  async createTrackpointMatchQuery(request: TrackpointMatchQueryRequest) {
    const track = this.tracks.find((item) => item.id === request.trackId)
    const trackpointIds = request.trackpointIds.filter(Boolean)
    const libraryIds = request.scope?.libraryIds?.length
      ? request.scope.libraryIds
      : Array.from(new Set(fixtureSessions.map((session) => session.libraryId)))
    const candidateSessions = fixtureSessions.filter((session) => libraryIds.includes(session.libraryId))
    const queryId = uniqueId(
      slugify([request.trackId, ...trackpointIds, request.matchMode, String(request.toleranceM)].join(' ')),
      Array.from(this.trackpointQueries.keys()),
    )
    const results = track
      ? candidateSessions
          .map((session) => fixtureTrackpointResult(track, session, request))
          .filter((result): result is TrackpointMatchQueryResult => Boolean(result))
      : []
    const query: TrackpointMatchQueryRecord = {
      queryId,
      status: track ? 'completed' : 'failed',
      trackId: request.trackId,
      trackRevision: track?.revision ?? 0,
      trackpointIds,
      matchMode: request.matchMode,
      toleranceM: request.toleranceM,
      candidateSessionCount: candidateSessions.length,
      processedSessionCount: candidateSessions.length,
      matchedSessionCount: results.length,
      failedSessionCount: track ? 0 : candidateSessions.length,
      error: track ? '' : 'Fixture track not found.',
    }
    this.trackpointQueries.set(queryId, { query, results })
    return { ...query }
  }

  async loadTrackpointMatchQuery(queryId: string) {
    const stored = this.trackpointQueries.get(queryId)
    if (!stored) {
      throw new Error(`Fixture trackpoint query ${queryId} was not found.`)
    }
    return { ...stored.query }
  }

  async loadTrackpointMatchQueryResults(queryId: string, cursor: string | null = null, limit = 100): Promise<TrackpointMatchQueryResults> {
    const stored = this.trackpointQueries.get(queryId)
    if (!stored) {
      throw new Error(`Fixture trackpoint query ${queryId} was not found.`)
    }
    const start = cursor ? Number(cursor) : 0
    const safeStart = Number.isFinite(start) ? Math.max(0, start) : 0
    const safeLimit = Math.max(1, Math.min(500, limit))
    const page = stored.results.slice(safeStart, safeStart + safeLimit)
    const nextOffset = safeStart + page.length
    return {
      queryId,
      resultCount: stored.results.length,
      returnedCount: page.length,
      nextCursor: nextOffset < stored.results.length ? String(nextOffset) : null,
      results: page.map(cloneTrackpointMatchQueryResult),
    }
  }

  async cancelTrackpointMatchQuery(queryId: string) {
    const stored = this.trackpointQueries.get(queryId)
    if (!stored) {
      throw new Error(`Fixture trackpoint query ${queryId} was not found.`)
    }
    const query = { ...stored.query, status: 'cancelled' as const }
    this.trackpointQueries.set(queryId, { ...stored, query })
    return { ...query }
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

function fixtureTrackpointResult(
  track: TrackRecord,
  session: SessionRecord,
  request: TrackpointMatchQueryRequest,
): TrackpointMatchQueryResult | null {
  const match = track.matchSummaries.find((item) => item.sessionRefId === sessionRefId(sessionToStudyRef(session)))
  if (!match) {
    return null
  }
  const matchedTrackpointIds = match.trackpointResults
    .filter(
      (result) =>
        request.trackpointIds.includes(result.trackpointId) &&
        result.crossed &&
        result.minDistanceM !== null &&
        result.minDistanceM <= request.toleranceM,
    )
    .map((result) => result.trackpointId)
  const missingTrackpointIds = request.trackpointIds.filter((trackpointId) => !matchedTrackpointIds.includes(trackpointId))
  const minCount = request.minCount ?? request.trackpointIds.length
  const accepted =
    request.matchMode === 'all'
      ? missingTrackpointIds.length === 0
      : request.matchMode === 'any'
        ? matchedTrackpointIds.length > 0
        : matchedTrackpointIds.length >= minCount
  if (!accepted) {
    return null
  }
  return {
    sessionRef: sessionToStudyRef(session),
    trackMatchId: `${track.id}-${session.sessionKey}`,
    matchedTrackpointIds,
    missingTrackpointIds,
    quality: missingTrackpointIds.length ? 'partial' : 'good',
  }
}

function cloneTrackpointMatchQueryResult(result: TrackpointMatchQueryResult): TrackpointMatchQueryResult {
  return {
    ...result,
    sessionRef: { ...result.sessionRef },
    matchedTrackpointIds: [...result.matchedTrackpointIds],
    missingTrackpointIds: [...result.missingTrackpointIds],
  }
}

function cloneSavedFilter(filter: SavedSessionFilterRecord): SavedSessionFilterRecord {
  return {
    ...filter,
    predicate: clonePredicate(filter.predicate),
  }
}

function clonePredicate(predicate: SessionFilterPredicate): SessionFilterPredicate {
  return JSON.parse(JSON.stringify(predicate)) as SessionFilterPredicate
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
