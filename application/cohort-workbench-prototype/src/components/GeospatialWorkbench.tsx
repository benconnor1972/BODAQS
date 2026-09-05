import { useMemo, useState } from 'react'
import { Crosshair, MapPin, Plus, Route, Save, Trash2, X } from 'lucide-react'
import {
  formatPercent,
  gpsSourceDisplay,
  studySetGpsAdequacy,
  trackMatchForSession,
  trackMatchStatusLabel,
} from '../domain/geospatial'
import { candidateId, sessionByRef, sessionRefId, slugify, uniqueId } from '../domain/studySets'
import { DEFAULT_ROUTE_GEOMETRY_DENOISING, denoiseRouteGeometry, pointAtStationM, routeLengthM } from '../domain/trackGeometry'
import type {
  SessionRecord,
  StudySessionRef,
  StudySet,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryResults,
  TrackRecord,
  TrackpointRecord,
} from '../domain/types'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { IconButton, InfoTip } from './Common'
import { GpsBadge } from './StatusBadges'

type TrackManagerMode = 'manage' | 'new'

export function GeospatialWorkbench({
  primarySession,
  currentStudySet,
  sessions,
  tracks,
  selectedTrackIds,
  dataSource,
  canWrite = true,
  onToggleTrack,
  onAttachTrack,
  onAttachSession,
  onTrackDeleted,
}: {
  primarySession: SessionRecord | null
  currentStudySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  selectedTrackIds: string[]
  dataSource: LibraryDataSource
  canWrite?: boolean
  onToggleTrack: (trackId: string) => void
  onAttachTrack: (trackId: string) => void
  onAttachSession: (sessionRef: StudySessionRef) => void
  onTrackDeleted: (trackId: string) => void
}) {
  const [activeTrackId, setActiveTrackId] = useState<string | null>(tracks[0]?.id ?? null)
  const [deletingTrackIds, setDeletingTrackIds] = useState<Set<string>>(() => new Set())
  const [trackpointQuery, setTrackpointQuery] = useState<TrackpointMatchQueryRecord | null>(null)
  const [trackpointQueryResults, setTrackpointQueryResults] = useState<TrackpointMatchQueryResults | null>(null)
  const [trackpointQueryMessage, setTrackpointQueryMessage] = useState('')
  const [trackpointQueryBusy, setTrackpointQueryBusy] = useState(false)
  const activeTrack = tracks.find((track) => track.id === activeTrackId) ?? tracks[0] ?? null
  const canRunTrackpointQuery = Boolean(
    canWrite &&
    activeTrack &&
      activeTrack.trackpoints.length > 0 &&
      dataSource.createTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQueryResults &&
      !trackpointQueryBusy,
  )
  const currentStudySessionIds = new Set(currentStudySet.sessions.map(sessionRefId))

  async function runTrackpointQuery() {
    if (
      !activeTrack ||
      !dataSource.createTrackpointMatchQuery ||
      !dataSource.loadTrackpointMatchQuery ||
      !dataSource.loadTrackpointMatchQueryResults
    ) {
      setTrackpointQueryMessage('Current data source cannot run trackpoint match queries.')
      return
    }
    const trackpointIds = activeTrack.trackpoints.map((trackpoint) => trackpoint.id)
    if (trackpointIds.length === 0) {
      setTrackpointQueryMessage('Add at least one trackpoint before running a trackpoint query.')
      return
    }
    setTrackpointQueryBusy(true)
    setTrackpointQueryResults(null)
    setTrackpointQueryMessage(`Starting trackpoint query for ${activeTrack.name}...`)
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
      while (isActiveTrackpointQuery(query)) {
        await delay(300)
        query = await dataSource.loadTrackpointMatchQuery(query.queryId)
        setTrackpointQuery(query)
      }
      if (query.status === 'completed') {
        const results = await dataSource.loadTrackpointMatchQueryResults(query.queryId, null, 50)
        setTrackpointQueryResults(results)
        setTrackpointQueryMessage(`Trackpoint query complete: ${results.resultCount} matching session(s).`)
      } else {
        setTrackpointQueryMessage(`Trackpoint query is ${query.status}.`)
      }
    } catch (error) {
      setTrackpointQueryMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setTrackpointQueryBusy(false)
    }
  }

  async function cancelTrackpointQuery() {
    if (!trackpointQuery || !dataSource.cancelTrackpointMatchQuery) {
      return
    }
    setTrackpointQueryBusy(true)
    try {
      const query = await dataSource.cancelTrackpointMatchQuery(trackpointQuery.queryId)
      setTrackpointQuery(query)
      setTrackpointQueryMessage(`Trackpoint query ${query.status}.`)
    } catch (error) {
      setTrackpointQueryMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setTrackpointQueryBusy(false)
    }
  }

  function clearTrackpointQuery() {
    setTrackpointQuery(null)
    setTrackpointQueryResults(null)
    setTrackpointQueryMessage('')
  }

  async function deleteTrack(track: TrackRecord) {
    if (!canWrite) {
      setTrackpointQueryMessage('The Library API is running in read-only mode.')
      return
    }
    if (!dataSource.deleteTrack) {
      setTrackpointQueryMessage('Current data source cannot delete tracks.')
      return
    }
    const confirmed = window.confirm(`Delete track "${track.name}"? This will also remove it from any open Study Set context.`)
    if (!confirmed) {
      return
    }
    setDeletingTrackIds((current) => new Set([...current, track.id]))
    setTrackpointQueryMessage(`Deleting ${track.name}...`)
    try {
      await dataSource.deleteTrack(track.id)
      onTrackDeleted(track.id)
      setSelectedActiveTrackAfterDelete(track.id)
      setTrackpointQueryMessage(`Deleted ${track.name}.`)
    } catch (error) {
      setTrackpointQueryMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setDeletingTrackIds((current) => {
        const next = new Set(current)
        next.delete(track.id)
        return next
      })
    }
  }

  function setSelectedActiveTrackAfterDelete(trackId: string) {
    if (activeTrackId !== trackId) {
      return
    }
    const nextTrack = tracks.find((track) => track.id !== trackId) ?? null
    setActiveTrackId(nextTrack?.id ?? null)
  }

  return (
    <section className="geospatial-workbench">
      <PrimaryGpsCard primarySession={primarySession} />

      <div className="geo-card">
        <div className="geo-card-title">
          <Route size={16} />
          <strong className="inline-heading">
            Tracks
            <InfoTip text="Tracks are reusable GPS paths with defined points. Select a track to preview it, or add it to the current Study Set." />
          </strong>
          <span className="subtle">{tracks.length} available</span>
        </div>
        <div className="track-list compact-track-list">
          {tracks.map((track) => {
            const attached = currentStudySet.trackIds.includes(track.id)
            const deleting = deletingTrackIds.has(track.id)
            return (
              <div className={`check-row compact track-row${activeTrack?.id === track.id ? ' active-track' : ''}`} key={track.id}>
                <input
                  aria-label={`Preview ${track.name}`}
                  type="checkbox"
                  checked={selectedTrackIds.includes(track.id)}
                  onChange={() => onToggleTrack(track.id)}
                />
                <button className="track-row-summary" onClick={() => setActiveTrackId(track.id)} type="button">
                  <strong>{track.name}</strong>
                  <small>
                    {track.trackpoints.length} trackpoints, {track.distanceKm.toFixed(1)} km
                  </small>
                </button>
                <IconButton
                  label={attached ? 'Track already in Study Set' : 'Add Track to Study Set'}
                  disabled={attached}
                  onClick={() => onAttachTrack(track.id)}
                  icon={<Plus size={16} />}
                  tone="good"
                />
                <IconButton
                  label={deleting ? 'Deleting Track' : 'Delete Track'}
                  disabled={!canWrite || !dataSource.deleteTrack || deleting}
                  onClick={() => void deleteTrack(track)}
                  icon={<Trash2 size={16} />}
                  tone="alert"
                />
              </div>
            )
          })}
          {tracks.length === 0 && <p className="empty-note">No tracks yet. Use Track Analysis and Lap Timing to create one from session GPS.</p>}
        </div>
        <div className="action-row tight">
          <button className="secondary-action" disabled={!canRunTrackpointQuery} onClick={() => void runTrackpointQuery()} type="button">
            <Crosshair size={16} />
            Find matching sessions
          </button>
          <InfoTip text="Find matching sessions runs all trackpoints on the active track against the selected libraries with a 5 m tolerance." />
          <button
            className="ghost-action"
            disabled={!canWrite || !isActiveTrackpointQuery(trackpointQuery) || !dataSource.cancelTrackpointMatchQuery || trackpointQueryBusy}
            onClick={() => void cancelTrackpointQuery()}
            type="button"
          >
            Cancel query
          </button>
          <button
            className="ghost-action"
            disabled={!trackpointQuery && !trackpointQueryResults && !trackpointQueryMessage}
            onClick={clearTrackpointQuery}
            type="button"
          >
            Clear
          </button>
        </div>
        {trackpointQuery && (
          <p className="track-manager-message">
            Query {trackpointQuery.status}: {trackpointQuery.processedSessionCount}/
            {trackpointQuery.candidateSessionCount} processed, {trackpointQuery.matchedSessionCount} matched
            {trackpointQuery.skippedSessionCount ? `, ${trackpointQuery.skippedSessionCount} skipped by GPS extent` : ''}.
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
                <IconButton
                  label={currentStudySessionIds.has(sessionRefId(result.sessionRef)) ? 'Session already in Study Set' : 'Add Session to Study Set'}
                  disabled={currentStudySessionIds.has(sessionRefId(result.sessionRef))}
                  onClick={() => onAttachSession(result.sessionRef)}
                  icon={<Plus size={14} />}
                  tone="good"
                />
              </article>
            ))}
          </div>
        )}
        {trackpointQueryMessage && <p className="track-manager-message">{trackpointQueryMessage}</p>}
      </div>
    </section>
  )
}

export function StudySetGpsCoverageCard({
  currentStudySet,
  sessions,
}: {
  currentStudySet: StudySet
  sessions: SessionRecord[]
}) {
  const adequacy = studySetGpsAdequacy(currentStudySet, sessions)

  return (
    <div className="geo-card">
      <div className="geo-card-title">
        <strong className="inline-heading">
          Study Set GPS
          <InfoTip text="Summarizes GPS quality for Study Set sessions." />
        </strong>
      </div>
      <div className="geo-adequacy-grid">
        <Metric label="usable" value={adequacy.usableCount} />
        <Metric label="limited" value={adequacy.limitedCount} />
        <Metric label="absent" value={adequacy.absentCount} />
        <Metric label="coverage" value={formatPercent(adequacy.averageCoverageRatio)} />
      </div>
    </div>
  )
}

export function MatchPreviewCard({
  currentStudySet,
  sessions,
  currentStudyTracks,
}: {
  currentStudySet: StudySet
  sessions: SessionRecord[]
  currentStudyTracks: TrackRecord[]
}) {
  const studySessions = useMemo(
    () =>
      currentStudySet.sessions
        .map((sessionRef) => sessionByRef(sessionRef, sessions))
        .filter((session): session is SessionRecord => Boolean(session)),
    [currentStudySet.sessions, sessions],
  )

  return (
    <div className="geo-card">
      <div className="geo-card-title">
        <Crosshair size={16} />
        <strong className="inline-heading">
          Match Preview
          <InfoTip text="Match preview shows current session/track coverage using available track-match summaries." />
        </strong>
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
  )
}

function PrimaryGpsCard({ primarySession }: { primarySession: SessionRecord | null }) {
  return (
    <div className="geo-card primary-gps-card">
      <div className="geo-card-title">
        <MapPin size={16} />
        <strong className="inline-heading">
          Selected session GPS
          <InfoTip text="Shows GPS source and coverage for the selected session." />
        </strong>
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
  )
}

export function TrackManagerModal({
  mode,
  primarySession,
  sessions,
  tracks,
  activeTrack,
  dataSource,
  canWrite = true,
  onActiveTrackChange,
  onClose,
  onTrackSaved,
  onTrackDeleted,
}: {
  mode: TrackManagerMode
  primarySession: SessionRecord | null
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  activeTrack: TrackRecord | null
  dataSource: LibraryDataSource
  canWrite?: boolean
  onActiveTrackChange: (trackId: string | null) => void
  onClose: () => void
  onTrackSaved: (track: TrackRecord) => void
  onTrackDeleted: (trackId: string) => void
}) {
  const [trackName, setTrackName] = useState('')
  const [trackDescription, setTrackDescription] = useState('')
  const [trackpointName, setTrackpointName] = useState('')
  const [trackpointStationM, setTrackpointStationM] = useState('')
  const [trackpointQuery, setTrackpointQuery] = useState<TrackpointMatchQueryRecord | null>(null)
  const [trackpointQueryResults, setTrackpointQueryResults] = useState<TrackpointMatchQueryResults | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const canCreateTrack = Boolean(canWrite && primarySession && dataSource.loadSessionGpsPoints && dataSource.saveTrack && !busy)
  const canEditTrack = Boolean(canWrite && activeTrack && dataSource.saveTrack && !busy)
  const canRunTrackpointQuery = Boolean(
    canWrite &&
    activeTrack &&
      activeTrack.trackpoints.length > 0 &&
      dataSource.createTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQueryResults &&
      !busy,
  )

  async function createTrackFromPrimaryGps() {
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
    if (!primarySession || !dataSource.loadSessionGpsPoints || !dataSource.saveTrack) {
      setMessage('Select a primary session and connect to a data source that can save tracks.')
      return
    }
    const displayName = trackName.trim() || `${primarySession.name} track`
    setBusy(true)
    setMessage(`Creating ${displayName}...`)
    try {
      const gpsPoints = await dataSource.loadSessionGpsPoints(
        primarySession,
        primarySession.gpsSummary.preferredSourceId,
        { maxPoints: 25_000 },
      )
      if (gpsPoints.path.length < 2) {
        setMessage('Primary session does not have enough GPS points to create a track.')
        return
      }
      const trackPath = denoiseRouteGeometry(gpsPoints.path)
      const lengthM = routeLengthM(trackPath)
      const savedTrack = await dataSource.saveTrack({
        id: '',
        name: displayName,
        description: trackDescription.trim(),
        revision: 0,
        pointCount: trackPath.length,
        distanceKm: lengthM / 1000,
        lengthM,
        points: trackPath,
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
          gpsSampling: {
            mode: gpsPoints.samplingMode,
            sourcePoints: gpsPoints.sourcePoints,
            returnedPoints: gpsPoints.returnedPoints,
            maxPoints: gpsPoints.maxPoints,
            stride: gpsPoints.stride,
          },
          geometryDenoising: {
            estimator: DEFAULT_ROUTE_GEOMETRY_DENOISING.estimator,
            windowM: DEFAULT_ROUTE_GEOMETRY_DENOISING.windowM,
            polynomialOrder: DEFAULT_ROUTE_GEOMETRY_DENOISING.polynomialOrder,
            fitWeighting: DEFAULT_ROUTE_GEOMETRY_DENOISING.fitWeighting,
            robustIterations: DEFAULT_ROUTE_GEOMETRY_DENOISING.robustIterations,
            robustTuningConstant: DEFAULT_ROUTE_GEOMETRY_DENOISING.robustTuningConstant,
          },
        },
      })
      onTrackSaved(savedTrack)
      onActiveTrackChange(savedTrack.id)
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
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
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
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
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
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
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
      onActiveTrackChange(null)
      setMessage(`Deleted ${activeTrack.name}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function saveTrackUpdate(track: TrackRecord, successMessage: string) {
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
    if (!dataSource.saveTrack) {
      setMessage('Current data source cannot save tracks.')
      return
    }
    setBusy(true)
    setMessage(`Saving ${track.name}...`)
    try {
      const savedTrack = await dataSource.saveTrack(track)
      onTrackSaved(savedTrack)
      onActiveTrackChange(savedTrack.id)
      setMessage(successMessage)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function runTrackpointQuery() {
    if (!canWrite) {
      setMessage('The Library API is running in read-only mode.')
      return
    }
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
      while (isActiveTrackpointQuery(query)) {
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
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal track-manager-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{mode === 'new' ? 'New Track' : 'Track Manager'}</h2>
          <IconButton label="Close" onClick={onClose} icon={<X size={18} />} />
        </div>
        <div className="modal-content track-manager-modal-content">
          <section className="modal-section">
            <h3>{mode === 'new' ? 'Create from primary GPS' : 'Create track'}</h3>
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
            {mode === 'new' && (
              <p className="track-manager-message">
                Guided track creation placeholder: this first cut creates a track from the current primary session GPS.
              </p>
            )}
          </section>

          <section className="track-manager-modal-grid">
            <aside className="track-manager-side">
              <h3>Tracks</h3>
              <div className="track-list compact-track-list">
                {tracks.map((track) => (
                  <button
                    className={`track-manager-list-item${activeTrack?.id === track.id ? ' active-track' : ''}`}
                    key={track.id}
                    onClick={() => onActiveTrackChange(track.id)}
                    type="button"
                  >
                    <strong>{track.name}</strong>
                    <small>
                      {track.trackpoints.length} trackpoints, {track.distanceKm.toFixed(1)} km
                    </small>
                  </button>
                ))}
                {tracks.length === 0 && <p className="empty-note">No tracks yet.</p>}
              </div>
            </aside>

            <section className="trackpoint-editor">
              <div className="trackpoint-editor-header">
                <strong>{activeTrack ? `Manage ${activeTrack.name}` : 'No track selected'}</strong>
                {activeTrack && (
                  <button
                    className="danger-action compact-danger"
                    disabled={!canWrite || !dataSource.deleteTrack || busy}
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
                  <div className="action-row tight">
                    <button className="secondary-action" disabled={!canRunTrackpointQuery} onClick={() => void runTrackpointQuery()} type="button">
                      <Crosshair size={16} />
                      Run trackpoint query
                    </button>
                    <InfoTip text="Trackpoint query prototype: runs all trackpoints on the active track against the selected libraries with a 5 m tolerance." />
                    <button
                      className="ghost-action"
                      disabled={!canWrite || !isActiveTrackpointQuery(trackpointQuery) || !dataSource.cancelTrackpointMatchQuery || busy}
                      onClick={() => void cancelTrackpointQuery()}
                      type="button"
                    >
                      Cancel query
                    </button>
                  </div>
                </>
              ) : (
                <p className="empty-note">Create or choose a track to add simple station-based trackpoints.</p>
              )}
              {trackpointQuery && (
                <p className="track-manager-message">
                  Query {trackpointQuery.status}: {trackpointQuery.processedSessionCount}/
                  {trackpointQuery.candidateSessionCount} processed, {trackpointQuery.matchedSessionCount} matched
                  {trackpointQuery.skippedSessionCount ? `, ${trackpointQuery.skippedSessionCount} skipped by GPS extent` : ''}.
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
            </section>
          </section>
        </div>
      </section>
    </div>
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

function isActiveTrackpointQuery(query: TrackpointMatchQueryRecord | null) {
  return query?.status === 'queued' || query?.status === 'running'
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}
