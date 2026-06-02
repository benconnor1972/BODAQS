import { groupingColors, sessionRefId } from '../domain/studySets'
import { emptyGpsSummary } from '../domain/geospatial'
import type {
  GpsQuality,
  GpsSourceKind,
  GpsTimebase,
  LibraryRecord,
  NoteStatus,
  QcLevel,
  SessionGpsSummary,
  SessionRecord,
  StudyGrouping,
  StudySet,
  TrackRecord,
} from '../domain/types'
import type { LibraryDataSource } from './LibraryDataSource'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8765'

type ApiObject = Record<string, unknown>

type ApiHealth = {
  libraries_root?: string
}

type ApiSetLibrariesRootResponse = {
  libraries_root?: string
  library_count?: number
}

export class LocalApiDataSource implements LibraryDataSource {
  readonly baseUrl: string

  constructor(baseUrl = import.meta.env.VITE_BODAQS_LIBRARY_API_URL || DEFAULT_API_BASE_URL) {
    this.baseUrl = String(baseUrl).replace(/\/+$/, '')
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

  async listSessions() {
    const libraries = await this.listLibraries()
    const catalogs = await Promise.all(
      libraries.map((libraryItem) =>
        requestJson<ApiObject>(`${this.baseUrl}/api/v1/libraries/${encodeURIComponent(libraryItem.id)}/catalog`),
      ),
    )
    return catalogs.flatMap((catalog) => {
      const rows = arrayValue(catalog.rows)
      return rows.filter(isObject).map(mapSession)
    })
  }

  async listTracks(): Promise<TrackRecord[]> {
    return []
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
}

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  })

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = (await response.json()) as ApiObject
      const error = isObject(payload.error) ? payload.error : null
      const message = error ? textValue(error.message, detail) : detail
      detail = message
    } catch {
      // Keep the HTTP status fallback.
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
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
  const libraryId = textValue(row.library_id)
  const sessionKey = textValue(row.session_key)
  const runId = textValue(row.run_id)
  const sessionId = textValue(row.session_id)
  const availableSignals = arrayValue(row.available_signals).filter(isObject)
  const qcLevel = qcLevelValue(qcSummary.status)
  const warningCount = numberValue(qcSummary.warning_count)
  const errorCount = numberValue(qcSummary.error_count)

  return {
    libraryId,
    runId,
    runName: textValue(display.run_label, runId),
    sessionId,
    sessionKey,
    name: textValue(display.label, textValue(display.session_label, sessionKey)),
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
    gps: [],
    gpsSummary: mapGpsSummary(gpsSummary),
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
  }))
  if (!Boolean(value.present) && sources.length === 0) {
    return emptyGpsSummary
  }
  return {
    present: Boolean(value.present),
    preferredSource: gpsSourceKindOrNull(value.preferred_source),
    sources,
    sessionDurationS: numberValue(value.session_duration_s),
    timeCoverageRatio: numberValue(value.time_coverage_ratio),
    positionPointCount: numberValue(value.position_point_count),
    quality,
    warnings: arrayValue(value.warnings).map((item) => textValue(item)).filter(Boolean),
  }
}

function mapStudySet(value: ApiObject): StudySet {
  const sessions = arrayValue(value.sessions).filter(isObject).map((sessionRef) => ({
    libraryId: textValue(sessionRef.library_id),
    sessionKey: textValue(sessionRef.session_key),
    runId: textValue(sessionRef.run_id),
    sessionId: textValue(sessionRef.session_id),
    label: textValue(sessionRef.label, textValue(sessionRef.session_id)),
  }))
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

function isObject(value: unknown): value is ApiObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
