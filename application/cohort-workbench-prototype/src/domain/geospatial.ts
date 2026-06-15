import { candidateId, sessionByRef } from './studySets'
import type {
  GpsQuality,
  SessionGpsSummary,
  SessionRecord,
  StudySet,
  TrackRecord,
} from './types'

export const emptyGpsSummary: SessionGpsSummary = {
  present: false,
  preferredSourceId: null,
  preferredSourceKind: null,
  sourceSelectionMethod: 'none',
  sources: [],
  sessionDurationS: 0,
  timeCoverageRatio: 0,
  positionPointCount: 0,
  quality: 'absent',
  warnings: [],
}

export function gpsQualityLabel(quality: GpsQuality) {
  if (quality === 'usable') {
    return 'usable'
  }
  if (quality === 'limited') {
    return 'limited'
  }
  if (quality === 'invalid') {
    return 'invalid'
  }
  return 'absent'
}

export function gpsQualityTone(quality: GpsQuality): 'good' | 'warning' | 'alert' {
  if (quality === 'usable') {
    return 'good'
  }
  if (quality === 'limited') {
    return 'warning'
  }
  return 'alert'
}

export function gpsSourceLabel(value: SessionGpsSummary['preferredSourceKind']) {
  if (value === 'fit_enrichment') {
    return 'FIT enrichment'
  }
  if (value === 'logger_sensor') {
    return 'logger sensor'
  }
  if (value === 'imported_route') {
    return 'imported route'
  }
  return 'unknown'
}

export function gpsSummaryLine(summary: SessionGpsSummary) {
  if (!summary.present) {
    return 'No GPS'
  }
  const source = gpsSourceDisplay(summary.preferredSourceKind, summary.preferredSourceId)
  return `${gpsQualityLabel(summary.quality)} ${source}, ${formatPercent(summary.timeCoverageRatio)} coverage`
}

export function gpsSourceDisplay(kind: SessionGpsSummary['preferredSourceKind'], sourceId?: string | null) {
  const label = gpsSourceLabel(kind)
  return sourceId ? `${label} (${sourceId})` : label
}

export function studySetGpsAdequacy(studySet: StudySet, sessions: SessionRecord[]) {
  const records = studySet.sessions
    .map((sessionRef) => sessionByRef(sessionRef, sessions))
    .filter((session): session is SessionRecord => Boolean(session))
  const usableCount = records.filter((session) => session.gpsSummary.quality === 'usable').length
  const limitedCount = records.filter((session) => session.gpsSummary.quality === 'limited').length
  const absentCount = records.filter(
    (session) => session.gpsSummary.quality === 'absent' || session.gpsSummary.quality === 'invalid',
  ).length
  const coverageTotal = records.reduce((total, session) => total + session.gpsSummary.timeCoverageRatio, 0)
  return {
    sessionCount: records.length,
    usableCount,
    limitedCount,
    absentCount,
    averageCoverageRatio: records.length ? coverageTotal / records.length : 0,
  }
}

export function trackMatchForSession(track: TrackRecord, session: SessionRecord) {
  return track.matchSummaries.find((match) => match.sessionRefId === candidateId(session))
}

export function trackMatchStatusLabel(status: string) {
  return status.replace(/_/g, ' ')
}

export function crossedTrackpointCount(track: TrackRecord, session: SessionRecord) {
  const match = trackMatchForSession(track, session)
  if (!match) {
    return 0
  }
  return match.trackpointResults.filter((result) => result.crossed).length
}

export function formatPercent(value: number) {
  if (!Number.isFinite(value)) {
    return '0%'
  }
  return `${Math.round(value * 100)}%`
}
