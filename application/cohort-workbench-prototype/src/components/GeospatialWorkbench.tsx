import { Crosshair, Eye, MapPin, Plus, Route } from 'lucide-react'
import {
  formatPercent,
  gpsSourceLabel,
  studySetGpsAdequacy,
  trackMatchForSession,
  trackMatchStatusLabel,
} from '../domain/geospatial'
import { candidateId, sessionByRef } from '../domain/studySets'
import type { SessionRecord, StudySet, TrackRecord } from '../domain/types'
import { IconButton } from './Common'
import { GpsBadge } from './StatusBadges'

export function GeospatialWorkbench({
  primarySession,
  currentStudySet,
  sessions,
  tracks,
  selectedTrackIds,
  currentStudyTracks,
  onToggleTrack,
  onAttachSelectedTracks,
  onInspectTrack,
}: {
  primarySession: SessionRecord | null
  currentStudySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  selectedTrackIds: string[]
  currentStudyTracks: TrackRecord[]
  onToggleTrack: (trackId: string) => void
  onAttachSelectedTracks: () => void
  onInspectTrack: (track: TrackRecord) => void
}) {
  const adequacy = studySetGpsAdequacy(currentStudySet, sessions)
  const studySessions = currentStudySet.sessions
    .map((sessionRef) => sessionByRef(sessionRef, sessions))
    .filter((session): session is SessionRecord => Boolean(session))

  return (
    <section className="geospatial-workbench">
      <div className="geo-card primary-gps-card">
        <div className="geo-card-title">
          <MapPin size={16} />
          <strong>Primary GPS</strong>
          {primarySession && <GpsBadge summary={primarySession.gpsSummary} />}
        </div>
        {primarySession ? (
          <dl className="geo-metrics">
            <dt>Session</dt>
            <dd>{primarySession.name}</dd>
            <dt>Source</dt>
            <dd>{gpsSourceLabel(primarySession.gpsSummary.preferredSource)}</dd>
            <dt>Coverage</dt>
            <dd>{formatPercent(primarySession.gpsSummary.timeCoverageRatio)}</dd>
            <dt>Points</dt>
            <dd>{primarySession.gpsSummary.positionPointCount}</dd>
          </dl>
        ) : (
          <p className="empty-note">Select a primary session to inspect GPS adequacy.</p>
        )}
      </div>

      <div className="geo-card">
        <div className="geo-card-title">
          <Crosshair size={16} />
          <strong>Study Set GPS</strong>
          <span className="pill neutral">catalog adequacy</span>
        </div>
        <div className="geo-adequacy-grid">
          <Metric label="usable" value={adequacy.usableCount} />
          <Metric label="limited" value={adequacy.limitedCount} />
          <Metric label="absent" value={adequacy.absentCount} />
          <Metric label="coverage" value={formatPercent(adequacy.averageCoverageRatio)} />
        </div>
      </div>

      <div className="geo-card">
        <div className="geo-card-title">
          <Route size={16} />
          <strong>Track Manager</strong>
          <span className="subtle">{tracks.length} available</span>
        </div>
        <div className="track-list compact-track-list">
          {tracks.map((track) => (
            <label className="check-row compact track-row" key={track.id}>
              <input
                type="checkbox"
                checked={selectedTrackIds.includes(track.id)}
                onChange={() => onToggleTrack(track.id)}
              />
              <span>
                <strong>{track.name}</strong>
                <small>
                  {track.trackpoints.length} trackpoints, {track.distanceKm.toFixed(1)} km, {track.defaultPolicyId}
                </small>
              </span>
              <IconButton label="Inspect Track" onClick={() => onInspectTrack(track)} icon={<Eye size={16} />} />
            </label>
          ))}
        </div>
        <div className="geo-policy-note">
          Default cutlines are policy-generated. Trackpoint rows show only explicit overrides.
        </div>
        <div className="action-row tight">
          <button
            className="secondary-action"
            disabled={selectedTrackIds.length === 0}
            onClick={onAttachSelectedTracks}
            type="button"
          >
            <Plus size={16} />
            Attach track
          </button>
          <button className="ghost-action" disabled type="button">
            New track later
          </button>
        </div>
      </div>

      <div className="geo-card">
        <div className="geo-card-title">
          <Crosshair size={16} />
          <strong>Match Preview</strong>
          <span className="pill neutral">derived preview</span>
        </div>
        {studySessions.length === 0 || currentStudyTracks.length === 0 ? (
          <p className="empty-note">Add sessions and attach a track to preview coverage.</p>
        ) : (
          <div className="match-preview-list">
            {currentStudyTracks.flatMap((track) =>
              studySessions.map((session) => {
                const match = trackMatchForSession(track, session)
                const crossedCount = match?.trackpointResults.filter((result) => result.crossed).length ?? 0
                const refId = candidateId(session)

                return (
                  <article className="match-row" key={`${track.id}-${refId}`}>
                    <div>
                      <strong>{session.name}</strong>
                      <small>{track.name}</small>
                    </div>
                    <span className={matchStatusClassName(match?.status)}>
                      {match ? trackMatchStatusLabel(match.status) : 'not computed'}
                    </span>
                    <span>{match ? formatPercent(match.coverageRatio) : '-'}</span>
                    <span>
                      {crossedCount}/{track.trackpoints.length} trackpoints
                    </span>
                  </article>
                )
              }),
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="geo-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

function matchStatusClassName(status: string | undefined) {
  if (status === 'matched') {
    return 'pill ok'
  }
  if (status === 'partial' || status === 'ambiguous') {
    return 'pill warning'
  }
  return 'pill neutral'
}
