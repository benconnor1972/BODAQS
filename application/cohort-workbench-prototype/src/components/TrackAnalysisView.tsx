import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Map as MapIcon, Trash2 } from 'lucide-react'
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type StyleSpecification,
} from 'maplibre-gl'
import { lineString, nearestPointOnLine, point } from '@turf/turf'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { pointAtStationM, routeLengthM, routeStationsM } from '../domain/trackGeometry'
import { sessionByRef, sessionRefId, sessionToStudyRef, slugify, uniqueId } from '../domain/studySets'
import type {
  GeoPosition,
  SessionGpsPoint,
  SessionGpsPointSet,
  SessionRecord,
  StudySet,
  TrackRecord,
  TrackpointRecord,
  TrackSegmentAliasRecord,
} from '../domain/types'
import { InfoTip, PanelTitle } from './Common'

type TrackAnalysisViewProps = {
  studySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
  canWrite?: boolean
  onTrackSaved?: (track: TrackRecord) => void
  onTrackDeleted?: (trackId: string) => void
}

type LoadedGpsState = {
  status: 'loading' | 'ready' | 'failed'
  pointSet: SessionGpsPointSet | null
  error: string
}

type DraftTrackpoint = TrackpointRecord & {
  draft: true
}

type WorkingTrack = {
  workingId: string
  persistedId: string | null
  origin: 'persisted' | 'scratch'
  dirty: boolean
  saving: boolean
  deleting: boolean
  status: string
  name: string
  description: string
  revision: number
  points: GeoPosition[]
  lengthM: number
  pointCount: number
  distanceKm: number
  defaultPolicyId: string
  trackpoints: DraftTrackpoint[]
  segmentAliases: TrackSegmentAliasRecord[]
  matchSummaries: TrackRecord['matchSummaries']
  source?: TrackRecord['source']
  sourceSessionId?: string
}

type CutlineHandle = 'left' | 'right'

type DragHandleRole = 'trackpoint' | CutlineHandle

type DragHandle = {
  trackpointId: string
  role: DragHandleRole
}

type SessionPath = {
  id: string
  label: string
  path: GeoPosition[]
  session: SessionRecord
}

type ActiveGpsPointSet = {
  session: SessionRecord
  loaded: LoadedGpsState & { status: 'ready'; pointSet: SessionGpsPointSet }
}

type LapTimingRow = {
  key: string
  label: string
  distanceM: number
  times: Array<{
    sessionId: string
    valueS: number | null
    status: 'ready' | 'missing' | 'reverse'
  }>
}

type AltitudeSample = {
  distanceM: number
  elevationM: number
}

type MapPointProperties = {
  color: string
  label: string
  radius: number
  role: DragHandleRole | 'segment'
  trackpointId: string
}

const SESSION_COLORS = ['#008c95', '#101820', '#3f6b7a', '#b66a2c', '#68737a', '#0f766e']
const TRACK_COLOR = '#b66a2c'
const DRAFT_COLOR = '#008c95'
const CUTLINE_LENGTH_M = 20

const OSM_RASTER_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '(c) OpenStreetMap contributors',
    },
  },
  layers: [
    {
      id: 'osm',
      type: 'raster',
      source: 'osm',
    },
  ],
}

function TrackPanelTitle({
  title,
  meta = '',
  info = '',
  action = null,
}: {
  title: string
  meta?: string
  info?: string
  action?: ReactNode
}) {
  return (
    <PanelTitle
      icon={<MapIcon size={15} />}
      title={title}
      action={
        <span className="track-analysis-title-meta">
          {meta}
          {info && <InfoTip text={info} />}
          {action}
        </span>
      }
    />
  )
}

export function TrackAnalysisView({
  studySet,
  sessions,
  tracks,
  dataSource,
  canWrite = true,
  onTrackSaved,
  onTrackDeleted,
}: TrackAnalysisViewProps) {
  const scopedSessions = useMemo(
    () => studySet.sessions.map((ref) => sessionByRef(ref, sessions)).filter(isSessionRecord),
    [sessions, studySet.sessions],
  )
  const scopedSessionIds = useMemo(
    () => scopedSessions.map((session) => sessionRecordId(session)),
    [scopedSessions],
  )
  const savedScopedTracks = useMemo(
    () => tracks.filter((track) => studySet.trackIds.includes(track.id)),
    [studySet.trackIds, tracks],
  )
  const [localTracks, setLocalTracks] = useState<TrackRecord[]>([])
  const scopedTracks = useMemo(
    () => mergeTrackLists(savedScopedTracks, localTracks),
    [localTracks, savedScopedTracks],
  )
  const [workingTracks, setWorkingTracks] = useState<WorkingTrack[]>(() =>
    scopedTracks.map((track) => workingTrackFromRecord(track)),
  )
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeSessionIds, setActiveSessionIds] = useState<Set<string>>(
    () => new Set(scopedSessionIds),
  )
  const previousScopedSessionIdsRef = useRef<Set<string>>(new Set(scopedSessionIds))
  const [gpsSourceBySessionId, setGpsSourceBySessionId] = useState<Record<string, string>>({})
  const [loadedGps, setLoadedGps] = useState<Record<string, LoadedGpsState>>({})
  const loadedGpsRef = useRef<Record<string, LoadedGpsState>>({})
  const [selectedWorkingTrackId, setSelectedWorkingTrackId] = useState(() => workingTracks[0]?.workingId ?? '')
  const [hideSegmentNames, setHideSegmentNames] = useState(true)
  const [lapTimingExpanded, setLapTimingExpanded] = useState(false)

  useEffect(() => {
    loadedGpsRef.current = loadedGps
  }, [loadedGps])

  useEffect(() => {
    setWorkingTracks((current) => {
      const currentByPersistedId = new Map(
        current
          .filter((track) => track.persistedId)
          .map((track) => [track.persistedId as string, track]),
      )
      const persistedTracks = scopedTracks.map((track) => {
        const currentTrack = currentByPersistedId.get(track.id)
        if (currentTrack?.dirty || currentTrack?.saving || currentTrack?.deleting) {
          return currentTrack
        }
        return workingTrackFromRecord(track, currentTrack)
      })
      const scratchTracks = current.filter((track) => track.origin === 'scratch' && !track.persistedId)
      return [...persistedTracks, ...scratchTracks]
    })
  }, [scopedTracks])

  useEffect(() => {
    const scopedIds = new Set(scopedSessionIds)
    const previousScopedIds = previousScopedSessionIdsRef.current
    setActiveSessionIds((current) => {
      const next = new Set<string>()
      scopedSessionIds.forEach((id) => {
        if (current.has(id) || !previousScopedIds.has(id)) {
          next.add(id)
        }
      })
      return next
    })
    previousScopedSessionIdsRef.current = scopedIds
  }, [scopedSessionIds])

  useEffect(() => {
    setGpsSourceBySessionId((current) => {
      const next = { ...current }
      scopedSessions.forEach((session) => {
        const id = sessionRecordId(session)
        if (!next[id] && session.gpsSummary.preferredSourceId) {
          next[id] = session.gpsSummary.preferredSourceId
        }
      })
      return next
    })
  }, [scopedSessions])

  useEffect(() => {
    setSelectedWorkingTrackId((current) => {
      if (current && workingTracks.some((track) => track.workingId === current)) {
        return current
      }
      return workingTracks[0]?.workingId ?? ''
    })
  }, [workingTracks])

  const activeSessions = useMemo(
    () => scopedSessions.filter((session) => activeSessionIds.has(sessionRecordId(session))),
    [activeSessionIds, scopedSessions],
  )

  useEffect(() => {
    let cancelled = false
    if (!dataSource.loadSessionGpsPoints) {
      setLoadedGps({})
      return
    }

    activeSessions.forEach((session) => {
      const sessionId = sessionRecordId(session)
      const sourceId = gpsSourceBySessionId[sessionId] || session.gpsSummary.preferredSourceId || null
      const loadKey = gpsLoadKey(sessionId, sourceId)
      const currentLoad = loadedGpsRef.current[loadKey]
      if (currentLoad?.status === 'ready') {
        return
      }
      setLoadedGps((current) => ({
        ...current,
        [loadKey]: { status: 'loading', pointSet: null, error: '' },
      }))
      dataSource
        .loadSessionGpsPoints?.(session, sourceId)
        .then((pointSet) => {
          if (cancelled) {
            return
          }
          setLoadedGps((current) => ({
            ...current,
            [loadKey]: { status: 'ready', pointSet, error: '' },
          }))
        })
        .catch((error) => {
          if (cancelled) {
            return
          }
          setLoadedGps((current) => ({
            ...current,
            [loadKey]: {
              status: 'failed',
              pointSet: null,
              error: error instanceof Error ? error.message : 'Could not load GPS points.',
            },
          }))
        })
    })

    return () => {
      cancelled = true
    }
  }, [activeSessions, dataSource, gpsSourceBySessionId])

  const selectedTrack = workingTracks.find((track) => track.workingId === selectedWorkingTrackId) ?? null
  const draftTrackpoints = selectedTrack?.trackpoints ?? []
  const orderedDraftTrackpoints = useMemo(
    () => [...draftTrackpoints].sort((a, b) => a.stationM - b.stationM),
    [draftTrackpoints],
  )
  const validSegmentAliases = useMemo(
    () => (selectedTrack ? validSegmentAliasesForTrack(selectedTrack) : []),
    [selectedTrack],
  )
  const activePointSets: ActiveGpsPointSet[] = activeSessions
    .map((session) => {
      const id = sessionRecordId(session)
      const sourceId = gpsSourceBySessionId[id] || session.gpsSummary.preferredSourceId || null
      return { session, loaded: loadedGps[gpsLoadKey(id, sourceId)] }
    })
    .filter(isReadyGpsPointSet)
  const sessionPaths = activePointSets.map<SessionPath>((item) => ({
    id: sessionRecordId(item.session),
    label: item.session.name,
    path: item.loaded.pointSet.path,
    session: item.session,
  }))
  const referencePath = selectedTrack?.points.length ? selectedTrack.points : sessionPaths[0]?.path ?? []
  const lapTimingRows = useMemo(
    () => buildLapTimingRows(activePointSets, referencePath, draftTrackpoints, validSegmentAliases),
    [activePointSets, draftTrackpoints, referencePath, validSegmentAliases],
  )
  const trackAltitudeSamples = useMemo(
    () => (selectedTrack ? altitudeSamplesForTrack(selectedTrack) : []),
    [selectedTrack],
  )
  const sessionAltitudeSamples = useMemo(
    () => altitudeSamplesForSessionGps(activePointSets[0]?.loaded.pointSet ?? null),
    [activePointSets],
  )
  const altitudeSamples = trackAltitudeSamples.length >= 2 ? trackAltitudeSamples : sessionAltitudeSamples
  const altitudeMeta =
    trackAltitudeSamples.length >= 2
      ? `${selectedTrack?.name ?? 'Track'} track altitude`
      : activePointSets[0]
        ? `${activePointSets[0].session.name} session altitude`
        : 'No altitude'
  const mapStatus = activePointSets.length
    ? `${activePointSets.length} session path(s) / ${draftTrackpoints.length} draft point(s) / ${validSegmentAliases.length} segment label(s)`
    : 'No active GPS paths loaded'
  const dirtyTrackCount = workingTracks.filter((track) => track.dirty).length
  const canPersistTrack = Boolean(canWrite && dataSource.saveTrack && selectedTrack && referencePath.length >= 2 && selectedTrack.name.trim())
  const canSaveAllTracks = Boolean(canWrite && dataSource.saveTrack && dirtyTrackCount > 0)

  function toggleSession(session: SessionRecord) {
    const id = sessionRecordId(session)
    setActiveSessionIds((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function updateWorkingTrack(
    workingId: string,
    updater: (track: WorkingTrack) => WorkingTrack,
    options: { markDirty?: boolean } = {},
  ) {
    setWorkingTracks((current) =>
      current.map((track) => {
        if (track.workingId !== workingId) {
          return track
        }
        const updated = updater(track)
        return options.markDirty === false ? updated : { ...updated, dirty: true, status: '' }
      }),
    )
  }

  const addDraftTrackpoint = useCallback((position: [number, number]) => {
    const targetTrack = selectedTrack
    if (!targetTrack) {
      const scratchTrack = scratchTrackFromNearestPath(position, sessionPaths, workingTracks, studySet)
      if (!scratchTrack) {
        return
      }
      setWorkingTracks((current) => [...current, scratchTrack])
      setSelectedWorkingTrackId(scratchTrack.workingId)
      return
    }
    if (targetTrack.points.length < 2) {
      return
    }
    const snapped = snapPositionToPath(position, targetTrack.points, routeLengthM(targetTrack.points))
    updateWorkingTrack(targetTrack.workingId, (track) => {
      const nextIndex = track.trackpoints.length + 1
      return {
        ...track,
        trackpoints: [...track.trackpoints, draftTrackpointFromSnap(snapped, nextIndex)],
      }
    })
  }, [selectedTrack, sessionPaths, studySet, workingTracks])

  function removeDraftTrackpoint(trackpointId: string) {
    if (!selectedTrack) {
      return
    }
    updateWorkingTrack(selectedTrack.workingId, (track) => ({
      ...track,
      trackpoints: track.trackpoints.filter((trackpoint) => trackpoint.id !== trackpointId),
      segmentAliases: track.segmentAliases.filter(
        (alias) => alias.fromTrackpointId !== trackpointId && alias.toTrackpointId !== trackpointId,
      ),
    }))
  }

  function renameDraftTrackpoint(trackpointId: string, name: string) {
    if (!selectedTrack) {
      return
    }
    updateWorkingTrack(selectedTrack.workingId, (track) => ({
      ...track,
      trackpoints: track.trackpoints.map((trackpoint) =>
        trackpoint.id === trackpointId ? { ...trackpoint, name } : trackpoint,
      ),
    }))
  }

  function sortSelectedTrackpointsByStation() {
    if (!selectedTrack) {
      return
    }
    updateWorkingTrack(
      selectedTrack.workingId,
      (track) => ({
        ...track,
        trackpoints: [...track.trackpoints].sort((a, b) => a.stationM - b.stationM),
      }),
      { markDirty: false },
    )
  }

  function renameSegmentAlias(fromTrackpointId: string, toTrackpointId: string, name: string) {
    if (!selectedTrack) {
      return
    }
    updateWorkingTrack(selectedTrack.workingId, (track) => ({
      ...track,
      segmentAliases: upsertSegmentAlias(track.segmentAliases, fromTrackpointId, toTrackpointId, name),
    }))
  }

  function renameWorkingTrack(workingId: string, name: string) {
    updateWorkingTrack(workingId, (track) => ({ ...track, name }))
  }

  function setTrackStatus(workingId: string, status: string) {
    setWorkingTracks((current) => current.map((track) => (track.workingId === workingId ? { ...track, status } : track)))
  }

  function setWorkingTrackFlags(workingId: string, flags: Partial<Pick<WorkingTrack, 'saving' | 'deleting' | 'status'>>) {
    setWorkingTracks((current) =>
      current.map((track) => (track.workingId === workingId ? { ...track, ...flags } : track)),
    )
  }

  function removeWorkingTrack(workingId: string) {
    setWorkingTracks((current) => {
      const next = current.filter((track) => track.workingId !== workingId)
      setSelectedWorkingTrackId((selected) => (selected === workingId ? next[0]?.workingId ?? '' : selected))
      return next
    })
  }

  async function saveTrackEdits(workingId = selectedWorkingTrackId) {
    const trackToSave = workingTracks.find((track) => track.workingId === workingId)
    if (!trackToSave) {
      return
    }
    if (!dataSource.saveTrack) {
      setTrackStatus(workingId, 'The current data source does not support track saving.')
      return
    }
    if (!canWrite) {
      setTrackStatus(workingId, 'The Library API is running in read-only mode.')
      return
    }
    const displayName = trackToSave.name.trim()
    if (!displayName) {
      setTrackStatus(workingId, 'Track name is required.')
      return
    }
    if (trackToSave.points.length < 2) {
      setTrackStatus(workingId, 'A GPS path or saved track path is required before saving.')
      return
    }
    setWorkingTrackFlags(workingId, { saving: true, status: '' })
    try {
      const generatedTrackpointIds: string[] = []
      const sortedTrackpoints = [...trackToSave.trackpoints]
        .map((trackpoint, index) => {
          const name = trackpoint.name.trim() || `Point ${index + 1}`
          const existingIds = [...trackToSave.trackpoints.map((item) => item.id), ...generatedTrackpointIds]
          const id = trackpoint.id.startsWith('draft-') ? uniqueId(slugify(name), existingIds) : trackpoint.id
          generatedTrackpointIds.push(id)
          return {
            id,
            name,
            stationM: trackpoint.stationM,
            position: copyPosition(trackpoint.position),
            cutlineOverride: trackpoint.cutlineOverride ? { ...trackpoint.cutlineOverride } : undefined,
          }
        })
        .sort((a, b) => a.stationM - b.stationM)
      const saved = await dataSource.saveTrack({
        id: trackToSave.persistedId ?? '',
        name: displayName,
        description: trackToSave.description || 'Track created from Track Analysis and Lap Timing.',
        revision: trackToSave.revision,
        pointCount: trackToSave.points.length,
        distanceKm: trackToSave.lengthM / 1000,
        lengthM: trackToSave.lengthM,
        points: trackToSave.points.map((position) => copyPosition(position)),
        defaultPolicyId: trackToSave.defaultPolicyId || 'default-geospatial-policy',
        trackpoints: sortedTrackpoints,
        segmentAliases: validSegmentAliasesForTrack(trackToSave),
        matchSummaries: trackToSave.matchSummaries,
        source: trackToSave.source,
      })
      setLocalTracks((current) => mergeTrackLists(current, [saved]))
      setWorkingTracks((current) =>
        current.map((track) =>
          track.workingId === workingId
            ? { ...workingTrackFromRecord(saved, track), workingId: track.workingId, status: `Saved ${saved.name}.` }
            : track,
        ),
      )
      setSelectedWorkingTrackId(workingId)
      onTrackSaved?.(saved)
    } catch (error) {
      setTrackStatus(workingId, error instanceof Error ? error.message : 'Could not save track edits.')
    } finally {
      setWorkingTrackFlags(workingId, { saving: false })
    }
  }

  async function saveAllTracks() {
    for (const track of workingTracks.filter((item) => item.dirty)) {
      await saveTrackEdits(track.workingId)
    }
  }

  async function deleteWorkingTrack(workingId: string) {
    const trackToDelete = workingTracks.find((track) => track.workingId === workingId)
    if (!trackToDelete) {
      return
    }
    const label = trackToDelete.persistedId ? `Delete saved track "${trackToDelete.name}"?` : `Delete scratch track "${trackToDelete.name}"?`
    if (!window.confirm(label)) {
      return
    }
    if (!trackToDelete.persistedId) {
      removeWorkingTrack(workingId)
      return
    }
    if (!dataSource.deleteTrack) {
      setTrackStatus(workingId, 'The current data source does not support track deletion.')
      return
    }
    if (!canWrite) {
      setTrackStatus(workingId, 'The Library API is running in read-only mode.')
      return
    }
    setWorkingTrackFlags(workingId, { deleting: true, status: '' })
    try {
      await dataSource.deleteTrack(trackToDelete.persistedId)
      setLocalTracks((current) => current.filter((track) => track.id !== trackToDelete.persistedId))
      removeWorkingTrack(workingId)
      onTrackDeleted?.(trackToDelete.persistedId)
    } catch (error) {
      setTrackStatus(workingId, error instanceof Error ? error.message : 'Could not delete track.')
    } finally {
      setWorkingTrackFlags(workingId, { deleting: false })
    }
  }

  const moveDraftTrackpoint = useCallback((trackpointId: string, position: [number, number]) => {
    const targetTrack = selectedTrack
    if (!targetTrack || targetTrack.points.length < 2) {
      return
    }
    const snapped = snapPositionToPath(position, targetTrack.points, routeLengthM(targetTrack.points))
    updateWorkingTrack(targetTrack.workingId, (track) => ({
      ...track,
      trackpoints: track.trackpoints.map((trackpoint) =>
        trackpoint.id === trackpointId
          ? {
              ...trackpoint,
              stationM: snapped.stationM,
              position: snapped.position,
            }
          : trackpoint,
      ),
    }))
  }, [selectedTrack])

  const adjustDraftCutline = useCallback((trackpointId: string, handle: CutlineHandle, position: [number, number]) => {
    const targetTrack = selectedTrack
    if (!targetTrack || targetTrack.points.length < 2) {
      return
    }
    updateWorkingTrack(targetTrack.workingId, (track) => ({
      ...track,
      trackpoints: track.trackpoints.map((trackpoint) => {
        if (trackpoint.id !== trackpointId) {
          return trackpoint
        }
        const normal = pathNormalAtTrackpoint(targetTrack.points, trackpoint)
        if (!normal) {
          return trackpoint
        }
        const vector = vectorMeters(trackpoint.position, position)
        const lengthM = Math.max(1, Math.hypot(vector.x, vector.y))
        const cutlineUnit =
          handle === 'right'
            ? { x: vector.x / lengthM, y: vector.y / lengthM }
            : { x: -vector.x / lengthM, y: -vector.y / lengthM }
        const angleDegFromPathNormal = signedAngleDeg(normal, cutlineUnit)
        return {
          ...trackpoint,
          cutlineOverride: {
            ...trackpoint.cutlineOverride,
            angleDegFromPathNormal,
            ...(handle === 'left' ? { leftLengthM: lengthM } : { rightLengthM: lengthM }),
          },
        }
      }),
    }))
  }, [selectedTrack])

  return (
    <div className={`track-analysis ${drawerOpen ? 'drawer-open' : 'drawer-closed'}`}>
      <aside className="track-analysis-drawer">
        <button
          className="track-analysis-drawer-tab"
          type="button"
          onClick={() => setDrawerOpen((current) => !current)}
          aria-expanded={drawerOpen}
        >
          {drawerOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
          <span>Select and filter</span>
        </button>
        {drawerOpen && (
          <div className="track-analysis-drawer-body">
            <section className="track-analysis-control-card">
              <TrackPanelTitle
                title="Sessions"
                meta={`${activeSessionIds.size} active / ${scopedSessions.length} available`}
                info="Groups in the launch scope are accepted but ignored in this first track-analysis slice."
              />
              <div className="track-analysis-session-list">
                {scopedSessions.map((session) => {
                  const id = sessionRecordId(session)
                  const gpsQuality = session.gpsSummary.quality
                  const sources = session.gpsSummary.sources ?? []
                  return (
                    <label key={id} className="track-analysis-session-row">
                      <input checked={activeSessionIds.has(id)} type="checkbox" onChange={() => toggleSession(session)} />
                      <span>
                        <strong>{session.name}</strong>
                        <small>{gpsQuality === 'usable' ? 'usable GPS' : `${gpsQuality || 'unknown'} GPS`}</small>
                      </span>
                      {sources.length > 1 && (
                        <select
                          value={gpsSourceBySessionId[id] ?? session.gpsSummary.preferredSourceId ?? sources[0]?.sourceId ?? ''}
                          onChange={(event) =>
                            setGpsSourceBySessionId((current) => ({ ...current, [id]: event.target.value }))
                          }
                        >
                          {sources.map((source) => (
                            <option key={source.sourceId} value={source.sourceId}>
                              {source.streamName || source.sourceId}
                            </option>
                          ))}
                        </select>
                      )}
                    </label>
                  )
                })}
              </div>
            </section>

            <section className="track-analysis-control-card">
              <TrackPanelTitle
                title="Tracks"
                meta={`${workingTracks.length} in scope / ${dirtyTrackCount} unsaved`}
                info="Scratch tracks are temporary working copies created from session GPS. Save them to make root-scoped reusable tracks."
              />
              {workingTracks.length ? (
                <div className="track-analysis-track-list">
                  {workingTracks.map((track) => (
                    <button
                      key={track.workingId}
                      type="button"
                      className={`track-analysis-track-row ${track.workingId === selectedWorkingTrackId ? 'selected' : ''} ${track.dirty ? 'dirty' : 'clean'}`}
                      onClick={() => setSelectedWorkingTrackId(track.workingId)}
                    >
                      <span>
                        <strong>{track.name || 'Unnamed track'}</strong>
                        <small>
                          {track.persistedId ? 'saved track' : 'scratch track'} · {track.trackpoints.length} point(s)
                        </small>
                      </span>
                      <em>{track.dirty ? 'unsaved' : 'saved'}</em>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="track-analysis-muted">No tracks yet. Click near an active GPS path to start a scratch track.</p>
              )}
              <button className="secondary-action compact" type="button" onClick={() => setSelectedWorkingTrackId('')}>
                New scratch on next map click
              </button>
              <div className="track-analysis-label-options">
                <label>
                  <input
                    checked={hideSegmentNames}
                    type="checkbox"
                    onChange={(event) => setHideSegmentNames(event.target.checked)}
                  />
                  <span>Hide segment names</span>
                </label>
              </div>
              {selectedTrack && (
                <label className="track-analysis-field">
                  <span>Track name</span>
                  <input value={selectedTrack.name} onChange={(event) => renameWorkingTrack(selectedTrack.workingId, event.target.value)} />
                </label>
              )}
              <div className="track-analysis-draft-list">
                {selectedTrack && draftTrackpoints.length ? (
                  orderedDraftTrackpoints.flatMap((trackpoint, index) => {
                    const nextTrackpoint = orderedDraftTrackpoints[index + 1]
                    const alias = nextTrackpoint
                      ? segmentAliasForPair(selectedTrack.segmentAliases, trackpoint.id, nextTrackpoint.id)
                      : null
                    return [
                      <div key={trackpoint.id} className="track-analysis-draft-row">
                        <span className="track-analysis-row-glyph track-analysis-point-glyph" aria-hidden="true" />
                        <label>
                          <span className="track-analysis-draft-heading">
                            <span>Point name</span>
                            <small>{formatDistance(trackpoint.stationM)} from start</small>
                          </span>
                          <input
                            value={trackpoint.name}
                            onChange={(event) => renameDraftTrackpoint(trackpoint.id, event.target.value)}
                          />
                        </label>
                        <button type="button" className="icon-only small" onClick={() => removeDraftTrackpoint(trackpoint.id)}>
                          <Trash2 size={13} />
                        </button>
                      </div>,
                      nextTrackpoint && !hideSegmentNames ? (
                        <label key={`${trackpoint.id}-${nextTrackpoint.id}-segment`} className="track-analysis-segment-row">
                          <span className="track-analysis-row-glyph track-analysis-segment-glyph" aria-hidden="true" />
                          <input
                            aria-label={`Segment name from ${trackpoint.name || trackpoint.id} to ${nextTrackpoint.name || nextTrackpoint.id}`}
                            placeholder="Optional segment name"
                            value={alias?.name ?? ''}
                            onChange={(event) => renameSegmentAlias(trackpoint.id, nextTrackpoint.id, event.target.value)}
                          />
                        </label>
                      ) : null,
                    ].filter(Boolean)
                  })
                ) : selectedTrack ? (
                  <p className="track-analysis-muted">Click near this track path on the map to add a temporary trackpoint.</p>
                ) : (
                  <p className="track-analysis-muted">Select a track, or click near a GPS path to create a scratch track.</p>
                )}
              </div>
              <div className="track-analysis-save-row">
                <button
                  className="primary-action compact"
                  disabled={!canPersistTrack || selectedTrack?.saving}
                  onClick={() => void saveTrackEdits()}
                  type="button"
                >
                  {selectedTrack?.saving ? 'Saving...' : selectedTrack?.persistedId ? 'Save track' : 'Create track'}
                </button>
                <button
                  className="secondary-action compact"
                  disabled={!canSaveAllTracks}
                  onClick={() => void saveAllTracks()}
                  type="button"
                >
                  Save all
                </button>
                {selectedTrack && (
                  <button
                    className="danger-action compact"
                    disabled={selectedTrack.deleting}
                    onClick={() => void deleteWorkingTrack(selectedTrack.workingId)}
                    type="button"
                  >
                    {selectedTrack.deleting ? 'Deleting...' : 'Delete'}
                  </button>
                )}
                {selectedTrack?.status && <span>{selectedTrack.status}</span>}
              </div>
            </section>
          </div>
        )}
      </aside>

      <section className="track-analysis-main">
        <section className="track-analysis-map-card">
          <TrackPanelTitle
            title="Track map"
            meta={mapStatus}
            info="Click near the reference path to place a temporary trackpoint. Drag a point to move it along the path, or drag cutline ends to rotate and resize the cutline."
          />
          <TrackAnalysisMap
            sessionPaths={sessionPaths}
            referencePath={referencePath}
            referenceTrackDirty={Boolean(selectedTrack?.dirty)}
            draftTrackpoints={draftTrackpoints}
            segmentAliases={validSegmentAliases}
            hideSegmentNames={hideSegmentNames}
            onCreateTrackpoint={addDraftTrackpoint}
            onMoveTrackpoint={moveDraftTrackpoint}
            onAdjustCutline={adjustDraftCutline}
            onDeleteTrackpoint={removeDraftTrackpoint}
            onTrackpointDragEnd={sortSelectedTrackpointsByStation}
          />
        </section>

        <section className={`track-analysis-bottom ${lapTimingExpanded ? 'lap-expanded' : ''}`}>
          {!lapTimingExpanded && (
            <div className="track-analysis-lower-card">
              <TrackPanelTitle title="Altitude profile" meta={altitudeMeta} />
              <AltitudeChart samples={altitudeSamples} />
            </div>
          )}
          {lapTimingExpanded && (
            <button
              type="button"
              className="track-analysis-altitude-rail"
              onClick={() => setLapTimingExpanded(false)}
              title="Show altitude profile"
            >
              <ChevronRight size={14} />
              <span>Altitude profile</span>
            </button>
          )}
          <div className="track-analysis-lower-card">
            <TrackPanelTitle
              title="Lap timing"
              meta={lapTimingRows.length ? `${lapTimingRows.length} timing row(s)` : 'No sectors'}
              action={
                <button
                  type="button"
                  className="track-analysis-title-button"
                  onClick={() => setLapTimingExpanded((current) => !current)}
                  title={lapTimingExpanded ? 'Show altitude profile' : 'Expand lap timing'}
                >
                  <ChevronLeft size={14} />
                  <span>{lapTimingExpanded ? 'Collapse' : 'Expand'}</span>
                </button>
              }
            />
            <LapTimingTable activePointSets={activePointSets} rows={lapTimingRows} trackpointCount={draftTrackpoints.length} />
          </div>
        </section>
      </section>
    </div>
  )
}

function LapTimingTable({
  activePointSets,
  rows,
  trackpointCount,
}: {
  activePointSets: ActiveGpsPointSet[]
  rows: LapTimingRow[]
  trackpointCount: number
}) {
  if (activePointSets.length === 0) {
    return (
      <div className="track-analysis-placeholder">
        <MapIcon size={22} />
        <p>No active GPS paths are loaded yet.</p>
      </div>
    )
  }
  if (trackpointCount < 2) {
    return (
      <div className="track-analysis-placeholder">
        <MapIcon size={22} />
        <p>Add at least two trackpoints to calculate start-to-finish and sector timing.</p>
        <small>V1 policy: latest crossing per trackpoint; reverse-order sectors are ignored.</small>
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div className="track-analysis-placeholder">
        <MapIcon size={22} />
        <p>No usable timing rows were found for these trackpoints.</p>
      </div>
    )
  }
  const visibleSessionIds = new Set<string>()
  rows.forEach((row) => {
    row.times.forEach((time) => {
      if (time.status !== 'missing') {
        visibleSessionIds.add(time.sessionId)
      }
    })
  })
  const visiblePointSets = activePointSets.filter((item) => visibleSessionIds.has(sessionRecordId(item.session)))
  if (visiblePointSets.length === 0) {
    return (
      <div className="track-analysis-placeholder">
        <MapIcon size={22} />
        <p>No sessions have point crossings for these trackpoints.</p>
      </div>
    )
  }
  const visibleRowOrder = [
    ...rows.filter((row) => row.key !== 'overall'),
    ...rows.filter((row) => row.key === 'overall'),
  ].map((row) => ({
    ...row,
    times: row.times.filter((time) => visibleSessionIds.has(time.sessionId)),
  }))
  return (
    <div className="track-analysis-lap-table-wrap">
      <table className="track-analysis-lap-table">
        <thead>
          <tr>
            <th>Section</th>
            <th>Distance</th>
            {visiblePointSets.map((item) => (
              <th key={sessionRecordId(item.session)}>{item.session.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleRowOrder.map((row) => (
            <tr key={row.key} className={row.key === 'overall' ? 'track-analysis-overall-row' : ''}>
              <td>{row.label}</td>
              <td>{formatDistance(row.distanceM)}</td>
              {row.times.map((time) => (
                <td key={time.sessionId} className={time.status !== 'ready' ? 'track-analysis-muted-cell' : ''}>
                  {time.status === 'ready' && time.valueS !== null
                    ? formatDuration(time.valueS)
                    : time.status === 'reverse'
                      ? 'reverse'
                      : 'no crossing'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="track-analysis-table-note">Latest crossing per trackpoint is used; sectors with reverse timing are ignored.</p>
    </div>
  )
}

function TrackAnalysisMap({
  sessionPaths,
  referencePath,
  referenceTrackDirty,
  draftTrackpoints,
  segmentAliases,
  hideSegmentNames,
  onCreateTrackpoint,
  onMoveTrackpoint,
  onAdjustCutline,
  onDeleteTrackpoint,
  onTrackpointDragEnd,
}: {
  sessionPaths: SessionPath[]
  referencePath: GeoPosition[]
  referenceTrackDirty: boolean
  draftTrackpoints: DraftTrackpoint[]
  segmentAliases: TrackSegmentAliasRecord[]
  hideSegmentNames: boolean
  onCreateTrackpoint: (position: [number, number]) => void
  onMoveTrackpoint: (trackpointId: string, position: [number, number]) => void
  onAdjustCutline: (trackpointId: string, handle: CutlineHandle, position: [number, number]) => void
  onDeleteTrackpoint: (trackpointId: string) => void
  onTrackpointDragEnd: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const createTrackpointRef = useRef(onCreateTrackpoint)
  const moveTrackpointRef = useRef(onMoveTrackpoint)
  const adjustCutlineRef = useRef(onAdjustCutline)
  const deleteTrackpointRef = useRef(onDeleteTrackpoint)
  const trackpointDragEndRef = useRef(onTrackpointDragEnd)
  const dragHandleRef = useRef<DragHandle | null>(null)
  const suppressClickRef = useRef(false)
  const hasFitInitialDataRef = useRef(false)
  const hasData = sessionPaths.some((path) => path.path.length >= 2) || referencePath.length >= 2

  useEffect(() => {
    createTrackpointRef.current = onCreateTrackpoint
  }, [onCreateTrackpoint])

  useEffect(() => {
    moveTrackpointRef.current = onMoveTrackpoint
  }, [onMoveTrackpoint])

  useEffect(() => {
    adjustCutlineRef.current = onAdjustCutline
  }, [onAdjustCutline])

  useEffect(() => {
    deleteTrackpointRef.current = onDeleteTrackpoint
  }, [onDeleteTrackpoint])

  useEffect(() => {
    trackpointDragEndRef.current = onTrackpointDragEnd
  }, [onTrackpointDragEnd])

  useEffect(() => {
    if (!hasData || !containerRef.current || mapRef.current) {
      return
    }
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_RASTER_STYLE,
      center: [0, 0],
      zoom: 13,
      attributionControl: false,
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    const preventContextMenu = (event: MouseEvent) => {
      event.preventDefault()
      const rect = map.getCanvas().getBoundingClientRect()
      const feature = queryPointHandleFeature(map, {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      })
      const handle = dragHandleFromFeature(feature?.properties)
      if (handle) {
        suppressClickRef.current = true
        deleteTrackpointRef.current(handle.trackpointId)
        window.setTimeout(() => {
          suppressClickRef.current = false
        }, 0)
      }
    }
    map.getCanvas().addEventListener('contextmenu', preventContextMenu)
    map.on('click', (event) => {
      if (suppressClickRef.current) {
        suppressClickRef.current = false
        return
      }
      createTrackpointRef.current([event.lngLat.lng, event.lngLat.lat])
    })
    map.on('mousedown', (event) => {
      const feature = queryPointHandleFeature(map, event.point)
      const handle = dragHandleFromFeature(feature?.properties)
      if (!handle) {
        return
      }
      event.preventDefault()
      if (event.originalEvent.button === 2) {
        suppressClickRef.current = true
        deleteTrackpointRef.current(handle.trackpointId)
        window.setTimeout(() => {
          suppressClickRef.current = false
        }, 0)
        return
      }
      dragHandleRef.current = handle
      suppressClickRef.current = true
      map.getCanvas().style.cursor = 'grabbing'
      map.dragPan.disable()
    })
    map.on('contextmenu', (event) => {
      const feature = queryPointHandleFeature(map, event.point)
      const handle = dragHandleFromFeature(feature?.properties)
      if (!handle) {
        return
      }
      event.preventDefault()
      deleteTrackpointRef.current(handle.trackpointId)
    })
    map.on('mousemove', (event) => {
      const handle = dragHandleRef.current
      if (!handle) {
        map.getCanvas().style.cursor = queryPointHandleFeature(map, event.point) ? 'grab' : ''
        return
      }
      const position: [number, number] = [event.lngLat.lng, event.lngLat.lat]
      if (handle.role === 'trackpoint') {
        moveTrackpointRef.current(handle.trackpointId, position)
      } else {
        adjustCutlineRef.current(handle.trackpointId, handle.role, position)
      }
    })
    map.on('mouseup', () => {
      if (!dragHandleRef.current) {
        return
      }
      dragHandleRef.current = null
      trackpointDragEndRef.current()
      window.setTimeout(() => {
        suppressClickRef.current = false
      }, 0)
      map.getCanvas().style.cursor = ''
      map.dragPan.enable()
    })
    mapRef.current = map
    return () => {
      map.getCanvas().removeEventListener('contextmenu', preventContextMenu)
      map.remove()
      mapRef.current = null
    }
  }, [hasData])

  useEffect(() => {
    if (!containerRef.current) {
      return
    }
    const observer = new ResizeObserver(() => mapRef.current?.resize())
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !hasData) {
      return
    }
    const activeMap = map
    function applyData() {
      const data = buildMapData(sessionPaths, referencePath, referenceTrackDirty, draftTrackpoints, segmentAliases, hideSegmentNames)
      ensureLineLayer(activeMap, data.lines)
      ensurePointLayer(activeMap, data.points)
      if (!hasFitInitialDataRef.current) {
        hasFitInitialDataRef.current = true
        fitToPositions(activeMap, data.bounds)
      }
    }
    if (activeMap.isStyleLoaded()) {
      applyData()
      return
    }
    activeMap.once('load', applyData)
    return () => {
      activeMap.off('load', applyData)
    }
  }, [draftTrackpoints, hasData, hideSegmentNames, referencePath, referenceTrackDirty, segmentAliases, sessionPaths])

  if (!hasData) {
    return (
      <div className="track-analysis-map-empty">
        <MapIcon size={28} />
        <span>Select at least one session with GPS to begin.</span>
      </div>
    )
  }

  return <div className="track-analysis-map" ref={containerRef} />
}

function AltitudeChart({ samples }: { samples: AltitudeSample[] }) {
  if (samples.length < 2) {
    return <div className="track-analysis-placeholder">No altitude data is available for the selected track or session.</div>
  }
  const width = 640
  const height = 170
  const padding = { top: 12, right: 16, bottom: 24, left: 42 }
  const minDistance = Math.min(...samples.map((item) => item.distanceM))
  const maxDistance = Math.max(...samples.map((item) => item.distanceM))
  const elevations = samples.map((item) => item.elevationM)
  const minElevation = Math.min(...elevations)
  const maxElevation = Math.max(...elevations)
  const spanElevation = Math.max(1, maxElevation - minElevation)
  const path = samples
    .map((item, index) => {
      const x = padding.left + ((item.distanceM - minDistance) / Math.max(1, maxDistance - minDistance)) * (width - padding.left - padding.right)
      const y = padding.top + (1 - (item.elevationM - minElevation) / spanElevation) * (height - padding.top - padding.bottom)
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg className="track-analysis-altitude-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Altitude profile chart">
      <line x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
      <line x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
      <path d={path} />
      <text x={padding.left} y={height - 6}>
        Distance
      </text>
      <text x={6} y={padding.top + 8}>
        {Math.round(maxElevation)} m
      </text>
      <text x={6} y={height - padding.bottom}>
        {Math.round(minElevation)} m
      </text>
    </svg>
  )
}

function buildMapData(
  sessionPaths: SessionPath[],
  referencePath: GeoPosition[],
  referenceTrackDirty: boolean,
  draftTrackpoints: DraftTrackpoint[],
  segmentAliases: TrackSegmentAliasRecord[],
  hideSegmentNames: boolean,
) {
  const lines: Array<Feature<LineString, { color: string; width: number; opacity: number }>> = []
  const points: Array<Feature<Point, MapPointProperties>> = []
  const bounds: GeoPosition[] = []

  sessionPaths.forEach((sessionPath, index) => {
    const path = filterPositions(sessionPath.path)
    if (path.length >= 2) {
      lines.push(lineFeature(`session-${sessionPath.id}`, path, SESSION_COLORS[index % SESSION_COLORS.length], 4, 0.74))
      bounds.push(...path)
    }
  })

  const safeReferencePath = filterPositions(referencePath)
  if (safeReferencePath.length >= 2) {
    lines.push(lineFeature('reference-track', safeReferencePath, referenceTrackDirty ? DRAFT_COLOR : TRACK_COLOR, 5, 0.92))
    bounds.push(...safeReferencePath)
  }

  draftTrackpoints.forEach((trackpoint) => {
    points.push(
      pointFeature(
        trackpoint.id,
        trackpoint.position,
        DRAFT_COLOR,
        trackpoint.name,
        7,
        'trackpoint',
        trackpoint.id,
      ),
    )
    bounds.push(trackpoint.position)
    const cutline = cutlineForTrackpoint(safeReferencePath, trackpoint)
    if (cutline) {
      lines.push(lineFeature(`cutline-${trackpoint.id}`, cutline, DRAFT_COLOR, 3, 0.95))
      points.push(pointFeature(`${trackpoint.id}-left`, cutline[0], '#ffffff', '', 5, 'left', trackpoint.id))
      points.push(pointFeature(`${trackpoint.id}-right`, cutline[1], '#ffffff', '', 5, 'right', trackpoint.id))
      bounds.push(...cutline)
    }
  })

  if (!hideSegmentNames) {
    segmentAliases.forEach((alias) => {
      const midpoint = segmentAliasMidpoint(draftTrackpoints, alias)
      if (!midpoint) {
        return
      }
      points.push(pointFeature(`segment-${alias.fromTrackpointId}-${alias.toTrackpointId}`, midpoint, TRACK_COLOR, alias.name, 0, 'segment', ''))
    })
  }

  return {
    lines: {
      type: 'FeatureCollection',
      features: lines,
    } satisfies FeatureCollection<LineString, { color: string; width: number; opacity: number }>,
    points: {
      type: 'FeatureCollection',
      features: points,
    } satisfies FeatureCollection<Point, MapPointProperties>,
    bounds,
  }
}

function altitudeSamplesForTrack(track: Pick<TrackRecord, 'points'>): AltitudeSample[] {
  const stations = routeStationsM(track.points)
  return track.points
    .map((position, index) =>
      Number.isFinite(position[2])
        ? {
            distanceM: stations[index] ?? 0,
            elevationM: position[2] as number,
          }
        : null,
    )
    .filter(isAltitudeSample)
}

function altitudeSamplesForSessionGps(pointSet: SessionGpsPointSet | null): AltitudeSample[] {
  if (!pointSet) {
    return []
  }
  const positions = pointSet.points
    .filter(
      (point) =>
        Number.isFinite(point.longitude) &&
        Number.isFinite(point.latitude) &&
        point.elevationM !== null &&
        Number.isFinite(point.elevationM),
    )
    .map((point) => [point.longitude, point.latitude, point.elevationM as number] as GeoPosition)
  const stations = routeStationsM(positions)
  return positions.map((position, index) => ({
    distanceM: stations[index] ?? 0,
    elevationM: position[2] as number,
  }))
}

function isAltitudeSample(value: AltitudeSample | null): value is AltitudeSample {
  return value !== null
}

function validSegmentAliasesForTrack(track: Pick<WorkingTrack, 'trackpoints' | 'segmentAliases'>): TrackSegmentAliasRecord[] {
  const ordered = [...track.trackpoints].sort((a, b) => a.stationM - b.stationM)
  const adjacentPairs = new Set<string>()
  for (let index = 0; index < ordered.length - 1; index += 1) {
    adjacentPairs.add(segmentAliasKey(ordered[index].id, ordered[index + 1].id))
  }
  return track.segmentAliases.filter(
    (alias) => alias.name.trim() && adjacentPairs.has(segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId)),
  )
}

function segmentAliasForPair(
  aliases: TrackSegmentAliasRecord[],
  fromTrackpointId: string,
  toTrackpointId: string,
) {
  return aliases.find((alias) => alias.fromTrackpointId === fromTrackpointId && alias.toTrackpointId === toTrackpointId) ?? null
}

function upsertSegmentAlias(
  aliases: TrackSegmentAliasRecord[],
  fromTrackpointId: string,
  toTrackpointId: string,
  name: string,
) {
  const trimmedName = name.trim()
  const key = segmentAliasKey(fromTrackpointId, toTrackpointId)
  const withoutExisting = aliases.filter((alias) => segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId) !== key)
  if (!trimmedName) {
    return withoutExisting
  }
  return [...withoutExisting, { fromTrackpointId, toTrackpointId, name }]
}

function segmentAliasKey(fromTrackpointId: string, toTrackpointId: string) {
  return `${fromTrackpointId}=>${toTrackpointId}`
}

function workingTrackFromRecord(track: TrackRecord, previous?: WorkingTrack): WorkingTrack {
  return {
    workingId: previous?.workingId ?? `saved:${track.id}`,
    persistedId: track.id,
    origin: 'persisted',
    dirty: false,
    saving: false,
    deleting: false,
    status: previous?.status ?? '',
    name: track.name,
    description: track.description ?? '',
    revision: track.revision,
    points: track.points.map(copyPosition),
    lengthM: track.lengthM,
    pointCount: track.pointCount,
    distanceKm: track.distanceKm,
    defaultPolicyId: track.defaultPolicyId,
    trackpoints: track.trackpoints.map(draftTrackpointFromRecord),
    segmentAliases: (track.segmentAliases ?? []).map((alias) => ({ ...alias })),
    matchSummaries: track.matchSummaries.map((match) => ({
      ...match,
      trackpointResults: match.trackpointResults.map((result) => ({ ...result })),
      warnings: [...match.warnings],
    })),
    source: track.source ? { ...track.source } : undefined,
    sourceSessionId: previous?.sourceSessionId,
  }
}

function draftTrackpointFromRecord(trackpoint: TrackpointRecord): DraftTrackpoint {
  return {
    ...trackpoint,
    position: copyPosition(trackpoint.position),
    cutlineOverride: trackpoint.cutlineOverride ? { ...trackpoint.cutlineOverride } : undefined,
    draft: true,
  }
}

function draftTrackpointFromSnap(
  snapped: { position: GeoPosition; stationM: number },
  nextIndex: number,
): DraftTrackpoint {
  return {
    id: `draft-${Date.now().toString(36)}-${nextIndex}`,
    name: `Point ${nextIndex}`,
    stationM: snapped.stationM,
    position: copyPosition(snapped.position),
    cutlineOverride: {
      leftLengthM: CUTLINE_LENGTH_M / 2,
      rightLengthM: CUTLINE_LENGTH_M / 2,
    },
    draft: true,
  }
}

function scratchTrackFromNearestPath(
  position: [number, number],
  sessionPaths: SessionPath[],
  existingTracks: WorkingTrack[],
  studySet: StudySet,
): WorkingTrack | null {
  const nearest = nearestSessionPath(position, sessionPaths)
  if (!nearest) {
    return null
  }
  const existingIds = existingTracks.map((track) => track.workingId)
  const workingId = uniqueId(`scratch-${Date.now().toString(36)}`, existingIds)
  const path = nearest.sessionPath.path.map(copyPosition)
  const lengthM = routeLengthM(path)
  const nextIndex = existingTracks.filter((track) => track.origin === 'scratch' && !track.persistedId).length + 1
  const name = `${studySet.displayName.trim() || nearest.sessionPath.label} scratch ${nextIndex}`
  return {
    workingId,
    persistedId: null,
    origin: 'scratch',
    dirty: true,
    saving: false,
    deleting: false,
    status: '',
    name,
    description: `Scratch track created from ${nearest.sessionPath.label}.`,
    revision: 0,
    points: path,
    lengthM,
    pointCount: path.length,
    distanceKm: lengthM / 1000,
    defaultPolicyId: 'default-geospatial-policy',
    trackpoints: [draftTrackpointFromSnap(nearest.snapped, 1)],
    segmentAliases: [],
    matchSummaries: [],
    source: {
      kind: 'session_gps',
      libraryId: nearest.sessionPath.session.libraryId,
      sessionRefId: sessionRecordId(nearest.sessionPath.session),
      sessionKey: nearest.sessionPath.session.sessionKey,
      runId: nearest.sessionPath.session.runId,
      sessionId: nearest.sessionPath.session.sessionId,
      gpsSourceId: nearest.sessionPath.session.gpsSummary.preferredSourceId ?? undefined,
      gpsSourceKind: nearest.sessionPath.session.gpsSummary.preferredSourceKind ?? undefined,
      gpsStreamName: nearest.sessionPath.session.gpsSummary.sources[0]?.streamName,
      gpsSourceSelectionMethod: nearest.sessionPath.session.gpsSummary.sourceSelectionMethod,
    },
    sourceSessionId: nearest.sessionPath.id,
  }
}

function nearestSessionPath(position: [number, number], sessionPaths: SessionPath[]) {
  const candidates = sessionPaths
    .filter((sessionPath) => sessionPath.path.length >= 2)
    .map((sessionPath) => {
      const pathLengthM = routeLengthM(sessionPath.path)
      const snappedPoint = nearestPointOnLine(lineString(sessionPath.path.map(lonLat)), point(position), { units: 'meters' })
      const stationM = clampNumber(Number(snappedPoint.properties?.location ?? 0), 0, pathLengthM)
      const distanceM = Number(snappedPoint.properties?.dist ?? Number.POSITIVE_INFINITY)
      return {
        sessionPath,
        distanceM,
        snapped: {
          stationM,
          position: pointAtStationM(sessionPath.path, stationM),
        },
      }
    })
    .filter((candidate) => Number.isFinite(candidate.distanceM))
    .sort((a, b) => a.distanceM - b.distanceM)
  return candidates[0] ?? null
}

function ensureLineLayer(
  map: MapLibreMap,
  data: FeatureCollection<LineString, { color: string; width: number; opacity: number }>,
) {
  const existingSource = map.getSource('track-analysis-lines') as GeoJSONSource | undefined
  if (existingSource) {
    existingSource.setData(data)
  } else {
    map.addSource('track-analysis-lines', { type: 'geojson', data })
  }
  if (!map.getLayer('track-analysis-lines')) {
    map.addLayer({
      id: 'track-analysis-lines',
      type: 'line',
      source: 'track-analysis-lines',
      paint: {
        'line-color': ['get', 'color'],
        'line-width': ['get', 'width'],
        'line-opacity': ['get', 'opacity'],
      },
    })
  }
}

function ensurePointLayer(
  map: MapLibreMap,
  data: FeatureCollection<Point, MapPointProperties>,
) {
  const existingSource = map.getSource('track-analysis-points') as GeoJSONSource | undefined
  if (existingSource) {
    existingSource.setData(data)
  } else {
    map.addSource('track-analysis-points', { type: 'geojson', data })
  }
  if (!map.getLayer('track-analysis-point-hitboxes')) {
    map.addLayer({
      id: 'track-analysis-point-hitboxes',
      type: 'circle',
      source: 'track-analysis-points',
      filter: ['!=', ['get', 'role'], 'segment'],
      paint: {
        'circle-color': '#ffffff',
        'circle-radius': ['+', ['get', 'radius'], 10],
        'circle-opacity': 0.01,
      },
    })
  }
  if (!map.getLayer('track-analysis-point-circles')) {
    map.addLayer({
      id: 'track-analysis-point-circles',
      type: 'circle',
      source: 'track-analysis-points',
      filter: ['!=', ['get', 'role'], 'segment'],
      paint: {
        'circle-color': ['get', 'color'],
        'circle-radius': ['get', 'radius'],
        'circle-stroke-width': 2,
        'circle-stroke-color': ['case', ['==', ['get', 'role'], 'trackpoint'], '#ffffff', DRAFT_COLOR],
      },
    })
  }
  if (!map.getLayer('track-analysis-point-labels')) {
    map.addLayer({
      id: 'track-analysis-point-labels',
      type: 'symbol',
      source: 'track-analysis-points',
      layout: {
        'text-field': ['get', 'label'],
        'text-offset': [0, 1.2],
        'text-size': 12,
      },
      paint: {
        'text-color': '#101820',
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.5,
      },
    })
  }
}

function queryPointHandleFeature(map: MapLibreMap, point: { x: number; y: number }) {
  if (!map.getLayer('track-analysis-point-hitboxes')) {
    return null
  }
  return (
    map.queryRenderedFeatures([point.x, point.y], {
      layers: ['track-analysis-point-hitboxes', 'track-analysis-point-circles'],
    })[0] ?? null
  )
}

function fitToPositions(map: MapLibreMap, positions: GeoPosition[]) {
  const validPositions = filterPositions(positions)
  if (validPositions.length === 0) {
    return
  }
  const bounds = validPositions.reduce(
    (nextBounds, position) => nextBounds.extend(lonLat(position)),
    new maplibregl.LngLatBounds(lonLat(validPositions[0]), lonLat(validPositions[0])),
  )
  map.fitBounds(bounds, { padding: 40, maxZoom: 16, duration: 0 })
}

function cutlineForTrackpoint(path: GeoPosition[], trackpoint: DraftTrackpoint): Array<[number, number]> | null {
  if (path.length < 2) {
    return null
  }
  const before = pointAtStationM(path, Math.max(0, trackpoint.stationM - 3))
  const after = pointAtStationM(path, Math.min(routeLengthM(path), trackpoint.stationM + 3))
  const pathNormal = perpendicularUnitVector(before, after, trackpoint.position[1])
  const normal = pathNormal
    ? rotateUnit(pathNormal, trackpoint.cutlineOverride?.angleDegFromPathNormal ?? 0)
    : null
  if (!normal) {
    return null
  }
  const leftLengthM = trackpoint.cutlineOverride?.leftLengthM ?? CUTLINE_LENGTH_M / 2
  const rightLengthM = trackpoint.cutlineOverride?.rightLengthM ?? CUTLINE_LENGTH_M / 2
  return [
    offsetPosition(trackpoint.position, -leftLengthM * normal.x, -leftLengthM * normal.y),
    offsetPosition(trackpoint.position, rightLengthM * normal.x, rightLengthM * normal.y),
  ]
}

function segmentAliasMidpoint(
  trackpoints: DraftTrackpoint[],
  alias: TrackSegmentAliasRecord,
): GeoPosition | null {
  const from = trackpoints.find((trackpoint) => trackpoint.id === alias.fromTrackpointId)
  const to = trackpoints.find((trackpoint) => trackpoint.id === alias.toTrackpointId)
  if (!from || !to) {
    return null
  }
  const longitude = (from.position[0] + to.position[0]) / 2
  const latitude = (from.position[1] + to.position[1]) / 2
  const fromElevation = from.position[2]
  const toElevation = to.position[2]
  if (Number.isFinite(fromElevation) && Number.isFinite(toElevation)) {
    return [longitude, latitude, ((fromElevation as number) + (toElevation as number)) / 2]
  }
  return [longitude, latitude]
}

function buildLapTimingRows(
  activePointSets: ActiveGpsPointSet[],
  referencePath: GeoPosition[],
  trackpoints: DraftTrackpoint[],
  segmentAliases: TrackSegmentAliasRecord[],
): LapTimingRow[] {
  const orderedTrackpoints = [...trackpoints].sort((a, b) => a.stationM - b.stationM)
  if (orderedTrackpoints.length < 2 || referencePath.length < 2) {
    return []
  }

  const crossingsBySession = new Map<string, Map<string, number>>()
  activePointSets.forEach((item) => {
    crossingsBySession.set(
      sessionRecordId(item.session),
      crossingsForSession(item.loaded.pointSet.points, referencePath, orderedTrackpoints),
    )
  })

  const rows: LapTimingRow[] = []
  const firstTrackpoint = orderedTrackpoints[0]
  const lastTrackpoint = orderedTrackpoints[orderedTrackpoints.length - 1]
  rows.push(
    timingRow(
      'overall',
      `${firstTrackpoint.name} to ${lastTrackpoint.name}`,
      Math.max(0, lastTrackpoint.stationM - firstTrackpoint.stationM),
      activePointSets,
      crossingsBySession,
      firstTrackpoint,
      lastTrackpoint,
    ),
  )

  for (let index = 1; index < orderedTrackpoints.length; index += 1) {
    const start = orderedTrackpoints[index - 1]
    const end = orderedTrackpoints[index]
    rows.push(
      timingRow(
        `${start.id}-${end.id}`,
        segmentAliasForPair(segmentAliases, start.id, end.id)?.name || `${start.name} to ${end.name}`,
        Math.max(0, end.stationM - start.stationM),
        activePointSets,
        crossingsBySession,
        start,
        end,
      ),
    )
  }

  return rows
}

function timingRow(
  key: string,
  label: string,
  distanceM: number,
  activePointSets: ActiveGpsPointSet[],
  crossingsBySession: Map<string, Map<string, number>>,
  start: DraftTrackpoint,
  end: DraftTrackpoint,
): LapTimingRow {
  return {
    key,
    label,
    distanceM,
    times: activePointSets.map((item) => {
      const sessionId = sessionRecordId(item.session)
      const crossings = crossingsBySession.get(sessionId)
      const startTimeS = crossings?.get(start.id)
      const endTimeS = crossings?.get(end.id)
      if (typeof startTimeS !== 'number' || typeof endTimeS !== 'number') {
        return { sessionId, valueS: null, status: 'missing' }
      }
      const valueS = endTimeS - startTimeS
      if (!Number.isFinite(valueS) || valueS <= 0) {
        return { sessionId, valueS: null, status: 'reverse' }
      }
      return { sessionId, valueS, status: 'ready' }
    }),
  }
}

function crossingsForSession(
  gpsPoints: SessionGpsPoint[],
  referencePath: GeoPosition[],
  trackpoints: DraftTrackpoint[],
) {
  const crossings = new Map<string, number>()
  const timedPoints = gpsPoints.filter(
    (point) =>
      point.timeS !== null &&
      Number.isFinite(point.timeS) &&
      Number.isFinite(point.longitude) &&
      Number.isFinite(point.latitude),
  )
  if (timedPoints.length < 2) {
    return crossings
  }

  trackpoints.forEach((trackpoint) => {
    const cutline = cutlineForTrackpoint(referencePath, trackpoint)
    if (!cutline) {
      return
    }
    let latestCrossingS: number | null = null
    for (let index = 1; index < timedPoints.length; index += 1) {
      const start = timedPoints[index - 1]
      const end = timedPoints[index]
      const intersection = segmentIntersectionT(
        [start.longitude, start.latitude],
        [end.longitude, end.latitude],
        cutline[0],
        cutline[1],
      )
      if (intersection === null || start.timeS === null || end.timeS === null) {
        continue
      }
      const crossingS = start.timeS + (end.timeS - start.timeS) * intersection
      if (Number.isFinite(crossingS) && (latestCrossingS === null || crossingS > latestCrossingS)) {
        latestCrossingS = crossingS
      }
    }
    if (latestCrossingS !== null) {
      crossings.set(trackpoint.id, latestCrossingS)
    }
  })

  return crossings
}

function segmentIntersectionT(
  pathStart: GeoPosition,
  pathEnd: GeoPosition,
  cutlineStart: [number, number],
  cutlineEnd: [number, number],
) {
  const rX = pathEnd[0] - pathStart[0]
  const rY = pathEnd[1] - pathStart[1]
  const sX = cutlineEnd[0] - cutlineStart[0]
  const sY = cutlineEnd[1] - cutlineStart[1]
  const denominator = cross2d(rX, rY, sX, sY)
  if (Math.abs(denominator) < 1e-14) {
    return null
  }
  const qpX = cutlineStart[0] - pathStart[0]
  const qpY = cutlineStart[1] - pathStart[1]
  const t = cross2d(qpX, qpY, sX, sY) / denominator
  const u = cross2d(qpX, qpY, rX, rY) / denominator
  const epsilon = 1e-9
  if (t < -epsilon || t > 1 + epsilon || u < -epsilon || u > 1 + epsilon) {
    return null
  }
  return clampNumber(t, 0, 1)
}

function cross2d(aX: number, aY: number, bX: number, bY: number) {
  return aX * bY - aY * bX
}

function perpendicularUnitVector(start: GeoPosition, end: GeoPosition, latitude: number) {
  const metersPerLon = metersPerDegreeLongitude(latitude)
  const dxM = (end[0] - start[0]) * metersPerLon
  const dyM = (end[1] - start[1]) * 110_540
  const length = Math.hypot(dxM, dyM)
  if (!Number.isFinite(length) || length <= 0) {
    return null
  }
  return { x: -dyM / length, y: dxM / length }
}

function pathNormalAtTrackpoint(path: GeoPosition[], trackpoint: DraftTrackpoint) {
  if (path.length < 2) {
    return null
  }
  const before = pointAtStationM(path, Math.max(0, trackpoint.stationM - 3))
  const after = pointAtStationM(path, Math.min(routeLengthM(path), trackpoint.stationM + 3))
  return perpendicularUnitVector(before, after, trackpoint.position[1])
}

function snapPositionToPath(position: [number, number], path: GeoPosition[], pathLengthM: number) {
  const snapped = nearestPointOnLine(lineString(path.map(lonLat)), point(position), { units: 'meters' })
  return {
    position: pointAtStationM(path, clampNumber(Number(snapped.properties?.location ?? 0), 0, pathLengthM)),
    stationM: clampNumber(Number(snapped.properties?.location ?? 0), 0, pathLengthM),
  }
}

function vectorMeters(from: GeoPosition, to: [number, number]) {
  return {
    x: (to[0] - from[0]) * metersPerDegreeLongitude(from[1]),
    y: (to[1] - from[1]) * 110_540,
  }
}

function rotateUnit(vector: { x: number; y: number }, angleDeg: number) {
  const angleRad = (angleDeg * Math.PI) / 180
  const cos = Math.cos(angleRad)
  const sin = Math.sin(angleRad)
  return {
    x: vector.x * cos - vector.y * sin,
    y: vector.x * sin + vector.y * cos,
  }
}

function signedAngleDeg(from: { x: number; y: number }, to: { x: number; y: number }) {
  return (Math.atan2(cross2d(from.x, from.y, to.x, to.y), from.x * to.x + from.y * to.y) * 180) / Math.PI
}

function offsetPosition(position: GeoPosition, dxM: number, dyM: number): [number, number] {
  return [position[0] + dxM / metersPerDegreeLongitude(position[1]), position[1] + dyM / 110_540]
}

function metersPerDegreeLongitude(latitude: number) {
  return Math.max(1, 111_320 * Math.cos((latitude * Math.PI) / 180))
}

function lineFeature(id: string, coordinates: GeoPosition[] | Array<[number, number]>, color: string, width: number, opacity: number) {
  return {
    type: 'Feature',
    id,
    properties: { color, width, opacity },
    geometry: { type: 'LineString', coordinates },
  } satisfies Feature<LineString, { color: string; width: number; opacity: number }>
}

function pointFeature(
  id: string,
  coordinates: GeoPosition,
  color: string,
  label: string,
  radius: number,
  role: MapPointProperties['role'],
  trackpointId: string,
) {
  return {
    type: 'Feature',
    id,
    properties: { color, label, radius, role, trackpointId },
    geometry: { type: 'Point', coordinates },
  } satisfies Feature<Point, MapPointProperties>
}

function copyPosition(position: GeoPosition): GeoPosition {
  return Number.isFinite(position[2]) ? [position[0], position[1], position[2] as number] : [position[0], position[1]]
}

function lonLat(position: GeoPosition): [number, number] {
  return [position[0], position[1]]
}

function mergeTrackLists(primary: TrackRecord[], secondary: TrackRecord[]) {
  const byId = new Map<string, TrackRecord>()
  primary.forEach((track) => byId.set(track.id, track))
  secondary.forEach((track) => byId.set(track.id, track))
  return Array.from(byId.values())
}

function dragHandleFromFeature(properties: unknown): DragHandle | null {
  if (!properties || typeof properties !== 'object') {
    return null
  }
  const value = properties as Partial<MapPointProperties>
  if (
    typeof value.trackpointId !== 'string' ||
    (value.role !== 'trackpoint' && value.role !== 'left' && value.role !== 'right')
  ) {
    return null
  }
  return { trackpointId: value.trackpointId, role: value.role }
}

function filterPositions(points: GeoPosition[]) {
  return points.filter((position) => Number.isFinite(position[0]) && Number.isFinite(position[1]))
}

function isSessionRecord(value: SessionRecord | undefined): value is SessionRecord {
  return Boolean(value)
}

function isReadyGpsPointSet(value: { session: SessionRecord; loaded: LoadedGpsState | undefined }): value is ActiveGpsPointSet {
  return value.loaded?.status === 'ready' && (value.loaded.pointSet?.path.length ?? 0) >= 2
}

function sessionRecordId(session: SessionRecord) {
  return sessionRefId(sessionToStudyRef(session))
}

function gpsLoadKey(sessionId: string, sourceId: string | null) {
  return `${sessionId}::${sourceId ?? 'preferred'}`
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) {
    return min
  }
  return Math.min(max, Math.max(min, value))
}

function formatDistance(valueM: number) {
  if (valueM >= 1000) {
    return `${(valueM / 1000).toFixed(2)} km`
  }
  return `${Math.round(valueM)} m`
}

function formatDuration(valueS: number) {
  if (valueS >= 60) {
    const minutes = Math.floor(valueS / 60)
    const seconds = valueS - minutes * 60
    return `${minutes}:${seconds.toFixed(1).padStart(4, '0')}`
  }
  return `${valueS.toFixed(2)} s`
}
