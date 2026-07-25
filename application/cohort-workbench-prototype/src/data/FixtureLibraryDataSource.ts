import { cloneStudySet, sessionRefId, sessionToStudyRef, slugify, uniqueId } from '../domain/studySets'
import {
  prototypeSavedSessionFilters,
  type SavedSessionFilterRecord,
  type SessionFilterPredicate,
} from '../domain/sessionFilters'
import type {
  AnalysisAdequacyResult,
  AnalysisViewRecord,
  GeoPosition,
  SessionGpsPointSet,
  SessionGpsSummary,
  SessionBookmarkRecord,
  SessionNoteFieldDef,
  SessionNoteRecord,
  SessionNoteValue,
  SessionRecord,
  SessionSignalSummary,
  SignalQueryRequest,
  SignalQueryResponse,
  StudySet,
  TableQueryRequest,
  TableQueryResponse,
  TableQueryRow,
  TimeseriesWindowRequest,
  TimeseriesWindowResponse,
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
  private sessions = fixtureSessions.map(cloneSession)
  private notes = new Map(this.sessions.map((session) => [sessionRefId(sessionToStudyRef(session)), sessionNoteFromSession(session)]))
  private tracks = fixtureTracks.map(cloneTrack)
  private bookmarks: SessionBookmarkRecord[] = []

  async listLibraries() {
    return fixtureLibraries.map((libraryItem) => ({ ...libraryItem }))
  }

  async listSessions() {
    return this.sessions.map(cloneSession)
  }

  async listTracks() {
    return this.tracks.map(cloneTrack)
  }

  async listStudySets() {
    return this.savedStudySets.map(cloneStudySet)
  }

  async renameSession(session: SessionRecord, name: string): Promise<SessionRecord> {
    const trimmedName = name.trim()
    if (!trimmedName) {
      return cloneSession(session)
    }
    const id = sessionRefId(sessionToStudyRef(session))
    const existing = this.sessions.find((item) => sessionRefId(sessionToStudyRef(item)) === id)
    if (!existing) {
      throw new Error(`Fixture session ${session.name} was not found.`)
    }
    const renamed: SessionRecord = {
      ...existing,
      name: trimmedName,
      sessionLabel: trimmedName,
    }
    this.sessions = this.sessions.map((item) =>
      sessionRefId(sessionToStudyRef(item)) === id ? renamed : item,
    )
    return cloneSession(renamed)
  }

  async loadStudySet(studySetId: string) {
    const studySet = this.savedStudySets.find((item) => item.id === studySetId)
    if (!studySet) {
      throw new Error(`Fixture Study Set ${studySetId} was not found.`)
    }
    return cloneStudySet(studySet)
  }

  async listAnalysisViews(): Promise<AnalysisViewRecord[]> {
    return [fixtureSimpleSuspensionAnalysisView(), fixtureTrackAnalysisView()]
  }

  async evaluateAnalysisAdequacy(viewId: string, studySet: StudySet): Promise<AnalysisAdequacyResult> {
    const view =
      viewId === 'track-analysis-lap-timing'
        ? fixtureTrackAnalysisView()
        : fixtureSimpleSuspensionAnalysisView()
    const totalSessionCount = studySet.sessions.length
    const usableSessionCount =
      viewId === 'track-analysis-lap-timing'
        ? studySet.sessions.filter((sessionRef) => {
            const session = this.sessions.find((candidate) => sessionRefId(sessionToStudyRef(candidate)) === sessionRefId(sessionRef))
            return Boolean(session?.gpsSummary.present)
          }).length
        : viewId === view.id
          ? totalSessionCount
          : 0
    return {
      viewId,
      displayName: viewId === view.id ? view.displayName : viewId,
      status: usableSessionCount > 0 ? 'warning' : 'blocked',
      policy: 'fixture heuristic',
      summary:
        usableSessionCount > 0
          ? 'Fixture sessions are treated as usable for prototype analysis; real adequacy comes from the library API.'
          : 'No sessions are available in this Study Set.',
      totalSessionCount,
      usableSessionCount,
      blockedSessionCount: totalSessionCount - usableSessionCount,
      messages:
        usableSessionCount > 0
          ? [
              {
                level: 'warning',
                code: 'fixture_adequacy',
                message: 'Fixture adequacy is approximate and does not inspect real signal/event coverage.',
              },
            ]
          : [
              {
                level: 'error',
                code: 'empty_scope',
                message: 'Add at least one session before opening an analysis view.',
              },
            ],
      sessionResults: studySet.sessions.map((sessionRef) => ({
        sessionRef: { ...sessionRef },
        status: usableSessionCount > 0 ? 'warning' : 'blocked',
        summary: usableSessionCount > 0 ? 'Fixture session assumed usable.' : 'No usable data.',
        requiredPassed: usableSessionCount > 0,
        recommendedMissing: ['real adequacy unavailable in fixture mode'],
        optionalMissing: [],
        units: {},
      })),
    }
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

  async deleteStudySet(studySetId: string) {
    this.savedStudySets = this.savedStudySets.filter((studySet) => studySet.id !== studySetId)
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
      : Array.from(new Set(this.sessions.map((session) => session.libraryId)))
    const candidateSessions = this.sessions.filter((session) => libraryIds.includes(session.libraryId))
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
      exactSessionCount: candidateSessions.length,
      skippedSessionCount: 0,
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

  async loadSessionGpsPoints(session: SessionRecord, sourceId?: string | null): Promise<SessionGpsPointSet> {
    const source =
      session.gpsSummary.sources.find((candidate) => candidate.sourceId === sourceId) ??
      session.gpsSummary.sources.find((candidate) => candidate.sourceId === session.gpsSummary.preferredSourceId) ??
      session.gpsSummary.sources[0]
    return {
      present: session.gps.length > 0,
      sourceId: source?.sourceId ?? '',
      sourceKind: source?.kind ?? session.gpsSummary.preferredSourceKind ?? 'unknown',
      streamName: source?.streamName ?? '',
      samplingMode: 'fixture',
      sourcePoints: session.gpsSummary.positionPointCount,
      returnedPoints: session.gps.length,
      maxPoints: session.gps.length,
      stride: null,
      sourceSelectionMethod: session.gpsSummary.sourceSelectionMethod,
      points: session.gps.map(([longitude, latitude], index) => ({
        timeS: index,
        longitude,
        latitude,
        elevationM: null,
      })),
      path: session.gps.map(([longitude, latitude]) => [longitude, latitude] as GeoPosition),
      warnings: [...session.gpsSummary.warnings],
    }
  }

  async loadSessionNote(session: SessionRecord): Promise<SessionNoteRecord> {
    const key = sessionRefId(sessionToStudyRef(session))
    return cloneSessionNote(this.notes.get(key) ?? sessionNoteFromSession(session))
  }

  async saveSessionNote(note: SessionNoteRecord): Promise<SessionNoteRecord> {
    const key = sessionRefId(note.sessionRef)
    const now = new Date().toISOString()
    const saved: SessionNoteRecord = {
      ...cloneSessionNote(note),
      present: true,
      createdAtUtc: note.createdAtUtc || now,
      updatedAtUtc: now,
    }
    this.notes.set(key, saved)
    this.sessions = this.sessions.map((session) =>
      sessionRefId(sessionToStudyRef(session)) === key
        ? {
            ...session,
            bike: noteValueText(saved.values.bike),
            rider: noteValueText(saved.values.rider),
            noteStatus: saved.draft ? 'draft' : 'edited',
          }
        : session,
    )
    return cloneSessionNote(saved)
  }

  async listSessionBookmarks(session: SessionRecord): Promise<SessionBookmarkRecord[]> {
    const wanted = sessionRefId(sessionToStudyRef(session))
    return this.bookmarks.filter((bookmark) => sessionRefId(bookmark.sessionRef) === wanted).map(cloneSessionBookmark)
  }

  async saveSessionBookmark(bookmark: SessionBookmarkRecord): Promise<SessionBookmarkRecord> {
    const now = new Date().toISOString()
    const existingIndex = bookmark.id ? this.bookmarks.findIndex((candidate) => candidate.id === bookmark.id) : -1
    const existing = existingIndex >= 0 ? this.bookmarks[existingIndex] : null
    const saved: SessionBookmarkRecord = {
      ...cloneSessionBookmark(bookmark),
      id: bookmark.id || uniqueId('bookmark', this.bookmarks.map((candidate) => candidate.id)),
      revision: existing ? existing.revision + 1 : 1,
      createdAtUtc: existing?.createdAtUtc || bookmark.createdAtUtc || now,
      updatedAtUtc: now,
    }
    if (existingIndex >= 0) {
      this.bookmarks = this.bookmarks.map((candidate, index) => (index === existingIndex ? saved : candidate))
    } else {
      this.bookmarks = [...this.bookmarks, saved]
    }
    return cloneSessionBookmark(saved)
  }

  async deleteSessionBookmark(bookmarkId: string): Promise<void> {
    this.bookmarks = this.bookmarks.filter((bookmark) => bookmark.id !== bookmarkId)
  }

  async loadTimeseriesWindow(_libraryId: string, request: TimeseriesWindowRequest): Promise<TimeseriesWindowResponse> {
    const session =
      this.sessions.find((candidate) => candidate.sessionKey === request.session.sessionKey) ?? this.sessions[0]
    if (!session) {
      throw new Error('No fixture sessions are available.')
    }
    const durationS = Math.max(1, session.gpsSummary.sessionDurationS || session.durationMin * 60 || 900)
    const startS = clamp(request.window?.startS ?? 0, 0, durationS)
    const endS = clamp(request.window?.endS ?? durationS, startS, durationS)
    const targetPoints = Math.max(80, Math.min(2500, request.resolution?.targetPoints ?? 1200))
    const count = Math.max(2, Math.min(targetPoints, Math.ceil((endS - startS) * 8)))
    const timeValues = Array.from({ length: count }, (_value, index) =>
      startS + ((endS - startS) * index) / Math.max(count - 1, 1),
    )
    const availableSignals = signalSummariesForSession(session)
    const signals = request.signals
      .map((signal, index) => resolveFixtureWindowSignal(signal, availableSignals, index))
      .filter((signal): signal is SessionSignalSummary => Boolean(signal))
      .map((signal) => ({
        ...signal,
        values: fixtureSignalValues(session.sessionKey, signal.column, count),
      }))
    const events = request.includeEvents
      ? fixtureEventRows(sessionToStudyRef(session))
          .map((row) => {
            const start = numberField(row.fields, 'start_time_s', numberField(row.fields, 'start_s', numberField(row.fields, 'trigger_time_s', 0)))
            const end = numberField(row.fields, 'end_time_s', numberField(row.fields, 'end_s', start))
            const peak = numberField(row.fields, 'peak_time_s', numberField(row.fields, 'trigger_time_s', start))
            return {
              eventId: String(row.fields.event_id ?? `${row.eventType}-${row.rowIndex}`),
              eventType: row.eventType,
              displayName: row.eventType.replace(/_/g, ' '),
              startS: start,
              endS: end,
              peakTimeS: peak,
              end: row.signalRole === 'unknown' ? '' : row.signalRole,
            }
          })
          .filter((event) => {
            const eventStart = event.startS ?? event.peakTimeS ?? 0
            const eventEnd = event.endS ?? eventStart
            return eventEnd >= startS && eventStart <= endS
          })
      : []
    const marks = request.includeMarks ? fixtureMarksForSession(session.sessionKey, startS, endS, durationS) : []
    return {
      sessionRef: sessionToStudyRef(session),
      window: {
        requestedStartS: startS,
        requestedEndS: endS,
        returnedStartS: timeValues[0] ?? null,
        returnedEndS: timeValues[timeValues.length - 1] ?? null,
      },
      sampling: {
        mode: 'fixture_raw',
        sourcePoints: count,
        returnedPoints: count,
        targetPoints,
      },
      time: {
        column: 'time_s',
        unit: 's',
        values: timeValues,
      },
      signals,
      events,
      marks,
      warnings: [],
    }
  }

  async querySignals(_libraryId: string, request: SignalQueryRequest): Promise<SignalQueryResponse> {
    return {
      sessions: request.sessions.map((sessionRef) => ({
        sessionRef: { ...sessionRef },
        time: {
          column: 'time_s',
          unit: 's',
          values: Array.from({ length: 900 }, (_value, index) => index),
        },
        sampling: {
          mode: 'fixture_raw',
          sourcePoints: 900,
          returnedPoints: 900,
          distributionCorrect: true,
        },
        signals: request.signals.map((signal) => {
          const role = signal.role || 'signal'
          const column = fixtureSignalColumn(signal)
          const values = fixtureSignalValues(sessionRef.sessionKey, column, 900)
          const unit = role.includes('velocity') ? 'mm/s' : role.includes('displacement') ? '1' : ''
          return {
            role,
            signalId: `${sessionRef.sessionId}-${role}`,
            column,
            displayName: role.replace(/_/g, ' '),
            end: role.startsWith('front') ? 'front' : role.startsWith('rear') ? 'rear' : '',
            domain: 'suspension',
            quantity: column === 'active_mask_qc' ? 'mask' : role.includes('velocity') ? 'vel' : 'disp_norm',
            unit,
            processingRole: column === 'active_mask_qc' ? 'activity_mask' : 'primary_analysis',
            kind: column === 'active_mask_qc' ? 'qc' : '',
            sensor: role.startsWith('front') ? 'front_fixture' : role.startsWith('rear') ? 'rear_fixture' : '',
            origin: 'fixture',
            values,
          }
        }),
      })),
      warnings: [],
    }
  }

  async queryEvents(_libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse> {
    const rows = request.sessions.flatMap((sessionRef) => fixtureEventRows(sessionRef))
    return {
      rowKind: 'event',
      rowCount: rows.length,
      rows,
      warnings: [],
    }
  }

  async queryMetrics(_libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse> {
    const wanted = new Set(request.eventTypes ?? [])
    const rows = request.sessions.flatMap((sessionRef) =>
      fixtureMetricRows(sessionRef).filter((row) => wanted.size === 0 || eventTypeMatches(row.eventType, wanted)),
    )
    return {
      rowKind: 'metric',
      rowCount: rows.length,
      rows,
      warnings: [],
    }
  }
}

function fixtureSignalColumn(signal: { role: string; selector?: Record<string, unknown>; column?: string }) {
  if (signal.column) {
    return signal.column
  }
  const selector = signal.selector ?? {}
  if (selector.kind === 'qc' && selector.quantity === 'mask') {
    return 'active_mask_qc'
  }
  return `${signal.role || 'signal'}_fixture`
}

function resolveFixtureWindowSignal(
  request: { selector?: Record<string, unknown>; column?: string },
  availableSignals: SessionSignalSummary[],
  index: number,
) {
  if (request.column) {
    return availableSignals.find((signal) => signal.column === request.column) ?? {
      signalId: `fixture-window-signal-${index}`,
      column: request.column,
      displayName: request.column.replace(/_/g, ' '),
      end: request.column.startsWith('rear') ? 'rear' : request.column.startsWith('front') ? 'front' : '',
      domain: 'suspension',
      quantity: request.column.includes('velocity') ? 'vel' : 'disp_norm',
      unit: request.column.includes('velocity') ? 'mm/s' : '1',
      processingRole: 'primary_analysis',
      kind: 'signal',
      sensor: '',
      origin: 'fixture',
    }
  }
  const selector = request.selector ?? {}
  const end = normalizedString(selector.end)
  const quantity = normalizedString(selector.quantity)
  const kind = normalizedString(selector.kind)
  return (
    availableSignals.find((signal) => {
      if (kind && signal.kind !== kind) {
        return false
      }
      if (end && signal.end !== end) {
        return false
      }
      if (quantity && signal.quantity !== quantity) {
        return false
      }
      return true
    }) ?? availableSignals[index]
  )
}

function signalSummariesForSession(session: SessionRecord): SessionSignalSummary[] {
  if (session.availableSignals?.length) {
    return session.availableSignals.map((signal) => ({ ...signal }))
  }
  const baseSignals: SessionSignalSummary[] = [
    {
      signalId: `${session.sessionKey}-front-displacement`,
      column: 'front_wheel_displacement_norm',
      displayName: 'Front wheel displacement',
      end: 'front',
      domain: 'suspension',
      quantity: 'disp_norm',
      unit: '1',
      processingRole: 'primary_analysis',
      kind: 'signal',
      sensor: 'fixture',
      origin: 'fixture',
    },
    {
      signalId: `${session.sessionKey}-rear-displacement`,
      column: 'rear_wheel_displacement_norm',
      displayName: 'Rear wheel displacement',
      end: 'rear',
      domain: 'suspension',
      quantity: 'disp_norm',
      unit: '1',
      processingRole: 'primary_analysis',
      kind: 'signal',
      sensor: 'fixture',
      origin: 'fixture',
    },
    {
      signalId: `${session.sessionKey}-front-velocity`,
      column: 'front_wheel_velocity_mm_s',
      displayName: 'Front wheel velocity',
      end: 'front',
      domain: 'suspension',
      quantity: 'vel',
      unit: 'mm/s',
      processingRole: 'primary_analysis',
      kind: 'signal',
      sensor: 'fixture',
      origin: 'fixture',
    },
    {
      signalId: `${session.sessionKey}-rear-velocity`,
      column: 'rear_wheel_velocity_mm_s',
      displayName: 'Rear wheel velocity',
      end: 'rear',
      domain: 'suspension',
      quantity: 'vel',
      unit: 'mm/s',
      processingRole: 'primary_analysis',
      kind: 'signal',
      sensor: 'fixture',
      origin: 'fixture',
    },
  ]
  const existingColumns = new Set(baseSignals.map((signal) => signal.column))
  const catalogSignals = session.signals
    .filter((column) => !existingColumns.has(column))
    .map((column, index): SessionSignalSummary => ({
      signalId: `${session.sessionKey}-catalog-${index}`,
      column,
      displayName: column.replace(/_/g, ' '),
      end: column.startsWith('rear') ? 'rear' : column.startsWith('front') ? 'front' : '',
      domain: 'fixture',
      quantity: column.includes('velocity') ? 'vel' : 'signal',
      unit: column.includes('velocity') ? 'mm/s' : '',
      processingRole: 'supporting',
      kind: 'signal',
      sensor: 'fixture',
      origin: 'fixture',
    }))
  return [...baseSignals, ...catalogSignals]
}

function normalizedString(value: unknown) {
  return typeof value === 'string' ? value.trim().toLowerCase() : ''
}

function numberField(fields: Record<string, unknown>, key: string, fallback: number) {
  const value = fields[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function fixtureSignalValues(sessionKey: string, role: string, count: number): number[] {
  if (role === 'inactive_mask_qc' || role === 'inactive_mask') {
    return fixtureInactiveMask(sessionKey, count)
  }
  if (role === 'active_mask_qc') {
    return fixtureInactiveMask(sessionKey, count).map((value) => (value ? 0 : 1))
  }
  const seed = seededNumber(`${sessionKey}:${role}`)
  const isVelocity = role.includes('velocity')
  const isRear = role.startsWith('rear')
  return Array.from({ length: count }, (_, index) => {
    const t = index / Math.max(count - 1, 1)
    const wave = Math.sin((t * 18 + seed) * Math.PI) + 0.4 * Math.sin((t * 73 + seed * 0.3) * Math.PI)
    if (isVelocity) {
      const scale = isRear ? 720 : 980
      return wave * scale + (seed - 0.5) * 180
    }
    const base = isRear ? 0.31 : 0.24
    const spread = isRear ? 0.26 : 0.22
    return clamp(base + spread * Math.abs(wave) + (seed - 0.5) * 0.08, 0, 1)
  })
}

function fixtureInactiveMask(sessionKey: string, count: number): number[] {
  const seed = seededNumber(`${sessionKey}:activity`)
  const firstIdleEnd = Math.floor(count * (0.04 + seed * 0.04))
  const middleIdleStart = Math.floor(count * (0.42 + seed * 0.16))
  const middleIdleEnd = Math.min(count, middleIdleStart + Math.floor(count * (0.04 + seed * 0.03)))
  const lastIdleStart = Math.floor(count * (0.92 - seed * 0.04))
  return Array.from({ length: count }, (_, index) =>
    index < firstIdleEnd || (index >= middleIdleStart && index < middleIdleEnd) || index >= lastIdleStart ? 1 : 0,
  )
}

function fixtureEventRows(sessionRef: { libraryId: string; sessionKey: string; runId: string; sessionId: string; label: string }): TableQueryRow[] {
  const rows: TableQueryRow[] = []
  for (const eventType of ['compressions_all', 'rebounds_all']) {
    for (const role of ['front', 'rear'] as const) {
      const count = 18 + Math.floor(seededNumber(`${sessionRef.sessionKey}:${eventType}:${role}`) * 46)
      for (let index = 0; index < count; index += 1) {
        const seed = seededNumber(`${sessionRef.sessionKey}:${eventType}:${role}:event:${index}`)
        rows.push({
          sessionRef: { ...sessionRef },
          setId: eventType,
          rowIndex: rows.length,
          eventType,
          signalRole: role,
          fields: {
            event_id: `${sessionRef.sessionId}-${eventType}-${role}-${index}`,
            schema_id: eventType,
            end: role,
            trigger_time_s: 20 + seed * 850,
          },
        })
      }
    }
  }
  return rows
}

function fixtureMarksForSession(sessionKey: string, startS: number, endS: number, durationS: number) {
  const seed = seededNumber(`${sessionKey}:marks`)
  const markTimes = [0.18, 0.36, 0.57, 0.74, 0.88].map((position, index) =>
    clamp((position + (seed - 0.5) * 0.035 + index * 0.002) * durationS, 0, durationS),
  )
  return markTimes
    .filter((timeS) => timeS >= startS && timeS <= endS)
    .map((timeS, index) => ({
      markId: `${sessionKey}-mark-${index + 1}`,
      timeS,
      displayName: `Mark ${index + 1}`,
      column: 'mark',
    }))
}

function fixtureMetricRows(sessionRef: { libraryId: string; sessionKey: string; runId: string; sessionId: string; label: string }): TableQueryRow[] {
  const rows: TableQueryRow[] = []
  for (const eventType of ['compressions_all', 'rebounds_all']) {
    for (const role of ['front', 'rear'] as const) {
      const count = 28 + Math.floor(seededNumber(`${sessionRef.sessionKey}:metrics:${eventType}:${role}`) * 28)
      const roleOffset = role === 'rear' ? 6 : -3
      for (let index = 0; index < count; index += 1) {
        const seed = seededNumber(`${sessionRef.sessionKey}:${eventType}:${role}:${index}`)
        const stroke = 18 + seed * 58 + roleOffset
        const velocityMagnitude = 180 + seed * 1250 + (role === 'rear' ? 120 : 0)
        rows.push({
          sessionRef: { ...sessionRef },
          setId: eventType,
          rowIndex: rows.length,
          eventType,
          signalRole: role,
          fields: {
            event_id: `${sessionRef.sessionId}-${eventType}-${role}-${index}`,
            schema_id: eventType,
            end: role,
            trigger_time_s: 20 + seed * 850,
            m_stroke_disp_max: stroke,
            m_stroke_disp_range: stroke * (0.72 + seed * 0.24),
            m_peak_disp_max: stroke,
            m_interval_vel_max: velocityMagnitude,
            m_interval_vel_min: -velocityMagnitude,
          },
        })
      }
    }
  }
  return rows
}

function eventTypeMatches(value: string, wanted: Set<string>) {
  for (const candidate of wanted) {
    if (value === candidate || value.startsWith(`${candidate}_`) || value.startsWith(`${candidate}>`)) {
      return true
    }
  }
  return false
}

function seededNumber(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0) / 4294967295
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
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
    availableSignals: session.availableSignals?.map((signal) => ({ ...signal })),
    gps: session.gps.map(([x, y]) => [x, y]),
    gpsSummary: cloneGpsSummary(session.gpsSummary),
  }
}

function sessionNoteFromSession(session: SessionRecord): SessionNoteRecord {
  const now = new Date().toISOString()
  return {
    sessionRef: sessionToStudyRef(session),
    present: session.noteStatus !== 'missing',
    title: 'Session note',
    templateId: 'fixture_session_note',
    templateVersion: '1.0',
    templateStatus: 'ok',
    templateError: '',
    fields: fixtureNoteFields.map((field) => ({ ...field, enumOptions: [...field.enumOptions] })),
    customFieldSection: 'Custom',
    values: {
      bike: session.bike,
      rider: session.rider,
    },
    customValues: {},
    freeTextNotes: '',
    draft: session.noteStatus !== 'edited',
    createdAtUtc: now,
    updatedAtUtc: now,
  }
}

const fixtureNoteFields: SessionNoteFieldDef[] = [
  {
    fieldId: 'bike',
    label: 'Bike',
    fieldType: 'string',
    section: 'Overview',
    required: false,
    default: '',
    unit: '',
    helpText: '',
    enumOptions: [],
  },
  {
    fieldId: 'rider',
    label: 'Rider',
    fieldType: 'string',
    section: 'Overview',
    required: false,
    default: '',
    unit: '',
    helpText: '',
    enumOptions: [],
  },
]

function cloneSessionNote(note: SessionNoteRecord): SessionNoteRecord {
  return {
    ...note,
    sessionRef: { ...note.sessionRef },
    fields: note.fields.map((field) => ({ ...field, enumOptions: [...field.enumOptions] })),
    values: cloneNoteValues(note.values),
    customValues: cloneNoteValues(note.customValues),
  }
}

function cloneSessionBookmark(bookmark: SessionBookmarkRecord): SessionBookmarkRecord {
  return {
    ...bookmark,
    sessionRef: { ...bookmark.sessionRef },
    window: { ...bookmark.window },
    viewState: JSON.parse(JSON.stringify(bookmark.viewState)) as SessionBookmarkRecord['viewState'],
    tags: [...bookmark.tags],
  }
}

function cloneNoteValues(values: Record<string, SessionNoteValue>): Record<string, SessionNoteValue> {
  return { ...values }
}

function noteValueText(value: SessionNoteValue | undefined) {
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return ''
}

function fixtureSimpleSuspensionAnalysisView(): AnalysisViewRecord {
  return {
    id: 'simple-suspension',
    displayName: 'Simple Suspension Analysis',
    category: 'Suspension',
    description: 'Compare wheel displacement, wheel velocity, stroke length, event counts, and simple compression/rebound metrics.',
    route: 'simple-suspension',
    adequacyPolicy: 'fixture heuristic',
    requirements: {
      required: [
        {
          requirementId: 'wheel_motion_data',
          label: 'Wheel motion data',
          tier: 'required',
          description: 'At least one suspension end needs usable displacement data and velocity evidence.',
        },
      ],
      recommended: [
        {
          requirementId: 'event_metrics',
          label: 'Event metrics',
          tier: 'recommended',
          description: 'Compression and rebound event metrics unlock the metric distributions and scatter plots.',
        },
        {
          requirementId: 'both_ends',
          label: 'Both ends',
          tier: 'recommended',
          description: 'Front and rear data enables the primary front-vs-rear comparisons.',
        },
      ],
      optional: [
        {
          requirementId: 'gps_and_tracks',
          label: 'GPS and tracks',
          tier: 'optional',
          description: 'GPS and track matches enable sector-based comparisons.',
        },
      ],
    },
  }
}

function fixtureTrackAnalysisView(): AnalysisViewRecord {
  return {
    id: 'track-analysis-lap-timing',
    displayName: 'Track Analysis and Lap Timing',
    category: 'Geospatial',
    description: 'Create trackpoints from GPS traces and compare track start-to-finish sector timing.',
    route: 'track-analysis-lap-timing',
    adequacyPolicy: 'fixture heuristic',
    requirements: {
      required: [
        {
          requirementId: 'gps',
          label: 'GPS data',
          tier: 'required',
          description: 'At least one selected session needs usable GPS data.',
        },
      ],
      recommended: [
        {
          requirementId: 'all_sessions_gps',
          label: 'GPS for all sessions',
          tier: 'recommended',
          description: 'All selected sessions have GPS for direct timing comparison.',
        },
        {
          requirementId: 'track_scope',
          label: 'Track in scope',
          tier: 'recommended',
          description: 'A saved or temporary track is available for trackpoint and sector timing work.',
        },
      ],
      optional: [
        {
          requirementId: 'alternate_gps_sources',
          label: 'Alternate GPS sources',
          tier: 'optional',
          description: 'Sessions with multiple GPS sources can be inspected with alternate source choices.',
        },
      ],
    },
  }
}

function cloneTrack(track: TrackRecord): TrackRecord {
  return {
    ...track,
    points: track.points.map(copyPosition),
    trackpoints: track.trackpoints.map((trackpoint) => ({
      ...trackpoint,
      position: copyPosition(trackpoint.position),
      cutlineOverride: trackpoint.cutlineOverride ? { ...trackpoint.cutlineOverride } : undefined,
    })),
    segmentAliases: track.segmentAliases?.map((alias) => ({ ...alias })),
    matchSummaries: track.matchSummaries.map((match) => ({
      ...match,
      trackpointResults: match.trackpointResults.map((result) => ({ ...result })),
      warnings: [...match.warnings],
    })),
    source: track.source ? { ...track.source } : undefined,
  }
}

function copyPosition(position: GeoPosition): GeoPosition {
  return Number.isFinite(position[2]) ? [position[0], position[1], position[2] as number] : [position[0], position[1]]
}

function cloneGpsSummary(summary: SessionGpsSummary): SessionGpsSummary {
  return {
    ...summary,
    sources: summary.sources.map((source) => ({ ...source })),
    warnings: [...summary.warnings],
  }
}
