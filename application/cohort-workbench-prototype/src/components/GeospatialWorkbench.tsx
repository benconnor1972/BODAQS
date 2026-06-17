import { useState } from 'react'
import { Crosshair, Eye, MapPin, Plus, Route, Save, Trash2 } from 'lucide-react'
import {
  formatPercent,
  gpsSourceDisplay,
  studySetGpsAdequacy,
  trackMatchForSession,
  trackMatchStatusLabel,
} from '../domain/geospatial'
import { candidateId, sessionByRef, slugify, uniqueId } from '../domain/studySets'
import { pointAtStationM, routeLengthM } from '../domain/trackGeometry'
import type { SessionRecord, StudySet, TrackpointMatchQueryRecord, TrackpointMatchQueryResults, TrackRecord, TrackpointRecord } from '../domain/types'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { IconButton } from './Common'
import { GpsBadge } from './StatusBadges'

export function GeospatialWorkbench({
  primarySession,
  currentStudySet,
  sessions,
  tracks,
  selectedTrackIds,
  currentStudyTracks,
  dataSource,
  onToggleTrack,
  onAttachSelectedTracks,
  onInspectTrack,
  onTrackSaved,
  onTrackDeleted,
}: {
  primarySession: SessionRecord | null
  currentStudySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  selectedTrackIds: string[]
  currentStudyTracks: TrackRecord[]
  dataSource: LibraryDataSource
  onToggleTrack: (trackId: string) => void
  onAttachSelectedTracks: () => void
  onInspectTrack: (track: TrackRecord) => void
  onTrackSaved: (track: TrackRecord) => void
  onTrackDeleted: (trackId: string) => void
}) {
  const [trackName, setTrackName] = useState('')
  const [trackDescription, setTrackDescription] = useState('')
  const [activeTrackId, setActiveTrackId] = useState<string | null>(null)
  const [trackpointName, setTrackpointName] = useState('')
  const [trackpointStationM, setTrackpointStationM] = useState('')
  const [trackpointQuery, setTrackpointQuery] = useState<TrackpointMatchQueryRecord | null>(null)
  const [trackpointQueryResults, setTrackpointQueryResults] = useState<TrackpointMatchQueryResults | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const adequacy = studySetGpsAdequacy(currentStudySet, sessions)
  const studySessions = currentStudySet.sessions
    .map((sessionRef) => sessionByRef(sessionRef, sessions))
    .filter((session): session is SessionRecord => Boolean(session))
  const activeTrack = tracks.find((track) => track.id === activeTrackId) ?? null
  const canCreateTrack = Boolean(primarySession && dataSource.loadSessionGpsPoints && dataSource.saveTrack && !busy)
  const canEditTrack = Boolean(activeTrack && dataSource.saveTrack && !busy)
  const canRunTrackpointQuery = Boolean(
    activeTrack &&
      activeTrack.trackpoints.length > 0 &&
      dataSource.createTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQueryResults &&
      !busy,
  )

  async function createTrackFromPrimaryGps() {
    if (!primarySession || !dataSource.loadSessionGpsPoints || !dataSource.saveTrack) {
      setMessage('Select a primary session and connect to a data source that can save tracks.')
      return
    }
    const displayName = trackName.trim() || `${primarySession.name} track`
    setBusy(true)
    setMessage(`Creating ${displayName}...`)
    try {
      const gpsPoints = await dataSource.loadSessionGpsPoints(primarySession, primarySession.gpsSummary.preferredSourceId)
      if (gpsPoints.path.length < 2) {
        setMessage('Primary session does not have enough GPS points to create a track.')
        return
      }
      const lengthM = routeLengthM(gpsPoints.path)
      const savedTrack = await dataSource.saveTrack({
        id: '',
        name: displayName,
        description: trackDescription.trim(),
        revision: 0,
        pointCount: gpsPoints.path.length,
        distanceKm: lengthM / 1000,
        lengthM,
        points: gpsPoints.path,
        defaultPolicyId: 'default-geospatial-policy',
        trackpoints: [],
        matchSummaries: [],
        source: {
          kind: 'session_gps',
          libraryId: primarySession.libraryId,
          sessionRefId: candidateId(primarySession),
          sessionKey: primarySession.sessionKey,
          runId: primarySession.runId,
          sessionId: primarySession.sessionId,
          gpsSourceId: gpsPoints.sourceId,
          gpsSourceKind: gpsPoints.sourceKind,
          gpsStreamName: gpsPoints.streamName,
          gpsSourceSelectionMethod: gpsPoints.sourceSelectionMethod,
        },
      })
      onTrackSaved(savedTrack)
      setActiveTrackId(savedTrack.id)
      setTrackName('')
      setTrackDescription('')
      setMessage(`Created ${savedTrack.name}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function addTrackpoint() {
    if (!activeTrack || !dataSource.saveTrack) {
      setMessage('Choose a track to manage first.')
      return
    }
    const name = trackpointName.trim()
    const stationM = Number(trackpointStationM)
    if (!name || !Number.isFinite(stationM)) {
      setMessage('Trackpoint name and station must be provided.')
      return
    }
    const clippedStationM = Math.max(0, Math.min(activeTrack.lengthM, stationM))
    const nextTrackpoint: TrackpointRecord = {
      id: uniqueId(slugify(name), activeTrack.trackpoints.map((trackpoint) => trackpoint.id)),
      name,
      stationM: clippedStationM,
      position: pointAtStationM(activeTrack.points, clippedStationM),
    }
    const updatedTrack = {
      ...activeTrack,
      trackpoints: [...activeTrack.trackpoints, nextTrackpoint].sort((a, b) => a.stationM - b.stationM),
    }
    await saveTrackUpdate(updatedTrack, `Added ${name}.`)
    setTrackpointName('')
    setTrackpointStationM('')
  }

  async function deleteTrackpoint(trackpointId: string) {
    if (!activeTrack) {
      return
    }
    const updatedTrack = {
      ...activeTrack,
      trackpoints: activeTrack.trackpoints.filter((trackpoint) => trackpoint.id !== trackpointId),
    }
    await saveTrackUpdate(updatedTrack, 'Trackpoint deleted.')
  }

  async function deleteActiveTrack() {
    if (!activeTrack || !dataSource.deleteTrack) {
      setMessage('Choose a track to delete first.')
      return
    }
    if (!window.confirm(`Delete track "${activeTrack.name}"?`)) {
      return
    }
    setBusy(true)
    setMessage(`Deleting ${activeTrack.name}...`)
    try {
      await dataSource.deleteTrack(activeTrack.id)
      onTrackDeleted(activeTrack.id)
      setActiveTrackId(null)
      setMessage(`Deleted ${activeTrack.name}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function saveTrackUpdate(track: TrackRecord, successMessage: string) {
    if (!dataSource.saveTrack) {
      setMessage('Current data source cannot save tracks.')
      return
    }
    setBusy(true)
    setMessage(`Saving ${track.name}...`)
    try {
      const savedTrack = await dataSource.saveTrack(track)
      onTrackSaved(savedTrack)
      setActiveTrackId(savedTrack.id)
      setMessage(successMessage)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function runTrackpointQuery() {
    if (
      !activeTrack ||
      !dataSource.createTrackpointMatchQuery ||
      !dataSource.loadTrackpointMatchQuery ||
      !dataSource.loadTrackpointMatchQueryResults
    ) {
      setMessage('Current data source cannot run trackpoint match queries.')
      return
    }
    const trackpointIds = activeTrack.trackpoints.map((trackpoint) => trackpoint.id)
    if (trackpointIds.length === 0) {
      setMessage('Add at least one trackpoint before running a trackpoint query.')
      return
    }
    setBusy(true)
    setTrackpointQueryResults(null)
    setMessage(`Starting trackpoint query for ${activeTrack.name}...`)
    try {
      let query = await dataSource.createTrackpointMatchQuery({
        trackId: activeTrack.id,
        trackpointIds,
        matchMode: 'all',
        toleranceM: 5,
        scope: {
          libraryIds: uniqueStrings(sessions.map((session) => session.libraryId)),
        },
        persist: true,
      })
      setTrackpointQuery(query)
      for (let attempt = 0; attempt < 40 && (query.status === 'queued' || query.status === 'running'); attempt += 1) {
        await delay(300)
        query = await dataSource.loadTrackpointMatchQuery(query.queryId)
        setTrackpointQuery(query)
      }
      if (query.status === 'completed') {
        const results = await dataSource.loadTrackpointMatchQueryResults(query.queryId, null, 50)
        setTrackpointQueryResults(results)
        setMessage(`Trackpoint query complete: ${results.resultCount} matching session(s).`)
      } else {
        setMessage(`Trackpoint query is ${query.status}.`)
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function cancelTrackpointQuery() {
    if (!trackpointQuery || !dataSource.cancelTrackpointMatchQuery) {
      return
    }
    setBusy(true)
    try {
      const query = await dataSource.cancelTrackpointMatchQuery(trackpointQuery.queryId)
      setTrackpointQuery(query)
      setMessage(`Trackpoint query ${query.status}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

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
            <dd>
              {gpsSourceDisplay(primarySession.gpsSummary.preferredSourceKind, primarySession.gpsSummary.preferredSourceId)}
            </dd>
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
            <div className={`check-row compact track-row${activeTrack?.id === track.id ? ' active-track' : ''}`} key={track.id}>
              <input
                aria-label={`Select ${track.name}`}
                type="checkbox"
                checked={selectedTrackIds.includes(track.id)}
                onChange={() => onToggleTrack(track.id)}
              />
              <button className="track-row-summary" onClick={() => setActiveTrackId(track.id)} type="button">
                <strong>{track.name}</strong>
                <small>
                  {track.trackpoints.length} trackpoints, {track.distanceKm.toFixed(1)} km, {track.defaultPolicyId}
                </small>
              </button>
              <IconButton label="Inspect Track" onClick={() => onInspectTrack(track)} icon={<Eye size={16} />} />
              <IconButton label="Manage Track" onClick={() => setActiveTrackId(track.id)} icon={<Route size={16} />} />
            </div>
          ))}
          {tracks.length === 0 && <p className="empty-note">No tracks yet. Create one from primary GPS.</p>}
        </div>
        <div className="track-create-form">
          <label>
            New track name
            <input
              value={trackName}
              onChange={(event) => setTrackName(event.target.value)}
              placeholder={primarySession ? `${primarySession.name} track` : 'Select a primary session first'}
            />
          </label>
          <label>
            Description
            <input
              value={trackDescription}
              onChange={(event) => setTrackDescription(event.target.value)}
              placeholder="Optional context for this reusable track"
            />
          </label>
          <button className="secondary-action" disabled={!canCreateTrack} onClick={() => void createTrackFromPrimaryGps()} type="button">
            <Plus size={16} />
            Create from primary GPS
          </button>
        </div>
        <div className="trackpoint-editor">
          <div className="trackpoint-editor-header">
            <strong>{activeTrack ? `Manage ${activeTrack.name}` : 'No track selected'}</strong>
            {activeTrack && (
              <button
                className="danger-action compact-danger"
                disabled={!dataSource.deleteTrack || busy}
                onClick={() => void deleteActiveTrack()}
                type="button"
              >
                <Trash2 size={14} />
                Delete
              </button>
            )}
          </div>
          {activeTrack ? (
            <>
              <div className="trackpoint-form">
                <label>
                  Trackpoint
                  <input
                    value={trackpointName}
                    onChange={(event) => setTrackpointName(event.target.value)}
                    placeholder="e.g. Rock garden entry"
                  />
                </label>
                <label>
                  Station m
                  <input
                    value={trackpointStationM}
                    onChange={(event) => setTrackpointStationM(event.target.value)}
                    placeholder={`0-${activeTrack.lengthM.toFixed(0)}`}
                  />
                </label>
                <button className="secondary-action" disabled={!canEditTrack} onClick={() => void addTrackpoint()} type="button">
                  <Save size={15} />
                  Add point
                </button>
              </div>
              <div className="trackpoint-list">
                {activeTrack.trackpoints.length === 0 && <span className="subtle">No trackpoints yet.</span>}
                {activeTrack.trackpoints.map((trackpoint) => (
                  <div className="trackpoint-row" key={trackpoint.id}>
                    <span>
                      <strong>{trackpoint.name}</strong>
                      <small>{trackpoint.stationM.toFixed(0)} m</small>
                    </span>
                    <IconButton
                      label={`Delete ${trackpoint.name}`}
                      disabled={!canEditTrack}
                      onClick={() => void deleteTrackpoint(trackpoint.id)}
                      icon={<Trash2 size={14} />}
                      tone="alert"
                    />
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="empty-note">Create or manage a track to add simple station-based trackpoints.</p>
          )}
        </div>
        <div className="geo-policy-note">
          Default cutlines are policy-generated. Trackpoint rows show only explicit overrides.
        </div>
        <div className="geo-policy-note">
          Trackpoint query prototype: runs all trackpoints on the active track against the selected libraries with a 5 m tolerance.
        </div>
        <div className="action-row tight">
          <button className="secondary-action" disabled={!canRunTrackpointQuery} onClick={() => void runTrackpointQuery()} type="button">
            <Crosshair size={16} />
            Run trackpoint query
          </button>
          <button
            className="ghost-action"
            disabled={!trackpointQuery || !dataSource.cancelTrackpointMatchQuery || busy}
            onClick={() => void cancelTrackpointQuery()}
            type="button"
          >
            Cancel query
          </button>
        </div>
        {trackpointQuery && (
          <p className="track-manager-message">
            Query {trackpointQuery.status}: {trackpointQuery.processedSessionCount}/
            {trackpointQuery.candidateSessionCount} processed, {trackpointQuery.matchedSessionCount} matched.
          </p>
        )}
        {trackpointQueryResults && trackpointQueryResults.results.length > 0 && (
          <div className="match-preview-list compact-query-results">
            {trackpointQueryResults.results.map((result) => (
              <article className="match-row" key={result.sessionRef.sessionKey}>
                <div>
                  <strong>{result.sessionRef.label || result.sessionRef.sessionId}</strong>
                  <small>{result.sessionRef.libraryId}</small>
                </div>
                <span className="pill ok">{result.quality}</span>
                <span>{result.matchedTrackpointIds.length} matched</span>
                <span>{result.missingTrackpointIds.length} missing</span>
              </article>
            ))}
          </div>
        )}
        {message && <p className="track-manager-message">{message}</p>}
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

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}
