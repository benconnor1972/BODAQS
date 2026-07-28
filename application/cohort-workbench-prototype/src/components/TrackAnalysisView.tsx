import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { ChevronLeft, ChevronRight, Map as MapIcon, Play, Plus, RotateCcw, Save, Trash2, Video, X } from 'lucide-react'
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
  SessionVideoAttachmentRecord,
  SessionVideoAttachmentsRecord,
  StudySet,
  TrackMatchStatus,
  TrackRecord,
  TrackpointMatchMode,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryResult,
  TrackpointMatchQueryResults,
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
  times: LapTimingCell[]
}

type LapTimingCell = {
  sessionId: string
  valueS: number | null
  status: 'ready' | 'missing' | 'reverse'
}

type LapTimingDisplayMode = 'segment' | 'cumulative'

type AltitudeSample = {
  distanceM: number
  elevationM: number
}

type PlaybackPosition = {
  position: GeoPosition
  stationM: number
  timeS: number
}

type VideoPanelState =
  | { status: 'idle'; message: string; data: SessionVideoAttachmentsRecord | null }
  | { status: 'loading'; message: string; data: SessionVideoAttachmentsRecord | null }
  | { status: 'ready'; message: string; data: SessionVideoAttachmentsRecord }
  | { status: 'error'; message: string; data: SessionVideoAttachmentsRecord | null }

type TrackSessionMatchCacheEntry = {
  trackWorkingId: string
  trackId: string
  sessionRefId: string
  status: TrackMatchStatus
  crossedCount: number
  trackpointCount: number
}

type VideoTargetTrackOption = {
  value: string
  label: string
  description: string
}

type LonLatBounds = {
  minLongitude: number
  minLatitude: number
  maxLongitude: number
  maxLatitude: number
}

type PersistedTrackAnalysisViewContext = {
  addedSessionIds: string[]
  removedSessionIds: string[]
  addedTrackIds: string[]
  videoPanelOpen: boolean
  videoPanelWidthPx: number
}

type MapPointProperties = {
  color: string
  label: string
  radius: number
  role: DragHandleRole | 'segment' | 'videoHead'
  trackpointId: string
}

const SESSION_COLORS = ['#008c95', '#101820', '#3f6b7a', '#b66a2c', '#68737a', '#0f766e']
const TRACK_COLOR = '#b66a2c'
const DRAFT_COLOR = '#008c95'
const CUTLINE_LENGTH_M = 20
const TRACK_ANALYSIS_VIEW_CONTEXT_STORAGE_PREFIX = 'bodaqs.track-analysis.view-context.v1:'
const TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX = 360
const TRACK_ANALYSIS_VIDEO_PANEL_MAX_WIDTH_PX = 680
const VIDEO_TARGET_SCRATCH = 'scratch'

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
  const viewContextStorageKey = useMemo(() => trackAnalysisViewContextStorageKey(studySet), [studySet])
  const initialViewContext = useMemo(
    () => readTrackAnalysisViewContext(viewContextStorageKey),
    [viewContextStorageKey],
  )
  const scopedSessions = useMemo(
    () => studySet.sessions.map((ref) => sessionByRef(ref, sessions)).filter(isSessionRecord),
    [sessions, studySet.sessions],
  )
  const scopedSessionIds = useMemo(
    () => scopedSessions.map((session) => sessionRecordId(session)),
    [scopedSessions],
  )
  const scopedSessionIdSet = useMemo(() => new Set(scopedSessionIds), [scopedSessionIds])
  const [addedSessionIds, setAddedSessionIds] = useState<Set<string>>(
    () => new Set(initialViewContext.addedSessionIds),
  )
  const [removedSessionIds, setRemovedSessionIds] = useState<Set<string>>(
    () => new Set(initialViewContext.removedSessionIds),
  )
  const visibleScopedSessions = useMemo(
    () => scopedSessions.filter((session) => !removedSessionIds.has(sessionRecordId(session))),
    [removedSessionIds, scopedSessions],
  )
  const addedSessions = useMemo(
    () =>
      sessions.filter((session) => {
        const id = sessionRecordId(session)
        return addedSessionIds.has(id) && !scopedSessionIdSet.has(id) && !removedSessionIds.has(id)
      }),
    [addedSessionIds, removedSessionIds, scopedSessionIdSet, sessions],
  )
  const viewSessions = useMemo(
    () => mergeSessionLists(visibleScopedSessions, addedSessions),
    [addedSessions, visibleScopedSessions],
  )
  const viewSessionIds = useMemo(
    () => viewSessions.map((session) => sessionRecordId(session)),
    [viewSessions],
  )
  const savedScopedTracks = useMemo(
    () => tracks.filter((track) => studySet.trackIds.includes(track.id)),
    [studySet.trackIds, tracks],
  )
  const savedScopedTrackIdSet = useMemo(() => new Set(savedScopedTracks.map((track) => track.id)), [savedScopedTracks])
  const [localAddedTrackIds, setLocalAddedTrackIds] = useState<Set<string>>(
    () => new Set(initialViewContext.addedTrackIds),
  )
  const locallyAddedTracks = useMemo(
    () => tracks.filter((track) => localAddedTrackIds.has(track.id) && !savedScopedTrackIdSet.has(track.id)),
    [localAddedTrackIds, savedScopedTrackIdSet, tracks],
  )
  const [localTracks, setLocalTracks] = useState<TrackRecord[]>([])
  const scopedTracks = useMemo(
    () => mergeTrackLists(mergeTrackLists(savedScopedTracks, locallyAddedTracks), localTracks),
    [localTracks, locallyAddedTracks, savedScopedTracks],
  )
  const [workingTracks, setWorkingTracks] = useState<WorkingTrack[]>(() =>
    scopedTracks.map((track) => workingTrackFromRecord(track)),
  )
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [activeSessionIds, setActiveSessionIds] = useState<Set<string>>(
    () => new Set(scopedSessionIds),
  )
  const previousViewSessionIdsRef = useRef<Set<string>>(new Set(viewSessionIds))
  const [gpsSourceBySessionId, setGpsSourceBySessionId] = useState<Record<string, string>>({})
  const [loadedGps, setLoadedGps] = useState<Record<string, LoadedGpsState>>({})
  const loadedGpsRef = useRef<Record<string, LoadedGpsState>>({})
  const [selectedWorkingTrackId, setSelectedWorkingTrackId] = useState(() => workingTracks[0]?.workingId ?? '')
  const [activeTrackIds, setActiveTrackIds] = useState<Set<string>>(() => new Set(workingTracks.map((track) => track.workingId)))
  const previousWorkingTrackIdsRef = useRef<Set<string>>(new Set(workingTracks.map((track) => track.workingId)))
  const [showSegments, setShowSegments] = useState(false)
  const [automaticEndpoints, setAutomaticEndpoints] = useState(false)
  const [trimTracksOnSave, setTrimTracksOnSave] = useState(false)
  const [lapTimingExpanded, setLapTimingExpanded] = useState(false)
  const [lapTimingDisplayMode, setLapTimingDisplayMode] = useState<LapTimingDisplayMode>('segment')
  const [findSessionsOpen, setFindSessionsOpen] = useState(false)
  const [findTracksOpen, setFindTracksOpen] = useState(false)
  const [mapViewportBounds, setMapViewportBounds] = useState<LonLatBounds | null>(null)
  const [videoPanelOpen, setVideoPanelOpen] = useState(initialViewContext.videoPanelOpen)
  const [videoPanelWidthPx, setVideoPanelWidthPx] = useState(initialViewContext.videoPanelWidthPx)
  const [referenceVideoSessionId, setReferenceVideoSessionId] = useState('')
  const [videoTargetTrackId, setVideoTargetTrackId] = useState(VIDEO_TARGET_SCRATCH)
  const [trackSessionMatchCache, setTrackSessionMatchCache] = useState<Record<string, TrackSessionMatchCacheEntry>>({})
  const [videoState, setVideoState] = useState<VideoPanelState>({
    status: 'idle',
    message: dataSource.loadSessionVideoAttachments ? 'Select a video reference session.' : 'Video attachments are not available from this data source.',
    data: null,
  })
  const [activeVideoId, setActiveVideoId] = useState('')
  const [videoPlaybackTimeS, setVideoPlaybackTimeS] = useState(0)
  const videoElementRef = useRef<HTMLVideoElement | null>(null)
  const trackAnalysisStyle = {
    '--track-analysis-video-width': `${videoPanelWidthPx}px`,
  } as CSSProperties

  useEffect(() => {
    loadedGpsRef.current = loadedGps
  }, [loadedGps])

  useEffect(() => {
    const restored = readTrackAnalysisViewContext(viewContextStorageKey)
    setAddedSessionIds(new Set(restored.addedSessionIds))
    setRemovedSessionIds(new Set(restored.removedSessionIds))
    setLocalAddedTrackIds(new Set(restored.addedTrackIds))
    setVideoPanelOpen(restored.videoPanelOpen)
    setVideoPanelWidthPx(restored.videoPanelWidthPx)
  }, [viewContextStorageKey])

  useEffect(() => {
    writeTrackAnalysisViewContext(viewContextStorageKey, {
      addedSessionIds: Array.from(addedSessionIds),
      removedSessionIds: Array.from(removedSessionIds),
      addedTrackIds: Array.from(localAddedTrackIds),
      videoPanelOpen,
      videoPanelWidthPx,
    })
  }, [addedSessionIds, localAddedTrackIds, removedSessionIds, videoPanelOpen, videoPanelWidthPx, viewContextStorageKey])

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
    const viewIds = new Set(viewSessionIds)
    const previousViewIds = previousViewSessionIdsRef.current
    setActiveSessionIds((current) => {
      const next = new Set<string>()
      viewSessionIds.forEach((id) => {
        if (current.has(id) || !previousViewIds.has(id)) {
          next.add(id)
        }
      })
      return next
    })
    previousViewSessionIdsRef.current = viewIds
  }, [viewSessionIds])

  useEffect(() => {
    setGpsSourceBySessionId((current) => {
      const next = { ...current }
      viewSessions.forEach((session) => {
        const id = sessionRecordId(session)
        if (!next[id] && session.gpsSummary.preferredSourceId) {
          next[id] = session.gpsSummary.preferredSourceId
        }
      })
      return next
    })
  }, [viewSessions])

  useEffect(() => {
    setSelectedWorkingTrackId((current) => {
      if (current && workingTracks.some((track) => track.workingId === current)) {
        return current
      }
      return workingTracks[0]?.workingId ?? ''
    })
  }, [workingTracks])

  useEffect(() => {
    const previousWorkingTrackIds = previousWorkingTrackIdsRef.current
    setActiveTrackIds((current) => {
      const workingIds = new Set(workingTracks.map((track) => track.workingId))
      const next = new Set<string>()
      workingTracks.forEach((track) => {
        if (current.has(track.workingId) || !previousWorkingTrackIds.has(track.workingId)) {
          next.add(track.workingId)
        }
      })
      current.forEach((id) => {
        if (workingIds.has(id)) {
          next.add(id)
        }
      })
      return next
    })
    previousWorkingTrackIdsRef.current = new Set(workingTracks.map((track) => track.workingId))
  }, [workingTracks])

  const activeSessions = useMemo(
    () => viewSessions.filter((session) => activeSessionIds.has(sessionRecordId(session))),
    [activeSessionIds, viewSessions],
  )
  const activeVideoSessions = useMemo(
    () => activeSessions.filter((session) => session.videoSummary.present),
    [activeSessions],
  )
  const effectivePersistedTrackIds = useMemo(
    () => uniqueStrings(workingTracks.map((track) => track.persistedId).filter((id): id is string => Boolean(id))).sort(),
    [workingTracks],
  )
  const effectiveTrackMatchKey = useMemo(
    () =>
      [
        ...viewSessionIds.slice().sort(),
        ...effectivePersistedTrackIds.map((id) => `track:${id}`),
      ].join('|'),
    [effectivePersistedTrackIds, viewSessionIds],
  )

  useEffect(() => {
    if (!activeVideoSessions.length) {
      setReferenceVideoSessionId('')
      return
    }
    if (!activeVideoSessions.some((session) => sessionRecordId(session) === referenceVideoSessionId)) {
      setReferenceVideoSessionId(sessionRecordId(activeVideoSessions[0]))
    }
  }, [activeVideoSessions, referenceVideoSessionId])

  const referenceVideoSession = useMemo(
    () => activeVideoSessions.find((session) => sessionRecordId(session) === referenceVideoSessionId) ?? null,
    [activeVideoSessions, referenceVideoSessionId],
  )

  useEffect(() => {
    if (!dataSource.listTrackMatches || !viewSessions.length || !effectivePersistedTrackIds.length) {
      return
    }
    let cancelled = false
    const effectiveStudySet: StudySet = {
      id: null,
      displayName: `${studySet.displayName || 'Track analysis'} effective scope`,
      revision: 0,
      saved: false,
      sessions: viewSessions.map(sessionToStudyRef),
      groupings: [],
      trackIds: effectivePersistedTrackIds,
      provenance: 'track_analysis_view_context',
    }
    async function loadEffectiveTrackMatches() {
      try {
        const matches = await dataSource.listTrackMatches?.(effectiveStudySet)
        if (cancelled || !matches) {
          return
        }
        const matchesByTrack = new Map<string, typeof matches>()
        matches.forEach((match) => {
          const trackMatches = matchesByTrack.get(match.trackId) ?? []
          trackMatches.push(match)
          matchesByTrack.set(match.trackId, trackMatches)
        })
        setWorkingTracks((current) =>
          current.map((track) => {
            if (!track.persistedId) {
              return track
            }
            const matchSummaries = matchesByTrack.get(track.persistedId) ?? []
            return {
              ...track,
              matchSummaries: matchSummaries.map(copyTrackMatchSummary),
            }
          }),
        )
      } catch {
        // Match hydration is an affordance for restored local tracks; failure should not block the view.
      }
    }
    void loadEffectiveTrackMatches()
    return () => {
      cancelled = true
    }
  }, [dataSource, effectiveTrackMatchKey, studySet.displayName, viewSessions])

  useEffect(() => {
    const sessionIdSet = new Set(viewSessionIds)
    const workingTrackIdSet = new Set(workingTracks.map((track) => track.workingId))
    const nextFromSummaries: Record<string, TrackSessionMatchCacheEntry> = {}
    workingTracks.forEach((track) => {
      const persistedId = track.persistedId
      if (!persistedId) {
        return
      }
      track.matchSummaries.forEach((match) => {
        if (!sessionIdSet.has(match.sessionRefId)) {
          return
        }
        const crossedCount = match.trackpointResults.filter((result) => result.crossed).length
        nextFromSummaries[trackSessionMatchKey(track.workingId, match.sessionRefId)] = {
          trackWorkingId: track.workingId,
          trackId: persistedId,
          sessionRefId: match.sessionRefId,
          status: match.status,
          crossedCount,
          trackpointCount: match.trackpointResults.length,
        }
      })
    })
    setTrackSessionMatchCache((current) => {
      const next = { ...nextFromSummaries }
      Object.values(current).forEach((entry) => {
        const key = trackSessionMatchKey(entry.trackWorkingId, entry.sessionRefId)
        if (next[key] || !sessionIdSet.has(entry.sessionRefId) || !workingTrackIdSet.has(entry.trackWorkingId)) {
          return
        }
        next[key] = entry
      })
      return next
    })
  }, [viewSessionIds, workingTracks])

  const videoTargetTrackOptions = useMemo<VideoTargetTrackOption[]>(() => {
    const options: VideoTargetTrackOption[] = [
      {
        value: VIDEO_TARGET_SCRATCH,
        label: 'Scratch track',
        description: 'Create or extend a local scratch track from the video reference session.',
      },
    ]
    if (!referenceVideoSession) {
      return options
    }
    const referenceId = sessionRecordId(referenceVideoSession)
    workingTracks.forEach((track) => {
      if (!track.persistedId) {
        return
      }
      const entry = trackSessionMatchCache[trackSessionMatchKey(track.workingId, referenceId)]
      if (!entry || entry.crossedCount <= 0 || !isUsableTrackMatchStatus(entry.status)) {
        return
      }
      options.push({
        value: track.workingId,
        label: track.name || track.persistedId,
        description: `${entry.crossedCount}/${entry.trackpointCount || '?'} point(s) matched to the video session.`,
      })
    })
    return options
  }, [referenceVideoSession, trackSessionMatchCache, workingTracks])

  useEffect(() => {
    if (!videoTargetTrackOptions.some((option) => option.value === videoTargetTrackId)) {
      setVideoTargetTrackId(VIDEO_TARGET_SCRATCH)
    }
  }, [videoTargetTrackId, videoTargetTrackOptions])

  useEffect(() => {
    let cancelled = false
    if (!videoPanelOpen || !referenceVideoSession || !dataSource.loadSessionVideoAttachments) {
      setVideoState({
        status: 'idle',
        message: dataSource.loadSessionVideoAttachments
          ? videoPanelOpen
            ? 'Select a video reference session.'
            : 'Open the video reference panel to load session video.'
          : 'Video attachments are not available from this data source.',
        data: null,
      })
      setActiveVideoId('')
      return
    }
    setVideoState({ status: 'loading', message: 'Loading session video attachments...', data: null })
    setActiveVideoId('')
    setVideoPlaybackTimeS(0)
    dataSource
      .loadSessionVideoAttachments(referenceVideoSession)
      .then((record) => {
        if (cancelled) {
          return
        }
        setVideoState({ status: 'ready', message: '', data: record })
        const firstEnabled = record.attachments.find((attachment) => attachment.enabled) ?? record.attachments[0] ?? null
        setActiveVideoId(firstEnabled?.attachmentId ?? '')
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        setVideoState({
          status: 'error',
          message: error instanceof Error ? error.message : 'Could not load video attachments.',
          data: null,
        })
      })
    return () => {
      cancelled = true
    }
  }, [dataSource, referenceVideoSession, videoPanelOpen])

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
  const selectedTrackVisible = Boolean(selectedTrack && activeTrackIds.has(selectedTrack.workingId))
  const timingTrack = selectedTrackVisible ? selectedTrack : null
  const draftTrackpoints = selectedTrack?.trackpoints ?? []
  const timingTrackpoints = timingTrack?.trackpoints ?? []
  const orderedDraftTrackpoints = useMemo(
    () => [...draftTrackpoints].sort((a, b) => a.stationM - b.stationM),
    [draftTrackpoints],
  )
  const validSegmentAliases = useMemo(
    () => (timingTrack ? validSegmentAliasesForTrack(timingTrack) : []),
    [timingTrack],
  )
  const visibleTracks = useMemo(
    () => workingTracks.filter((track) => activeTrackIds.has(track.workingId)),
    [activeTrackIds, workingTracks],
  )
  const activePointSets: ActiveGpsPointSet[] = activeSessions
    .map((session) => {
      const id = sessionRecordId(session)
      const sourceId = gpsSourceBySessionId[id] || session.gpsSummary.preferredSourceId || null
      return { session, loaded: loadedGps[gpsLoadKey(id, sourceId)] }
    })
    .filter(isReadyGpsPointSet)
  const referenceVideoPointSet =
    referenceVideoSession
      ? activePointSets.find((item) => sessionRecordId(item.session) === sessionRecordId(referenceVideoSession))?.loaded.pointSet ?? null
      : null
  const videoAttachments = videoStateData(videoState)?.attachments ?? []
  const activeVideo =
    videoAttachments.find((attachment) => attachment.attachmentId === activeVideoId) ??
    videoAttachments.find((attachment) => attachment.enabled) ??
    videoAttachments[0] ??
    null
  const activeVideoStreamUrl =
    referenceVideoSession && activeVideo && dataSource.sessionVideoStreamUrl
      ? dataSource.sessionVideoStreamUrl(referenceVideoSession, activeVideo.attachmentId)
      : ''

  useEffect(() => {
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.repeat || !isSpaceKey(event) || isEditableKeyboardTarget(event.target)) {
        return
      }
      const video = videoElementRef.current
      if (!activeVideo || !video) {
        return
      }
      event.preventDefault()
      if (video.paused || video.ended) {
        void video.play()
      } else {
        video.pause()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [activeVideo])

  const videoSessionTimeS =
    activeVideo && Number.isFinite(activeVideo.sessionTimeAtVideoZeroS)
      ? activeVideo.sessionTimeAtVideoZeroS + videoPlaybackTimeS
      : null
  const videoPlaybackPosition = useMemo(
    () =>
      videoSessionTimeS !== null && referenceVideoPointSet
        ? playbackPositionForSessionTime(referenceVideoPointSet, videoSessionTimeS)
        : null,
    [referenceVideoPointSet, videoSessionTimeS],
  )
  const canPlayFocusedTrackFromVideo = useMemo(
    () => canUseReferenceVideoForTrack(selectedTrack, referenceVideoSession, trackSessionMatchCache),
    [referenceVideoSession, selectedTrack, trackSessionMatchCache],
  )
  const sessionPaths = activePointSets.map<SessionPath>((item) => ({
    id: sessionRecordId(item.session),
    label: item.session.name,
    path: item.loaded.pointSet.path,
    session: item.session,
  }))
  const referencePath = timingTrack?.points.length ? timingTrack.points : sessionPaths[0]?.path ?? []
  const lapTimingRows = useMemo(
    () => buildLapTimingRows(activePointSets, referencePath, timingTrackpoints, validSegmentAliases),
    [activePointSets, timingTrackpoints, referencePath, validSegmentAliases],
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
  const videoAltitudeStationM = useMemo(() => {
    if (!videoPlaybackPosition) {
      return null
    }
    if (trackAltitudeSamples.length >= 2 && selectedTrack?.points.length) {
      return snapPositionToPath(lonLat(videoPlaybackPosition.position), selectedTrack.points, routeLengthM(selectedTrack.points)).stationM
    }
    return videoPlaybackPosition.stationM
  }, [selectedTrack, trackAltitudeSamples.length, videoPlaybackPosition])
  const altitudeMeta =
    trackAltitudeSamples.length >= 2
      ? `${selectedTrack?.name ?? 'Track'} track altitude`
      : activePointSets[0]
        ? `${activePointSets[0].session.name} session altitude`
        : 'No altitude'
  const mapStatus = activePointSets.length
    ? `${activePointSets.length} session path(s) / ${visibleTracks.length} visible track(s) / ${timingTrackpoints.length} focused point(s)`
    : 'No active GPS paths loaded'
  const dirtyTrackCount = workingTracks.filter((track) => track.dirty).length

  function addTrackpointAtVideoHead() {
    if (!videoPlaybackPosition) {
      return
    }
    const videoHeadPosition = lonLat(videoPlaybackPosition.position)
    if (videoTargetTrackId !== VIDEO_TARGET_SCRATCH) {
      const targetTrack = workingTracks.find((track) => track.workingId === videoTargetTrackId) ?? null
      if (!targetTrack) {
        return
      }
      setSelectedWorkingTrackId(targetTrack.workingId)
      setActiveTrackIds((current) => {
        const next = new Set(current)
        next.add(targetTrack.workingId)
        return next
      })
      addPositionToWorkingTrack(targetTrack, videoHeadPosition)
      return
    }
    if (selectedTrack?.origin === 'scratch') {
      setActiveTrackIds((current) => {
        const next = new Set(current)
        next.add(selectedTrack.workingId)
        return next
      })
      addPositionToWorkingTrack(selectedTrack, videoHeadPosition)
      return
    }
    if (referenceVideoSession && referenceVideoPointSet?.path.length) {
      const sessionPath: SessionPath = {
        id: sessionRecordId(referenceVideoSession),
        label: referenceVideoSession.name,
        path: referenceVideoPointSet.path,
        session: referenceVideoSession,
      }
      const scratchTrack = scratchTrackFromSessionPath(
        sessionPath,
        { position: videoPlaybackPosition.position, stationM: videoPlaybackPosition.stationM },
        workingTracks,
        studySet,
        automaticEndpoints,
      )
      setWorkingTracks((current) => [...current, scratchTrack])
      setSelectedWorkingTrackId(scratchTrack.workingId)
      setActiveTrackIds((current) => {
        const next = new Set(current)
        next.add(scratchTrack.workingId)
        return next
      })
      return
    }
    addDraftTrackpoint(videoHeadPosition)
  }

  function addPositionToWorkingTrack(targetTrack: WorkingTrack, position: [number, number]) {
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
  }

  function playVideoFromTrackpoint(trackpoint: DraftTrackpoint) {
    if (!activeVideo || !referenceVideoPointSet || !videoElementRef.current || !canPlayFocusedTrackFromVideo) {
      return
    }
    const sessionTimeS = sessionTimeForPosition(referenceVideoPointSet, trackpoint.position)
    if (sessionTimeS === null) {
      return
    }
    const videoTimeS = Math.max(0, sessionTimeS - activeVideo.sessionTimeAtVideoZeroS)
    const duration = videoElementRef.current.duration
    videoElementRef.current.currentTime = Number.isFinite(duration)
      ? clampNumber(videoTimeS, 0, Math.max(0, duration - 0.05))
      : videoTimeS
    void videoElementRef.current.play()
  }

  function beginVideoPanelResize(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    const startClientX = event.clientX
    const startWidthPx = videoPanelWidthPx
    const onMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidthPx + (startClientX - moveEvent.clientX)
      setVideoPanelWidthPx(clampNumber(nextWidth, TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX, TRACK_ANALYSIS_VIDEO_PANEL_MAX_WIDTH_PX))
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  function addSessionsToView(sessionsToAdd: SessionRecord[]) {
    if (!sessionsToAdd.length) {
      return
    }
    const ids = sessionsToAdd.map((session) => sessionRecordId(session))
    setAddedSessionIds((current) => {
      const next = new Set(current)
      ids.forEach((id) => next.add(id))
      return next
    })
    setRemovedSessionIds((current) => {
      const next = new Set(current)
      ids.forEach((id) => next.delete(id))
      return next
    })
    setActiveSessionIds((current) => {
      const next = new Set(current)
      ids.forEach((id) => next.add(id))
      return next
    })
  }

  function warmTrackSessionMatchCache(track: TrackRecord, queryResults: TrackpointMatchQueryResult[]) {
    const workingTrack = workingTracks.find((candidate) => candidate.persistedId === track.id)
    if (!workingTrack || !queryResults.length) {
      return
    }
    setTrackSessionMatchCache((current) => {
      const next = { ...current }
      queryResults.forEach((result) => {
        const sessionId = sessionRefId(result.sessionRef)
        const crossedCount = result.matchedTrackpointIds.length
        const trackpointCount = crossedCount + result.missingTrackpointIds.length
        if (crossedCount <= 0) {
          return
        }
        next[trackSessionMatchKey(workingTrack.workingId, sessionId)] = {
          trackWorkingId: workingTrack.workingId,
          trackId: track.id,
          sessionRefId: sessionId,
          status: result.missingTrackpointIds.length ? 'partial' : 'matched',
          crossedCount,
          trackpointCount,
        }
      })
      return next
    })
  }

  function addTracksToView(tracksToAdd: TrackRecord[]) {
    if (!tracksToAdd.length) {
      return
    }
    setLocalAddedTrackIds((current) => {
      const next = new Set(current)
      tracksToAdd.forEach((track) => next.add(track.id))
      return next
    })
    setSelectedWorkingTrackId((current) => current || (tracksToAdd[0] ? `saved:${tracksToAdd[0].id}` : ''))
    setActiveTrackIds((current) => {
      const next = new Set(current)
      tracksToAdd.forEach((track) => next.add(`saved:${track.id}`))
      return next
    })
  }

  function removeLocalTrackFromView(trackId: string) {
    const workingTrack = workingTracks.find((track) => track.persistedId === trackId)
    if (workingTrack?.dirty && !window.confirm(`Remove "${workingTrack.name}" from this view and discard unsaved edits?`)) {
      return
    }
    setLocalAddedTrackIds((current) => {
      const next = new Set(current)
      next.delete(trackId)
      return next
    })
    setLocalTracks((current) => current.filter((track) => track.id !== trackId))
    if (workingTrack) {
      setActiveTrackIds((current) => {
        const next = new Set(current)
        next.delete(workingTrack.workingId)
        return next
      })
    }
    setSelectedWorkingTrackId((current) => {
      if (workingTrack?.workingId !== current) {
        return current
      }
      return workingTracks.find((track) => track.workingId !== current)?.workingId ?? ''
    })
  }

  function removeSessionFromView(session: SessionRecord) {
    const id = sessionRecordId(session)
    setAddedSessionIds((current) => {
      const next = new Set(current)
      next.delete(id)
      return next
    })
    setRemovedSessionIds((current) => {
      const next = new Set(current)
      if (scopedSessionIdSet.has(id)) {
        next.add(id)
      } else {
        next.delete(id)
      }
      return next
    })
    setActiveSessionIds((current) => {
      const next = new Set(current)
      next.delete(id)
      return next
    })
  }

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

  function toggleTrackVisibility(workingId: string) {
    setActiveTrackIds((current) => {
      const next = new Set(current)
      if (next.has(workingId)) {
        next.delete(workingId)
      } else {
        next.add(workingId)
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
    const targetTrack = selectedTrackVisible ? selectedTrack : null
    if (!targetTrack) {
      const scratchTrack = scratchTrackFromNearestPath(position, sessionPaths, workingTracks, studySet, automaticEndpoints)
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
  }, [automaticEndpoints, selectedTrack, selectedTrackVisible, sessionPaths, studySet, workingTracks])

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
      segmentAliases: upsertSegmentAlias(track.segmentAliases, fromTrackpointId, toTrackpointId, { name }),
    }))
  }

  function setSegmentUntimed(fromTrackpointId: string, toTrackpointId: string, untimed: boolean, fallbackName: string) {
    if (!selectedTrack) {
      return
    }
    updateWorkingTrack(selectedTrack.workingId, (track) => ({
      ...track,
      segmentAliases: upsertSegmentAlias(track.segmentAliases, fromTrackpointId, toTrackpointId, {
        name: fallbackName,
        timingRole: untimed ? 'untimed' : 'timed',
      }),
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
    setActiveTrackIds((current) => {
      const next = new Set(current)
      next.delete(workingId)
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
      const preparedTrack = trimTracksOnSave ? trimWorkingTrackToTrackpoints(trackToSave) : trackToSave
      const generatedTrackpointIds: string[] = []
      const sortedTrackpoints = [...preparedTrack.trackpoints]
        .map((trackpoint, index) => {
          const name = trackpoint.name.trim() || `Point ${index + 1}`
          const existingIds = [...preparedTrack.trackpoints.map((item) => item.id), ...generatedTrackpointIds]
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
        description: preparedTrack.description || 'Track created from Track Analysis and Lap Timing.',
        revision: preparedTrack.revision,
        pointCount: preparedTrack.points.length,
        distanceKm: preparedTrack.lengthM / 1000,
        lengthM: preparedTrack.lengthM,
        points: preparedTrack.points.map((position) => copyPosition(position)),
        defaultPolicyId: preparedTrack.defaultPolicyId || 'default-geospatial-policy',
        trackpoints: sortedTrackpoints,
        segmentAliases: validSegmentAliasesForTrack(preparedTrack),
        matchSummaries: preparedTrack.matchSummaries,
        source: preparedTrack.source,
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

  function canPersistWorkingTrack(track: WorkingTrack) {
    return Boolean(canWrite && dataSource.saveTrack && track.dirty && track.points.length >= 2 && track.name.trim())
  }

  function discardWorkingTrack(workingId: string) {
    const trackToDiscard = workingTracks.find((track) => track.workingId === workingId)
    if (!trackToDiscard) {
      return
    }
    const label = trackToDiscard.persistedId
      ? `Discard unsaved edits to "${trackToDiscard.name}"?`
      : `Discard scratch track "${trackToDiscard.name}"?`
    if (!window.confirm(label)) {
      return
    }
    if (!trackToDiscard.persistedId) {
      removeWorkingTrack(workingId)
      return
    }
    const saved = scopedTracks.find((track) => track.id === trackToDiscard.persistedId)
    if (!saved) {
      setTrackStatus(workingId, 'Could not find the saved track to restore.')
      return
    }
    setWorkingTracks((current) =>
      current.map((track) =>
        track.workingId === workingId
          ? { ...workingTrackFromRecord(saved, track), workingId: track.workingId, status: 'Discarded unsaved changes.' }
          : track,
      ),
    )
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
                meta={`${activeSessionIds.size} active / ${viewSessions.length} in view${addedSessions.length ? ` / ${addedSessions.length} added` : ''}`}
                info="Groups in the launch scope are accepted but ignored in this first track-analysis slice."
                action={
                  <button
                    type="button"
                    className="track-analysis-panel-toggle"
                    onClick={() => setFindSessionsOpen(true)}
                    title="Find sessions to add to this analysis view"
                  >
                    <Plus size={14} />
                  </button>
                }
              />
              <div className="track-analysis-session-list">
                {viewSessions.map((session) => {
                  const id = sessionRecordId(session)
                  const gpsQuality = session.gpsSummary.quality
                  const sources = session.gpsSummary.sources ?? []
                  const addedOnly = addedSessionIds.has(id) && !scopedSessionIdSet.has(id)
                  return (
                    <div key={id} className={`track-analysis-session-row ${addedOnly ? 'added' : 'scoped'}`}>
                      <input
                        aria-label={`Toggle ${session.name}`}
                        checked={activeSessionIds.has(id)}
                        type="checkbox"
                        onChange={() => toggleSession(session)}
                      />
                      <span>
                        <strong>
                          {session.name}
                          {session.videoSummary.present && (
                            <Video
                              aria-label={`${session.videoSummary.attachmentCount} video attachment${session.videoSummary.attachmentCount === 1 ? '' : 's'}`}
                              className="track-analysis-video-session-icon"
                              size={13}
                            />
                          )}
                        </strong>
                        <small>
                          {gpsQuality === 'usable' ? 'usable GPS' : `${gpsQuality || 'unknown'} GPS`}
                          {session.videoSummary.present ? ` - ${session.videoSummary.enabledCount} video enabled` : ''}
                          {addedOnly ? ' - added to view' : ''}
                        </small>
                      </span>
                      <button
                        type="button"
                        className="icon-only small"
                        onClick={() => removeSessionFromView(session)}
                        title="Remove from this analysis view"
                        aria-label={`Remove ${session.name} from this analysis view`}
                      >
                        <X size={13} />
                      </button>
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
                    </div>
                  )
                })}
              </div>
            </section>

            <section className="track-analysis-control-card">
              <TrackPanelTitle
                title="Tracks"
                meta={`${activeTrackIds.size} visible / ${workingTracks.length} in scope / ${dirtyTrackCount} unsaved`}
                info="Scratch tracks are temporary working copies created from session GPS. Save them to make root-scoped reusable tracks."
                action={
                  <button
                    type="button"
                    className="track-analysis-panel-toggle"
                    onClick={() => setFindTracksOpen(true)}
                    title="Find tracks to add to this analysis view"
                  >
                    <Plus size={14} />
                  </button>
                }
              />
              {workingTracks.length ? (
                <div className="track-analysis-track-list">
                  {workingTracks.map((track) => (
                    <div
                      key={track.workingId}
                      role="button"
                      tabIndex={0}
                      className={`track-analysis-track-row ${track.workingId === selectedWorkingTrackId ? 'selected' : ''} ${track.dirty ? 'dirty' : 'clean'}`}
                      onClick={() => setSelectedWorkingTrackId(track.workingId)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setSelectedWorkingTrackId(track.workingId)
                        }
                      }}
                    >
                      <input
                        aria-label={`Toggle ${track.name || 'Unnamed track'}`}
                        checked={activeTrackIds.has(track.workingId)}
                        type="checkbox"
                        onChange={(event) => {
                          event.stopPropagation()
                          toggleTrackVisibility(track.workingId)
                        }}
                        onClick={(event) => event.stopPropagation()}
                      />
                      <span>
                        <strong>{track.name || 'Unnamed track'}</strong>
                        <small>
                          {track.persistedId && localAddedTrackIds.has(track.persistedId) && !studySet.trackIds.includes(track.persistedId)
                            ? 'added track'
                            : track.persistedId
                              ? 'saved track'
                              : 'scratch track'} - {track.trackpoints.length} point(s)
                        </small>
                      </span>
                      {track.status && <small className="track-analysis-row-status">{track.status}</small>}
                      <div className="track-analysis-track-actions">
                        <em>{track.dirty ? 'unsaved' : 'saved'}</em>
                        {track.dirty && (
                          <>
                            <button
                              type="button"
                              className="icon-only small track-analysis-row-save"
                              disabled={!canPersistWorkingTrack(track) || track.saving}
                              onClick={(event) => {
                                event.stopPropagation()
                                void saveTrackEdits(track.workingId)
                              }}
                              aria-label={track.persistedId ? `Save ${track.name}` : `Create ${track.name}`}
                              title={track.persistedId ? 'Save track' : 'Create track'}
                            >
                              <Save size={13} />
                            </button>
                            <button
                              type="button"
                              className={`icon-only small ${track.persistedId ? '' : 'danger-icon'}`}
                              disabled={track.saving}
                              onClick={(event) => {
                                event.stopPropagation()
                                discardWorkingTrack(track.workingId)
                              }}
                              aria-label={`Discard ${track.name}`}
                              title={track.persistedId ? 'Discard changes' : 'Discard scratch track'}
                            >
                              {track.persistedId ? <RotateCcw size={13} /> : <Trash2 size={13} />}
                            </button>
                          </>
                        )}
                        {!track.dirty &&
                          track.persistedId &&
                          localAddedTrackIds.has(track.persistedId) &&
                          !studySet.trackIds.includes(track.persistedId) && (
                            <button
                              type="button"
                              className="icon-only small"
                              onClick={(event) => {
                                event.stopPropagation()
                                removeLocalTrackFromView(track.persistedId as string)
                              }}
                              aria-label={`Remove ${track.name} from view`}
                              title="Remove from view"
                            >
                              <X size={13} />
                            </button>
                          )}
                        {!track.dirty &&
                          track.persistedId &&
                          (!localAddedTrackIds.has(track.persistedId) || studySet.trackIds.includes(track.persistedId)) && (
                            <button
                              type="button"
                              className="icon-only small danger-icon"
                              disabled={track.deleting}
                              onClick={(event) => {
                                event.stopPropagation()
                                void deleteWorkingTrack(track.workingId)
                              }}
                              aria-label={`Delete ${track.name}`}
                              title="Delete saved track"
                            >
                              <Trash2 size={13} />
                            </button>
                          )}
                        {!track.dirty && !track.persistedId && (
                          <button
                            type="button"
                            className="icon-only small danger-icon"
                            onClick={(event) => {
                              event.stopPropagation()
                              discardWorkingTrack(track.workingId)
                            }}
                            aria-label={`Discard ${track.name}`}
                            title="Discard scratch track"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="track-analysis-muted">No tracks yet. Click near an active GPS path to start a scratch track.</p>
              )}
              <button className="secondary-action compact" type="button" onClick={() => setSelectedWorkingTrackId('')}>
                New scratch track on next map click
              </button>
            </section>

            <section className="track-analysis-control-card">
              <TrackPanelTitle
                title="Trackpoints"
                meta={selectedTrack ? `${draftTrackpoints.length} point(s)` : 'No focused track'}
                info="Edit the focused track's point names, segment labels, and save-time track-shaping options."
              />
              <div className="track-analysis-label-options">
                <label>
                  <input
                    checked={automaticEndpoints}
                    type="checkbox"
                    onChange={(event) => setAutomaticEndpoints(event.target.checked)}
                  />
                  <span>Automatic endpoints</span>
                </label>
                <label>
                  <input
                    checked={trimTracksOnSave}
                    type="checkbox"
                    onChange={(event) => setTrimTracksOnSave(event.target.checked)}
                  />
                  <span>Trim tracks on save</span>
                </label>
              </div>
              {selectedTrack && (
                <div className="track-analysis-trackpoint-name-row">
                  <label className="track-analysis-field">
                    <span>Track name</span>
                    <input value={selectedTrack.name} onChange={(event) => renameWorkingTrack(selectedTrack.workingId, event.target.value)} />
                  </label>
                  <label className="track-analysis-inline-toggle">
                    <input
                      checked={showSegments}
                      type="checkbox"
                      onChange={(event) => setShowSegments(event.target.checked)}
                    />
                    <span>Show segments</span>
                  </label>
                </div>
              )}
              <div className="track-analysis-draft-list">
                {selectedTrack && draftTrackpoints.length ? (
                  orderedDraftTrackpoints.flatMap((trackpoint, index) => {
                    const nextTrackpoint = orderedDraftTrackpoints[index + 1]
                    const segmentDefaultName = `Segment ${index + 1}`
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
                        <div className="track-analysis-draft-actions">
                          {activeVideo && referenceVideoPointSet && canPlayFocusedTrackFromVideo && (
                            <button
                              type="button"
                              className="icon-only small"
                              onClick={() => playVideoFromTrackpoint(trackpoint)}
                              title="Play video from this trackpoint"
                              aria-label={`Play video from ${trackpoint.name || trackpoint.id}`}
                            >
                              <Play size={13} />
                            </button>
                          )}
                          <button type="button" className="icon-only small" onClick={() => removeDraftTrackpoint(trackpoint.id)}>
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>,
                      nextTrackpoint && showSegments ? (
                        <div key={`${trackpoint.id}-${nextTrackpoint.id}-segment`} className="track-analysis-segment-row">
                          <span className="track-analysis-row-glyph track-analysis-segment-glyph" aria-hidden="true" />
                          <input
                            aria-label={`Segment name from ${trackpoint.name || trackpoint.id} to ${nextTrackpoint.name || nextTrackpoint.id}`}
                            placeholder="Optional segment name"
                            value={alias?.name ?? ''}
                            onChange={(event) => renameSegmentAlias(trackpoint.id, nextTrackpoint.id, event.target.value)}
                          />
                          <label className="track-analysis-segment-timing-toggle">
                            <input
                              checked={alias?.timingRole === 'untimed'}
                              type="checkbox"
                              onChange={(event) =>
                                setSegmentUntimed(trackpoint.id, nextTrackpoint.id, event.target.checked, alias?.name || segmentDefaultName)
                              }
                            />
                            <span>Untimed</span>
                          </label>
                        </div>
                      ) : null,
                    ].filter(Boolean)
                  })
                ) : selectedTrack ? (
                  <p className="track-analysis-muted">Click near this track path on the map to add a temporary trackpoint.</p>
                ) : (
                  <p className="track-analysis-muted">Select a track, or click near a GPS path to create a scratch track.</p>
                )}
              </div>
            </section>
          </div>
        )}
      </aside>

      <section className={`track-analysis-main ${videoPanelOpen ? 'video-open' : 'video-closed'}`} style={trackAnalysisStyle}>
        <div className="track-analysis-map-band">
          <section className="track-analysis-map-card">
            <TrackPanelTitle
              title="Track map"
              meta={mapStatus}
              info="Click near the reference path to place a temporary trackpoint. Drag a point to move it along the path, or drag cutline ends to rotate and resize the cutline."
            />
            <TrackAnalysisMap
              sessionPaths={sessionPaths}
              visibleTracks={visibleTracks}
              focusedTrackId={timingTrack?.workingId ?? ''}
              draftTrackpoints={timingTrackpoints}
              segmentAliases={validSegmentAliases}
              hideSegmentNames={!showSegments}
              videoMarkerPosition={videoPlaybackPosition?.position ?? null}
              onCreateTrackpoint={addDraftTrackpoint}
              onMoveTrackpoint={moveDraftTrackpoint}
              onAdjustCutline={adjustDraftCutline}
              onDeleteTrackpoint={removeDraftTrackpoint}
              onTrackpointDragEnd={sortSelectedTrackpointsByStation}
              onViewportBoundsChanged={setMapViewportBounds}
            />
          </section>
        {videoPanelOpen ? (
          <aside className="track-analysis-video-panel">
            <button
              aria-label="Resize video reference panel"
              className="track-analysis-video-resizer"
              type="button"
              onPointerDown={beginVideoPanelResize}
              title="Drag to resize video reference"
            />
            <TrackPanelTitle
              title="Video reference"
              meta={activeVideoSessions.length ? `${activeVideoSessions.length} session(s) with video` : 'No active video sessions'}
                action={
                  <button
                    type="button"
                    className="track-analysis-panel-toggle"
                    onClick={() => setVideoPanelOpen(false)}
                    title="Collapse video reference"
                  >
                    <ChevronRight size={14} />
                  </button>
                }
              />
              <TrackAnalysisVideoPanel
                activeVideo={activeVideo}
                attachments={videoAttachments}
                disabled={!dataSource.loadSessionVideoAttachments || !dataSource.sessionVideoStreamUrl}
                onActiveVideoIdChange={setActiveVideoId}
                onAddTrackpoint={addTrackpointAtVideoHead}
                onPlaybackTimeChange={setVideoPlaybackTimeS}
                onReferenceSessionIdChange={setReferenceVideoSessionId}
                onTargetTrackIdChange={setVideoTargetTrackId}
                playbackPosition={videoPlaybackPosition}
                referenceSession={referenceVideoSession}
                sessions={activeVideoSessions}
                focusedTrack={selectedTrack}
                state={videoState}
                streamUrl={activeVideoStreamUrl}
                targetTrackId={videoTargetTrackId}
                targetTrackOptions={videoTargetTrackOptions}
                videoRef={videoElementRef}
              />
            </aside>
          ) : (
            <button
              type="button"
              className="track-analysis-video-rail"
              onClick={() => setVideoPanelOpen(true)}
              title="Show video reference"
            >
              <ChevronLeft size={14} />
              <span>Video reference</span>
            </button>
          )}
        </div>

        <section className={`track-analysis-bottom ${lapTimingExpanded ? 'lap-expanded' : ''}`}>
          {!lapTimingExpanded && (
            <div className="track-analysis-lower-card">
              <TrackPanelTitle
                title="Altitude profile"
                meta={altitudeMeta}
                action={
                  <button
                    type="button"
                    className="track-analysis-panel-toggle"
                    onClick={() => setLapTimingExpanded(true)}
                    title="Collapse altitude profile"
                  >
                    <ChevronLeft size={14} />
                  </button>
                }
              />
              <AltitudeChart samples={altitudeSamples} trackpoints={timingTrackpoints} playbackStationM={videoAltitudeStationM} />
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
                <div className="track-analysis-lap-mode-toggle" role="group" aria-label="Lap timing display mode">
                  <button
                    type="button"
                    className={lapTimingDisplayMode === 'segment' ? 'active' : ''}
                    onClick={() => setLapTimingDisplayMode('segment')}
                  >
                    Segment
                  </button>
                  <button
                    type="button"
                    className={lapTimingDisplayMode === 'cumulative' ? 'active' : ''}
                    onClick={() => setLapTimingDisplayMode('cumulative')}
                  >
                    Cumulative
                  </button>
                </div>
              }
            />
            <LapTimingTable
              activePointSets={activePointSets}
              rows={lapTimingRows}
              trackpointCount={draftTrackpoints.length}
              displayMode={lapTimingDisplayMode}
            />
          </div>
        </section>
      </section>
      {findSessionsOpen && (
        <TrackAnalysisFindSessionsModal
          dataSource={dataSource}
          sessions={sessions}
          tracks={tracks}
          viewSessionIds={new Set(viewSessionIds)}
          initialTrackId={selectedTrack?.persistedId ?? savedScopedTracks[0]?.id ?? tracks[0]?.id ?? ''}
          onAddSessions={addSessionsToView}
          onAddSessionMatches={warmTrackSessionMatchCache}
          onClose={() => setFindSessionsOpen(false)}
        />
      )}
      {findTracksOpen && (
        <TrackAnalysisFindTracksModal
          tracks={tracks}
          viewTrackIds={new Set(scopedTracks.map((track) => track.id))}
          viewportBounds={mapViewportBounds}
          onAddTracks={addTracksToView}
          onClose={() => setFindTracksOpen(false)}
        />
      )}
    </div>
  )
}

function TrackAnalysisFindSessionsModal({
  dataSource,
  sessions,
  tracks,
  viewSessionIds,
  initialTrackId,
  onAddSessions,
  onAddSessionMatches,
  onClose,
}: {
  dataSource: LibraryDataSource
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  viewSessionIds: Set<string>
  initialTrackId: string
  onAddSessions: (sessions: SessionRecord[]) => void
  onAddSessionMatches: (track: TrackRecord, results: TrackpointMatchQueryResult[]) => void
  onClose: () => void
}) {
  const queryableTracks = useMemo(() => tracks.filter((track) => track.trackpoints.length > 0), [tracks])
  const initialQueryableTrackId = queryableTracks.some((track) => track.id === initialTrackId)
    ? initialTrackId
    : queryableTracks[0]?.id ?? ''
  const [trackId, setTrackId] = useState(initialQueryableTrackId)
  const selectedTrack = queryableTracks.find((track) => track.id === trackId) ?? null
  const [selectedTrackpointIds, setSelectedTrackpointIds] = useState<string[]>(
    () => selectedTrack?.trackpoints.map((trackpoint) => trackpoint.id) ?? [],
  )
  const [matchMode, setMatchMode] = useState<TrackpointMatchMode>('all')
  const [minCount, setMinCount] = useState(2)
  const [toleranceM, setToleranceM] = useState(10)
  const [query, setQuery] = useState<TrackpointMatchQueryRecord | null>(null)
  const [results, setResults] = useState<TrackpointMatchQueryResult[]>([])
  const [selectedResultIds, setSelectedResultIds] = useState<Set<string>>(() => new Set())
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    setSelectedTrackpointIds(selectedTrack?.trackpoints.map((trackpoint) => trackpoint.id) ?? [])
    setResults([])
    setSelectedResultIds(new Set())
    setQuery(null)
    setMessage('')
  }, [selectedTrack])

  const selectedTrackpointIdSet = useMemo(() => new Set(selectedTrackpointIds), [selectedTrackpointIds])
  const canRunQuery = Boolean(
    selectedTrack &&
      selectedTrackpointIds.length > 0 &&
      dataSource.createTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQueryResults,
  )
  const effectiveMinCount = Math.max(1, Math.min(minCount, selectedTrackpointIds.length || 1))

  async function runQuery() {
    const createQuery = dataSource.createTrackpointMatchQuery?.bind(dataSource)
    const loadQuery = dataSource.loadTrackpointMatchQuery?.bind(dataSource)
    const loadResults = dataSource.loadTrackpointMatchQueryResults?.bind(dataSource)
    if (!selectedTrack || !createQuery || !loadQuery || !loadResults || !canRunQuery) {
      setMessage('Select a track with at least one trackpoint. The current data source must support trackpoint queries.')
      return
    }
    setBusy(true)
    setResults([])
    setSelectedResultIds(new Set())
    setMessage(`Searching for sessions matching ${selectedTrack.name}...`)
    try {
      let currentQuery: TrackpointMatchQueryRecord = await createQuery({
        trackId: selectedTrack.id,
        trackpointIds: selectedTrackpointIds,
        matchMode,
        minCount: matchMode === 'min_count' ? effectiveMinCount : undefined,
        toleranceM,
        scope: {
          libraryIds: uniqueStrings(sessions.map((session) => session.libraryId)),
        },
        persist: true,
      })
      if (mountedRef.current) {
        setQuery(currentQuery)
      }
      while (isActiveTrackpointQuery(currentQuery)) {
        await delay(300)
        currentQuery = await loadQuery(currentQuery.queryId)
        if (mountedRef.current) {
          setQuery(currentQuery)
        }
      }
      if (currentQuery.status !== 'completed') {
        if (mountedRef.current) {
          setMessage(currentQuery.error || `Trackpoint query is ${currentQuery.status}.`)
        }
        return
      }
      const loadedResults = await loadAllTrackpointQueryResults(loadResults, currentQuery.queryId)
      const addableIds = loadedResults
        .map((result) => sessionRefId(result.sessionRef))
        .filter((id) => !viewSessionIds.has(id) && sessionByRefId(id, sessions))
      if (mountedRef.current) {
        setResults(loadedResults)
        setSelectedResultIds(new Set(addableIds))
        setMessage(`Found ${loadedResults.length} matching session(s). ${addableIds.length} can be added to this view.`)
      }
    } catch (error) {
      if (mountedRef.current) {
        setMessage(error instanceof Error ? error.message : 'Trackpoint query failed.')
      }
    } finally {
      if (mountedRef.current) {
        setBusy(false)
      }
    }
  }

  async function cancelQuery() {
    if (!query || !dataSource.cancelTrackpointMatchQuery || !isActiveTrackpointQuery(query)) {
      return
    }
    setBusy(true)
    try {
      const cancelled = await dataSource.cancelTrackpointMatchQuery(query.queryId)
      setQuery(cancelled)
      setMessage(`Trackpoint query ${cancelled.status}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not cancel trackpoint query.')
    } finally {
      setBusy(false)
    }
  }

  function toggleResult(result: TrackpointMatchQueryResult) {
    const id = sessionRefId(result.sessionRef)
    if (viewSessionIds.has(id) || !sessionByRefId(id, sessions)) {
      return
    }
    setSelectedResultIds((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function addSelectedResults() {
    const selectedSessions = Array.from(selectedResultIds)
      .map((id) => sessionByRefId(id, sessions))
      .filter(isSessionRecord)
    const selectedMatches = results.filter((result) => selectedResultIds.has(sessionRefId(result.sessionRef)))
    onAddSessions(selectedSessions)
    if (selectedTrack) {
      onAddSessionMatches(selectedTrack, selectedMatches)
    }
    onClose()
  }

  return (
    <div className="modal-backdrop">
      <div className="modal track-analysis-add-modal" role="dialog" aria-modal="true" aria-label="Find sessions for analysis view">
        <div className="modal-header">
          <div>
            <h2>Find sessions</h2>
            <p>Find sessions that fit a selected track. Added sessions only affect this analysis view.</p>
          </div>
          <button className="icon-only" type="button" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="track-analysis-add-grid track-analysis-add-grid-single">
          <section className="track-analysis-add-card">
            <h3>Trackpoint query</h3>
            {queryableTracks.length ? (
              <>
                <label className="track-analysis-field">
                  <span>Track</span>
                  <select value={trackId} onChange={(event) => setTrackId(event.target.value)}>
                    {queryableTracks.map((track) => (
                      <option key={track.id} value={track.id}>
                        {track.name} ({track.trackpoints.length} point{track.trackpoints.length === 1 ? '' : 's'})
                      </option>
                    ))}
                  </select>
                </label>
                <div className="track-analysis-add-trackpoints">
                  {selectedTrack?.trackpoints.map((trackpoint) => (
                    <label key={trackpoint.id}>
                      <input
                        checked={selectedTrackpointIdSet.has(trackpoint.id)}
                        type="checkbox"
                        onChange={(event) => {
                          setSelectedTrackpointIds((current) =>
                            event.target.checked
                              ? [...current, trackpoint.id]
                              : current.filter((id) => id !== trackpoint.id),
                          )
                        }}
                      />
                      <span>{trackpoint.name || trackpoint.id}</span>
                    </label>
                  ))}
                </div>
                <div className="track-analysis-add-controls">
                  <label className="track-analysis-field">
                    <span>Fit mode</span>
                    <select value={matchMode} onChange={(event) => setMatchMode(event.target.value as TrackpointMatchMode)}>
                      <option value="all">All selected points</option>
                      <option value="min_count">Minimum count</option>
                      <option value="any">Any selected point</option>
                    </select>
                  </label>
                  {matchMode === 'min_count' && (
                    <label className="track-analysis-field">
                      <span>Minimum</span>
                      <input
                        min={1}
                        max={Math.max(1, selectedTrackpointIds.length)}
                        type="number"
                        value={effectiveMinCount}
                        onChange={(event) => setMinCount(Number(event.target.value) || 1)}
                      />
                    </label>
                  )}
                  <label className="track-analysis-field">
                    <span>Tolerance (m)</span>
                    <input
                      min={1}
                      step={1}
                      type="number"
                      value={toleranceM}
                      onChange={(event) => setToleranceM(Math.max(1, Number(event.target.value) || 1))}
                    />
                  </label>
                </div>
                <div className="track-analysis-add-actions">
                  <button className="primary-action compact" type="button" disabled={!canRunQuery || busy} onClick={() => void runQuery()}>
                    {busy && isActiveTrackpointQuery(query) ? 'Searching...' : 'Find sessions'}
                  </button>
                  <button
                    className="secondary-action compact"
                    type="button"
                    disabled={!query || !isActiveTrackpointQuery(query) || !dataSource.cancelTrackpointMatchQuery}
                    onClick={() => void cancelQuery()}
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <p className="track-analysis-muted">No saved tracks with trackpoints are available for matching.</p>
            )}
            {query && (
              <p className="track-analysis-muted">
                {query.status}: {query.processedSessionCount} / {query.candidateSessionCount} processed, {query.matchedSessionCount} matched.
              </p>
            )}
            {message && <p className="track-analysis-muted">{message}</p>}
          </section>

          <section className="track-analysis-add-card">
            <h3>Matching sessions</h3>
            {results.length ? (
              <div className="track-analysis-add-results">
                {results.map((result) => {
                  const id = sessionRefId(result.sessionRef)
                  const session = sessionByRefId(id, sessions)
                  const alreadyInView = viewSessionIds.has(id)
                  const disabled = !session || alreadyInView
                  return (
                    <label key={`${id}-${result.trackMatchId}`} className={`track-analysis-add-result ${disabled ? 'disabled' : ''}`}>
                      <input
                        checked={selectedResultIds.has(id)}
                        disabled={disabled}
                        type="checkbox"
                        onChange={() => toggleResult(result)}
                      />
                      <span>
                        <strong>
                          {session?.name ?? id}
                          {session?.videoSummary.present && (
                            <Video
                              aria-label={`${session.videoSummary.attachmentCount} video attachment${session.videoSummary.attachmentCount === 1 ? '' : 's'}`}
                              className="track-analysis-video-session-icon"
                              size={13}
                            />
                          )}
                        </strong>
                        <small>
                          {result.matchedTrackpointIds.length} matched / {result.missingTrackpointIds.length} missing
                          {session?.videoSummary.present ? ` - ${session.videoSummary.enabledCount} video enabled` : ''}
                          {alreadyInView ? ' - already in view' : ''}
                          {!session ? ' - unavailable in current catalog' : ''}
                        </small>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="track-analysis-placeholder">
                <MapIcon size={22} />
                <p>Run a trackpoint query to find sessions.</p>
              </div>
            )}
          </section>
        </div>

        <div className="modal-actions">
          <button className="secondary-action" type="button" onClick={onClose}>
            Close
          </button>
          <button className="primary-action" type="button" disabled={!selectedResultIds.size} onClick={addSelectedResults}>
            Add {selectedResultIds.size || ''} session{selectedResultIds.size === 1 ? '' : 's'}
          </button>
        </div>
      </div>
    </div>
  )
}

function TrackAnalysisVideoPanel({
  activeVideo,
  attachments,
  disabled,
  onActiveVideoIdChange,
  onAddTrackpoint,
  onPlaybackTimeChange,
  onReferenceSessionIdChange,
  onTargetTrackIdChange,
  playbackPosition,
  referenceSession,
  sessions,
  focusedTrack,
  state,
  streamUrl,
  targetTrackId,
  targetTrackOptions,
  videoRef,
}: {
  activeVideo: SessionVideoAttachmentRecord | null
  attachments: SessionVideoAttachmentRecord[]
  disabled: boolean
  onActiveVideoIdChange: (attachmentId: string) => void
  onAddTrackpoint: () => void
  onPlaybackTimeChange: (timeS: number) => void
  onReferenceSessionIdChange: (sessionId: string) => void
  onTargetTrackIdChange: (trackId: string) => void
  playbackPosition: PlaybackPosition | null
  referenceSession: SessionRecord | null
  sessions: SessionRecord[]
  focusedTrack: WorkingTrack | null
  state: VideoPanelState
  streamUrl: string
  targetTrackId: string
  targetTrackOptions: VideoTargetTrackOption[]
  videoRef: RefObject<HTMLVideoElement | null>
}) {
  const referenceSessionId = referenceSession ? sessionRecordId(referenceSession) : ''
  const targetOption = targetTrackOptions.find((option) => option.value === targetTrackId) ?? targetTrackOptions[0] ?? null

  if (disabled) {
    return <p className="track-analysis-muted">Video playback is not available from this data source.</p>
  }

  return (
    <div className="track-analysis-video-body">
      {sessions.length ? (
        <label className="track-analysis-field">
          <span>Reference session</span>
          <select value={referenceSessionId} onChange={(event) => onReferenceSessionIdChange(event.target.value)}>
            {sessions.map((session) => (
              <option key={sessionRecordId(session)} value={sessionRecordId(session)}>
                {session.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="track-analysis-muted">No active sessions with video attachments. Toggle a video-capable session on to use video placement.</p>
      )}

      {state.status === 'loading' && <p className="track-analysis-muted">{state.message}</p>}
      {state.status === 'error' && <p className="track-analysis-muted">Could not load video attachments: {state.message}</p>}

      {attachments.length > 0 && (
        <label className="track-analysis-field">
          <span>Attachment</span>
          <select value={activeVideo?.attachmentId ?? ''} onChange={(event) => onActiveVideoIdChange(event.target.value)}>
            {attachments.map((attachment) => (
              <option key={attachment.attachmentId} value={attachment.attachmentId}>
                {attachment.displayName || attachment.cameraLabel || attachment.attachmentId}
              </option>
            ))}
          </select>
        </label>
      )}

      {streamUrl ? (
        <video
          className="track-analysis-video-player"
          controls
          muted
          onTimeUpdate={(event) => onPlaybackTimeChange(event.currentTarget.currentTime)}
          preload="metadata"
          ref={videoRef}
          src={streamUrl}
        />
      ) : attachments.length ? (
        <div className="track-analysis-video-empty">No stream URL is available for the selected attachment.</div>
      ) : referenceSession ? (
        <div className="track-analysis-video-empty">No video attachments were returned for this session.</div>
      ) : null}

      <div className="track-analysis-video-meta">
        <span>
          Target{' '}
          <strong>
            {targetOption?.label ??
              (focusedTrack
                ? `${focusedTrack.name || 'Unnamed track'} (${focusedTrack.origin === 'scratch' ? 'scratch' : 'saved'} track)`
                : 'next scratch track')}
          </strong>
        </span>
        {targetOption && <span>{targetOption.description}</span>}
        <span>{referenceSession ? `Reference session: ${referenceSession.name}` : 'No reference session selected'}</span>
        <span>
          Video head{' '}
          <strong>{playbackPosition ? formatDuration(playbackPosition.timeS) : 'not on GPS path'}</strong>
        </span>
        <span>{activeVideo ? `Offset ${formatSignedSeconds(activeVideo.sessionTimeAtVideoZeroS)}` : 'No active attachment'}</span>
      </div>
      <div className="track-analysis-video-placement-row">
        <label className="track-analysis-field">
          <span>Target track</span>
          <select value={targetOption?.value ?? VIDEO_TARGET_SCRATCH} onChange={(event) => onTargetTrackIdChange(event.target.value)}>
            {targetTrackOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="primary-action"
          disabled={!playbackPosition || !targetOption}
          onClick={onAddTrackpoint}
          title="Add a trackpoint at the current video GPS position"
        >
          <Plus size={14} />
          Add point at video head
        </button>
      </div>
      <p className="track-analysis-muted">
        Video remains attached to the session. Saved tracks are available only when the reference session has a trackpoint match.
      </p>
    </div>
  )
}

function TrackAnalysisFindTracksModal({
  tracks,
  viewTrackIds,
  viewportBounds,
  onAddTracks,
  onClose,
}: {
  tracks: TrackRecord[]
  viewTrackIds: Set<string>
  viewportBounds: LonLatBounds | null
  onAddTracks: (tracks: TrackRecord[]) => void
  onClose: () => void
}) {
  const [trackResults, setTrackResults] = useState<TrackRecord[]>([])
  const [selectedTrackResultIds, setSelectedTrackResultIds] = useState<Set<string>>(() => new Set())
  const [modalViewportBounds, setModalViewportBounds] = useState<LonLatBounds | null>(viewportBounds)
  const [message, setMessage] = useState('')

  function findTracksInViewport() {
    if (!modalViewportBounds) {
      setMessage('The modal map viewport is not available yet. Pan or zoom the map, then try again.')
      setTrackResults([])
      setSelectedTrackResultIds(new Set())
      return
    }
    const matchingTracks = tracks.filter((track) => trackIntersectsBounds(track, modalViewportBounds))
    const addableTracks = matchingTracks.filter((track) => !viewTrackIds.has(track.id))
    setTrackResults(matchingTracks)
    setSelectedTrackResultIds(new Set(addableTracks.map((track) => track.id)))
    setMessage(`Found ${matchingTracks.length} track(s) in the current map view. ${addableTracks.length} can be added.`)
  }

  function toggleTrackResult(track: TrackRecord) {
    if (viewTrackIds.has(track.id)) {
      return
    }
    setSelectedTrackResultIds((current) => {
      const next = new Set(current)
      if (next.has(track.id)) {
        next.delete(track.id)
      } else {
        next.add(track.id)
      }
      return next
    })
  }

  function addSelectedTracks() {
    const selectedTracks = tracks.filter((track) => selectedTrackResultIds.has(track.id))
    onAddTracks(selectedTracks)
    onClose()
  }

  return (
    <div className="modal-backdrop">
      <div className="modal track-analysis-add-modal" role="dialog" aria-modal="true" aria-label="Find tracks for analysis view">
        <div className="modal-header">
          <div>
            <h2>Find tracks</h2>
            <p>Find saved tracks whose geometry overlaps the map viewport. Added tracks only affect this analysis view.</p>
          </div>
          <button className="icon-only" type="button" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <TrackAnalysisAddViewportMap
          initialBounds={viewportBounds}
          tracks={trackResults}
          selectedTrackIds={selectedTrackResultIds}
          onViewportBoundsChanged={setModalViewportBounds}
        />

        <div className="track-analysis-add-grid track-analysis-add-grid-single">
          <section className="track-analysis-add-card">
            <h3>Tracks in map view</h3>
            <p className="track-analysis-muted">
              Pan or zoom the map above, then search for saved tracks that overlap its visible area.
            </p>
            <div className="track-analysis-add-actions">
              <button className="primary-action compact" type="button" onClick={findTracksInViewport}>
                Find tracks
              </button>
            </div>
            {message && <p className="track-analysis-muted">{message}</p>}
            {trackResults.length ? (
              <div className="track-analysis-add-results">
                {trackResults.map((track) => {
                  const alreadyInView = viewTrackIds.has(track.id)
                  return (
                    <label key={track.id} className={`track-analysis-add-result ${alreadyInView ? 'disabled' : ''}`}>
                      <input
                        checked={selectedTrackResultIds.has(track.id)}
                        disabled={alreadyInView}
                        type="checkbox"
                        onChange={() => toggleTrackResult(track)}
                      />
                      <span>
                        <strong>{track.name}</strong>
                        <small>
                          {track.trackpoints.length} point(s), {formatDistance(track.lengthM)}
                          {alreadyInView ? ' - already in view' : ''}
                        </small>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="track-analysis-placeholder">
                <MapIcon size={22} />
                <p>No track search results yet.</p>
              </div>
            )}
          </section>
        </div>

        <div className="modal-actions">
          <button className="secondary-action" type="button" onClick={onClose}>
            Close
          </button>
          <button className="primary-action" type="button" disabled={!selectedTrackResultIds.size} onClick={addSelectedTracks}>
            Add {selectedTrackResultIds.size || ''} track{selectedTrackResultIds.size === 1 ? '' : 's'}
          </button>
        </div>
      </div>
    </div>
  )
}

function TrackAnalysisAddToViewModal({
  dataSource,
  sessions,
  tracks,
  viewSessionIds,
  viewTrackIds,
  viewportBounds,
  initialTrackId,
  onAddSessions,
  onAddTracks,
  onClose,
}: {
  dataSource: LibraryDataSource
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  viewSessionIds: Set<string>
  viewTrackIds: Set<string>
  viewportBounds: LonLatBounds | null
  initialTrackId: string
  onAddSessions: (sessions: SessionRecord[]) => void
  onAddTracks: (tracks: TrackRecord[]) => void
  onClose: () => void
}) {
  const queryableTracks = useMemo(() => tracks.filter((track) => track.trackpoints.length > 0), [tracks])
  const initialQueryableTrackId = queryableTracks.some((track) => track.id === initialTrackId)
    ? initialTrackId
    : queryableTracks[0]?.id ?? ''
  const [trackId, setTrackId] = useState(initialQueryableTrackId)
  const selectedTrack = queryableTracks.find((track) => track.id === trackId) ?? null
  const [selectedTrackpointIds, setSelectedTrackpointIds] = useState<string[]>(
    () => selectedTrack?.trackpoints.map((trackpoint) => trackpoint.id) ?? [],
  )
  const [matchMode, setMatchMode] = useState<TrackpointMatchMode>('all')
  const [minCount, setMinCount] = useState(2)
  const [toleranceM, setToleranceM] = useState(10)
  const [query, setQuery] = useState<TrackpointMatchQueryRecord | null>(null)
  const [results, setResults] = useState<TrackpointMatchQueryResult[]>([])
  const [selectedResultIds, setSelectedResultIds] = useState<Set<string>>(() => new Set())
  const [trackResults, setTrackResults] = useState<TrackRecord[]>([])
  const [selectedTrackResultIds, setSelectedTrackResultIds] = useState<Set<string>>(() => new Set())
  const [modalViewportBounds, setModalViewportBounds] = useState<LonLatBounds | null>(viewportBounds)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [trackSearchMessage, setTrackSearchMessage] = useState('')
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    setSelectedTrackpointIds(selectedTrack?.trackpoints.map((trackpoint) => trackpoint.id) ?? [])
    setResults([])
    setSelectedResultIds(new Set())
    setQuery(null)
    setMessage('')
  }, [selectedTrack])

  const selectedTrackpointIdSet = useMemo(() => new Set(selectedTrackpointIds), [selectedTrackpointIds])
  const canRunQuery = Boolean(
    selectedTrack &&
      selectedTrackpointIds.length > 0 &&
      dataSource.createTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQuery &&
      dataSource.loadTrackpointMatchQueryResults,
  )
  const effectiveMinCount = Math.max(1, Math.min(minCount, selectedTrackpointIds.length || 1))

  async function runQuery() {
    const createQuery = dataSource.createTrackpointMatchQuery?.bind(dataSource)
    const loadQuery = dataSource.loadTrackpointMatchQuery?.bind(dataSource)
    const loadResults = dataSource.loadTrackpointMatchQueryResults?.bind(dataSource)
    if (!selectedTrack || !createQuery || !loadQuery || !loadResults || !canRunQuery) {
      setMessage('Select a track with at least one trackpoint. The current data source must support trackpoint queries.')
      return
    }
    setBusy(true)
    setResults([])
    setSelectedResultIds(new Set())
    setMessage(`Searching for sessions matching ${selectedTrack.name}...`)
    try {
      let currentQuery: TrackpointMatchQueryRecord = await createQuery({
        trackId: selectedTrack.id,
        trackpointIds: selectedTrackpointIds,
        matchMode,
        minCount: matchMode === 'min_count' ? effectiveMinCount : undefined,
        toleranceM,
        scope: {
          libraryIds: uniqueStrings(sessions.map((session) => session.libraryId)),
        },
        persist: true,
      })
      if (mountedRef.current) {
        setQuery(currentQuery)
      }
      while (isActiveTrackpointQuery(currentQuery)) {
        await delay(300)
        const loaded: TrackpointMatchQueryRecord = await loadQuery(currentQuery.queryId)
        currentQuery = loaded
        if (mountedRef.current) {
          setQuery(currentQuery)
        }
      }
      if (currentQuery.status !== 'completed') {
        if (mountedRef.current) {
          setMessage(currentQuery.error || `Trackpoint query is ${currentQuery.status}.`)
        }
        return
      }
      const loadedResults = await loadAllTrackpointQueryResults(loadResults, currentQuery.queryId)
      const addableIds = loadedResults
        .map((result) => sessionRefId(result.sessionRef))
        .filter((id) => !viewSessionIds.has(id) && sessionByRefId(id, sessions))
      if (mountedRef.current) {
        setResults(loadedResults)
        setSelectedResultIds(new Set(addableIds))
        setMessage(`Found ${loadedResults.length} matching session(s). ${addableIds.length} can be added to this view.`)
      }
    } catch (error) {
      if (mountedRef.current) {
        setMessage(error instanceof Error ? error.message : 'Trackpoint query failed.')
      }
    } finally {
      if (mountedRef.current) {
        setBusy(false)
      }
    }
  }

  async function cancelQuery() {
    if (!query || !dataSource.cancelTrackpointMatchQuery || !isActiveTrackpointQuery(query)) {
      return
    }
    setBusy(true)
    try {
      const cancelled = await dataSource.cancelTrackpointMatchQuery(query.queryId)
      setQuery(cancelled)
      setMessage(`Trackpoint query ${cancelled.status}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not cancel trackpoint query.')
    } finally {
      setBusy(false)
    }
  }

  function toggleResult(result: TrackpointMatchQueryResult) {
    const id = sessionRefId(result.sessionRef)
    if (viewSessionIds.has(id) || !sessionByRefId(id, sessions)) {
      return
    }
    setSelectedResultIds((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function addSelectedResults() {
    const selectedSessions = Array.from(selectedResultIds)
      .map((id) => sessionByRefId(id, sessions))
      .filter(isSessionRecord)
    onAddSessions(selectedSessions)
    onClose()
  }

  function findTracksInViewport() {
    if (!modalViewportBounds) {
      setTrackSearchMessage('The modal map viewport is not available yet. Pan or zoom the map, then try again.')
      setTrackResults([])
      setSelectedTrackResultIds(new Set())
      return
    }
    const matchingTracks = tracks.filter((track) => trackIntersectsBounds(track, modalViewportBounds))
    const addableTracks = matchingTracks.filter((track) => !viewTrackIds.has(track.id))
    setTrackResults(matchingTracks)
    setSelectedTrackResultIds(new Set(addableTracks.map((track) => track.id)))
    setTrackSearchMessage(`Found ${matchingTracks.length} track(s) in the current map view. ${addableTracks.length} can be added.`)
  }

  function toggleTrackResult(track: TrackRecord) {
    if (viewTrackIds.has(track.id)) {
      return
    }
    setSelectedTrackResultIds((current) => {
      const next = new Set(current)
      if (next.has(track.id)) {
        next.delete(track.id)
      } else {
        next.add(track.id)
      }
      return next
    })
  }

  function addSelectedTracks() {
    const selectedTracks = tracks.filter((track) => selectedTrackResultIds.has(track.id))
    onAddTracks(selectedTracks)
    setSelectedTrackResultIds(new Set())
    setTrackSearchMessage(`Added ${selectedTracks.length} track${selectedTracks.length === 1 ? '' : 's'} to this view.`)
  }

  return (
    <div className="modal-backdrop">
      <div className="modal track-analysis-add-modal" role="dialog" aria-modal="true" aria-label="Add sessions to analysis view">
        <div className="modal-header">
          <div>
            <h2>Add to view</h2>
            <p>Find sessions that fit a selected track. Added sessions only affect this analysis view.</p>
          </div>
          <button className="icon-only" type="button" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <TrackAnalysisAddViewportMap
          initialBounds={viewportBounds}
          tracks={trackResults.length ? trackResults : selectedTrack ? [selectedTrack] : []}
          selectedTrackIds={selectedTrackResultIds}
          onViewportBoundsChanged={setModalViewportBounds}
        />

        <div className="track-analysis-add-grid">
          <section className="track-analysis-add-card">
            <h3>Trackpoint query</h3>
            {queryableTracks.length ? (
              <>
                <label className="track-analysis-field">
                  <span>Track</span>
                  <select value={trackId} onChange={(event) => setTrackId(event.target.value)}>
                    {queryableTracks.map((track) => (
                      <option key={track.id} value={track.id}>
                        {track.name} ({track.trackpoints.length} point{track.trackpoints.length === 1 ? '' : 's'})
                      </option>
                    ))}
                  </select>
                </label>
                <div className="track-analysis-add-trackpoints">
                  {selectedTrack?.trackpoints.map((trackpoint) => (
                    <label key={trackpoint.id}>
                      <input
                        checked={selectedTrackpointIdSet.has(trackpoint.id)}
                        type="checkbox"
                        onChange={(event) => {
                          setSelectedTrackpointIds((current) =>
                            event.target.checked
                              ? [...current, trackpoint.id]
                              : current.filter((id) => id !== trackpoint.id),
                          )
                        }}
                      />
                      <span>{trackpoint.name || trackpoint.id}</span>
                    </label>
                  ))}
                </div>
                <div className="track-analysis-add-controls">
                  <label className="track-analysis-field">
                    <span>Fit mode</span>
                    <select value={matchMode} onChange={(event) => setMatchMode(event.target.value as TrackpointMatchMode)}>
                      <option value="all">All selected points</option>
                      <option value="min_count">Minimum count</option>
                      <option value="any">Any selected point</option>
                    </select>
                  </label>
                  {matchMode === 'min_count' && (
                    <label className="track-analysis-field">
                      <span>Minimum</span>
                      <input
                        min={1}
                        max={Math.max(1, selectedTrackpointIds.length)}
                        type="number"
                        value={effectiveMinCount}
                        onChange={(event) => setMinCount(Number(event.target.value) || 1)}
                      />
                    </label>
                  )}
                  <label className="track-analysis-field">
                    <span>Tolerance (m)</span>
                    <input
                      min={1}
                      step={1}
                      type="number"
                      value={toleranceM}
                      onChange={(event) => setToleranceM(Math.max(1, Number(event.target.value) || 1))}
                    />
                  </label>
                </div>
                <div className="track-analysis-add-actions">
                  <button className="primary-action compact" type="button" disabled={!canRunQuery || busy} onClick={() => void runQuery()}>
                    {busy && isActiveTrackpointQuery(query) ? 'Searching...' : 'Find sessions'}
                  </button>
                  <button
                    className="secondary-action compact"
                    type="button"
                    disabled={!query || !isActiveTrackpointQuery(query) || !dataSource.cancelTrackpointMatchQuery}
                    onClick={() => void cancelQuery()}
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <p className="track-analysis-muted">No saved tracks with trackpoints are available for matching.</p>
            )}
            {query && (
              <p className="track-analysis-muted">
                {query.status}: {query.processedSessionCount} / {query.candidateSessionCount} processed, {query.matchedSessionCount} matched.
              </p>
            )}
            {message && <p className="track-analysis-muted">{message}</p>}
          </section>

          <section className="track-analysis-add-card">
            <h3>Tracks in map view</h3>
            <p className="track-analysis-muted">
              Finds saved tracks whose geometry overlaps the current Track map viewport. Added tracks stay local to this analysis view.
            </p>
            <div className="track-analysis-add-actions">
              <button className="primary-action compact" type="button" onClick={findTracksInViewport}>
                Find tracks
              </button>
              <button
                className="secondary-action compact"
                type="button"
                disabled={!selectedTrackResultIds.size}
                onClick={addSelectedTracks}
              >
                Add selected
              </button>
            </div>
            {trackSearchMessage && <p className="track-analysis-muted">{trackSearchMessage}</p>}
            {trackResults.length ? (
              <div className="track-analysis-add-results">
                {trackResults.map((track) => {
                  const alreadyInView = viewTrackIds.has(track.id)
                  return (
                    <label key={track.id} className={`track-analysis-add-result ${alreadyInView ? 'disabled' : ''}`}>
                      <input
                        checked={selectedTrackResultIds.has(track.id)}
                        disabled={alreadyInView}
                        type="checkbox"
                        onChange={() => toggleTrackResult(track)}
                      />
                      <span>
                        <strong>{track.name}</strong>
                        <small>
                          {track.trackpoints.length} point(s), {formatDistance(track.lengthM)}
                          {alreadyInView ? ' · already in view' : ''}
                        </small>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <p className="track-analysis-muted">No track search results yet.</p>
            )}
          </section>

          <section className="track-analysis-add-card">
            <h3>Matching sessions</h3>
            {results.length ? (
              <div className="track-analysis-add-results">
                {results.map((result) => {
                  const id = sessionRefId(result.sessionRef)
                  const session = sessionByRefId(id, sessions)
                  const alreadyInView = viewSessionIds.has(id)
                  const disabled = !session || alreadyInView
                  return (
                    <label key={`${id}-${result.trackMatchId}`} className={`track-analysis-add-result ${disabled ? 'disabled' : ''}`}>
                      <input
                        checked={selectedResultIds.has(id)}
                        disabled={disabled}
                        type="checkbox"
                        onChange={() => toggleResult(result)}
                      />
                      <span>
                        <strong>{session?.name ?? id}</strong>
                        <small>
                          {result.matchedTrackpointIds.length} matched / {result.missingTrackpointIds.length} missing
                          {alreadyInView ? ' · already in view' : ''}
                          {!session ? ' · unavailable in current catalog' : ''}
                        </small>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="track-analysis-placeholder">
                <MapIcon size={22} />
                <p>Run a trackpoint query to find sessions.</p>
              </div>
            )}
          </section>
        </div>

        <div className="modal-actions">
          <button className="secondary-action" type="button" onClick={onClose}>
            Close
          </button>
          <button className="primary-action" type="button" disabled={!selectedResultIds.size} onClick={addSelectedResults}>
            Add {selectedResultIds.size || ''} session{selectedResultIds.size === 1 ? '' : 's'}
          </button>
        </div>
      </div>
    </div>
  )
}

void TrackAnalysisAddToViewModal

function LapTimingTable({
  activePointSets,
  rows,
  trackpointCount,
  displayMode,
}: {
  activePointSets: ActiveGpsPointSet[]
  rows: LapTimingRow[]
  trackpointCount: number
  displayMode: LapTimingDisplayMode
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
  const displayRows = displayMode === 'cumulative' ? cumulativeLapTimingRows(visibleRowOrder) : visibleRowOrder
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
          {displayRows.map((row) => {
            const highlights = lapTimingHighlightClasses(row)
            return (
              <tr key={row.key} className={row.key === 'overall' ? 'track-analysis-overall-row' : ''}>
                <td>{row.label}</td>
                <td>{formatDistance(row.distanceM)}</td>
                {row.times.map((time) => {
                  const highlightClass = time.status === 'ready' ? highlights.get(time.sessionId) ?? '' : ''
                  return (
                    <td
                      key={time.sessionId}
                      className={[
                        time.status !== 'ready' ? 'track-analysis-muted-cell' : '',
                        highlightClass,
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {time.status === 'ready' && time.valueS !== null
                        ? formatDuration(time.valueS)
                        : time.status === 'reverse'
                          ? 'reverse'
                          : 'no crossing'}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="track-analysis-table-note">Latest crossing per trackpoint is used; sectors with reverse timing are ignored.</p>
    </div>
  )
}

function cumulativeLapTimingRows(rows: LapTimingRow[]): LapTimingRow[] {
  const segmentRows = rows.filter((row) => row.key !== 'overall')
  const overallRows = rows.filter((row) => row.key === 'overall')
  const cumulativeBySession = new Map<string, { valueS: number; blockedStatus: Exclude<LapTimingCell['status'], 'ready'> | null }>()
  let cumulativeDistanceM = 0

  const cumulativeSegments = segmentRows.map((row) => {
    cumulativeDistanceM += row.distanceM
    const times: LapTimingCell[] = row.times.map((time) => {
      const current = cumulativeBySession.get(time.sessionId) ?? { valueS: 0, blockedStatus: null }
      if (current.blockedStatus) {
        return { sessionId: time.sessionId, valueS: null, status: current.blockedStatus }
      }
      if (time.status !== 'ready' || time.valueS === null) {
        const blockedStatus: Exclude<LapTimingCell['status'], 'ready'> = time.status === 'reverse' ? 'reverse' : 'missing'
        cumulativeBySession.set(time.sessionId, { valueS: current.valueS, blockedStatus })
        return { sessionId: time.sessionId, valueS: null, status: blockedStatus }
      }
      const nextValue = current.valueS + time.valueS
      cumulativeBySession.set(time.sessionId, { valueS: nextValue, blockedStatus: null })
      return { sessionId: time.sessionId, valueS: nextValue, status: 'ready' as const }
    })
    return {
      ...row,
      distanceM: cumulativeDistanceM,
      times,
    }
  })

  return [...cumulativeSegments, ...overallRows]
}

function lapTimingHighlightClasses(row: LapTimingRow) {
  const readyTimes = row.times.filter((time) => time.status === 'ready' && time.valueS !== null)
  const classes = new Map<string, string>()
  if (readyTimes.length < 2) {
    return classes
  }
  const values = readyTimes.map((time) => time.valueS ?? 0)
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (Math.abs(max - min) < 1e-9) {
    return classes
  }
  readyTimes.forEach((time) => {
    if (time.valueS === min) {
      classes.set(time.sessionId, 'track-analysis-lap-fastest')
    } else if (time.valueS === max) {
      classes.set(time.sessionId, 'track-analysis-lap-slowest')
    }
  })
  return classes
}

function TrackAnalysisAddViewportMap({
  initialBounds,
  tracks,
  selectedTrackIds,
  onViewportBoundsChanged,
}: {
  initialBounds: LonLatBounds | null
  tracks: TrackRecord[]
  selectedTrackIds: Set<string>
  onViewportBoundsChanged: (bounds: LonLatBounds | null) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const viewportChangedRef = useRef(onViewportBoundsChanged)
  const fittedInitialBoundsRef = useRef(false)

  useEffect(() => {
    viewportChangedRef.current = onViewportBoundsChanged
  }, [onViewportBoundsChanged])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return
    }
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_RASTER_STYLE,
      center: [0, 0],
      zoom: 13,
      attributionControl: false,
    })
    const reportViewportBounds = () => {
      viewportChangedRef.current(boundsFromMap(map))
    }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    map.on('moveend', reportViewportBounds)
    map.on('zoomend', reportViewportBounds)
    map.once('load', () => {
      if (initialBounds) {
        fitToLonLatBounds(map, initialBounds)
        fittedInitialBoundsRef.current = true
      }
      reportViewportBounds()
    })
    mapRef.current = map
    return () => {
      map.off('moveend', reportViewportBounds)
      map.off('zoomend', reportViewportBounds)
      map.remove()
      mapRef.current = null
      viewportChangedRef.current(null)
    }
  }, [initialBounds])

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
    if (!map) {
      return
    }
    const activeMap = map
    function applyTracks() {
      const lines = buildModalTrackLines(tracks, selectedTrackIds)
      ensureLineLayer(activeMap, lines)
      if (!fittedInitialBoundsRef.current && tracks.length) {
        const positions = tracks.flatMap((track) => track.points)
        fitToPositions(activeMap, positions)
        fittedInitialBoundsRef.current = true
        viewportChangedRef.current(boundsFromMap(activeMap))
      }
    }
    if (activeMap.isStyleLoaded()) {
      applyTracks()
      return
    }
    activeMap.once('load', applyTracks)
    return () => {
      activeMap.off('load', applyTracks)
    }
  }, [selectedTrackIds, tracks])

  return (
    <section className="track-analysis-add-map-card">
      <div className="track-analysis-add-map-heading">
        <strong>Search map</strong>
        <span>Pan or zoom this map, then search for tracks in its visible area.</span>
      </div>
      <div className="track-analysis-add-map" ref={containerRef} />
    </section>
  )
}

function TrackAnalysisMap({
  sessionPaths,
  visibleTracks,
  focusedTrackId,
  draftTrackpoints,
  segmentAliases,
  hideSegmentNames,
  videoMarkerPosition,
  onCreateTrackpoint,
  onMoveTrackpoint,
  onAdjustCutline,
  onDeleteTrackpoint,
  onTrackpointDragEnd,
  onViewportBoundsChanged,
}: {
  sessionPaths: SessionPath[]
  visibleTracks: WorkingTrack[]
  focusedTrackId: string
  draftTrackpoints: DraftTrackpoint[]
  segmentAliases: TrackSegmentAliasRecord[]
  hideSegmentNames: boolean
  videoMarkerPosition: GeoPosition | null
  onCreateTrackpoint: (position: [number, number]) => void
  onMoveTrackpoint: (trackpointId: string, position: [number, number]) => void
  onAdjustCutline: (trackpointId: string, handle: CutlineHandle, position: [number, number]) => void
  onDeleteTrackpoint: (trackpointId: string) => void
  onTrackpointDragEnd: () => void
  onViewportBoundsChanged: (bounds: LonLatBounds | null) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const createTrackpointRef = useRef(onCreateTrackpoint)
  const moveTrackpointRef = useRef(onMoveTrackpoint)
  const adjustCutlineRef = useRef(onAdjustCutline)
  const deleteTrackpointRef = useRef(onDeleteTrackpoint)
  const trackpointDragEndRef = useRef(onTrackpointDragEnd)
  const viewportBoundsChangedRef = useRef(onViewportBoundsChanged)
  const dragHandleRef = useRef<DragHandle | null>(null)
  const suppressClickRef = useRef(false)
  const hasFitInitialDataRef = useRef(false)
  const previousGeometrySignatureRef = useRef('')
  const hasData = sessionPaths.some((path) => path.path.length >= 2) || visibleTracks.some((track) => track.points.length >= 2)
  const geometrySignature = useMemo(
    () =>
      [
        ...sessionPaths.filter((path) => path.path.length >= 2).map((path) => `session:${path.id}:${path.path.length}`),
        ...visibleTracks.filter((track) => track.points.length >= 2).map((track) => `track:${track.workingId}:${track.points.length}`),
      ].join('|'),
    [sessionPaths, visibleTracks],
  )

  useEffect(() => {
    if (!hasData) {
      hasFitInitialDataRef.current = false
      previousGeometrySignatureRef.current = ''
      onViewportBoundsChanged(null)
    }
  }, [hasData, onViewportBoundsChanged])

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
    viewportBoundsChangedRef.current = onViewportBoundsChanged
  }, [onViewportBoundsChanged])

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
    const reportViewportBounds = () => {
      viewportBoundsChangedRef.current(boundsFromMap(map))
    }
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
    map.on('moveend', reportViewportBounds)
    map.on('zoomend', reportViewportBounds)
    map.once('load', reportViewportBounds)
    mapRef.current = map
    return () => {
      map.getCanvas().removeEventListener('contextmenu', preventContextMenu)
      map.off('moveend', reportViewportBounds)
      map.off('zoomend', reportViewportBounds)
      map.remove()
      mapRef.current = null
      viewportBoundsChangedRef.current(null)
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
      const data = buildMapData(
        sessionPaths,
        visibleTracks,
        focusedTrackId,
        draftTrackpoints,
        segmentAliases,
        hideSegmentNames,
        videoMarkerPosition,
      )
      ensureLineLayer(activeMap, data.lines)
      ensurePointLayer(activeMap, data.points)
      const shouldFitToData =
        data.bounds.length > 0 &&
        (!hasFitInitialDataRef.current ||
          (previousGeometrySignatureRef.current === '' && Boolean(geometrySignature)))
      if (shouldFitToData) {
        hasFitInitialDataRef.current = true
        fitToPositions(activeMap, data.bounds)
        viewportBoundsChangedRef.current(boundsFromMap(activeMap))
      }
      previousGeometrySignatureRef.current = geometrySignature
    }
    if (activeMap.isStyleLoaded()) {
      applyData()
      return
    }
    activeMap.once('load', applyData)
    return () => {
      activeMap.off('load', applyData)
    }
  }, [draftTrackpoints, focusedTrackId, geometrySignature, hasData, hideSegmentNames, segmentAliases, sessionPaths, videoMarkerPosition, visibleTracks])

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

function AltitudeChart({
  samples,
  trackpoints,
  playbackStationM,
}: {
  samples: AltitudeSample[]
  trackpoints: DraftTrackpoint[]
  playbackStationM: number | null
}) {
  if (samples.length < 2) {
    return <div className="track-analysis-placeholder">No altitude data is available for the selected track or session.</div>
  }
  const width = 640
  const height = 178
  const padding = { top: 20, right: 22, bottom: 46, left: 54 }
  const minDistance = Math.min(...samples.map((item) => item.distanceM))
  const maxDistance = Math.max(...samples.map((item) => item.distanceM))
  const elevations = samples.map((item) => item.elevationM)
  const minElevation = Math.min(...elevations)
  const maxElevation = Math.max(...elevations)
  const elevationStep = gridStep(maxElevation - minElevation, [10, 20, 50, 100, 200], 3)
  const distanceStep = gridStep(maxDistance - minDistance, [100, 200, 500, 1000, 2000], 3)
  const elevationDomain = gridDomain(minElevation, maxElevation, elevationStep)
  const distanceDomain = gridDomain(minDistance, maxDistance, distanceStep)
  const elevationTicks = gridTicks(elevationDomain.min, elevationDomain.max, elevationStep)
  const distanceTicks = gridTicks(distanceDomain.min, distanceDomain.max, distanceStep)
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const xForDistance = (distanceM: number) =>
    padding.left + ((distanceM - distanceDomain.min) / Math.max(1, distanceDomain.max - distanceDomain.min)) * plotWidth
  const yForElevation = (elevationM: number) =>
    padding.top + (1 - (elevationM - elevationDomain.min) / Math.max(1, elevationDomain.max - elevationDomain.min)) * plotHeight
  const path = samples
    .map((item, index) => {
      const x = xForDistance(item.distanceM)
      const y = yForElevation(item.elevationM)
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
  const plottedTrackpoints = trackpoints
    .filter((trackpoint) => trackpoint.stationM >= distanceDomain.min && trackpoint.stationM <= distanceDomain.max)
    .map((trackpoint) => ({
      trackpoint,
      x: xForDistance(trackpoint.stationM),
      y: yForElevation(interpolateAltitude(samples, trackpoint.stationM)),
    }))
  const playbackMarker =
    playbackStationM !== null && playbackStationM >= distanceDomain.min && playbackStationM <= distanceDomain.max
      ? {
          x: xForDistance(playbackStationM),
          y: yForElevation(interpolateAltitude(samples, playbackStationM)),
        }
      : null
  return (
    <svg className="track-analysis-altitude-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Altitude profile chart">
      {elevationTicks.map((tick) => {
        const y = yForElevation(tick)
        return (
          <g key={`elevation-${tick}`} className="track-analysis-altitude-grid">
            <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
            <text x={padding.left - 7} y={y + 3} textAnchor="end">
              {Math.round(tick)}
            </text>
          </g>
        )
      })}
      {distanceTicks.map((tick) => {
        const x = xForDistance(tick)
        return (
          <g key={`distance-${tick}`} className="track-analysis-altitude-grid">
            <line x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} />
            <text x={x} y={height - padding.bottom + 16} textAnchor="middle">
              {formatDistanceTick(tick)}
            </text>
          </g>
        )
      })}
      <line className="track-analysis-altitude-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
      <line className="track-analysis-altitude-axis" x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
      <path className="track-analysis-altitude-line" d={path} />
      {plottedTrackpoints.map(({ trackpoint, x, y }) => (
        <g key={trackpoint.id} className="track-analysis-altitude-trackpoint">
          <title>{trackpoint.name || trackpoint.id}</title>
          <line x1={x} x2={x} y1={y} y2={height - padding.bottom} />
          <circle cx={x} cy={y} r={3.4} />
        </g>
      ))}
      {playbackMarker && (
        <g className="track-analysis-altitude-playback-marker">
          <line x1={playbackMarker.x} x2={playbackMarker.x} y1={padding.top} y2={height - padding.bottom} />
          <circle cx={playbackMarker.x} cy={playbackMarker.y} r={4.4} />
        </g>
      )}
      <text className="track-analysis-altitude-axis-title" x={(padding.left + width - padding.right) / 2} y={height - 3} textAnchor="middle">
        Distance from start
      </text>
      <text
        className="track-analysis-altitude-axis-title"
        x={16}
        y={(padding.top + height - padding.bottom) / 2}
        textAnchor="middle"
        transform={`rotate(-90 16 ${(padding.top + height - padding.bottom) / 2})`}
      >
        Altitude (m)
      </text>
    </svg>
  )
}

function buildMapData(
  sessionPaths: SessionPath[],
  visibleTracks: WorkingTrack[],
  focusedTrackId: string,
  draftTrackpoints: DraftTrackpoint[],
  segmentAliases: TrackSegmentAliasRecord[],
  hideSegmentNames: boolean,
  videoMarkerPosition: GeoPosition | null,
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

  const focusedTrack = visibleTracks.find((track) => track.workingId === focusedTrackId) ?? null

  visibleTracks.forEach((track) => {
    const safeTrackPath = filterPositions(track.points)
    if (safeTrackPath.length < 2) {
      return
    }
    const focused = track.workingId === focusedTrackId
    lines.push(
      lineFeature(
        `track-${track.workingId}`,
        safeTrackPath,
        track.dirty ? DRAFT_COLOR : TRACK_COLOR,
        focused ? 5 : 3,
        focused ? 0.92 : 0.58,
      ),
    )
    bounds.push(...safeTrackPath)
  })

  const safeReferencePath = focusedTrack ? filterPositions(focusedTrack.points) : []

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

  if (videoMarkerPosition && Number.isFinite(videoMarkerPosition[0]) && Number.isFinite(videoMarkerPosition[1])) {
    points.push(pointFeature('video-head', videoMarkerPosition, '#f59e0b', 'Video head', 7, 'videoHead', ''))
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

function buildModalTrackLines(tracks: TrackRecord[], selectedTrackIds: Set<string>) {
  const lines: Array<Feature<LineString, { color: string; width: number; opacity: number }>> = []
  tracks.forEach((track) => {
    const points = filterPositions(track.points)
    if (points.length < 2) {
      return
    }
    const selected = selectedTrackIds.has(track.id)
    lines.push(
      lineFeature(
        `modal-track-${track.id}`,
        points,
        selected ? DRAFT_COLOR : TRACK_COLOR,
        selected ? 5 : 3,
        selected ? 0.94 : 0.62,
      ),
    )
  })
  return {
    type: 'FeatureCollection',
    features: lines,
  } satisfies FeatureCollection<LineString, { color: string; width: number; opacity: number }>
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

function videoStateData(state: VideoPanelState) {
  return state.data
}

function playbackPositionForSessionTime(pointSet: SessionGpsPointSet, sessionTimeS: number): PlaybackPosition | null {
  const timedPoints = pointSet.points
    .filter(
      (point) =>
        point.timeS !== null &&
        Number.isFinite(point.timeS) &&
        Number.isFinite(point.longitude) &&
        Number.isFinite(point.latitude),
    )
    .sort((a, b) => (a.timeS ?? 0) - (b.timeS ?? 0))
  if (!timedPoints.length || !Number.isFinite(sessionTimeS)) {
    return null
  }
  const positions = timedPoints.map(
    (point) =>
      Number.isFinite(point.elevationM)
        ? ([point.longitude, point.latitude, point.elevationM as number] as GeoPosition)
        : ([point.longitude, point.latitude] as GeoPosition),
  )
  const stations = routeStationsM(positions)
  if (sessionTimeS <= (timedPoints[0].timeS ?? 0)) {
    return { position: positions[0], stationM: stations[0] ?? 0, timeS: timedPoints[0].timeS ?? 0 }
  }
  for (let index = 1; index < timedPoints.length; index += 1) {
    const previous = timedPoints[index - 1]
    const next = timedPoints[index]
    const previousTime = previous.timeS ?? 0
    const nextTime = next.timeS ?? previousTime
    if (sessionTimeS <= nextTime) {
      const fraction = clampNumber((sessionTimeS - previousTime) / Math.max(1e-9, nextTime - previousTime), 0, 1)
      const previousPosition = positions[index - 1]
      const nextPosition = positions[index]
      const interpolated: GeoPosition =
        Number.isFinite(previousPosition[2]) && Number.isFinite(nextPosition[2])
          ? [
              previousPosition[0] + (nextPosition[0] - previousPosition[0]) * fraction,
              previousPosition[1] + (nextPosition[1] - previousPosition[1]) * fraction,
              (previousPosition[2] as number) + ((nextPosition[2] as number) - (previousPosition[2] as number)) * fraction,
            ]
          : [
              previousPosition[0] + (nextPosition[0] - previousPosition[0]) * fraction,
              previousPosition[1] + (nextPosition[1] - previousPosition[1]) * fraction,
            ]
      return {
        position: interpolated,
        stationM: (stations[index - 1] ?? 0) + ((stations[index] ?? 0) - (stations[index - 1] ?? 0)) * fraction,
        timeS: sessionTimeS,
      }
    }
  }
  const lastIndex = timedPoints.length - 1
  return {
    position: positions[lastIndex],
    stationM: stations[lastIndex] ?? 0,
    timeS: timedPoints[lastIndex].timeS ?? sessionTimeS,
  }
}

function sessionTimeForPosition(pointSet: SessionGpsPointSet, position: GeoPosition): number | null {
  const route = timedSessionRoute(pointSet)
  if (route.positions.length < 2) {
    return null
  }
  const snapped = nearestPointOnLine(lineString(route.positions.map(lonLat)), point(lonLat(position)), { units: 'meters' })
  const stationM = clampNumber(Number(snapped.properties?.location ?? 0), 0, route.stations[route.stations.length - 1] ?? 0)
  return interpolateTimeAtStation(route.stations, route.times, stationM)
}

function timedSessionRoute(pointSet: SessionGpsPointSet) {
  const timedPoints = pointSet.points
    .filter(
      (point) =>
        point.timeS !== null &&
        Number.isFinite(point.timeS) &&
        Number.isFinite(point.longitude) &&
        Number.isFinite(point.latitude),
    )
    .sort((a, b) => (a.timeS ?? 0) - (b.timeS ?? 0))
  const positions = timedPoints.map(
    (point) =>
      Number.isFinite(point.elevationM)
        ? ([point.longitude, point.latitude, point.elevationM as number] as GeoPosition)
        : ([point.longitude, point.latitude] as GeoPosition),
  )
  return {
    positions,
    stations: routeStationsM(positions),
    times: timedPoints.map((point) => point.timeS ?? 0),
  }
}

function interpolateTimeAtStation(stations: number[], times: number[], stationM: number) {
  if (!stations.length || stations.length !== times.length) {
    return null
  }
  if (stationM <= stations[0]) {
    return times[0]
  }
  for (let index = 1; index < stations.length; index += 1) {
    if (stationM <= stations[index]) {
      const fraction = clampNumber((stationM - stations[index - 1]) / Math.max(1e-9, stations[index] - stations[index - 1]), 0, 1)
      return times[index - 1] + (times[index] - times[index - 1]) * fraction
    }
  }
  return times[times.length - 1]
}

function isAltitudeSample(value: AltitudeSample | null): value is AltitudeSample {
  return value !== null
}

function gridStep(span: number, candidates: number[], minimumGridlines = 4) {
  const safeSpan = Math.max(0, span)
  return [...candidates].reverse().find((candidate) => safeSpan / candidate >= minimumGridlines) ?? candidates[0]
}

function gridDomain(minValue: number, maxValue: number, step: number) {
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
    return { min: 0, max: step * 4 }
  }
  let min = Math.floor(minValue / step) * step
  let max = Math.ceil(maxValue / step) * step
  if (max <= min) {
    max = min + step * 4
  }
  while ((max - min) / step < 4) {
    max += step
  }
  return { min, max }
}

function gridTicks(minValue: number, maxValue: number, step: number) {
  const ticks: number[] = []
  const start = Math.ceil(minValue / step) * step
  const end = Math.floor(maxValue / step) * step
  for (let value = start; value <= end + step * 0.001; value += step) {
    ticks.push(Math.round(value * 1000) / 1000)
  }
  return ticks
}

function formatDistanceTick(distanceM: number) {
  if (Math.abs(distanceM) >= 1000) {
    return `${(distanceM / 1000).toFixed(distanceM % 1000 === 0 ? 0 : 1)} km`
  }
  return `${Math.round(distanceM)} m`
}

function interpolateAltitude(samples: AltitudeSample[], distanceM: number) {
  if (!samples.length) {
    return 0
  }
  const sorted = [...samples].sort((a, b) => a.distanceM - b.distanceM)
  if (distanceM <= sorted[0].distanceM) {
    return sorted[0].elevationM
  }
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1]
    const next = sorted[index]
    if (distanceM <= next.distanceM) {
      const fraction = (distanceM - previous.distanceM) / Math.max(1e-9, next.distanceM - previous.distanceM)
      return previous.elevationM + (next.elevationM - previous.elevationM) * fraction
    }
  }
  return sorted[sorted.length - 1].elevationM
}

function validSegmentAliasesForTrack(track: Pick<WorkingTrack, 'trackpoints' | 'segmentAliases'>): TrackSegmentAliasRecord[] {
  const ordered = [...track.trackpoints].sort((a, b) => a.stationM - b.stationM)
  const adjacentPairs = new Set<string>()
  const pairDefaultNames = new Map<string, string>()
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const key = segmentAliasKey(ordered[index].id, ordered[index + 1].id)
    adjacentPairs.add(key)
    pairDefaultNames.set(key, `Segment ${index + 1}`)
  }
  return track.segmentAliases
    .map((alias) => {
      const key = segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId)
      const name = alias.name.trim() || (alias.timingRole === 'untimed' ? pairDefaultNames.get(key) || 'Segment' : '')
      const timingRole: TrackSegmentAliasRecord['timingRole'] = alias.timingRole === 'untimed' ? 'untimed' : 'timed'
      return { ...alias, name, timingRole }
    })
    .filter((alias) => alias.name && adjacentPairs.has(segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId)))
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
  patch: { name?: string; timingRole?: 'timed' | 'untimed' },
) {
  const key = segmentAliasKey(fromTrackpointId, toTrackpointId)
  const existing = aliases.find((alias) => segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId) === key)
  const withoutExisting = aliases.filter((alias) => segmentAliasKey(alias.fromTrackpointId, alias.toTrackpointId) !== key)
  const name = patch.name !== undefined ? patch.name : existing?.name ?? ''
  const timingRole = patch.timingRole ?? existing?.timingRole ?? 'timed'
  const trimmedName = name.trim()
  if (!trimmedName && timingRole !== 'untimed') {
    return withoutExisting
  }
  return [...withoutExisting, { fromTrackpointId, toTrackpointId, name: trimmedName || name, timingRole }]
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
    matchSummaries: track.matchSummaries.map(copyTrackMatchSummary),
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

function trackSessionMatchKey(trackWorkingId: string, sessionRefId: string) {
  return `${trackWorkingId}::${sessionRefId}`
}

function isUsableTrackMatchStatus(status: TrackMatchStatus) {
  return status === 'matched' || status === 'partial'
}

function canUseReferenceVideoForTrack(
  track: WorkingTrack | null,
  referenceSession: SessionRecord | null,
  matchCache: Record<string, TrackSessionMatchCacheEntry>,
) {
  if (!track || !referenceSession) {
    return false
  }
  const referenceId = sessionRecordId(referenceSession)
  if (track.origin === 'scratch') {
    return track.sourceSessionId === referenceId
  }
  if (!track.persistedId) {
    return false
  }
  const entry = matchCache[trackSessionMatchKey(track.workingId, referenceId)]
  return Boolean(entry && entry.crossedCount > 0 && isUsableTrackMatchStatus(entry.status))
}

function copyTrackMatchSummary(match: TrackRecord['matchSummaries'][number]) {
  return {
    ...match,
    trackpointResults: match.trackpointResults.map((result) => ({ ...result })),
    warnings: [...match.warnings],
  }
}

function draftTrackpointFromSnap(
  snapped: { position: GeoPosition; stationM: number },
  nextIndex: number,
  name?: string,
): DraftTrackpoint {
  return {
    id: `draft-${Date.now().toString(36)}-${nextIndex}`,
    name: name ?? `Point ${nextIndex}`,
    stationM: snapped.stationM,
    position: copyPosition(snapped.position),
    cutlineOverride: {
      leftLengthM: CUTLINE_LENGTH_M / 2,
      rightLengthM: CUTLINE_LENGTH_M / 2,
    },
    draft: true,
  }
}

function initialScratchTrackpoints(
  path: GeoPosition[],
  snapped: { position: GeoPosition; stationM: number },
  includeEndpoints: boolean,
) {
  if (!includeEndpoints || path.length < 2) {
    return [draftTrackpointFromSnap(snapped, 1)]
  }
  const lengthM = routeLengthM(path)
  const endpointToleranceM = 1
  const trackpoints: DraftTrackpoint[] = []
  let nextIndex = 1
  if (snapped.stationM > endpointToleranceM) {
    trackpoints.push(draftTrackpointFromSnap({ position: path[0], stationM: 0 }, nextIndex, 'Start'))
    nextIndex += 1
  }
  trackpoints.push(draftTrackpointFromSnap(snapped, nextIndex, 'Point 1'))
  nextIndex += 1
  if (lengthM - snapped.stationM > endpointToleranceM) {
    trackpoints.push(draftTrackpointFromSnap({ position: path[path.length - 1], stationM: lengthM }, nextIndex, 'End'))
  }
  return trackpoints.sort((a, b) => a.stationM - b.stationM)
}

function trimWorkingTrackToTrackpoints(track: WorkingTrack): WorkingTrack {
  if (track.points.length < 2 || track.trackpoints.length < 2) {
    return track
  }
  const routeLength = routeLengthM(track.points)
  const orderedTrackpoints = [...track.trackpoints].sort((a, b) => a.stationM - b.stationM)
  const startStationM = clampNumber(orderedTrackpoints[0].stationM, 0, routeLength)
  const endStationM = clampNumber(orderedTrackpoints[orderedTrackpoints.length - 1].stationM, 0, routeLength)
  if (endStationM - startStationM < 1) {
    return track
  }
  const points = trimRoutePoints(track.points, startStationM, endStationM)
  if (points.length < 2) {
    return track
  }
  const lengthM = routeLengthM(points)
  return {
    ...track,
    points,
    lengthM,
    pointCount: points.length,
    distanceKm: lengthM / 1000,
    trackpoints: track.trackpoints
      .map((trackpoint) => {
        const stationM = clampNumber(trackpoint.stationM - startStationM, 0, lengthM)
        return {
          ...trackpoint,
          stationM,
          position: pointAtStationM(points, stationM),
          cutlineOverride: trackpoint.cutlineOverride ? { ...trackpoint.cutlineOverride } : undefined,
          draft: true as const,
        }
      })
      .sort((a, b) => a.stationM - b.stationM),
  }
}

function trimRoutePoints(points: GeoPosition[], startStationM: number, endStationM: number) {
  const stations = routeStationsM(points)
  const out: GeoPosition[] = [pointAtStationM(points, startStationM)]
  points.forEach((position, index) => {
    const stationM = stations[index] ?? 0
    if (stationM > startStationM && stationM < endStationM) {
      out.push(copyPosition(position))
    }
  })
  out.push(pointAtStationM(points, endStationM))
  return dedupeAdjacentPositions(out)
}

function dedupeAdjacentPositions(points: GeoPosition[]) {
  const out: GeoPosition[] = []
  points.forEach((position) => {
    const previous = out[out.length - 1]
    if (previous && Math.abs(previous[0] - position[0]) < 1e-12 && Math.abs(previous[1] - position[1]) < 1e-12) {
      return
    }
    out.push(copyPosition(position))
  })
  return out
}

function scratchTrackFromNearestPath(
  position: [number, number],
  sessionPaths: SessionPath[],
  existingTracks: WorkingTrack[],
  studySet: StudySet,
  includeEndpoints: boolean,
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
    trackpoints: initialScratchTrackpoints(path, nearest.snapped, includeEndpoints),
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

function scratchTrackFromSessionPath(
  sessionPath: SessionPath,
  snapped: { position: GeoPosition; stationM: number },
  existingTracks: WorkingTrack[],
  studySet: StudySet,
  includeEndpoints: boolean,
): WorkingTrack {
  const existingIds = existingTracks.map((track) => track.workingId)
  const workingId = uniqueId(`scratch-${Date.now().toString(36)}`, existingIds)
  const path = sessionPath.path.map(copyPosition)
  const lengthM = routeLengthM(path)
  const nextIndex = existingTracks.filter((track) => track.origin === 'scratch' && !track.persistedId).length + 1
  const name = `${studySet.displayName.trim() || sessionPath.label} scratch ${nextIndex}`
  return {
    workingId,
    persistedId: null,
    origin: 'scratch',
    dirty: true,
    saving: false,
    deleting: false,
    status: '',
    name,
    description: `Scratch track created from ${sessionPath.label}.`,
    revision: 0,
    points: path,
    lengthM,
    pointCount: path.length,
    distanceKm: lengthM / 1000,
    defaultPolicyId: 'default-geospatial-policy',
    trackpoints: initialScratchTrackpoints(path, snapped, includeEndpoints),
    segmentAliases: [],
    matchSummaries: [],
    source: {
      kind: 'session_gps',
      libraryId: sessionPath.session.libraryId,
      sessionRefId: sessionRecordId(sessionPath.session),
      sessionKey: sessionPath.session.sessionKey,
      runId: sessionPath.session.runId,
      sessionId: sessionPath.session.sessionId,
      gpsSourceId: sessionPath.session.gpsSummary.preferredSourceId ?? undefined,
      gpsSourceKind: sessionPath.session.gpsSummary.preferredSourceKind ?? undefined,
      gpsStreamName: sessionPath.session.gpsSummary.sources[0]?.streamName,
      gpsSourceSelectionMethod: sessionPath.session.gpsSummary.sourceSelectionMethod,
    },
    sourceSessionId: sessionPath.id,
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
      filter: ['in', ['get', 'role'], ['literal', ['trackpoint', 'left', 'right']]],
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

function fitToLonLatBounds(map: MapLibreMap, bounds: LonLatBounds) {
  map.fitBounds(
    new maplibregl.LngLatBounds(
      [bounds.minLongitude, bounds.minLatitude],
      [bounds.maxLongitude, bounds.maxLatitude],
    ),
    { padding: 32, maxZoom: 16, duration: 0 },
  )
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

  const segmentRows: LapTimingRow[] = []

  for (let index = 1; index < orderedTrackpoints.length; index += 1) {
    const start = orderedTrackpoints[index - 1]
    const end = orderedTrackpoints[index]
    const alias = segmentAliasForPair(segmentAliases, start.id, end.id)
    if (alias?.timingRole === 'untimed') {
      continue
    }
    segmentRows.push(
      timingRow(
        `${start.id}-${end.id}`,
        alias?.name || `${start.name} to ${end.name}`,
        Math.max(0, end.stationM - start.stationM),
        activePointSets,
        crossingsBySession,
        start,
        end,
      ),
    )
  }

  if (!segmentRows.length) {
    return []
  }
  return [...segmentRows, timedTotalRow(segmentRows, activePointSets)]
}

function timedTotalRow(segmentRows: LapTimingRow[], activePointSets: ActiveGpsPointSet[]): LapTimingRow {
  return {
    key: 'overall',
    label: 'Timed total',
    distanceM: segmentRows.reduce((total, row) => total + row.distanceM, 0),
    times: activePointSets.map((item) => {
      const sessionId = sessionRecordId(item.session)
      const segmentTimes = segmentRows.map((row) => row.times.find((time) => time.sessionId === sessionId))
      if (segmentTimes.some((time) => time?.status === 'reverse')) {
        return { sessionId, valueS: null, status: 'reverse' }
      }
      if (segmentTimes.some((time) => time?.status !== 'ready' || time.valueS === null)) {
        return { sessionId, valueS: null, status: 'missing' }
      }
      return {
        sessionId,
        valueS: segmentTimes.reduce((total, time) => total + (time?.valueS ?? 0), 0),
        status: 'ready',
      }
    }),
  }
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

function mergeSessionLists(primary: SessionRecord[], secondary: SessionRecord[]) {
  const byId = new Map<string, SessionRecord>()
  primary.forEach((session) => byId.set(sessionRecordId(session), session))
  secondary.forEach((session) => byId.set(sessionRecordId(session), session))
  return Array.from(byId.values())
}

function trackIntersectsBounds(track: Pick<TrackRecord, 'points' | 'trackpoints'>, bounds: LonLatBounds) {
  const trackBounds = boundsForPositions([
    ...track.points,
    ...track.trackpoints.map((trackpoint) => trackpoint.position),
  ])
  return Boolean(trackBounds && lonLatBoundsIntersect(trackBounds, bounds))
}

function boundsForPositions(positions: GeoPosition[]): LonLatBounds | null {
  const validPositions = filterPositions(positions)
  if (!validPositions.length) {
    return null
  }
  return validPositions.reduce<LonLatBounds>(
    (bounds, position) => ({
      minLongitude: Math.min(bounds.minLongitude, position[0]),
      minLatitude: Math.min(bounds.minLatitude, position[1]),
      maxLongitude: Math.max(bounds.maxLongitude, position[0]),
      maxLatitude: Math.max(bounds.maxLatitude, position[1]),
    }),
    {
      minLongitude: validPositions[0][0],
      minLatitude: validPositions[0][1],
      maxLongitude: validPositions[0][0],
      maxLatitude: validPositions[0][1],
    },
  )
}

function boundsFromMap(map: MapLibreMap): LonLatBounds {
  const bounds = map.getBounds()
  return {
    minLongitude: bounds.getWest(),
    minLatitude: bounds.getSouth(),
    maxLongitude: bounds.getEast(),
    maxLatitude: bounds.getNorth(),
  }
}

function lonLatBoundsIntersect(a: LonLatBounds, b: LonLatBounds) {
  return !(
    a.maxLongitude < b.minLongitude ||
    a.minLongitude > b.maxLongitude ||
    a.maxLatitude < b.minLatitude ||
    a.minLatitude > b.maxLatitude
  )
}

function sessionByRefId(id: string, sessions: SessionRecord[]) {
  return sessions.find((session) => sessionRecordId(session) === id)
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
}

function isActiveTrackpointQuery(query: TrackpointMatchQueryRecord | null) {
  return query?.status === 'queued' || query?.status === 'running'
}

async function loadAllTrackpointQueryResults(
  loadResults: NonNullable<LibraryDataSource['loadTrackpointMatchQueryResults']>,
  queryId: string,
) {
  const results: TrackpointMatchQueryResult[] = []
  let cursor: string | null = null
  do {
    const page: TrackpointMatchQueryResults = await loadResults(queryId, cursor, 500)
    results.push(...page.results)
    cursor = page.nextCursor
  } while (cursor)
  return results
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
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

function isSpaceKey(event: globalThis.KeyboardEvent) {
  return event.code === 'Space' || event.key === ' ' || event.key === 'Spacebar'
}

function isEditableKeyboardTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false
  }
  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  )
}

function trackAnalysisViewContextStorageKey(studySet: StudySet) {
  const stableScope =
    studySet.id ||
    [
      studySet.displayName,
      ...studySet.sessions.map(sessionRefId).sort(),
      ...studySet.trackIds.map((id) => `track:${id}`).sort(),
    ].join('|')
  return `${TRACK_ANALYSIS_VIEW_CONTEXT_STORAGE_PREFIX}${hashString(stableScope)}`
}

function readTrackAnalysisViewContext(key: string): PersistedTrackAnalysisViewContext {
  if (typeof window === 'undefined') {
    return emptyTrackAnalysisViewContext()
  }
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) {
      return emptyTrackAnalysisViewContext()
    }
    const parsed = JSON.parse(raw) as Partial<PersistedTrackAnalysisViewContext>
    return {
      addedSessionIds: stringArrayValue(parsed.addedSessionIds),
      removedSessionIds: stringArrayValue(parsed.removedSessionIds),
      addedTrackIds: stringArrayValue(parsed.addedTrackIds),
      videoPanelOpen: typeof parsed.videoPanelOpen === 'boolean' ? parsed.videoPanelOpen : false,
      videoPanelWidthPx: clampNumber(
        typeof parsed.videoPanelWidthPx === 'number' ? parsed.videoPanelWidthPx : TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX,
        TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX,
        TRACK_ANALYSIS_VIDEO_PANEL_MAX_WIDTH_PX,
      ),
    }
  } catch {
    return emptyTrackAnalysisViewContext()
  }
}

function writeTrackAnalysisViewContext(key: string, context: PersistedTrackAnalysisViewContext) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    const normalized: PersistedTrackAnalysisViewContext = {
      addedSessionIds: uniqueStrings(context.addedSessionIds),
      removedSessionIds: uniqueStrings(context.removedSessionIds),
      addedTrackIds: uniqueStrings(context.addedTrackIds),
      videoPanelOpen: context.videoPanelOpen,
      videoPanelWidthPx: clampNumber(
        context.videoPanelWidthPx,
        TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX,
        TRACK_ANALYSIS_VIDEO_PANEL_MAX_WIDTH_PX,
      ),
    }
    if (
      !normalized.addedSessionIds.length &&
      !normalized.removedSessionIds.length &&
      !normalized.addedTrackIds.length &&
      !normalized.videoPanelOpen &&
      normalized.videoPanelWidthPx === TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX
    ) {
      window.localStorage.removeItem(key)
      return
    }
    window.localStorage.setItem(key, JSON.stringify(normalized))
  } catch {
    // Local context persistence is a convenience; failures should not block analysis.
  }
}

function emptyTrackAnalysisViewContext(): PersistedTrackAnalysisViewContext {
  return {
    addedSessionIds: [],
    removedSessionIds: [],
    addedTrackIds: [],
    videoPanelOpen: false,
    videoPanelWidthPx: TRACK_ANALYSIS_VIDEO_PANEL_MIN_WIDTH_PX,
  }
}

function stringArrayValue(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function hashString(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
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

function formatSignedSeconds(valueS: number) {
  const sign = valueS > 0 ? '+' : ''
  return `${sign}${valueS.toFixed(1)}s`
}
