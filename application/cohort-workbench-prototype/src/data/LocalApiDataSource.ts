import { candidateId, groupingColors, sessionRefId } from '../domain/studySets'
import { emptyGpsSummary } from '../domain/geospatial'
import type { SavedSessionFilterRecord, SessionFilterPredicate } from '../domain/sessionFilters'
import type {
  AnalysisAdequacyMessage,
  AnalysisAdequacyCriterionResult,
  AnalysisAdequacyResult,
  AnalysisAdequacySessionResult,
  AnalysisAdequacyStatus,
  AnalysisRequirementRecord,
  AnalysisRequirementTier,
  AnalysisViewRecord,
  GeoPosition,
  GpsQuality,
  GpsSourceKind,
  GpsTimebase,
  LibraryRecord,
  LocalVideoFileSelection,
  NoteStatus,
  QcLevel,
  SessionGpsPointSet,
  SessionGpsSummary,
  SessionBookmarkRecord,
  SessionNoteFieldDef,
  SessionNoteFieldType,
  SessionNoteRecord,
  SessionNoteValue,
  SessionRecord,
  SessionSignalSummary,
  SessionVideoAttachmentRecord,
  SessionVideoAttachmentsRecord,
  SessionTrackMatchRecord,
  SignalQueryRequest,
  SignalQueryResponse,
  SignalQuerySession,
  SignalQuerySignal,
  StudyGrouping,
  StudySessionRef,
  StudySet,
  TableQueryRequest,
  TableQueryResponse,
  TableQueryRow,
  TimeseriesWindowEvent,
  TimeseriesWindowMark,
  TimeseriesWindowRequest,
  TimeseriesWindowResponse,
  TimeseriesWindowSignal,
  TrackDirection,
  TrackGeometryEditRecord,
  TrackMatchStatus,
  TrackSegmentAliasRecord,
  TrackpointMatchMode,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryRequest,
  TrackpointMatchQueryResults,
  TrackpointMatchQueryStatus,
  TrackRecord,
} from '../domain/types'
import type {
  CatalogRevision,
  LibraryDataSource,
  SessionGpsPointLoadOptions,
  SessionNoteSaveResult,
  SignalSetDefinition,
  WorkbenchBootstrapData,
} from './LibraryDataSource'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8765'
const VITE_DEV_PORTS = new Set(['5173', '4173'])
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])
const BULK_NOTE_FALLBACK_CONCURRENCY = 4

function normalizeApiBaseUrl(baseUrl: string) {
  return String(baseUrl).replace(/\/+$/, '')
}

function isBundledLocalOrigin(location: Location) {
  if (import.meta.env.DEV || VITE_DEV_PORTS.has(location.port)) {
    return false
  }
  if (location.port === '8765') {
    return true
  }
  return LOOPBACK_HOSTS.has(location.hostname)
}

export function defaultLibraryApiBaseUrl() {
  const configuredBaseUrl = import.meta.env.VITE_BODAQS_LIBRARY_API_URL
  if (configuredBaseUrl) {
    return normalizeApiBaseUrl(configuredBaseUrl)
  }
  if (typeof window !== 'undefined' && window.location?.origin && isBundledLocalOrigin(window.location)) {
    return normalizeApiBaseUrl(window.location.origin)
  }
  if (!import.meta.env.DEV && typeof window !== 'undefined' && /^https?:$/.test(window.location.protocol)) {
    return normalizeApiBaseUrl(window.location.origin)
  }
  return DEFAULT_API_BASE_URL
}

type ApiObject = Record<string, unknown>

type ApiHealth = {
  libraries_root?: string
  read_only?: boolean
  web_app?: {
    demo_welcome_enabled?: boolean
  }
}

type ApiSetLibrariesRootResponse = {
  libraries_root?: string
  library_count?: number
}

export class LocalApiDataSource implements LibraryDataSource {
  readonly baseUrl: string

  constructor(baseUrl = defaultLibraryApiBaseUrl()) {
    this.baseUrl = normalizeApiBaseUrl(baseUrl)
  }

  async getHealth() {
    return requestJson<ApiHealth>(`${this.baseUrl}/api/v1/health`)
  }

  async setLibrariesRoot(librariesRoot: string) {
    return requestJson<ApiSetLibrariesRootResponse>(`${this.baseUrl}/api/v1/config/libraries-root`, {
      method: 'POST',
      body: JSON.stringify({ libraries_root: librariesRoot }),
    })
  }

  async listLibraries() {
    const libraries = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/libraries`)
    return libraries.map(mapLibrary)
  }

  async listCatalogRevisions(): Promise<CatalogRevision[]> {
    const response = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/libraries/catalog-revisions`)
    return arrayValue(response.libraries)
      .filter(isObject)
      .map((item) => ({ libraryId: textValue(item.library_id), revision: numberValue(item.revision) }))
      .filter((item) => item.libraryId)
  }

  async refreshLibrary(libraryId: string) {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/refresh`,
      {
        method: 'POST',
      },
    )
    const library = objectValue(response.library)
    return mapLibrary(library)
  }

  async loadWorkbenchBootstrap(): Promise<WorkbenchBootstrapData> {
    const bootstrap = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/workbench/bootstrap`)
    const catalogs = arrayValue(bootstrap.catalogs).filter(isObject)
    const sessions = catalogs.flatMap((catalog) => {
      const rows = arrayValue(catalog.rows)
      return rows.filter(isObject).map(mapSession)
    })
    return {
      libraries: arrayValue(bootstrap.libraries).filter(isObject).map(mapLibrary),
      sessions,
      tracks: arrayValue(bootstrap.tracks).filter(isObject).map(mapTrack),
      studySets: arrayValue(bootstrap.study_sets).filter(isObject).map(mapStudySet),
      savedFilters: arrayValue(bootstrap.session_filters).filter(isObject).map(mapSavedSessionFilter),
      timings: objectValue(bootstrap.timings),
    }
  }

  async loadSignalSets(): Promise<SignalSetDefinition[]> {
    const response = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/signal-sets`)
    return arrayValue(response.sets)
      .filter(isObject)
      .map((signalSet) => ({
        id: textValue(signalSet.id),
        displayName: textValue(signalSet.display_name, textValue(signalSet.id)),
        description: textValue(signalSet.description),
        defaultSelectionSetId: textValue(signalSet.default_selection_set),
        defaultExclusionRules: arrayValue(signalSet.default_exclusion_rules).filter(isObject),
        rules: arrayValue(signalSet.rules).filter(isObject),
      }))
      .filter((signalSet) => signalSet.id && signalSet.rules.length > 0)
  }

  async listSessions(libraries?: LibraryRecord[]) {
    const libraryList = libraries ?? (await this.listLibraries())
    const catalogs = await Promise.all(
      libraryList.map((libraryItem) =>
        requestJson<ApiObject>(`${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryItem.id)}/catalog`),
      ),
    )
    return catalogs.flatMap((catalog) => {
      const rows = arrayValue(catalog.rows)
      return rows.filter(isObject).map(mapSession)
    })
  }

  async listTracks(): Promise<TrackRecord[]> {
    const tracks = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/tracks`)
    return tracks.map(mapTrack)
  }

  async listStudySets() {
    const summaries = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/study-sets`)
    const studySets = await Promise.all(
      summaries.map((summary) => {
        const studySetId = textValue(summary.study_set_id)
        return requestJson<ApiObject>(`${this.baseUrl}/api/v1/study-sets/${encodeURIComponent(studySetId)}`)
      }),
    )
    return studySets.map(mapStudySet)
  }

  async loadStudySet(studySetId: string) {
    const studySet = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/study-sets/${encodeURIComponent(studySetId)}`)
    return mapStudySet(studySet)
  }

  async listAnalysisViews() {
    const views = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/analysis-views`)
    return views.map(mapAnalysisView)
  }

  async evaluateAnalysisAdequacy(viewId: string, studySet: StudySet) {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/analysis-views/${encodeURIComponent(viewId)}/adequacy`,
      {
        method: 'POST',
        body: JSON.stringify({
          study_set: toApiStudySet(studySet),
        }),
      },
    )
    return mapAnalysisAdequacy(response)
  }

  async listSavedSessionFilters() {
    const filters = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/session-filters`)
    return filters.map(mapSavedSessionFilter)
  }

  async saveStudySet(studySet: StudySet) {
    const payload = toApiStudySet(studySet)
    const saved = studySet.id
      ? await requestJson<ApiObject>(`${this.baseUrl}/api/v1/study-sets/${encodeURIComponent(studySet.id)}`, {
          method: 'PUT',
          body: JSON.stringify({
            expected_revision: studySet.revision,
            study_set: payload,
          }),
        })
      : await requestJson<ApiObject>(`${this.baseUrl}/api/v1/study-sets`, {
          method: 'POST',
          body: JSON.stringify(payload),
        })
    return mapStudySet(saved)
  }

  async deleteStudySet(studySetId: string) {
    await requestJson<ApiObject>(`${this.baseUrl}/api/v1/study-sets/${encodeURIComponent(studySetId)}`, {
      method: 'DELETE',
    })
  }

  async deleteSession(session: SessionRecord, options: { cleanupMemberships?: boolean } = {}) {
    const params = options.cleanupMemberships ? '?cleanup_memberships=true' : ''
    return requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(session.libraryId)}/runs/${encodeURIComponent(
        session.runId,
      )}/sessions/${encodeURIComponent(session.sessionId)}${params}`,
      {
        method: 'DELETE',
      },
    )
  }

  async renameSession(session: SessionRecord, name: string): Promise<SessionRecord> {
    const trimmedName = name.trim()
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(session.libraryId)}/sessions/descriptions`,
      {
        method: 'PUT',
        body: JSON.stringify({
          session_ref: toApiSessionRef(session),
          descriptions: {
            session_description: trimmedName,
          },
        }),
      },
    )
    const sessionLabel = textValue(response.session_description, trimmedName)
    return {
      ...session,
      name: sessionLabel,
      sessionLabel,
    }
  }

  async saveSavedSessionFilter(filter: SavedSessionFilterRecord) {
    const payload = toApiSessionFilter(filter)
    const saved =
      filter.id && filter.origin === 'api_saved'
        ? await requestJson<ApiObject>(`${this.baseUrl}/api/v1/session-filters/${encodeURIComponent(filter.id)}`, {
            method: 'PUT',
            body: JSON.stringify({
              expected_revision: filter.revision,
              session_filter: payload,
            }),
          })
        : await requestJson<ApiObject>(`${this.baseUrl}/api/v1/session-filters`, {
            method: 'POST',
            body: JSON.stringify(payload),
          })
    return mapSavedSessionFilter(saved)
  }

  async deleteSavedSessionFilter(filterId: string) {
    await requestJson<ApiObject>(`${this.baseUrl}/api/v1/session-filters/${encodeURIComponent(filterId)}`, {
      method: 'DELETE',
    })
  }

  async saveTrack(track: TrackRecord) {
    const payload = toApiTrack(track)
    const saved = track.id
      ? await requestJson<ApiObject>(`${this.baseUrl}/api/v1/tracks/${encodeURIComponent(track.id)}`, {
          method: 'PUT',
          body: JSON.stringify({
            expected_revision: track.revision,
            track: payload,
          }),
        })
      : await requestJson<ApiObject>(`${this.baseUrl}/api/v1/tracks`, {
          method: 'POST',
          body: JSON.stringify(payload),
        })
    return mapTrack(saved)
  }

  async deleteTrack(trackId: string) {
    await requestJson<ApiObject>(`${this.baseUrl}/api/v1/tracks/${encodeURIComponent(trackId)}`, {
      method: 'DELETE',
    })
  }

  async listTrackMatches(studySet: StudySet) {
    if (studySet.sessions.length === 0 || studySet.trackIds.length === 0) {
      return []
    }
    const payload = {
      sessions: studySet.sessions.map((session) => ({
        library_id: session.libraryId,
        session_ref_id: sessionRefId(session),
        session_key: session.sessionKey,
        run_id: session.runId,
        session_id: session.sessionId,
      })),
      track_ids: studySet.trackIds,
    }
    const response = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/track-matches/query`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    return arrayValue(response.matches).filter(isObject).map(mapTrackMatch)
  }

  async createTrackpointMatchQuery(request: TrackpointMatchQueryRequest) {
    const response = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/trackpoint-match-queries`, {
      method: 'POST',
      body: JSON.stringify(toApiTrackpointMatchQueryRequest(request)),
    })
    return mapTrackpointMatchQuery(response)
  }

  async loadTrackpointMatchQuery(queryId: string) {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/trackpoint-match-queries/${encodeURIComponent(queryId)}`,
    )
    return mapTrackpointMatchQuery(response)
  }

  async loadTrackpointMatchQueryResults(queryId: string, cursor: string | null = null, limit = 100) {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) {
      params.set('cursor', cursor)
    }
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/trackpoint-match-queries/${encodeURIComponent(queryId)}/results?${params}`,
    )
    return mapTrackpointMatchQueryResults(response)
  }

  async cancelTrackpointMatchQuery(queryId: string) {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/trackpoint-match-queries/${encodeURIComponent(queryId)}`,
      { method: 'DELETE' },
    )
    return mapTrackpointMatchQuery(response)
  }

  async loadSessionGpsPoints(
    session: SessionRecord,
    sourceId?: string | null,
    options?: SessionGpsPointLoadOptions,
  ): Promise<SessionGpsPointSet> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(session.libraryId)}/sessions/gps/points`,
      {
        method: 'POST',
        body: JSON.stringify({
          session_ref: toApiSessionRef(session),
          max_points: options?.maxPoints ?? 1800,
          ...(sourceId ? { source_id: sourceId } : {}),
        }),
      },
    )
    return mapSessionGpsPoints(response)
  }

  async loadSessionNote(session: SessionRecord): Promise<SessionNoteRecord> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(session.libraryId)}/sessions/note`,
      {
        method: 'POST',
        body: JSON.stringify({
          session_ref: toApiSessionRef(session),
        }),
      },
    )
    return mapSessionNote(response, session)
  }

  async saveSessionNote(note: SessionNoteRecord): Promise<SessionNoteRecord> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(note.sessionRef.libraryId)}/sessions/note`,
      {
        method: 'PUT',
        body: JSON.stringify({
          session_ref: toApiStudySessionRef(note.sessionRef),
          note: toApiSessionNote(note),
        }),
      },
    )
    return mapSessionNote(response, note.sessionRef)
  }

  async saveSessionNotes(notes: SessionNoteRecord[]): Promise<SessionNoteSaveResult[]> {
    const indexedNotes = notes.map((note, index) => ({ note, index }))
    const groups = new Map<string, Array<{ note: SessionNoteRecord; index: number }>>()
    for (const item of indexedNotes) {
      const libraryId = item.note.sessionRef.libraryId
      groups.set(libraryId, [...(groups.get(libraryId) ?? []), item])
    }

    const results: SessionNoteSaveResult[] = new Array(notes.length)
    await Promise.all(
      [...groups.entries()].map(async ([libraryId, group]) => {
        try {
          const response = await requestJson<ApiObject>(
            `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/sessions/notes`,
            {
              method: 'PUT',
              body: JSON.stringify({
                items: group.map(({ note }) => ({
                  session_ref: toApiStudySessionRef(note.sessionRef),
                  note: toApiSessionNote(note),
                })),
              }),
            },
          )
          const responseResults = arrayValue(response.results).filter(isObject)
          responseResults.forEach((result, responseIndex) => {
            const rawIndex = Number(result.index)
            const source = group[Number.isInteger(rawIndex) ? rawIndex : responseIndex] ?? group[responseIndex]
            if (!source) {
              return
            }
            if (result.ok) {
              const notePayload = objectValue(result.note)
              results[source.index] = {
                ok: true,
                note: mapSessionNote(notePayload, source.note.sessionRef),
              }
              return
            }
            results[source.index] = {
              ok: false,
              sessionRef: source.note.sessionRef,
              message: textValue(result.error, 'Could not save session note.'),
            }
          })
        } catch (error) {
          if (!(error instanceof ApiRequestError) || error.status !== 404) {
            throw error
          }
          const fallbackResults = await mapWithConcurrency(
            group,
            BULK_NOTE_FALLBACK_CONCURRENCY,
            async (source): Promise<SessionNoteSaveResult> => {
              try {
                return { ok: true, note: await this.saveSessionNote(source.note) }
              } catch (saveError) {
                return {
                  ok: false,
                  sessionRef: source.note.sessionRef,
                  message: saveError instanceof Error ? saveError.message : String(saveError),
                }
              }
            },
          )
          fallbackResults.forEach((result, index) => {
            results[group[index].index] = result
          })
        }
      }),
    )

    return results.map((result, index) =>
      result ?? {
        ok: false,
        sessionRef: notes[index].sessionRef,
        message: 'No save result was returned for this session note.',
      },
    )
  }

  async loadSessionVideoAttachments(session: SessionRecord): Promise<SessionVideoAttachmentsRecord> {
    const response = await requestJson<ApiObject>(`${this.baseUrl}${sessionVideosPath(session)}`)
    return mapSessionVideoAttachments(response)
  }

  async saveSessionVideoAttachments(attachments: SessionVideoAttachmentsRecord): Promise<SessionVideoAttachmentsRecord> {
    const response = await requestJson<ApiObject>(`${this.baseUrl}${sessionVideosPathFromRef(attachments.sessionRef)}`, {
      method: 'PUT',
      body: JSON.stringify(toApiSessionVideoAttachments(attachments)),
    })
    return mapSessionVideoAttachments(response)
  }

  sessionVideoStreamUrl(session: SessionRecord, attachmentId: string): string {
    return `${this.baseUrl}${sessionVideosPath(session)}/${encodeURIComponent(attachmentId)}/stream`
  }

  async selectLocalVideoFile(): Promise<LocalVideoFileSelection> {
    const response = await requestJson<ApiObject>(`${this.baseUrl}/api/v1/local/video-file-dialog`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    return {
      selected: Boolean(response.selected),
      path: textValue(response.path),
      workspaceRelativePath: textValue(response.workspace_relative_path),
      displayName: textValue(response.display_name),
      fileName: textValue(response.file_name),
      mediaCreatedAtUnixS: nullableNumberValue(response.media_created_at_unix_s),
      mediaCreatedAtUtc: textValue(response.media_created_at_utc),
    }
  }

  async listSessionBookmarks(session: SessionRecord): Promise<SessionBookmarkRecord[]> {
    const params = new URLSearchParams({
      library_id: session.libraryId,
      session_key: session.sessionKey,
    })
    const response = await requestJson<ApiObject[]>(`${this.baseUrl}/api/v1/bookmarks?${params}`)
    return response.map(mapSessionBookmark)
  }

  async saveSessionBookmark(bookmark: SessionBookmarkRecord): Promise<SessionBookmarkRecord> {
    const payload = toApiSessionBookmark(bookmark)
    const saved =
      bookmark.id && bookmark.revision > 0
        ? await requestJson<ApiObject>(`${this.baseUrl}/api/v1/bookmarks/${encodeURIComponent(bookmark.id)}`, {
            method: 'PUT',
            body: JSON.stringify({
              expected_revision: bookmark.revision,
              bookmark: payload,
            }),
          })
        : await requestJson<ApiObject>(`${this.baseUrl}/api/v1/bookmarks`, {
            method: 'POST',
            body: JSON.stringify(payload),
          })
    return mapSessionBookmark(saved)
  }

  async deleteSessionBookmark(bookmarkId: string): Promise<void> {
    await requestJson<ApiObject>(`${this.baseUrl}/api/v1/bookmarks/${encodeURIComponent(bookmarkId)}`, {
      method: 'DELETE',
    })
  }

  async loadTimeseriesWindow(libraryId: string, request: TimeseriesWindowRequest): Promise<TimeseriesWindowResponse> {
    const usesSecondaryStream = request.signals.some((signal) => signal.streamName && signal.streamName !== 'primary')
    if (usesSecondaryStream) {
      const response = await requestJson<ApiObject>(
        `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/timeseries/multistream-window`,
        {
          method: 'POST',
          body: JSON.stringify(toApiTimeseriesWindowRequest(request)),
        },
      )
      return mapMultistreamTimeseriesWindowResponse(response)
    }
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/timeseries/window`,
      {
        method: 'POST',
        body: JSON.stringify(toApiTimeseriesWindowRequest(request)),
      },
    )
    return mapTimeseriesWindowResponse(response)
  }

  async querySignals(libraryId: string, request: SignalQueryRequest): Promise<SignalQueryResponse> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/signals/query`,
      {
        method: 'POST',
        body: JSON.stringify(toApiSignalQueryRequest(request)),
      },
    )
    return mapSignalQueryResponse(response)
  }

  async queryEvents(libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/events/query`,
      {
        method: 'POST',
        body: JSON.stringify(toApiTableQueryRequest(request)),
      },
    )
    return mapTableQueryResponse(response)
  }

  async queryMetrics(libraryId: string, request: TableQueryRequest): Promise<TableQueryResponse> {
    const response = await requestJson<ApiObject>(
      `${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryId)}/metrics/query`,
      {
        method: 'POST',
        body: JSON.stringify(toApiTableQueryRequest(request)),
      },
    )
    return mapTableQueryResponse(response)
  }
}

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers,
    })
  } catch (error) {
    const method = init.method ?? 'GET'
    const message = error instanceof Error ? error.message : String(error)
    const origin = typeof window === 'undefined' ? 'unknown origin' : window.location.origin
    throw new Error(`Network request failed (${method} ${url} from ${origin}): ${message}`)
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = (await response.json()) as ApiObject
      const error = isObject(payload.error) ? payload.error : null
      const message = error ? textValue(error.message, detail) : detail
      const details = error && isObject(error.details) ? formatApiErrorDetails(error.details) : ''
      detail = details ? `${message} ${details}` : message
    } catch {
      // Keep the HTTP status fallback.
    }
    throw new ApiRequestError(response.status, detail)
  }
  return (await response.json()) as T
}

class ApiRequestError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
  }
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let nextIndex = 0
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      results[index] = await mapper(items[index])
    }
  })
  await Promise.all(workers)
  return results
}

function formatApiErrorDetails(details: ApiObject) {
  const fragments = [
    textValue(details.exception_type),
    textValue(details.exception_message),
    textValue(details.session_dir),
  ].filter(Boolean)
  return fragments.length ? `(${fragments.join('; ')})` : ''
}

function mapLibrary(value: ApiObject): LibraryRecord {
  const id = textValue(value.library_id)
  return {
    id,
    name: textValue(value.display_name, id),
    path: textValue(value.root),
    sessionCount: 0,
  }
}

function mapSession(row: ApiObject): SessionRecord {
  const display = objectValue(row.display)
  const timestamps = objectValue(row.timestamps)
  const noteStatus = objectValue(row.note_status)
  const noteFields = objectValue(row.note_fields)
  const qcSummary = objectValue(row.qc_summary)
  const provenance = objectValue(row.provenance)
  const eventSchema = objectValue(row.event_schema)
  const summary = objectValue(row.summary)
  const gpsSummary = objectValue(row.gps_summary)
  const videoSummary = objectValue(row.video_summary)
  const libraryId = textValue(row.library_id)
  const sessionKey = textValue(row.session_key)
  const runId = textValue(row.run_id)
  const sessionId = textValue(row.session_id)
  const availableSignals = arrayValue(row.available_signals).filter(isObject)
  const qcLevel = qcLevelValue(qcSummary.status)
  const warningCount = numberValue(qcSummary.warning_count)
  const errorCount = numberValue(qcSummary.error_count)
  const sessionLabel = textValue(display.session_label)
  const sessionDisplayName = sessionLabel || textValue(display.label, sessionId || sessionKey)

  return {
    libraryId,
    runId,
    runName: textValue(display.run_label, runId),
    sessionId,
    sessionKey,
    name: sessionDisplayName,
    sessionLabel: sessionLabel || sessionDisplayName,
    startedAt: textValue(timestamps.started_at_local, textValue(timestamps.started_at_utc)),
    bike: textValue(noteFields.bike),
    rider: textValue(noteFields.rider),
    durationMin: numberValue(summary.duration_min),
    distanceKm: numberValue(summary.distance_km),
    noteStatus: noteStatusValue(noteStatus.status),
    qcLevel,
    qcAlerts: qcAlertLabels(qcLevel, warningCount, errorCount),
    preprocessingProfile: textValue(provenance.preprocessing_profile),
    firmware: textValue(provenance.firmware_version),
    eventSchema: textValue(eventSchema.display_name, textValue(eventSchema.schema_id)),
    sourceArchive: textValue(provenance.archive_name),
    signals: availableSignals.map((signal) => textValue(signal.display_name, textValue(signal.column))),
    availableSignals: availableSignals.map(mapSessionSignalSummary),
    gps: [],
    gpsSummary: mapGpsSummary(gpsSummary),
    videoSummary: mapVideoSummary(videoSummary),
  }
}

function mapVideoSummary(value: ApiObject) {
  const attachmentCount = numberValue(value.attachment_count)
  const enabledCount = numberValue(value.enabled_count)
  return {
    present: Boolean(value.present) || attachmentCount > 0,
    attachmentCount,
    enabledCount,
    warnings: arrayValue(value.warnings).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapSessionSignalSummary(value: ApiObject): SessionSignalSummary {
  const motionSource = objectValue(value.motion_source)
  const derivation = objectRecordValue(value.derivation)
  return {
    signalId: textValue(value.signal_id, textValue(value.column)),
    column: textValue(value.column),
    streamName: textValue(value.stream_name, 'primary'),
    streamKind: textValue(value.stream_kind, 'primary'),
    timeColumn: textValue(value.time_column, 'time_s'),
    displayName: textValue(value.display_name, textValue(value.column)),
    end: textValue(value.end),
    domain: textValue(value.domain),
    quantity: textValue(value.quantity),
    unit: textValue(value.unit),
    processingRole: textValue(value.processing_role),
    inspectionVisibility: inspectionVisibilityValue(value.inspection_visibility),
    analysisVariant: textValue(value.analysis_variant),
    kind: textValue(value.kind),
    sensor: textValue(value.sensor),
    component: textValue(value.component),
    coordinateFrame: textValue(value.coordinate_frame),
    vectorGroup: textValue(value.vector_group),
    motionSourceId: textValue(value.motion_source_id, textValue(motionSource.source_id, textValue(value.motion_source))),
    origin: textValue(value.origin),
    ...(Object.keys(derivation).length ? { derivation } : {}),
  }
}

function inspectionVisibilityValue(value: unknown): 'standard' | 'advanced' | 'diagnostic' | '' {
  const normalized = textValue(value).trim().toLowerCase()
  return normalized === 'standard' || normalized === 'advanced' || normalized === 'diagnostic' ? normalized : ''
}

function mapTrack(value: ApiObject): TrackRecord {
  const path = objectValue(value.path)
  const coordinates = arrayValue(path.coordinates).map(coordinatePosition).filter(isCoordinatePosition)
  const lengthM = numberValue(path.length_m)
  const policyRef = objectValue(value.default_policy_ref)
  const source = objectValue(value.source)
  const gpsSampling = objectValue(source.gps_sampling)
  const geometryDenoising = objectValue(source.geometry_denoising)
  return {
    id: textValue(value.track_id),
    name: textValue(value.display_name, textValue(value.track_id)),
    description: textValue(value.description),
    revision: numberValue(value.revision),
    pointCount: coordinates.length,
    distanceKm: lengthM / 1000,
    lengthM,
    points: coordinates,
    defaultPolicyId: textValue(policyRef.policy_id, 'default-geospatial-policy'),
    trackpoints: arrayValue(value.trackpoints)
      .filter(isObject)
      .map((trackpoint) => {
        const position = objectValue(trackpoint.position)
        const cutlineOverride = objectValue(trackpoint.cutline_override)
        const mappedOverride = {
          leftLengthM: nullableNumberValue(cutlineOverride.left_length_m) ?? undefined,
          rightLengthM: nullableNumberValue(cutlineOverride.right_length_m) ?? undefined,
          angleDegFromPathNormal: nullableNumberValue(cutlineOverride.angle_deg_from_path_normal) ?? undefined,
        }
        const hasOverride = Object.values(mappedOverride).some((item) => item !== undefined)
        return {
          id: textValue(trackpoint.trackpoint_id),
          name: textValue(trackpoint.display_name, textValue(trackpoint.trackpoint_id)),
          stationM: numberValue(trackpoint.station_m),
          position: coordinatePosition(position.coordinates) ?? ([0, 0] as GeoPosition),
          cutlineOverride: hasOverride ? mappedOverride : undefined,
        }
      }),
    segmentAliases: arrayValue(value.segment_aliases)
      .filter(isObject)
      .map((alias) => ({
        fromTrackpointId: textValue(alias.from_trackpoint_id),
        toTrackpointId: textValue(alias.to_trackpoint_id),
        name: textValue(alias.display_name, textValue(alias.name)),
        timingRole: (textValue(alias.timing_role) === 'untimed' ? 'untimed' : 'timed') as TrackSegmentAliasRecord['timingRole'],
      }))
      .filter((alias) => alias.fromTrackpointId && alias.toTrackpointId && (alias.name || alias.timingRole === 'untimed')),
    geometryEdits: arrayValue(value.geometry_edits)
      .filter(isObject)
      .filter((edit) => textValue(edit.operation) === 'replace_sector_with_connector')
      .map((edit) => ({
        operation: 'replace_sector_with_connector' as TrackGeometryEditRecord['operation'],
        fromTrackpointId: textValue(edit.from_trackpoint_id),
        toTrackpointId: textValue(edit.to_trackpoint_id),
        fromStationM: numberValue(edit.from_station_m),
        toStationM: numberValue(edit.to_station_m),
        removedLengthM: numberValue(edit.removed_length_m),
        replacementLengthM: numberValue(edit.replacement_length_m),
        appliedAtUtc: textValue(edit.applied_at_utc),
      }))
      .filter((edit) => edit.fromTrackpointId && edit.toTrackpointId),
    matchSummaries: arrayValue(value.match_summaries).filter(isObject).map(mapTrackMatch),
    source: textValue(source.kind)
      ? {
          kind: textValue(source.kind),
          libraryId: textValue(source.library_id) || undefined,
          sessionRefId: textValue(source.session_ref_id) || undefined,
          sessionKey: textValue(source.session_key) || undefined,
          runId: textValue(source.run_id) || undefined,
          sessionId: textValue(source.session_id) || undefined,
          gpsSourceId: textValue(source.gps_source_id) || undefined,
          gpsSourceKind: gpsSourceKindOrNull(source.gps_source_kind) ?? undefined,
          gpsStreamName: textValue(source.gps_stream_name) || undefined,
          gpsSourceSelectionMethod: textValue(source.gps_source_selection_method) || undefined,
          gpsSampling: textValue(gpsSampling.mode)
            ? {
                mode: textValue(gpsSampling.mode),
                sourcePoints: numberValue(gpsSampling.source_points),
                returnedPoints: numberValue(gpsSampling.returned_points),
                maxPoints: numberValue(gpsSampling.max_points),
                stride: nullableNumberValue(gpsSampling.stride),
              }
            : undefined,
          geometryDenoising: textValue(geometryDenoising.estimator) === 'local_polynomial'
            ? {
                estimator: 'local_polynomial',
                windowM: numberValue(geometryDenoising.window_m),
                polynomialOrder: numberValue(geometryDenoising.polynomial_order),
                fitWeighting: textValue(geometryDenoising.fit_weighting) === 'uniform' ? 'uniform' : 'tricube',
                robustIterations: numberValue(geometryDenoising.robust_iterations),
                robustTuningConstant: numberValue(geometryDenoising.robust_tuning_constant),
              }
            : undefined,
        }
      : undefined,
  }
}

function mapTrackMatch(value: ApiObject): SessionTrackMatchRecord {
  const coverage = objectValue(value.coverage)
  const sessionRef = objectValue(value.session_ref)
  const trackRef = objectValue(value.track_ref)
  return {
    trackId: textValue(trackRef.track_id),
    sessionRefId: textValue(sessionRef.session_ref_id),
    status: trackMatchStatusValue(value.status),
    direction: trackDirectionValue(value.direction),
    coverageRatio: numberValue(coverage.track_coverage_ratio),
    matchedGpsPointCount: numberValue(coverage.matched_gps_point_count),
    trackpointResults: arrayValue(value.trackpoint_results)
      .filter(isObject)
      .map((result) => ({
        trackpointId: textValue(result.trackpoint_id),
        crossed: Boolean(result.crossed),
        crossingTimeS: nullableNumberValue(result.crossing_time_s),
        minDistanceM: nullableNumberValue(result.min_distance_m),
        quality: trackpointQualityValue(result.quality),
      })),
    warnings: arrayValue(value.warnings).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapTrackpointMatchQuery(value: ApiObject): TrackpointMatchQueryRecord {
  const trackRef = objectValue(value.track_ref)
  return {
    queryId: textValue(value.query_id),
    status: trackpointMatchQueryStatusValue(value.status),
    trackId: textValue(trackRef.track_id),
    trackRevision: numberValue(trackRef.revision),
    trackpointIds: arrayValue(value.trackpoint_ids).map((item) => textValue(item)).filter(Boolean),
    matchMode: trackpointMatchModeValue(value.match_mode),
    toleranceM: numberValue(value.tolerance_m),
    candidateSessionCount: numberValue(value.candidate_session_count),
    processedSessionCount: numberValue(value.processed_session_count),
    exactSessionCount: numberValue(value.exact_session_count),
    skippedSessionCount: numberValue(value.skipped_session_count),
    matchedSessionCount: numberValue(value.matched_session_count),
    failedSessionCount: numberValue(value.failed_session_count),
    error: textValue(value.error),
  }
}

function mapTrackpointMatchQueryResults(value: ApiObject): TrackpointMatchQueryResults {
  return {
    queryId: textValue(value.query_id),
    resultCount: numberValue(value.result_count),
    returnedCount: numberValue(value.returned_count),
    nextCursor: textValue(value.next_cursor) || null,
    results: arrayValue(value.results)
      .filter(isObject)
      .map((result) => {
        const sessionRef = objectValue(result.session_ref)
        return {
          sessionRef: {
            libraryId: textValue(sessionRef.library_id),
            sessionKey: textValue(sessionRef.session_key),
            runId: textValue(sessionRef.run_id),
            sessionId: textValue(sessionRef.session_id),
            label: textValue(sessionRef.label, textValue(sessionRef.session_id)),
          },
          trackMatchId: textValue(result.track_match_id),
          matchedTrackpointIds: arrayValue(result.matched_trackpoint_ids).map((item) => textValue(item)).filter(Boolean),
          missingTrackpointIds: arrayValue(result.missing_trackpoint_ids).map((item) => textValue(item)).filter(Boolean),
          quality: textValue(result.quality, 'unknown'),
        }
      }),
  }
}

function mapGpsSummary(value: ApiObject): SessionGpsSummary {
  const quality = gpsQualityValue(value.quality)
  const sources = arrayValue(value.sources).filter(isObject).map((source) => ({
    sourceId: textValue(source.source_id),
    kind: gpsSourceKindValue(source.kind),
    streamName: textValue(source.stream_name),
    timebase: gpsTimebaseValue(source.timebase),
    pointCount: numberValue(source.point_count),
    nominalSampleRateHz: nullableNumberValue(source.nominal_sample_rate_hz),
    medianGapS: nullableNumberValue(source.median_gap_s),
    maxGapS: nullableNumberValue(source.max_gap_s),
    gapCountOverThreshold: numberValue(source.gap_count_over_threshold),
    gapThresholdS: numberValue(source.gap_threshold_s),
    qualityColumns: stringRecordValue(source.quality_columns),
    routeReconstruction: objectRecordValue(source.route_reconstruction),
    validCoverageRatio: nullableNumberValue(source.valid_coverage_ratio),
    freshCoverageRatio: nullableNumberValue(source.fresh_coverage_ratio),
    dedupeMethod: textValue(source.dedupe_method) || null,
    cachedAsyncSnapshots: booleanOrNullValue(source.cached_async_snapshots),
  }))
  if (!value.present && sources.length === 0) {
    return emptyGpsSummary
  }
  return {
    present: Boolean(value.present),
    preferredSourceId: textValue(value.preferred_source_id, textValue(value.preferred_source)) || null,
    preferredSourceKind: gpsSourceKindOrNull(value.preferred_source_kind),
    sourceSelectionMethod: textValue(value.source_selection_method, 'unknown'),
    sources,
    sessionDurationS: numberValue(value.session_duration_s),
    timeCoverageRatio: numberValue(value.time_coverage_ratio),
    positionPointCount: numberValue(value.position_point_count),
    quality,
    warnings: arrayValue(value.warnings).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapSessionGpsPoints(value: ApiObject): SessionGpsPointSet {
  const source = objectValue(value.source)
  const sampling = objectValue(value.sampling)
  const points = arrayValue(value.points)
    .filter(isObject)
    .map((point) => ({
      timeS: nullableNumberValue(point.time_s),
      longitude: numberValue(point.longitude),
      latitude: numberValue(point.latitude),
      elevationM: nullableNumberValue(point.elevation_m),
    }))
    .filter((point) => Number.isFinite(point.longitude) && Number.isFinite(point.latitude))
  return {
    present: Boolean(value.present),
    sourceId: textValue(source.source_id),
    sourceKind: gpsSourceKindValue(source.kind),
    streamName: textValue(source.stream_name),
    samplingMode: textValue(sampling.mode),
    sourcePoints: numberValue(sampling.source_points),
    returnedPoints: numberValue(sampling.returned_points),
    maxPoints: numberValue(sampling.max_points),
    stride: nullableNumberValue(sampling.stride),
    sourceSelectionMethod: textValue(source.source_selection_method),
    sourcePolicy: objectRecordValue(source.gps_source_policy),
    routeReconstruction: objectRecordValue(source.route_reconstruction),
    points,
    path: points.map((point) =>
      point.elevationM !== null && Number.isFinite(point.elevationM)
        ? ([point.longitude, point.latitude, point.elevationM] as GeoPosition)
        : ([point.longitude, point.latitude] as GeoPosition),
    ),
    warnings: arrayValue(value.warnings).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapSessionNote(value: ApiObject, fallbackSession: SessionRecord | StudySessionRef): SessionNoteRecord {
  const note = objectValue(value.note)
  const template = objectValue(value.template)
  const rawSessionRef = objectValue(value.session_ref)
  const sessionRef = {
    libraryId: textValue(rawSessionRef.library_id, fallbackSession.libraryId),
    sessionKey: textValue(rawSessionRef.session_key, fallbackSession.sessionKey),
    runId: textValue(rawSessionRef.run_id, fallbackSession.runId),
    sessionId: textValue(rawSessionRef.session_id, fallbackSession.sessionId),
    label: 'label' in fallbackSession ? fallbackSession.label : fallbackSession.name,
  }
  const values = jsonRecordValue(note.values)
  const customValues = jsonRecordValue(note.custom_values)
  return {
    sessionRef,
    present: Boolean(value.present),
    title: textValue(note.title, 'Session note'),
    templateId: textValue(note.template_id),
    templateVersion: textValue(note.template_version),
    templateStatus: template.status === 'ok' ? 'ok' : 'missing',
    templateError: textValue(template.error),
    fields: arrayValue(template.fields).filter(isObject).map(mapSessionNoteField),
    customFieldSection: textValue(template.custom_field_section, 'Custom'),
    values,
    customValues,
    freeTextNotes: textValue(note.free_text_notes),
    draft: Boolean(note.draft),
    createdAtUtc: textValue(note.created_at_utc),
    updatedAtUtc: textValue(note.updated_at_utc),
  }
}

function mapSessionNoteField(value: ApiObject): SessionNoteFieldDef {
  return {
    fieldId: textValue(value.field_id),
    label: textValue(value.label, textValue(value.field_id)),
    fieldType: sessionNoteFieldTypeValue(value.field_type),
    section: textValue(value.section, 'General'),
    required: Boolean(value.required),
    default: jsonNoteValue(value.default),
    unit: textValue(value.unit),
    helpText: textValue(value.help_text),
    enumOptions: arrayValue(value.enum_options).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapSessionBookmark(value: ApiObject): SessionBookmarkRecord {
  const window = objectValue(value.window)
  const provenance = objectValue(value.provenance)
  const rawViewState = objectValue(value.view_state)
  const rawInspectorState = objectValue(rawViewState.bodaqs_web_signal_inspector_v1)
  const signalColumns = arrayValue(rawInspectorState.signal_columns).map((item) => textValue(item)).filter(Boolean)
  const signalRefs = arrayValue(rawInspectorState.signal_refs)
    .filter(isObject)
    .map((item) => ({ streamName: textValue(item.stream_name, 'primary'), column: textValue(item.column) }))
    .filter((item) => Boolean(item.column))
  return {
    id: textValue(value.bookmark_id),
    revision: numberValue(value.revision),
    title: textValue(value.display_name, textValue(value.title, 'Bookmark')),
    description: textValue(value.description),
    sessionRef: mapStudySessionRef(objectValue(value.session)),
    window: {
      startS: numberValue(window.start_s),
      endS: numberValue(window.end_s),
    },
    viewState: {
      ...rawViewState,
      signalInspector: {
        signalColumns,
        ...(signalRefs.length ? { signalRefs } : {}),
        showMarks: rawInspectorState.show_marks === false ? false : true,
      },
    },
    tags: arrayValue(value.tags).map((item) => textValue(item)).filter(Boolean),
    private: value.private === false ? false : true,
    createdAtUtc: textValue(provenance.created_at),
    updatedAtUtc: textValue(provenance.updated_at, textValue(provenance.created_at)),
  }
}

function mapSessionVideoAttachments(value: ApiObject): SessionVideoAttachmentsRecord {
  const doc = objectValue(value.video_attachments)
  return {
    sessionRef: mapStudySessionRef(objectValue(value.session_ref)),
    present: Boolean(value.present),
    revision: numberValue(doc.revision),
    attachments: arrayValue(doc.attachments).filter(isObject).map(mapSessionVideoAttachment),
    createdAtUtc: textValue(doc.created_at_utc),
    updatedAtUtc: textValue(doc.updated_at_utc),
  }
}

function mapSessionVideoAttachment(value: ApiObject): SessionVideoAttachmentRecord {
  return {
    attachmentId: textValue(value.attachment_id),
    displayName: textValue(value.display_name, 'Video'),
    cameraLabel: textValue(value.camera_label),
    path: textValue(value.path),
    workspaceRelativePath: textValue(value.workspace_relative_path),
    libraryRelativePath: textValue(value.library_relative_path),
    sessionRelativePath: textValue(value.session_relative_path),
    uri: textValue(value.uri),
    mediaType: textValue(value.media_type),
    enabled: value.enabled === false ? false : true,
    sessionTimeAtVideoZeroS: numberValue(value.session_time_at_video_zero_s),
  }
}

function mapSignalQueryResponse(value: ApiObject): SignalQueryResponse {
  return {
    sessions: arrayValue(value.sessions).filter(isObject).map(mapSignalQuerySession),
    warnings: arrayValue(value.warnings).filter(isObject).map((warning) => ({ ...warning })),
  }
}

function mapSignalQuerySession(value: ApiObject): SignalQuerySession {
  const sampling = objectValue(value.sampling)
  const time = objectValue(value.time)
  const timeColumn = textValue(time.column)
  const timeUnit = textValue(time.unit, 's')
  return {
    sessionRef: mapStudySessionRef(objectValue(value.session)),
    time: timeColumn
      ? {
          column: timeColumn,
          unit: 's',
          values: normalizeTimeValues(arrayValue(time.values).map(nullableNumberValue), timeUnit),
        }
      : null,
    sampling: {
      mode: textValue(sampling.mode),
      sourcePoints: numberValue(sampling.source_points),
      returnedPoints: numberValue(sampling.returned_points),
      distributionCorrect: Boolean(sampling.distribution_correct),
    },
    signals: arrayValue(value.signals).filter(isObject).map(mapSignalQuerySignal),
  }
}

function mapSignalQuerySignal(value: ApiObject): SignalQuerySignal {
  const motionSource = objectValue(value.motion_source)
  const derivation = objectRecordValue(value.derivation)
  return {
    role: textValue(value.role, 'signal'),
    signalId: textValue(value.signal_id),
    column: textValue(value.column),
    displayName: textValue(value.display_name, textValue(value.column)),
    end: textValue(value.end),
    domain: textValue(value.domain),
    quantity: textValue(value.quantity),
    unit: textValue(value.unit),
    processingRole: textValue(value.processing_role),
    kind: textValue(value.kind),
    sensor: textValue(value.sensor),
    motionSourceId: textValue(value.motion_source_id, textValue(motionSource.source_id, textValue(value.motion_source))),
    origin: textValue(value.origin),
    ...(Object.keys(derivation).length ? { derivation } : {}),
    values: arrayValue(value.values).map(nullableNumberValue),
  }
}

function mapTimeseriesWindowResponse(value: ApiObject): TimeseriesWindowResponse {
  const sampling = objectValue(value.sampling)
  const window = objectValue(value.window)
  const time = objectValue(value.time)
  const timeUnit = textValue(time.unit, 's')
  return {
    sessionRef: mapStudySessionRef(objectValue(value.session)),
    window: {
      requestedStartS: nullableNumberValue(window.requested_start_s),
      requestedEndS: nullableNumberValue(window.requested_end_s),
      returnedStartS: nullableNumberValue(window.returned_start_s),
      returnedEndS: nullableNumberValue(window.returned_end_s),
    },
    sampling: {
      mode: textValue(sampling.mode),
      sourcePoints: numberValue(sampling.source_points),
      returnedPoints: numberValue(sampling.returned_points),
      targetPoints: numberValue(sampling.target_points),
    },
    time: {
      column: textValue(time.column),
      unit: 's',
      values: normalizeTimeValues(arrayValue(time.values).map(nullableNumberValue), timeUnit),
    },
    signals: arrayValue(value.signals).filter(isObject).map(mapTimeseriesWindowSignal),
    events: arrayValue(value.events).filter(isObject).map(mapTimeseriesWindowEvent),
    marks: arrayValue(value.marks)
      .filter(isObject)
      .map((mark) => mapTimeseriesWindowMark(mark, timeUnit)),
    warnings: arrayValue(value.warnings).map((warning) => textValue(warning)).filter(Boolean),
  }
}

function mapTimeseriesWindowSignal(value: ApiObject): TimeseriesWindowSignal {
  return {
    ...mapSessionSignalSummary(value),
    values: arrayValue(value.values).map(nullableNumberValue),
  }
}

function mapMultistreamTimeseriesWindowResponse(value: ApiObject): TimeseriesWindowResponse {
  const window = objectValue(value.window)
  const groups = arrayValue(value.groups).filter(isObject)
  const series: Array<{ signal: TimeseriesWindowSignal; time: Array<number | null> }> = []
  let sourcePoints = 0
  let returnedPoints = 0
  let targetPoints = 0
  for (const group of groups) {
    const stream = objectValue(group.stream)
    const sampling = objectValue(group.sampling)
    const time = objectValue(group.time)
    const timeUnit = textValue(time.unit, 's')
    const values = normalizeTimeValues(arrayValue(time.values).map(nullableNumberValue), timeUnit)
    sourcePoints += numberValue(sampling.source_points)
    returnedPoints += numberValue(sampling.returned_points)
    targetPoints = Math.max(targetPoints, numberValue(sampling.target_points))
    for (const rawSignal of arrayValue(group.signals).filter(isObject)) {
      const signal = mapTimeseriesWindowSignal(rawSignal)
      series.push({
        signal: {
          ...signal,
          streamName: textValue(rawSignal.stream_name, textValue(stream.stream_name, 'primary')),
          streamKind: textValue(rawSignal.stream_kind, textValue(stream.stream_kind, 'primary')),
          timeColumn: textValue(rawSignal.time_column, textValue(stream.time_column, textValue(time.column, 'time_s'))),
          connectAlignmentGaps: true,
          nativeTimeValues: values,
          nativeValues: signal.values,
        },
        time: values,
      })
    }
  }
  const allTimes = Array.from(new Set(series.flatMap((item) => item.time.filter((time): time is number => typeof time === 'number' && Number.isFinite(time))))).sort((a, b) => a - b)
  const signals = series.map(({ signal, time }) => {
    const byTime = new Map<number, number | null>()
    signal.values.forEach((value, index) => {
      const sampleTime = time[index]
      if (typeof sampleTime === 'number' && Number.isFinite(sampleTime)) byTime.set(sampleTime, value)
    })
    return { ...signal, values: allTimes.map((sampleTime) => byTime.get(sampleTime) ?? null) }
  })
  return {
    sessionRef: mapStudySessionRef(objectValue(value.session)),
    window: {
      requestedStartS: nullableNumberValue(window.requested_start_s),
      requestedEndS: nullableNumberValue(window.requested_end_s),
      returnedStartS: nullableNumberValue(window.returned_start_s),
      returnedEndS: nullableNumberValue(window.returned_end_s),
    },
    sampling: { mode: 'multi_stream', sourcePoints, returnedPoints, targetPoints },
    time: { column: 'session_time_s', unit: 's', values: allTimes },
    signals,
    events: arrayValue(value.events).filter(isObject).map(mapTimeseriesWindowEvent),
    marks: arrayValue(value.marks).filter(isObject).map((mark) => mapTimeseriesWindowMark(mark, 's')),
    warnings: arrayValue(value.warnings).map((warning) => textValue(warning)).filter(Boolean),
  }
}

function mapTimeseriesWindowEvent(value: ApiObject): TimeseriesWindowEvent {
  return {
    eventId: textValue(value.event_id, textValue(value.id)),
    eventType: textValue(value.event_type, textValue(value.schema_id)),
    displayName: textValue(value.display_name, textValue(value.event_type, textValue(value.schema_id))),
    startS: nullableNumberValue(value.start_s),
    endS: nullableNumberValue(value.end_s),
    peakTimeS: nullableNumberValue(value.peak_time_s),
    end: textValue(value.end),
    metrics: objectRecordValue(value.metrics),
  }
}

function mapTimeseriesWindowMark(value: ApiObject, timeUnit: string): TimeseriesWindowMark {
  const factor = timeUnitToSecondsFactor(timeUnit)
  const rawTimeS = nullableNumberValue(value.time_s)
  return {
    markId: textValue(value.mark_id, textValue(value.id)),
    timeS: rawTimeS !== null ? rawTimeS * factor : Number.NaN,
    displayName: textValue(value.display_name, 'Mark'),
    column: textValue(value.column),
  }
}

function normalizeTimeValues(values: Array<number | null>, unit: string) {
  const factor = timeUnitToSecondsFactor(unit)
  return values.map((value) => (typeof value === 'number' && Number.isFinite(value) ? value * factor : null))
}

function timeUnitToSecondsFactor(unit: string) {
  const normalized = unit.trim().toLowerCase()
  if (['ms', 'millisecond', 'milliseconds'].includes(normalized)) {
    return 1 / 1000
  }
  if (['us', 'microsecond', 'microseconds'].includes(normalized)) {
    return 1 / 1_000_000
  }
  if (['ns', 'nanosecond', 'nanoseconds'].includes(normalized)) {
    return 1 / 1_000_000_000
  }
  if (['min', 'mins', 'minute', 'minutes'].includes(normalized)) {
    return 60
  }
  return 1
}

function mapTableQueryResponse(value: ApiObject): TableQueryResponse {
  return {
    rowKind: value.row_kind === 'metric' ? 'metric' : 'event',
    rowCount: numberValue(value.row_count),
    rows: arrayValue(value.rows).filter(isObject).map(mapTableQueryRow),
    warnings: arrayValue(value.warnings).filter(isObject).map((warning) => ({ ...warning })),
  }
}

function mapTableQueryRow(value: ApiObject): TableQueryRow {
  return {
    sessionRef: mapStudySessionRef(objectValue(value.session)),
    setId: textValue(value.event_set_id, textValue(value.metric_set_id)),
    rowIndex: numberValue(value.row_index),
    eventType: textValue(value.event_type),
    signalRole: signalRoleValue(value.signal_role),
    fields: objectRecordValue(value.fields),
  }
}

function mapStudySessionRef(value: ApiObject): StudySessionRef {
  return {
    libraryId: textValue(value.library_id),
    sessionKey: textValue(value.session_key),
    runId: textValue(value.run_id),
    sessionId: textValue(value.session_id),
    label: textValue(value.label, textValue(value.session_id)),
  }
}

function mapAnalysisView(value: ApiObject): AnalysisViewRecord {
  const viewId = textValue(value.view_id, textValue(value.id))
  const requirements = objectValue(value.requirements)
  return {
    id: viewId,
    displayName: textValue(value.display_name, viewId),
    category: textValue(value.category),
    description: textValue(value.description),
    route: textValue(value.route),
    adequacyPolicy: textValue(value.adequacy_policy),
    requirements: Object.fromEntries(
      Object.entries(requirements).map(([tier, items]) => [
        tier,
        arrayValue(items)
          .filter(isObject)
          .map((item) => mapAnalysisRequirement(item, requirementTierValue(tier))),
      ]),
    ),
  }
}

function mapAnalysisRequirement(value: ApiObject, fallbackTier: AnalysisRequirementTier): AnalysisRequirementRecord {
  const requirementId = textValue(value.requirement_id, textValue(value.id))
  return {
    requirementId,
    label: textValue(value.label, requirementId),
    tier: requirementTierValue(value.tier, fallbackTier),
    description: textValue(value.description),
  }
}

function mapAnalysisAdequacy(value: ApiObject): AnalysisAdequacyResult {
  const viewId = textValue(value.view_id, textValue(value.id))
  return {
    viewId,
    displayName: textValue(value.display_name, viewId),
    status: adequacyStatusValue(value.status),
    policy: textValue(value.policy, textValue(value.adequacy_policy)),
    summary: textValue(value.summary),
    totalSessionCount: numberValue(value.total_session_count),
    usableSessionCount: numberValue(value.usable_session_count),
    blockedSessionCount: numberValue(value.blocked_session_count),
    messages: arrayValue(value.messages).filter(isObject).map(mapAnalysisAdequacyMessage),
    sessionResults: arrayValue(value.session_results).filter(isObject).map(mapAnalysisAdequacySessionResult),
    scopeCriteria: arrayValue(value.scope_criteria).filter(isObject).map(mapAnalysisAdequacyCriterionResult),
  }
}

function mapAnalysisAdequacyMessage(value: ApiObject): AnalysisAdequacyMessage {
  const sessionRef = objectValue(value.session_ref)
  return {
    level: messageLevelValue(value.level ?? value.severity),
    code: textValue(value.code),
    message: textValue(value.message),
    ...(Object.keys(sessionRef).length ? { sessionRef: mapStudySessionRef(sessionRef) } : {}),
    detail: objectRecordValue(value.detail),
  }
}

function mapAnalysisAdequacySessionResult(value: ApiObject): AnalysisAdequacySessionResult {
  const sessionRef = objectValue(value.session_ref)
  return {
    sessionRef: mapStudySessionRef(Object.keys(sessionRef).length ? sessionRef : value),
    status: adequacyStatusValue(value.status),
    summary: textValue(value.summary),
    requiredPassed: value.required_passed === true || value.usable === true,
    recommendedMissing: arrayValue(value.recommended_missing ?? value.missing_recommended).map((item) => textValue(item)).filter(Boolean),
    optionalMissing: arrayValue(value.optional_missing ?? value.missing_optional).map((item) => textValue(item)).filter(Boolean),
    criteria: arrayValue(value.criteria).filter(isObject).map(mapAnalysisAdequacyCriterionResult),
    units: objectRecordValue(value.units),
  }
}

function mapAnalysisAdequacyCriterionResult(value: ApiObject): AnalysisAdequacyCriterionResult {
  return {
    requirementId: textValue(value.requirement_id),
    met: value.met === true,
    detail: textValue(value.detail),
  }
}

function mapStudySet(value: ApiObject): StudySet {
  const sessions = arrayValue(value.sessions).filter(isObject).map(mapStudySessionRef)
  const groupings = arrayValue(value.groupings).filter(isObject).map<StudyGrouping>((grouping, index) => ({
    id: textValue(grouping.grouping_id),
    name: textValue(grouping.display_name, textValue(grouping.grouping_id)),
    color: textValue(grouping.color, groupingColors[index % groupingColors.length]),
    sessionRefs: arrayValue(grouping.session_refs).map((item) => textValue(item)),
  }))
  const tracks = arrayValue(value.tracks).filter(isObject)
  return {
    id: textValue(value.study_set_id) || null,
    displayName: textValue(value.display_name),
    revision: numberValue(value.revision),
    saved: true,
    sessions,
    groupings,
    trackIds: tracks.map((track) => textValue(track.track_id)).filter(Boolean),
    provenance: provenanceLabel(objectValue(value.provenance)),
  }
}

function mapSavedSessionFilter(value: ApiObject): SavedSessionFilterRecord {
  const filterId = textValue(value.filter_id)
  return {
    id: filterId,
    displayName: textValue(value.display_name, filterId),
    description: textValue(value.description),
    category: textValue(value.category),
    origin: 'api_saved',
    revision: numberValue(value.revision),
    predicate: sessionFilterPredicateValue(value.predicate),
  }
}

function toApiStudySet(studySet: StudySet) {
  const payload: ApiObject = {
    schema: 'bodaqs.study_set',
    version: 1,
    display_name: studySet.displayName.trim(),
    revision: studySet.revision,
    sessions: studySet.sessions.map((session) => ({
      library_id: session.libraryId,
      session_ref_id: sessionRefId(session),
      session_key: session.sessionKey,
      run_id: session.runId,
      session_id: session.sessionId,
      label: session.label,
    })),
    groupings: studySet.groupings.map((grouping) => ({
      grouping_id: grouping.id,
      display_name: grouping.name,
      color: grouping.color,
      session_refs: grouping.sessionRefs,
    })),
    tracks: studySet.trackIds.map((trackId) => ({ track_id: trackId })),
    bookmarks: [],
    provenance: {
      created_by: 'bodaqs_web_prototype',
      created_from: {
        kind: 'manual_selection',
        details: {
          note: studySet.provenance || 'Created in the Library Browser prototype',
        },
      },
    },
    display_state: {
      bodaqs_web_v1: {},
    },
  }

  if (studySet.id) {
    payload.study_set_id = studySet.id
  }

  return payload
}

function toApiSessionFilter(filter: SavedSessionFilterRecord) {
  const payload: ApiObject = {
    schema: 'bodaqs.session_filter',
    version: 1,
    display_name: filter.displayName.trim(),
    description: filter.description ?? '',
    category: filter.category.trim(),
    revision: filter.revision,
    predicate: filter.predicate as unknown as ApiObject,
    display_state: {
      bodaqs_web_v1: {},
    },
  }

  if (filter.id && filter.origin === 'api_saved') {
    payload.filter_id = filter.id
  }

  return payload
}

function toApiTrack(track: TrackRecord) {
  const payload: ApiObject = {
    schema: 'bodaqs.track',
    version: 1,
    display_name: track.name.trim(),
    description: track.description ?? '',
    revision: track.revision,
    path: {
      type: 'LineString',
      coordinates: track.points.map((position) => coordinatePayload(position)),
      coordinate_reference_system: 'EPSG:4326',
      distance_model: 'geodesic',
      length_m: track.lengthM,
    },
    direction: {
      positive: 'coordinate_order',
      description: 'Positive direction follows the stored coordinate order.',
    },
    default_policy_ref: {
      policy_id: track.defaultPolicyId || 'default-geospatial-policy',
      version: 1,
    },
    trackpoints: track.trackpoints.map((trackpoint) => {
      const out: ApiObject = {
        trackpoint_id: trackpoint.id,
        display_name: trackpoint.name,
        station_m: trackpoint.stationM,
        position: {
          type: 'Point',
          coordinates: coordinatePayload(trackpoint.position),
        },
      }
      if (trackpoint.cutlineOverride) {
        out.cutline_override = {
          left_length_m: trackpoint.cutlineOverride.leftLengthM,
          right_length_m: trackpoint.cutlineOverride.rightLengthM,
          angle_deg_from_path_normal: trackpoint.cutlineOverride.angleDegFromPathNormal,
        }
      }
      return out
    }),
    segment_aliases: (track.segmentAliases ?? []).map((alias) => ({
      from_trackpoint_id: alias.fromTrackpointId,
      to_trackpoint_id: alias.toTrackpointId,
      display_name: alias.name,
      ...(alias.timingRole === 'untimed' ? { timing_role: 'untimed' } : {}),
    })),
    geometry_edits: (track.geometryEdits ?? []).map((edit) => ({
      operation: edit.operation,
      from_trackpoint_id: edit.fromTrackpointId,
      to_trackpoint_id: edit.toTrackpointId,
      from_station_m: edit.fromStationM,
      to_station_m: edit.toStationM,
      removed_length_m: edit.removedLengthM,
      replacement_length_m: edit.replacementLengthM,
      applied_at_utc: edit.appliedAtUtc,
    })),
    display_state: {
      bodaqs_web_v1: {},
    },
  }
  if (track.id) {
    payload.track_id = track.id
  }
  if (track.source) {
    payload.source = {
      kind: track.source.kind,
      library_id: track.source.libraryId,
      session_ref_id: track.source.sessionRefId,
      session_key: track.source.sessionKey,
      run_id: track.source.runId,
      session_id: track.source.sessionId,
      gps_source_id: track.source.gpsSourceId,
      gps_source_kind: track.source.gpsSourceKind,
      gps_stream_name: track.source.gpsStreamName,
      gps_source_selection_method: track.source.gpsSourceSelectionMethod,
      gps_sampling: track.source.gpsSampling
        ? {
            mode: track.source.gpsSampling.mode,
            source_points: track.source.gpsSampling.sourcePoints,
            returned_points: track.source.gpsSampling.returnedPoints,
            max_points: track.source.gpsSampling.maxPoints,
            stride: track.source.gpsSampling.stride,
          }
        : undefined,
      geometry_denoising: track.source.geometryDenoising
        ? {
            estimator: track.source.geometryDenoising.estimator,
            window_m: track.source.geometryDenoising.windowM,
            polynomial_order: track.source.geometryDenoising.polynomialOrder,
            fit_weighting: track.source.geometryDenoising.fitWeighting,
            robust_iterations: track.source.geometryDenoising.robustIterations,
            robust_tuning_constant: track.source.geometryDenoising.robustTuningConstant,
          }
        : undefined,
    }
  }
  return payload
}

function toApiTrackpointMatchQueryRequest(request: TrackpointMatchQueryRequest) {
  const payload: ApiObject = {
    track_id: request.trackId,
    trackpoint_ids: request.trackpointIds,
    match_mode: request.matchMode,
    tolerance_m: request.toleranceM,
    persist: request.persist ?? true,
  }
  if (request.minCount !== undefined) {
    payload.min_count = request.minCount
  }
  if (request.scope) {
    payload.scope = {
      library_ids: request.scope.libraryIds,
      session_refs: request.scope.sessionRefs?.map((session) => ({
        library_id: session.libraryId,
        session_key: session.sessionKey,
        run_id: session.runId,
        session_id: session.sessionId,
        label: session.label,
      })),
    }
  }
  return payload
}

function toApiSessionRef(session: SessionRecord) {
  return {
    library_id: session.libraryId,
    session_ref_id: candidateId(session),
    session_key: session.sessionKey,
    run_id: session.runId,
    session_id: session.sessionId,
  }
}

function toApiStudySessionRef(sessionRef: StudySessionRef) {
  return {
    library_id: sessionRef.libraryId,
    session_ref_id: sessionRefId(sessionRef),
    session_key: sessionRef.sessionKey,
    run_id: sessionRef.runId,
    session_id: sessionRef.sessionId,
    label: sessionRef.label,
  }
}

function toApiSignalQueryRequest(request: SignalQueryRequest) {
  return {
    sessions: request.sessions.map(toApiStudySessionRef),
    signals: request.signals.map((signal) => ({
      role: signal.role,
      ...(signal.column ? { column: signal.column } : {}),
      ...(signal.selector ? { selector: signal.selector } : {}),
    })),
  }
}

function toApiTimeseriesWindowRequest(request: TimeseriesWindowRequest) {
  return {
    session: toApiStudySessionRef(request.session),
    signals: request.signals.map((signal) => ({
      ...(signal.column ? { column: signal.column } : {}),
      ...(signal.selector ? { selector: signal.selector } : {}),
      ...(signal.streamName ? { stream_name: signal.streamName } : {}),
    })),
    ...(request.window
      ? {
          window: {
            start_s: request.window.startS ?? null,
            end_s: request.window.endS ?? null,
          },
        }
      : {}),
    ...(request.resolution?.targetPoints
      ? {
          resolution: {
            target_points: request.resolution.targetPoints,
          },
        }
      : {}),
    include_events: Boolean(request.includeEvents),
    include_marks: Boolean(request.includeMarks),
  }
}

function toApiTableQueryRequest(request: TableQueryRequest) {
  return {
    sessions: request.sessions.map(toApiStudySessionRef),
    ...(request.eventTypes?.length ? { event_types: request.eventTypes } : {}),
  }
}

function toApiSessionNote(note: SessionNoteRecord) {
  return {
    schema: 'bodaqs.session_notes.document',
    version: 1,
    run_id: note.sessionRef.runId,
    session_id: note.sessionRef.sessionId,
    session_key: note.sessionRef.sessionKey,
    title: note.title.trim() || 'Session note',
    template_id: note.templateId || 'web_session_note',
    template_version: note.templateVersion || '1.0',
    values: note.values,
    custom_values: note.customValues,
    free_text_notes: note.freeTextNotes,
    created_at_utc: note.createdAtUtc,
    updated_at_utc: note.updatedAtUtc,
    draft: note.draft,
  }
}

function toApiSessionBookmark(bookmark: SessionBookmarkRecord) {
  const existingViewState = { ...bookmark.viewState }
  delete existingViewState.signalInspector
  return {
    ...(bookmark.id ? { bookmark_id: bookmark.id } : {}),
    display_name: bookmark.title.trim() || 'Bookmark',
    description: bookmark.description,
    session: toApiStudySessionRef(bookmark.sessionRef),
    window: {
      start_s: bookmark.window.startS,
      end_s: bookmark.window.endS,
    },
    view_state: {
      ...existingViewState,
      bodaqs_web_signal_inspector_v1: {
        signal_columns: bookmark.viewState.signalInspector?.signalColumns ?? [],
        ...(bookmark.viewState.signalInspector?.signalRefs
          ? {
              signal_refs: bookmark.viewState.signalInspector.signalRefs.map((signal) => ({
                stream_name: signal.streamName,
                column: signal.column,
              })),
            }
          : {}),
        show_marks: bookmark.viewState.signalInspector?.showMarks ?? true,
      },
    },
    tags: bookmark.tags,
    private: bookmark.private,
  }
}

function toApiSessionVideoAttachments(attachments: SessionVideoAttachmentsRecord) {
  return {
    schema: 'bodaqs.session_video_attachments',
    version: 1,
    revision: attachments.revision,
    run_id: attachments.sessionRef.runId,
    session_id: attachments.sessionRef.sessionId,
    session_key: attachments.sessionRef.sessionKey,
    attachments: attachments.attachments.map((attachment) => ({
      ...(attachment.attachmentId ? { attachment_id: attachment.attachmentId } : {}),
      display_name: attachment.displayName.trim() || 'Video',
      camera_label: attachment.cameraLabel,
      path: attachment.path,
      workspace_relative_path: attachment.workspaceRelativePath,
      library_relative_path: attachment.libraryRelativePath,
      session_relative_path: attachment.sessionRelativePath,
      uri: attachment.uri,
      media_type: attachment.mediaType,
      enabled: attachment.enabled,
      session_time_at_video_zero_s: attachment.sessionTimeAtVideoZeroS,
    })),
    created_at_utc: attachments.createdAtUtc,
    updated_at_utc: attachments.updatedAtUtc,
  }
}

function sessionVideosPath(session: SessionRecord) {
  return `/api/v1/libraries/${encodeURIComponent(session.libraryId)}/runs/${encodeURIComponent(session.runId)}/sessions/${encodeURIComponent(
    session.sessionId,
  )}/videos`
}

function sessionVideosPathFromRef(session: StudySessionRef) {
  return `/api/v1/libraries/${encodeURIComponent(session.libraryId)}/runs/${encodeURIComponent(session.runId)}/sessions/${encodeURIComponent(
    session.sessionId,
  )}/videos`
}

function noteStatusValue(value: unknown): NoteStatus {
  if (value === 'draft' || value === 'edited') {
    return value
  }
  return 'missing'
}

function gpsQualityValue(value: unknown): GpsQuality {
  if (value === 'usable' || value === 'limited' || value === 'invalid') {
    return value
  }
  return 'absent'
}

function gpsSourceKindValue(value: unknown): GpsSourceKind {
  if (value === 'logger_sensor' || value === 'fit_enrichment' || value === 'imported_route') {
    return value
  }
  return 'unknown'
}

function gpsSourceKindOrNull(value: unknown): GpsSourceKind | null {
  const kind = gpsSourceKindValue(value)
  return kind === 'unknown' ? null : kind
}

function gpsTimebaseValue(value: unknown): GpsTimebase {
  if (value === 'uniform' || value === 'intermittent') {
    return value
  }
  return 'unknown'
}

function trackMatchStatusValue(value: unknown): TrackMatchStatus {
  if (
    value === 'matched' ||
    value === 'partial' ||
    value === 'no_gps' ||
    value === 'no_overlap' ||
    value === 'ambiguous' ||
    value === 'failed'
  ) {
    return value
  }
  return 'failed'
}

function trackDirectionValue(value: unknown): TrackDirection {
  if (value === 'positive' || value === 'reverse') {
    return value
  }
  return 'unknown'
}

function trackpointQualityValue(value: unknown): 'good' | 'approximate' | 'ambiguous' | 'missing' {
  if (value === 'good' || value === 'approximate' || value === 'ambiguous') {
    return value
  }
  return 'missing'
}

function trackpointMatchModeValue(value: unknown): TrackpointMatchMode {
  if (value === 'any' || value === 'min_count') {
    return value
  }
  return 'all'
}

function trackpointMatchQueryStatusValue(value: unknown): TrackpointMatchQueryStatus {
  if (value === 'running' || value === 'completed' || value === 'cancelled' || value === 'failed') {
    return value
  }
  return 'queued'
}

function signalRoleValue(value: unknown): 'front' | 'rear' | 'unknown' {
  if (value === 'front' || value === 'rear') {
    return value
  }
  return 'unknown'
}

function qcLevelValue(value: unknown): QcLevel {
  if (value === 'warning' || value === 'alert') {
    return value
  }
  return 'ok'
}

function qcAlertLabels(level: QcLevel, warnings: number, alerts: number) {
  if (level === 'ok') {
    return []
  }
  const labels: string[] = []
  if (warnings > 0) {
    labels.push(`${warnings} warning${warnings === 1 ? '' : 's'} reported`)
  }
  if (alerts > 0) {
    labels.push(`${alerts} alert${alerts === 1 ? '' : 's'} reported`)
  }
  return labels.length ? labels : [`${level} status reported`]
}

function provenanceLabel(provenance: ApiObject) {
  const createdFrom = objectValue(provenance.created_from)
  const kind = textValue(createdFrom.kind)
  return kind ? `Created from ${kind.replace(/_/g, ' ')}` : ''
}

function objectValue(value: unknown): ApiObject {
  return isObject(value) ? value : {}
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function textValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function nullableNumberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function jsonRecordValue(value: unknown): Record<string, SessionNoteValue> {
  const raw = objectValue(value)
  return Object.fromEntries(
    Object.entries(raw).map(([key, item]) => [key, jsonNoteValue(item)]),
  )
}

function objectRecordValue(value: unknown): Record<string, unknown> {
  return { ...objectValue(value) }
}

function stringRecordValue(value: unknown): Record<string, string> {
  const raw = objectValue(value)
  return Object.fromEntries(
    Object.entries(raw)
      .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
      .map(([key, item]) => [key, item]),
  )
}

function booleanOrNullValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null
}

function jsonNoteValue(value: unknown): SessionNoteValue {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  if (Array.isArray(value)) {
    return value.map((item) => textValue(item)).filter(Boolean)
  }
  return null
}

function sessionNoteFieldTypeValue(value: unknown): SessionNoteFieldType {
  if (
    value === 'text' ||
    value === 'int' ||
    value === 'float' ||
    value === 'bool' ||
    value === 'enum' ||
    value === 'multi_enum' ||
    value === 'date'
  ) {
    return value
  }
  return 'string'
}

function sessionFilterPredicateValue(value: unknown): SessionFilterPredicate {
  if (isObject(value) && typeof value.op === 'string') {
    return value as unknown as SessionFilterPredicate
  }
  return { field: 'rider', op: 'contains', value: '' }
}

function requirementTierValue(value: unknown, fallback: AnalysisRequirementTier = 'optional'): AnalysisRequirementTier {
  if (value === 'required' || value === 'recommended' || value === 'optional') {
    return value
  }
  return fallback
}

function adequacyStatusValue(value: unknown): AnalysisAdequacyStatus {
  if (value === 'ready' || value === 'warning' || value === 'partial' || value === 'blocked') {
    return value
  }
  return 'unknown'
}

function messageLevelValue(value: unknown): AnalysisAdequacyMessage['level'] {
  if (value === 'warning' || value === 'error') {
    return value
  }
  return 'info'
}

function coordinatePosition(value: unknown): GeoPosition | null {
  if (!Array.isArray(value) || value.length < 2) {
    return null
  }
  const x = value[0]
  const y = value[1]
  if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) {
    return null
  }
  const z = value[2]
  return typeof z === 'number' && Number.isFinite(z) ? [x, y, z] : [x, y]
}

function isCoordinatePosition(value: GeoPosition | null): value is GeoPosition {
  return value !== null
}

function coordinatePayload(position: GeoPosition) {
  return Number.isFinite(position[2]) ? [position[0], position[1], position[2]] : [position[0], position[1]]
}

function isObject(value: unknown): value is ApiObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
