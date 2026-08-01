import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MutableRefObject,
  type PointerEvent,
  type RefObject,
} from 'react'
import * as d3 from 'd3'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsLeft,
  ChevronsRight,
  Film,
  Map as MapIcon,
  Play,
  RefreshCcw,
  Save,
  SkipBack,
  SkipForward,
  Trash2,
} from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionToStudyRef } from '../domain/studySets'
import { InfoTip } from './Common'
import { MapRoutePreview, type HighlightPathOverlay } from './MapRoutePreview'
import { GpsBadge } from './StatusBadges'
import type {
  GeoPosition,
  SessionRecord,
  SessionBookmarkRecord,
  SessionGpsPoint,
  SessionGpsPointSet,
  SessionVideoAttachmentRecord,
  SessionVideoAttachmentsRecord,
  SessionSignalSummary,
  TimeseriesWindowEvent,
  TimeseriesWindowMark,
  TimeseriesWindowResponse,
} from '../domain/types'

const TARGET_POINTS = 1800
const NAVIGATOR_POINTS = 900
const DENSE_EVENT_CUTOFF = 50
const CHART_WINDOW_DRAG_THRESHOLD_PX = 8
const SIGNAL_INSPECTOR_HOVER_DEBUG = false
const SIGNAL_INSPECTOR_CHART_MODE_STORAGE_KEY = 'bodaqs.signalInspector.chartMode.v1'
const SIGNAL_INSPECTOR_SESSION_COLUMNS_STORAGE_KEY = 'bodaqs.signalInspector.sessionColumns.v1'
const SIGNAL_INSPECTOR_SESSION_PINNED_TIME_STORAGE_KEY = 'bodaqs.signalInspector.sessionPinnedTime.v1'
const SIGNAL_INSPECTOR_VIEW_STORAGE_KEY = 'bodaqs.signalInspector.view.v1'
const SIGNAL_INSPECTOR_SIDEBAR_MIN_WIDTH_PX = 320
const SIGNAL_INSPECTOR_SIDEBAR_MAX_WIDTH_PX = 560
const SIGNAL_INSPECTOR_GPS_MAP_MIN_HEIGHT_PX = 140
const SIGNAL_INSPECTOR_GPS_MAP_MAX_HEIGHT_PX = 420
const SIGNAL_INSPECTOR_VIDEO_MIN_HEIGHT_PX = 120
const SIGNAL_INSPECTOR_VIDEO_MAX_HEIGHT_PX = 420
const SIGNAL_INSPECTOR_VIDEO_BUFFER_MIN_SPAN_S = 30
const SIGNAL_INSPECTOR_VIDEO_BUFFER_MULTIPLIER = 6
const SIGNAL_INSPECTOR_VIDEO_BUFFER_MAX_SPAN_S = 180
const SIGNAL_INSPECTOR_SHORT_WINDOW_DETAIL_SPAN_S = 5
const SIGNAL_INSPECTOR_MEDIUM_WINDOW_DETAIL_SPAN_S = 10
const SIGNAL_INSPECTOR_SHORT_WINDOW_TARGET_POINTS = 12000
const SIGNAL_INSPECTOR_MEDIUM_WINDOW_TARGET_POINTS = 16000
const SIGNAL_INSPECTOR_MAX_TARGET_POINTS = 48000
const SIGNAL_COLORS = ['#008c95', '#101820', '#2d5f64', '#b88a43', '#6f7b80', '#9aa7a3']
const EVENT_COLORS = ['#b66a2c', '#4d70a8', '#8a5a7b', '#6f7e2e', '#c46f58', '#2f7d6d']

type SignalInspectorChartMode = 'single' | 'multi'
type SidebarPanelKey = 'bookmarks' | 'gpsMap' | 'gpsAltitude' | 'video'

type SignalInspectorViewPreferences = {
  sidebarOpen: boolean
  controlsOpen: boolean
  sidebarWidthPx: number
  collapsedSidebarPanels: Record<SidebarPanelKey, boolean>
  gpsMapHeightPx: number
  videoHeightPx: number
  showEventDetails: boolean
  videoSettingsCollapsed: boolean
  videoScrollWithPlayback: boolean
}

type LoadState =
  | { status: 'idle'; message: string }
  | { status: 'loading'; message: string; data?: TimeseriesWindowResponse }
  | { status: 'ready'; message: string; data: TimeseriesWindowResponse }
  | { status: 'error'; message: string; data?: TimeseriesWindowResponse }

type GpsPanelState =
  | { status: 'idle'; message: string; pointSet: SessionGpsPointSet | null }
  | { status: 'loading'; message: string; pointSet: SessionGpsPointSet | null }
  | { status: 'ready'; message: string; pointSet: SessionGpsPointSet }
  | { status: 'error'; message: string; pointSet: SessionGpsPointSet | null }

type VideoPanelState =
  | { status: 'idle'; message: string; data: SessionVideoAttachmentsRecord | null }
  | { status: 'loading'; message: string; data: SessionVideoAttachmentsRecord | null }
  | { status: 'ready'; message: string; data: SessionVideoAttachmentsRecord }
  | { status: 'error'; message: string; data: SessionVideoAttachmentsRecord | null }

type EventGroup = {
  key: string
  label: string
  count: number
  dense: boolean
  color: string
}

type HoverReadout = {
  x: number
  timeS: number
  values: Array<{
    label: string
    value: number
    unit: string
    color: string
  }>
}

type HoverDebugEvent = {
  chart: string
  rawIndex: number | null
  rawLeft: number | null
  resolvedIndex: number | null
  resolvedTimeS: number | null
  action: 'hover' | 'clear' | 'leave'
  reason: string
  at: number
}

type NavigatorDrag = {
  mode: 'start' | 'end' | 'move'
  originS: number
  currentS: number
  startS: number
  endS: number
}

type TimeWindowDrag = {
  pointerId: number
  startS: number
  currentS: number
}

type VideoAttachmentInput = {
  displayName: string
  cameraLabel: string
  path: string
  sessionTimeAtVideoZeroS: number
}

type AxisId = string

type UnitChoice = {
  key: string
  label: string
}

type AxisConfig = {
  id: AxisId
  unit: UnitChoice
  side: 'left' | 'right'
  offset: number
}

type ChartSignal = TimeseriesWindowResponse['signals'][number] & {
  axisId: AxisId
  displayLabel: string
  originalIndex: number
  unitKey: string
}

type SignalChartModel = {
  axisConfigs: AxisConfig[]
  chartSignals: ChartSignal[]
  alignedData: uPlot.AlignedData
  times: number[]
  seriesValues: Array<Array<number | null>>
}

type SessionTimeWindow = {
  startS: number
  endS: number
}

function loadStateData(state: LoadState) {
  return state.status === 'ready' || state.status === 'loading' || state.status === 'error' ? state.data : undefined
}

function videoStateData(state: VideoPanelState) {
  return state.status === 'ready' || state.status === 'loading' || state.status === 'error' ? state.data : null
}

function useSessionTimeInteraction({
  durationS,
  initialWindow,
  initialPinnedTimeS,
}: {
  durationS: number
  initialWindow?: SessionTimeWindow | null
  initialPinnedTimeS?: number | null
}) {
  const initialSessionWindow = () =>
    sanitizeWindow(
      sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS),
      sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS),
      durationS,
    )
  const [windowState, setWindowState] = useState<SessionTimeWindow>(initialSessionWindow)
  const [pinnedTimeS, setPinnedTimeSState] = useState<number | null>(() =>
    initialPinnedTimeS !== null && initialPinnedTimeS !== undefined
      ? roundForInput(sanitizeWindowBoundary(initialPinnedTimeS, durationS))
      : midpointOfWindow(initialSessionWindow()),
  )
  const [hoverTimeS, setHoverTimeS] = useState<number | null>(null)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const windowDragRef = useRef<TimeWindowDrag | null>(null)

  function setWindowDrag(nextDrag: TimeWindowDrag | null) {
    windowDragRef.current = nextDrag
  }

  function setWindow(window: SessionTimeWindow) {
    const nextWindow = sanitizeWindow(window.startS, window.endS, durationS)
    setWindowState(nextWindow)
  }

  function setPinnedTime(timeS: number | null) {
    setPinnedTimeSState(timeS === null || !Number.isFinite(timeS) ? null : roundForInput(sanitizeWindowBoundary(timeS, durationS)))
  }

  function reset(nextInitialWindow: SessionTimeWindow | null | undefined = initialWindow, nextPinnedTimeS: number | null | undefined = initialPinnedTimeS) {
    const nextWindow = sanitizeWindow(
      sanitizeWindowBoundary(nextInitialWindow?.startS ?? 0, durationS),
      sanitizeWindowBoundary(nextInitialWindow?.endS ?? durationS, durationS),
      durationS,
    )
    setWindowState(nextWindow)
    setPinnedTimeSState(
      nextPinnedTimeS !== null && nextPinnedTimeS !== undefined
        ? roundForInput(sanitizeWindowBoundary(nextPinnedTimeS, durationS))
        : midpointOfWindow(nextWindow),
    )
    setHoverTimeS(null)
    setSelectedEventId(null)
    setWindowDrag(null)
  }

  function beginWindowDrag(pointerId: number, startS: number) {
    const sanitizedStartS = sanitizeWindowBoundary(startS, durationS)
    setWindowDrag({ pointerId, startS: sanitizedStartS, currentS: sanitizedStartS })
  }

  function updateWindowDrag(pointerId: number, currentS: number) {
    const currentDrag = windowDragRef.current
    if (!currentDrag || currentDrag.pointerId !== pointerId) {
      return
    }
    windowDragRef.current = {
      ...currentDrag,
      currentS: sanitizeWindowBoundary(currentS, durationS),
    }
  }

  function cancelWindowDrag(pointerId?: number) {
    const currentDrag = windowDragRef.current
    if (pointerId !== undefined && currentDrag && currentDrag.pointerId !== pointerId) {
      return
    }
    setWindowDrag(null)
  }

  function commitWindowDrag(pointerId: number, currentS: number) {
    const currentDrag = windowDragRef.current
    if (!currentDrag || currentDrag.pointerId !== pointerId) {
      return null
    }
    const nextWindow = sanitizeWindow(currentDrag.startS, sanitizeWindowBoundary(currentS, durationS), durationS)
    setWindowDrag(null)
    if (nextWindow.endS - nextWindow.startS < 0.1) {
      return null
    }
    setWindow(nextWindow)
    return nextWindow
  }

  function getWindowDrag() {
    return windowDragRef.current
  }

  return {
    activeWindow: windowState,
    pinnedTimeS,
    hoverTimeS,
    selectedEventId,
    beginWindowDrag,
    cancelWindowDrag,
    commitWindowDrag,
    getWindowDrag,
    setPinnedTime,
    setHoverTimeS,
    setSelectedEventId,
    setWindow,
    updateWindowDrag,
    reset,
  }
}

type SessionTimeInteraction = ReturnType<typeof useSessionTimeInteraction>

export function SignalInspector({
  session,
  dataSource,
  initialWindow = null,
  onBookmarksChanged,
}: {
  session: SessionRecord
  dataSource: LibraryDataSource
  initialWindow?: { startS: number; endS: number } | null
  onBookmarksChanged?: (session: SessionRecord) => void
}) {
  const durationS = Math.max(1, session.gpsSummary.sessionDurationS || session.durationMin * 60 || 1)
  const signalOptions = useMemo(() => inspectorSignalOptions(session), [session])
  const signalOptionLabels = useMemo(() => duplicateAwareSignalLabels(signalOptions), [signalOptions])
  const signalOptionColumns = useMemo(() => new Set(signalOptions.map((signal) => signal.column)), [signalOptions])
  const initialColumns = useMemo(
    () => loadStoredSignalColumns(session, signalOptionColumns) ?? defaultSignalColumns(signalOptions),
    [session.libraryId, session.sessionKey, signalOptionColumns, signalOptions],
  )
  const initialViewPreferences = useMemo(() => loadStoredViewPreferences(), [])
  const [chartMode, setChartMode] = useState<SignalInspectorChartMode>(() => loadStoredChartMode())
  const [selectedColumns, setSelectedColumns] = useState<string[]>(initialColumns)
  const initialPinnedTimeS = useMemo(
    () => loadStoredPinnedTime(session, durationS),
    [durationS, session.libraryId, session.sessionKey],
  )
  const timeInteraction = useSessionTimeInteraction({ durationS, initialWindow, initialPinnedTimeS })
  const { activeWindow, pinnedTimeS, selectedEventId } = timeInteraction
  const [bookmarks, setBookmarks] = useState<SessionBookmarkRecord[]>([])
  const [activeBookmarkId, setActiveBookmarkId] = useState<string | null>(null)
  const [bookmarkTitle, setBookmarkTitle] = useState('')
  const [bookmarkPointTitle, setBookmarkPointTitle] = useState('')
  const [bookmarkContextMenu, setBookmarkContextMenu] = useState<{ bookmark: SessionBookmarkRecord; x: number; y: number } | null>(null)
  const [editingBookmarkId, setEditingBookmarkId] = useState<string | null>(null)
  const [savingBookmarkId, setSavingBookmarkId] = useState<string | null>(null)
  const [bookmarkMessage, setBookmarkMessage] = useState('')
  const [showMarks, setShowMarks] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(initialViewPreferences.sidebarOpen)
  const [controlsOpen, setControlsOpen] = useState(initialViewPreferences.controlsOpen)
  const [sidebarWidthPx, setSidebarWidthPx] = useState(initialViewPreferences.sidebarWidthPx)
  const [collapsedSidebarPanels, setCollapsedSidebarPanels] = useState<Record<SidebarPanelKey, boolean>>({
    ...initialViewPreferences.collapsedSidebarPanels,
  })
  const [gpsMapHeightPx, setGpsMapHeightPx] = useState(initialViewPreferences.gpsMapHeightPx)
  const [videoHeightPx, setVideoHeightPx] = useState(initialViewPreferences.videoHeightPx)
  const [showEventDetails, setShowEventDetails] = useState(initialViewPreferences.showEventDetails)
  const [videoSettingsCollapsed, setVideoSettingsCollapsed] = useState(initialViewPreferences.videoSettingsCollapsed)
  const [videoScrollWithPlayback, setVideoScrollWithPlayback] = useState(initialViewPreferences.videoScrollWithPlayback)
  const [loadState, setLoadState] = useState<LoadState>({
    status: 'idle',
    message: signalOptions.length ? 'Choose signals to inspect.' : 'No signal catalog is available for this session.',
  })
  const [visibleEventGroups, setVisibleEventGroups] = useState<string[]>([])
  const [eventGroups, setEventGroups] = useState<EventGroup[]>([])
  const [navigatorState, setNavigatorState] = useState<LoadState>({
    status: 'idle',
    message: 'Navigator not loaded.',
  })
  const [videoState, setVideoState] = useState<VideoPanelState>({
    status: 'idle',
    message: dataSource.loadSessionVideoAttachments ? 'Video attachments not loaded.' : 'Video attachments are not available from this data source.',
    data: null,
  })
  const [activeVideoId, setActiveVideoId] = useState('')
  const [videoScrubToCursor, setVideoScrubToCursor] = useState(false)
  const [videoMessage, setVideoMessage] = useState('')
  const [videoPlaybackSessionTimeS, setVideoPlaybackSessionTimeS] = useState<number | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const videoSeekFrameRef = useRef<number | null>(null)
  const videoFollowFrameRef = useRef<number | null>(null)
  const latestRequestWindowRef = useRef<SessionTimeWindow | null>(null)
  const latestSignalRequestSignatureRef = useRef('')
  const signalFetchInFlightRef = useRef<{ window: SessionTimeWindow; signature: string } | null>(null)
  const sidebarResizeRef = useRef<{ pointerId: number; startClientX: number; startWidthPx: number } | null>(null)
  const eventGroupsInitializedRef = useRef(false)
  const bookmarkContextMenuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setSelectedColumns(loadStoredSignalColumns(session, signalOptionColumns) ?? defaultSignalColumns(signalOptions))
    timeInteraction.reset(initialWindow, loadStoredPinnedTime(session, durationS))
    setActiveBookmarkId(null)
    setBookmarkTitle('')
    setBookmarkPointTitle('')
    setBookmarkContextMenu(null)
    setEditingBookmarkId(null)
    setSavingBookmarkId(null)
    setBookmarkMessage('')
    setShowMarks(true)
    setEventGroups([])
    setVisibleEventGroups([])
    setVideoState({
      status: 'idle',
      message: dataSource.loadSessionVideoAttachments ? 'Video attachments not loaded.' : 'Video attachments are not available from this data source.',
      data: null,
    })
    setActiveVideoId('')
    setVideoScrubToCursor(false)
    setVideoMessage('')
    setVideoPlaybackSessionTimeS(null)
    eventGroupsInitializedRef.current = false
  }, [durationS, initialWindow?.endS, initialWindow?.startS, session.libraryId, session.sessionKey, signalOptionColumns, signalOptions])

  useEffect(() => {
    storePinnedTime(session, pinnedTimeS)
  }, [pinnedTimeS, session.libraryId, session.sessionKey])

  useEffect(() => {
    storeChartMode(chartMode)
  }, [chartMode])

  useEffect(() => {
    storeSignalColumns(session, selectedColumns.filter((column) => signalOptionColumns.has(column)))
  }, [selectedColumns, session.libraryId, session.sessionKey, signalOptionColumns])

  useEffect(() => {
    storeViewPreferences({
      sidebarOpen,
      controlsOpen,
      sidebarWidthPx,
      collapsedSidebarPanels,
      gpsMapHeightPx,
      videoHeightPx,
      showEventDetails,
      videoSettingsCollapsed,
      videoScrollWithPlayback,
    })
  }, [
    collapsedSidebarPanels,
    controlsOpen,
    gpsMapHeightPx,
    showEventDetails,
    sidebarOpen,
    sidebarWidthPx,
    videoHeightPx,
    videoScrollWithPlayback,
    videoSettingsCollapsed,
  ])

  useEffect(() => {
    function handlePointerMove(event: globalThis.PointerEvent) {
      const drag = sidebarResizeRef.current
      if (!drag) {
        return
      }
      const nextWidth = drag.startWidthPx + event.clientX - drag.startClientX
      setSidebarWidthPx(clamp(nextWidth, SIGNAL_INSPECTOR_SIDEBAR_MIN_WIDTH_PX, SIGNAL_INSPECTOR_SIDEBAR_MAX_WIDTH_PX))
    }

    function handlePointerUp(event: globalThis.PointerEvent) {
      const drag = sidebarResizeRef.current
      if (!drag || event.pointerId !== drag.pointerId) {
        return
      }
      sidebarResizeRef.current = null
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [])

  const requestWindow = sanitizeWindow(activeWindow.startS, activeWindow.endS, durationS)
  latestRequestWindowRef.current = requestWindow
  const displayedWindowData = loadStateData(loadState)
  const visibleWarnings = displayedWindowData
    ? visibleWindowWarnings(displayedWindowData.warnings, requestWindow, durationS)
    : []
  const bookmarkWindow = {
    startS: sanitizeWindowBoundary(activeWindow.startS, durationS),
    endS: sanitizeWindowBoundary(activeWindow.endS, durationS),
  }
  const navigatorColumns = useMemo(() => {
    const defaults = defaultSignalColumns(signalOptions)
    return defaults.length > 0 ? defaults.slice(0, 2) : selectedColumns.slice(0, 1)
  }, [selectedColumns, signalOptions])
  const navigatorColumnKey = navigatorColumns.join('|')
  const eventSignalColumn = navigatorColumns[0] ?? selectedColumns[0] ?? ''
  const sortedBookmarks = useMemo(
    () => [...bookmarks].sort((a, b) => a.window.startS - b.window.startS || a.title.localeCompare(b.title)),
    [bookmarks],
  )
  const videoAttachmentsData = videoStateData(videoState)
  const videoAttachments = videoAttachmentsData?.attachments ?? []
  const activeVideo =
    videoAttachments.find((attachment) => attachment.attachmentId === activeVideoId) ??
    videoAttachments.find((attachment) => attachment.enabled) ??
    videoAttachments[0] ??
    null
  const activeVideoStreamUrl =
    activeVideo && dataSource.sessionVideoStreamUrl ? dataSource.sessionVideoStreamUrl(session, activeVideo.attachmentId) : ''
  const activeBookmarkIndex = activeBookmarkId
    ? sortedBookmarks.findIndex((bookmark) => bookmark.id === activeBookmarkId)
    : -1

  useEffect(() => {
    let cancelled = false
    async function loadBookmarks() {
      setBookmarkMessage('Loading bookmarks...')
      try {
        const loaded = await dataSource.listSessionBookmarks(session)
        if (!cancelled) {
          setBookmarks(loaded)
          setBookmarkMessage('')
        }
      } catch (error) {
        if (!cancelled) {
          setBookmarks([])
          setBookmarkMessage(error instanceof Error ? `Could not load bookmarks: ${error.message}` : 'Could not load bookmarks.')
        }
      }
    }
    void loadBookmarks()
    return () => {
      cancelled = true
    }
  }, [dataSource, session])

  useEffect(() => {
    let cancelled = false
    async function loadVideos() {
      if (!dataSource.loadSessionVideoAttachments) {
        setVideoState({ status: 'idle', message: 'Video attachments are not available from this data source.', data: null })
        return
      }
      setVideoState((current) => ({
        status: 'loading',
        message: 'Loading video attachments...',
        data: videoStateData(current),
      }))
      try {
        const loaded = await dataSource.loadSessionVideoAttachments(session)
        if (cancelled) {
          return
        }
        setVideoState({ status: 'ready', message: 'Video attachments loaded.', data: loaded })
        setActiveVideoId((current) => {
          if (current && loaded.attachments.some((attachment) => attachment.attachmentId === current)) {
            return current
          }
          return loaded.attachments.find((attachment) => attachment.enabled)?.attachmentId ?? loaded.attachments[0]?.attachmentId ?? ''
        })
        setVideoMessage('')
      } catch (error) {
        if (!cancelled) {
          setVideoState({ status: 'error', message: error instanceof Error ? error.message : String(error), data: null })
        }
      }
    }

    void loadVideos()
    return () => {
      cancelled = true
    }
  }, [dataSource, session])

  useEffect(() => {
    if (!bookmarkContextMenu) {
      return
    }

    function handlePointerDown(event: globalThis.PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }
      if (bookmarkContextMenuRef.current?.contains(target)) {
        return
      }
      setBookmarkContextMenu(null)
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setBookmarkContextMenu(null)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [bookmarkContextMenu])

  useEffect(() => {
    let cancelled = false
    async function loadWindow() {
      if (selectedColumns.length === 0) {
        setLoadState({ status: 'idle', message: 'Select one or more signals to inspect.' })
        return
      }
      const useBufferedWindow = videoScrollWithPlayback && Boolean(activeVideo)
      const requestSignature = signalWindowRequestSignature(session, selectedColumns, useBufferedWindow)
      latestSignalRequestSignatureRef.current = requestSignature
      const fetchWindow = useBufferedWindow ? bufferedSignalFetchWindow(requestWindow, durationS) : requestWindow
      const targetPoints = signalWindowTargetPoints(requestWindow, fetchWindow)
      const loadedData = loadStateData(loadState)
      const loadedCoverage = timeseriesDataCoverage(loadedData)
      const loadedWindowIsReady =
        timeseriesDataMatchesSelectedSignals(loadedData, selectedColumns) &&
        loadedCoverage &&
        (useBufferedWindow
          ? windowHasPlaybackRunway(loadedCoverage, requestWindow, durationS)
          : windowContains(loadedCoverage, requestWindow)) &&
        timeseriesDataMeetsResolution(loadedData, targetPoints)
      if (
        loadedWindowIsReady
      ) {
        return
      }
      const pendingRequest = signalFetchInFlightRef.current
      if (
        pendingRequest &&
        pendingRequest.signature === requestSignature &&
        (useBufferedWindow
          ? windowHasPlaybackRunway(pendingRequest.window, requestWindow, durationS)
          : windowContains(pendingRequest.window, requestWindow))
      ) {
        return
      }
      const fetchRequest = { window: fetchWindow, signature: requestSignature }
      signalFetchInFlightRef.current = fetchRequest
      setLoadState((current) => {
        const data = loadStateData(current)
        return data
          ? { status: 'loading', message: 'Updating signal window...', data }
          : { status: 'loading', message: 'Loading signal window...' }
      })
      try {
        const data = await dataSource.loadTimeseriesWindow(session.libraryId, {
          session: sessionToStudyRef(session),
          signals: selectedColumns.map((column) => ({ column })),
          window: fetchWindow,
          resolution: { targetPoints },
          includeEvents: true,
          includeMarks: true,
        })
        const currentRequestWindow = latestRequestWindowRef.current ?? requestWindow
        const returnedCoverage = timeseriesDataCoverage(data) ?? fetchWindow
        // React can re-run this effect while the same request is still in flight.
        // Accept its result when it still covers the live window; otherwise the
        // replacement effect may wait on a request whose cancelled caller drops it.
        const resultStillUseful =
          requestSignature === latestSignalRequestSignatureRef.current &&
          windowContains(returnedCoverage, currentRequestWindow)
        if (!cancelled || resultStillUseful) {
          setLoadState({ status: 'ready', message: 'Signal window loaded.', data })
        }
      } catch (error) {
        if (!cancelled) {
          setLoadState((current) => {
            const data = loadStateData(current)
            const message = error instanceof Error ? error.message : String(error)
            return data ? { status: 'error', message, data } : { status: 'error', message }
          })
        }
      }
      if (signalFetchInFlightRef.current === fetchRequest) {
        signalFetchInFlightRef.current = null
      }
    }

    void loadWindow()
    return () => {
      cancelled = true
    }
  }, [
    activeVideo,
    dataSource,
    durationS,
    requestWindow.endS,
    requestWindow.startS,
    selectedColumns,
    session,
    videoScrollWithPlayback,
  ])

  const markCount = displayedWindowData?.marks.length ?? 0
  const fallbackEventGroups = useMemo(
    () => (displayedWindowData ? groupEvents(displayedWindowData.events) : []),
    [displayedWindowData],
  )
  const effectiveEventGroups = eventGroups.length > 0 ? eventGroups : fallbackEventGroups

  useEffect(() => {
    let cancelled = false
    async function loadFullSessionEvents() {
      if (!eventSignalColumn) {
        setEventGroups([])
        setVisibleEventGroups([])
        eventGroupsInitializedRef.current = false
        return
      }
      try {
        const data = await dataSource.loadTimeseriesWindow(session.libraryId, {
          session: sessionToStudyRef(session),
          signals: [{ column: eventSignalColumn }],
          window: { startS: 0, endS: durationS },
          resolution: { targetPoints: 2 },
          includeEvents: true,
          includeMarks: false,
        })
        if (cancelled) {
          return
        }
        const groups = groupEvents(data.events)
        setEventGroups(groups)
        setVisibleEventGroups((current) => {
          const validKeys = new Set(groups.map((group) => group.key))
          if (!eventGroupsInitializedRef.current) {
            eventGroupsInitializedRef.current = true
            return groups.filter((group) => !group.dense).map((group) => group.key)
          }
          return current.filter((groupKey) => validKeys.has(groupKey))
        })
      } catch {
        if (!cancelled) {
          setEventGroups([])
        }
      }
    }

    void loadFullSessionEvents()
    return () => {
      cancelled = true
    }
  }, [dataSource, durationS, eventSignalColumn, session.libraryId, session.sessionKey])

  useEffect(() => {
    if (eventGroups.length > 0 || fallbackEventGroups.length === 0) {
      return
    }
    setVisibleEventGroups((current) => {
      const validKeys = new Set(fallbackEventGroups.map((group) => group.key))
      if (!eventGroupsInitializedRef.current) {
        eventGroupsInitializedRef.current = true
        return fallbackEventGroups.filter((group) => !group.dense).map((group) => group.key)
      }
      return current.filter((groupKey) => validKeys.has(groupKey))
    })
  }, [eventGroups.length, fallbackEventGroups])

  useEffect(() => {
    let cancelled = false
    async function loadNavigator() {
      if (navigatorColumns.length === 0) {
        setNavigatorState({ status: 'idle', message: 'No displacement signal is available for navigation.' })
        return
      }
      setNavigatorState({ status: 'loading', message: 'Loading full-session navigator...' })
      try {
        const data = await dataSource.loadTimeseriesWindow(session.libraryId, {
          session: sessionToStudyRef(session),
          signals: navigatorColumns.map((column) => ({ column })),
          window: { startS: 0, endS: durationS },
          resolution: { targetPoints: NAVIGATOR_POINTS },
          includeEvents: false,
          includeMarks: false,
        })
        if (!cancelled) {
          setNavigatorState({ status: 'ready', message: 'Navigator loaded.', data })
        }
      } catch (error) {
        if (!cancelled) {
          setNavigatorState({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        }
      }
    }

    void loadNavigator()
    return () => {
      cancelled = true
    }
  }, [dataSource, durationS, navigatorColumnKey, session.libraryId, session.sessionKey])

  useEffect(() => {
    const data = loadStateData(loadState)
    if (!data) {
      timeInteraction.setSelectedEventId(null)
      return
    }
    timeInteraction.setSelectedEventId((current) =>
      current && data.events.some((event) => event.eventId === current) ? current : null,
    )
  }, [loadState])

  useEffect(() => {
    setActiveBookmarkId((current) => {
      const bookmark = current ? bookmarks.find((candidate) => candidate.id === current) : null
      if (
        bookmark &&
        nearlyEqual(bookmark.window.startS, bookmarkWindow.startS) &&
        nearlyEqual(bookmark.window.endS, bookmarkWindow.endS) &&
        sameStringSet(bookmark.viewState.signalInspector?.signalColumns ?? [], selectedColumns) &&
        (bookmark.viewState.signalInspector?.showMarks ?? true) === showMarks
      ) {
        return current
      }
      return null
    })
  }, [bookmarks, bookmarkWindow.endS, bookmarkWindow.startS, selectedColumns, showMarks])

  useEffect(() => {
    if (!videoScrubToCursor || !activeVideo || timeInteraction.hoverTimeS === null) {
      return
    }
    const video = videoRef.current
    if (!video || !video.paused) {
      return
    }
    const targetVideoTimeS = Math.max(0, timeInteraction.hoverTimeS - activeVideo.sessionTimeAtVideoZeroS)
    if (!Number.isFinite(targetVideoTimeS) || Math.abs(video.currentTime - targetVideoTimeS) < 0.04) {
      return
    }
    if (videoSeekFrameRef.current !== null) {
      cancelAnimationFrame(videoSeekFrameRef.current)
    }
    videoSeekFrameRef.current = requestAnimationFrame(() => {
      videoSeekFrameRef.current = null
      if (videoRef.current && videoRef.current.paused) {
        videoRef.current.currentTime = targetVideoTimeS
      }
    })
    return () => {
      if (videoSeekFrameRef.current !== null) {
        cancelAnimationFrame(videoSeekFrameRef.current)
        videoSeekFrameRef.current = null
      }
    }
  }, [activeVideo?.attachmentId, activeVideo?.sessionTimeAtVideoZeroS, timeInteraction.hoverTimeS, videoScrubToCursor])

  useEffect(() => {
    if (!videoScrollWithPlayback || !activeVideo) {
      return
    }
    let cancelled = false

    function tick() {
      if (cancelled) {
        return
      }
      const video = videoRef.current
      if (video && !video.paused && !video.ended) {
        syncSignalWindowToVideoPlayback()
      }
      videoFollowFrameRef.current = requestAnimationFrame(tick)
    }

    videoFollowFrameRef.current = requestAnimationFrame(tick)
    return () => {
      cancelled = true
      if (videoFollowFrameRef.current !== null) {
        cancelAnimationFrame(videoFollowFrameRef.current)
        videoFollowFrameRef.current = null
      }
    }
  }, [
    activeVideo?.attachmentId,
    activeVideo?.sessionTimeAtVideoZeroS,
    durationS,
    loadState.status,
    requestWindow.endS,
    requestWindow.startS,
    videoScrollWithPlayback,
  ])

  useEffect(() => {
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.repeat || !isSpaceKey(event) || isEditableKeyboardTarget(event.target)) {
        return
      }
      const video = videoRef.current
      if (!activeVideo || !video) {
        return
      }
      event.preventDefault()
      if (video.paused || video.ended) {
        video.play().catch((error: unknown) => {
          setVideoMessage(error instanceof Error ? `Could not start video playback: ${error.message}` : 'Could not start video playback.')
        })
      } else {
        video.pause()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [activeVideo])

  function toggleColumn(column: string) {
    setSelectedColumns((current) =>
      current.includes(column) ? current.filter((item) => item !== column) : [...current, column],
    )
  }

  function toggleEventGroup(groupKey: string) {
    setVisibleEventGroups((current) =>
      current.includes(groupKey) ? current.filter((item) => item !== groupKey) : [...current, groupKey],
    )
  }

  function seekActiveVideoToSessionTime(timeS: number) {
    if (!activeVideo || !videoRef.current) {
      return
    }
    const videoTimeS = Math.max(0, sanitizeWindowBoundary(timeS, durationS) - activeVideo.sessionTimeAtVideoZeroS)
    if (Number.isFinite(videoTimeS)) {
      videoRef.current.currentTime = videoTimeS
    }
  }

  function playActiveVideoFromSessionTime(timeS: number) {
    seekActiveVideoToSessionTime(timeS)
    const video = videoRef.current
    if (!video) {
      return
    }
    video.play().catch((error: unknown) => {
      setVideoMessage(error instanceof Error ? `Could not start video playback: ${error.message}` : 'Could not start video playback.')
    })
  }

  async function syncActiveVideoToPinnedTime() {
    if (!activeVideo || !videoRef.current || pinnedTimeS === null) {
      return
    }
    if (!dataSource.saveSessionVideoAttachments) {
      setVideoMessage('This data source does not support video attachment edits.')
      return
    }
    const nextOffsetS = roundForInput(sanitizeWindowBoundary(pinnedTimeS, durationS) - videoRef.current.currentTime)
    await updateVideoAttachment(activeVideo.attachmentId, {
      displayName: activeVideo.displayName,
      cameraLabel: activeVideo.cameraLabel,
      path: videoAttachmentPathValue(activeVideo),
      sessionTimeAtVideoZeroS: nextOffsetS,
    })
    timeInteraction.setHoverTimeS(sanitizeWindowBoundary(pinnedTimeS, durationS))
  }

  function syncSignalWindowToVideoPlayback() {
    if (!activeVideo || !videoRef.current) {
      return
    }
    const sessionTimeS = videoRef.current.currentTime + activeVideo.sessionTimeAtVideoZeroS
    if (!Number.isFinite(sessionTimeS)) {
      return
    }
    const boundedSessionTimeS = sanitizeWindowBoundary(sessionTimeS, durationS)
    setVideoPlaybackSessionTimeS(boundedSessionTimeS)
    if (sessionTimeS > durationS) {
      videoRef.current.pause()
      timeInteraction.setHoverTimeS(durationS)
      return
    }
    if (videoScrollWithPlayback && !videoRef.current.paused) {
      const windowSizeS = Math.max(0.1, requestWindow.endS - requestWindow.startS)
      const maxStartS = Math.max(0, durationS - windowSizeS)
      const nextStartS = clamp(sessionTimeS - windowSizeS / 2, 0, maxStartS)
      const nextEndS = Math.min(durationS, nextStartS + windowSizeS)
      if (Math.abs(nextStartS - requestWindow.startS) > 0.03 || Math.abs(nextEndS - requestWindow.endS) > 0.03) {
        timeInteraction.setWindow({ startS: nextStartS, endS: nextEndS })
      }
      timeInteraction.setHoverTimeS(boundedSessionTimeS)
      return
    }
    if (sessionTimeS > requestWindow.endS) {
      videoRef.current.currentTime = Math.max(0, requestWindow.endS - activeVideo.sessionTimeAtVideoZeroS)
      videoRef.current.pause()
      timeInteraction.setHoverTimeS(requestWindow.endS)
      return
    }
    if (sessionTimeS < requestWindow.startS && !videoRef.current.paused) {
      videoRef.current.currentTime = Math.max(0, requestWindow.startS - activeVideo.sessionTimeAtVideoZeroS)
      timeInteraction.setHoverTimeS(requestWindow.startS)
      return
    }
    timeInteraction.setHoverTimeS(boundedSessionTimeS)
  }

  function handleVideoTimeUpdate() {
    syncSignalWindowToVideoPlayback()
  }

  async function saveVideoAttachments(nextAttachments: SessionVideoAttachmentRecord[], pendingMessage: string) {
    if (!dataSource.saveSessionVideoAttachments) {
      setVideoMessage('This data source does not support video attachment edits.')
      return
    }
    const currentData =
      videoAttachmentsData ?? {
        sessionRef: sessionToStudyRef(session),
        present: false,
        revision: 0,
        attachments: [],
        createdAtUtc: '',
        updatedAtUtc: '',
      }
    setVideoMessage(pendingMessage)
    try {
      const saved = await dataSource.saveSessionVideoAttachments({
        ...currentData,
        present: true,
        attachments: nextAttachments,
      })
      setVideoState({ status: 'ready', message: 'Video attachments loaded.', data: saved })
      setActiveVideoId((current) => {
        if (current && saved.attachments.some((attachment) => attachment.attachmentId === current)) {
          return current
        }
        return saved.attachments.find((attachment) => attachment.enabled)?.attachmentId ?? saved.attachments[0]?.attachmentId ?? ''
      })
      setVideoMessage('')
    } catch (error) {
      setVideoMessage(error instanceof Error ? `Could not save video attachment: ${error.message}` : 'Could not save video attachment.')
    }
  }

  async function addVideoAttachment(input: VideoAttachmentInput) {
    const trimmedPath = input.path.trim()
    if (!trimmedPath) {
      setVideoMessage('Enter a video path before saving.')
      return
    }
    const attachment: SessionVideoAttachmentRecord = {
      attachmentId: makeVideoAttachmentId(),
      displayName: input.displayName.trim() || 'Session video',
      cameraLabel: input.cameraLabel.trim(),
      path: isAbsoluteLocalPath(trimmedPath) ? trimmedPath : '',
      workspaceRelativePath: isAbsoluteLocalPath(trimmedPath) ? '' : trimmedPath,
      libraryRelativePath: '',
      sessionRelativePath: '',
      uri: '',
      mediaType: 'video/mp4',
      enabled: true,
      sessionTimeAtVideoZeroS: Number.isFinite(input.sessionTimeAtVideoZeroS) ? input.sessionTimeAtVideoZeroS : 0,
    }
    const nextAttachments = videoAttachments.map((existing) => ({ ...existing, enabled: false })).concat(attachment)
    setActiveVideoId(attachment.attachmentId)
    await saveVideoAttachments(nextAttachments, 'Saving video attachment...')
  }

  async function updateVideoAttachment(attachmentId: string, input: VideoAttachmentInput) {
    const trimmedPath = input.path.trim()
    if (!trimmedPath) {
      setVideoMessage('Enter a video path before saving.')
      return
    }
    const nextAttachments = videoAttachments.map((attachment) =>
      attachment.attachmentId === attachmentId
        ? {
            ...attachment,
            displayName: input.displayName.trim() || attachment.displayName || 'Session video',
            cameraLabel: input.cameraLabel.trim(),
            path: isAbsoluteLocalPath(trimmedPath) ? trimmedPath : '',
            workspaceRelativePath: isAbsoluteLocalPath(trimmedPath) ? '' : trimmedPath,
            libraryRelativePath: '',
            sessionRelativePath: '',
            sessionTimeAtVideoZeroS: Number.isFinite(input.sessionTimeAtVideoZeroS) ? input.sessionTimeAtVideoZeroS : 0,
          }
        : attachment,
    )
    await saveVideoAttachments(nextAttachments, 'Saving video attachment...')
  }

  async function deleteVideoAttachment(attachmentId: string) {
    const attachment = videoAttachments.find((candidate) => candidate.attachmentId === attachmentId)
    const label = attachment?.displayName || attachment?.cameraLabel || attachmentId
    if (!window.confirm(`Delete video attachment "${label}" from this session? The video file itself will not be deleted.`)) {
      return
    }
    const nextAttachments = videoAttachments.filter((candidate) => candidate.attachmentId !== attachmentId)
    await saveVideoAttachments(nextAttachments, 'Deleting video attachment...')
  }

  async function saveBookmark(kind: 'window' | 'point') {
    if (kind === 'point' && pinnedTimeS === null) {
      setBookmarkMessage('Pin a time before saving a point bookmark.')
      return
    }
    const pointS = sanitizeWindowBoundary(pinnedTimeS ?? activeWindow.startS, durationS)
    const window =
      kind === 'point'
        ? { startS: pointS, endS: pointS }
        : { startS: requestWindow.startS, endS: requestWindow.endS }
    const title =
      (kind === 'point' ? bookmarkPointTitle.trim() : bookmarkTitle.trim()) ||
      (kind === 'point' ? `Point ${formatTime(pointS)}` : `Window ${formatTime(window.startS)}-${formatTime(window.endS)}`)
    const bookmark: SessionBookmarkRecord = {
      id: '',
      revision: 0,
      title,
      description: '',
      sessionRef: sessionToStudyRef(session),
      window,
      viewState: {
        signalInspector: {
          signalColumns: [...selectedColumns],
          showMarks,
        },
      },
      tags: [],
      private: true,
      createdAtUtc: '',
      updatedAtUtc: '',
    }
    setBookmarkMessage(kind === 'point' ? 'Saving point bookmark...' : 'Saving window bookmark...')
    try {
      const saved = await dataSource.saveSessionBookmark(bookmark)
      setBookmarks((current) => [...current.filter((candidate) => candidate.id !== saved.id), saved])
      setActiveBookmarkId(saved.id)
      if (kind === 'point') {
        setBookmarkPointTitle('')
      } else {
        setBookmarkTitle('')
      }
      setBookmarkMessage('')
      onBookmarksChanged?.(session)
    } catch (error) {
      setBookmarkMessage(error instanceof Error ? `Could not save bookmark: ${error.message}` : 'Could not save bookmark.')
    }
  }

  function applyBookmark(bookmark: SessionBookmarkRecord) {
    timeInteraction.setWindow(bookmark.window)
    timeInteraction.setPinnedTime(bookmark.window.startS)
    seekActiveVideoToSessionTime(bookmark.window.startS)
    const restoredColumns = (bookmark.viewState.signalInspector?.signalColumns ?? []).filter((column) =>
      signalOptionColumns.has(column),
    )
    if (restoredColumns.length > 0) {
      setSelectedColumns(restoredColumns)
    }
    setShowMarks(bookmark.viewState.signalInspector?.showMarks ?? true)
    setActiveBookmarkId(bookmark.id)
  }

  async function deleteBookmark(bookmarkId: string) {
    const existing = bookmarks
    setBookmarks((current) => current.filter((bookmark) => bookmark.id !== bookmarkId))
    setActiveBookmarkId((current) => (current === bookmarkId ? null : current))
    setBookmarkMessage('Deleting bookmark...')
    try {
      await dataSource.deleteSessionBookmark(bookmarkId)
      setBookmarkMessage('')
      onBookmarksChanged?.(session)
    } catch (error) {
      setBookmarks(existing)
      setBookmarkMessage(error instanceof Error ? `Could not delete bookmark: ${error.message}` : 'Could not delete bookmark.')
    }
  }

  async function renameBookmark(bookmark: SessionBookmarkRecord, title: string) {
    const trimmedTitle = title.trim()
    if (!trimmedTitle || trimmedTitle === bookmark.title) {
      setEditingBookmarkId(null)
      setSavingBookmarkId(null)
      return
    }
    setSavingBookmarkId(bookmark.id)
    setBookmarkMessage('Renaming bookmark...')
    try {
      const saved = await dataSource.saveSessionBookmark({ ...bookmark, title: trimmedTitle })
      setBookmarks((current) => current.map((candidate) => (candidate.id === saved.id ? saved : candidate)))
      setEditingBookmarkId(null)
      setSavingBookmarkId(null)
      setBookmarkMessage('')
      onBookmarksChanged?.(session)
    } catch (error) {
      setSavingBookmarkId(null)
      setBookmarkMessage(error instanceof Error ? `Could not rename bookmark: ${error.message}` : 'Could not rename bookmark.')
    }
  }

  function goToAdjacentBookmark(direction: -1 | 1) {
    if (sortedBookmarks.length === 0) {
      return
    }
    if (activeBookmarkIndex >= 0) {
      const nextIndex = clamp(activeBookmarkIndex + direction, 0, sortedBookmarks.length - 1)
      applyBookmark(sortedBookmarks[nextIndex])
      return
    }
    const nextBookmark =
      direction > 0
        ? sortedBookmarks.find((bookmark) => bookmark.window.startS > requestWindow.startS) ?? sortedBookmarks[0]
        : [...sortedBookmarks].reverse().find((bookmark) => bookmark.window.startS < requestWindow.startS) ??
          sortedBookmarks[sortedBookmarks.length - 1]
    applyBookmark(nextBookmark)
  }

  function toggleSidebarPanel(panel: SidebarPanelKey) {
    setCollapsedSidebarPanels((current) => ({
      ...current,
      [panel]: !current[panel],
    }))
  }

  function beginSidebarResize(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    sidebarResizeRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startWidthPx: sidebarWidthPx,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const layoutStyle = sidebarOpen
    ? ({ '--signal-inspector-sidebar-width': `${sidebarWidthPx}px` } as CSSProperties)
    : undefined

  return (
    <div className="signal-inspector">
      <div
        className={`signal-inspector-layout${sidebarOpen ? '' : ' sidebar-collapsed'}${
          controlsOpen ? '' : ' controls-collapsed'
        }`}
        style={layoutStyle}
      >
        {sidebarOpen ? (
        <aside className="signal-inspector-sidebar">
          <div className="signal-inspector-control-panel-header signal-inspector-sidebar-header">
            <strong>Bookmarks, GPS and Video</strong>
            <button aria-label="Collapse bookmarks, GPS and video" type="button" onClick={() => setSidebarOpen(false)}>
              <ChevronLeft size={15} />
            </button>
          </div>
          <section className="signal-inspector-card">
            <div className="signal-inspector-card-header">
              <h3>
                Bookmarks
                <InfoTip text="Save bookmarks to return to windows or exact points while inspecting this session." />
              </h3>
              <div className="signal-inspector-card-actions">
                <small>{sortedBookmarks.length} saved</small>
                <button
                  aria-label={collapsedSidebarPanels.bookmarks ? 'Expand bookmarks' : 'Collapse bookmarks'}
                  type="button"
                  onClick={() => toggleSidebarPanel('bookmarks')}
                >
                  {collapsedSidebarPanels.bookmarks ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
                </button>
              </div>
            </div>
            {!collapsedSidebarPanels.bookmarks && (
              <div className="signal-inspector-card-body">
                <div className="signal-inspector-save-row">
                  <input
                    type="text"
                    value={bookmarkTitle}
                    onChange={(event) => setBookmarkTitle(event.target.value)}
                    placeholder={`Bookmark ${formatTime(requestWindow.startS)}-${formatTime(requestWindow.endS)}`}
                  />
                  <button type="button" onClick={() => saveBookmark('window')} disabled={selectedColumns.length === 0}>
                    <Save size={14} />
                    Save window
                  </button>
                </div>
                <div className="signal-inspector-point-row">
                  <input
                    aria-label="Point bookmark name"
                    type="text"
                    value={bookmarkPointTitle}
                    onChange={(event) => setBookmarkPointTitle(event.target.value)}
                    placeholder={`Point ${pinnedTimeS === null ? 'unpinned' : formatTime(pinnedTimeS)}`}
                  />
                  <input
                    aria-label="Pinned time in seconds"
                    min={0}
                    max={durationS}
                    step={0.1}
                    type="number"
                    value={pinnedTimeS === null ? '' : roundForInput(pinnedTimeS)}
                    onChange={(event) => timeInteraction.setPinnedTime(event.target.value === '' ? null : Number(event.target.value))}
                    placeholder="Pin time"
                  />
                  <button type="button" onClick={() => saveBookmark('point')} disabled={selectedColumns.length === 0 || pinnedTimeS === null}>
                    Save point
                  </button>
                </div>
                <div className="signal-inspector-pinned-row compact">
                  <span>Pinned time {pinnedTimeS === null ? 'not set' : formatTime(pinnedTimeS)}</span>
                  <button type="button" onClick={() => timeInteraction.setPinnedTime(null)} disabled={pinnedTimeS === null}>
                    Clear
                  </button>
                </div>
                {bookmarkMessage && <p className="signal-inspector-bookmark-message">{bookmarkMessage}</p>}
                {sortedBookmarks.length === 0 ? (
                  <p>No bookmarks yet.</p>
                ) : (
                  <div className="signal-inspector-bookmark-list">
                    {sortedBookmarks.map((bookmark) => (
                      <div
                        className={bookmark.id === activeBookmarkId ? 'active' : ''}
                        key={bookmark.id}
                        onContextMenu={(event) => {
                          event.preventDefault()
                          setBookmarkContextMenu({ bookmark, x: event.clientX, y: event.clientY })
                        }}
                      >
                        {editingBookmarkId === bookmark.id ? (
                          <BookmarkRenameInput
                            disabled={savingBookmarkId === bookmark.id}
                            initialValue={bookmark.title}
                            onCancel={() => {
                              setEditingBookmarkId(null)
                              setSavingBookmarkId(null)
                            }}
                            onCommit={(title) => {
                              void renameBookmark(bookmark, title)
                            }}
                          />
                        ) : (
                          <button type="button" onClick={() => applyBookmark(bookmark)}>
                            <strong>{bookmark.title}</strong>
                            <small>{formatBookmarkWindow(bookmark.window)}</small>
                          </button>
                        )}
                        <button
                          aria-label={`Delete bookmark ${bookmark.title}`}
                          className="signal-inspector-delete-bookmark"
                          type="button"
                          onClick={() => deleteBookmark(bookmark.id)}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {bookmarkContextMenu && (
                  <div
                    className="signal-inspector-bookmark-context-menu"
                    ref={bookmarkContextMenuRef}
                    style={{ left: bookmarkContextMenu.x, top: bookmarkContextMenu.y }}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        setEditingBookmarkId(bookmarkContextMenu.bookmark.id)
                        setBookmarkContextMenu(null)
                      }}
                    >
                      Rename bookmark
                    </button>
                  </div>
                )}
                <div className="signal-inspector-bookmark-actions">
                  <button type="button" onClick={() => goToAdjacentBookmark(-1)} disabled={sortedBookmarks.length === 0}>
                    <SkipBack size={14} />
                    Previous
                  </button>
                  <button type="button" onClick={() => goToAdjacentBookmark(1)} disabled={sortedBookmarks.length === 0}>
                    <SkipForward size={14} />
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
          <SignalInspectorGpsPanel
            activeWindow={requestWindow}
            collapsedAltitude={collapsedSidebarPanels.gpsAltitude}
            collapsedMap={collapsedSidebarPanels.gpsMap}
            cursorTimeS={timeInteraction.hoverTimeS}
            dataSource={dataSource}
            mapHeightPx={gpsMapHeightPx}
            onToggleAltitude={() => toggleSidebarPanel('gpsAltitude')}
            onToggleMap={() => toggleSidebarPanel('gpsMap')}
            onMapHeightChange={setGpsMapHeightPx}
            session={session}
            videoHeadTimeS={videoPlaybackSessionTimeS}
          />
          <SignalInspectorVideoPanel
            activeVideo={activeVideo}
            activeVideoId={activeVideoId}
            activeWindow={requestWindow}
            canWrite={Boolean(dataSource.saveSessionVideoAttachments)}
            collapsed={collapsedSidebarPanels.video}
            durationS={durationS}
            message={videoMessage}
            onActiveVideoIdChange={setActiveVideoId}
            onAddAttachment={(input) => {
              void addVideoAttachment(input)
            }}
            onDeleteAttachment={(attachmentId) => {
              void deleteVideoAttachment(attachmentId)
            }}
            onSelectVideoFile={dataSource.selectLocalVideoFile?.bind(dataSource)}
            onSettingsCollapsedChange={setVideoSettingsCollapsed}
            onScrubToCursorChange={setVideoScrubToCursor}
            onScrollWithPlaybackChange={setVideoScrollWithPlayback}
            onPlayFromPinnedTime={() => pinnedTimeS !== null && playActiveVideoFromSessionTime(pinnedTimeS)}
            onSyncToPinnedTime={() => {
              void syncActiveVideoToPinnedTime()
            }}
            onTimeUpdate={handleVideoTimeUpdate}
            onToggleCollapsed={() => toggleSidebarPanel('video')}
            onUpdateAttachment={(attachmentId, input) => {
              void updateVideoAttachment(attachmentId, input)
            }}
            onVideoHeightChange={setVideoHeightPx}
            scrubToCursor={videoScrubToCursor}
            pinnedTimeS={pinnedTimeS}
            sessionStartedAt={session.startedAt}
            settingsCollapsed={videoSettingsCollapsed}
            state={videoState}
            streamUrl={activeVideoStreamUrl}
            videoHeightPx={videoHeightPx}
            videoRef={videoRef}
            scrollWithPlayback={videoScrollWithPlayback}
          />
        </aside>
        ) : (
          <button
            className="signal-inspector-side-rail"
            type="button"
            onClick={() => setSidebarOpen(true)}
            title="Show bookmarks and GPS"
          >
            <ChevronRight size={15} />
            <span>Bookmarks, GPS and Video</span>
          </button>
        )}

        {sidebarOpen && (
          <button
            aria-label="Resize bookmarks and GPS panel"
            className="signal-inspector-sidebar-resizer"
            type="button"
            onPointerDown={beginSidebarResize}
            title="Drag to reallocate space between the sidebar and charts"
          />
        )}

        {controlsOpen ? (
          <aside className="signal-inspector-control-panel">
            <div className="signal-inspector-control-panel-header">
              <strong>Signals and events</strong>
              <button aria-label="Collapse signals and events" type="button" onClick={() => setControlsOpen(false)}>
                <ChevronLeft size={15} />
              </button>
            </div>
          <section className="signal-inspector-card">
            <h3>Chart mode</h3>
            <div className="signal-inspector-mode-toggle">
              <button
                className={chartMode === 'single' ? 'active' : ''}
                type="button"
                onClick={() => setChartMode('single')}
              >
                <strong>Single chart</strong>
                <small>Selected signals share one plot.</small>
              </button>
              <button
                className={chartMode === 'multi' ? 'active' : ''}
                type="button"
                onClick={() => setChartMode('multi')}
              >
                <strong>Multi chart</strong>
                <small>One synchronized chart per signal.</small>
              </button>
            </div>
          </section>
          <section className="signal-inspector-card">
            <h3>Signals</h3>
            {signalOptions.length === 0 ? (
              <p>No signal catalog is available for this session.</p>
            ) : (
              <div className="signal-inspector-check-list">
                {signalOptions.map((signal, index) => (
                  <label key={signal.column}>
                    <input
                      checked={selectedColumns.includes(signal.column)}
                      onChange={() => toggleColumn(signal.column)}
                      type="checkbox"
                    />
                    <span>
                      <strong>{signalOptionLabels[index]}</strong>
                      <small>
                        {[signal.end, signal.quantity, signal.unit].filter(Boolean).join(' / ') || signal.column}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </section>

          <section className="signal-inspector-card">
            <h3>Events</h3>
            <label className="signal-inspector-video-checkbox">
              <input
                checked={showEventDetails}
                onChange={(event) => setShowEventDetails(event.target.checked)}
                type="checkbox"
              />
              <span>Show event details</span>
            </label>
            <div className="signal-inspector-check-list">
              <label>
                <input checked={showMarks} onChange={(event) => setShowMarks(event.target.checked)} type="checkbox" />
                <span>
                  <strong>
                    <i className="signal-inspector-mark-swatch" />
                    Logger marks
                  </strong>
                  <small>
                    {markCount} mark{markCount === 1 ? '' : 's'} in window
                  </small>
                </span>
              </label>
              {effectiveEventGroups.length === 0 ? (
                <p>No event overlays returned for this session.</p>
              ) : effectiveEventGroups.map((group) => (
                  <label key={group.key}>
                    <input
                      checked={visibleEventGroups.includes(group.key)}
                      onChange={() => toggleEventGroup(group.key)}
                      type="checkbox"
                    />
                    <span>
                      <strong>
                        <i style={{ background: group.color }} />
                        {group.label}
                      </strong>
                      <small>
                        {group.count} event{group.count === 1 ? '' : 's'}
                      </small>
                    </span>
                  </label>
                ))
              }
            </div>
          </section>
          </aside>
        ) : (
          <button
            className="signal-inspector-control-rail"
            type="button"
            onClick={() => setControlsOpen(true)}
            title="Show signals and events"
          >
            <ChevronRight size={15} />
            <span>Signals / Events</span>
          </button>
        )}

        <section className="signal-inspector-main">
          <div className="signal-inspector-main-scroll">
            {loadState.status === 'loading' && !displayedWindowData && <div className="signal-inspector-message">{loadState.message}</div>}
            {loadState.status === 'error' && !displayedWindowData && (
              <div className="signal-inspector-message warning">Could not load signals: {loadState.message}</div>
            )}
            {loadState.status === 'idle' && <div className="signal-inspector-message">{loadState.message}</div>}
            {displayedWindowData && (
              <>
                {loadState.status === 'loading' && <div className="signal-inspector-update-pill">{loadState.message}</div>}
                {chartMode === 'multi' ? (
                  <SignalMultiChartStack
                    activeBookmarkId={activeBookmarkId}
                    bookmarks={sortedBookmarks}
                    data={displayedWindowData}
                    durationS={durationS}
                    timeInteraction={timeInteraction}
                    visibleWindow={requestWindow}
                    visibleEventGroups={visibleEventGroups}
                    showMarks={showMarks}
                    eventGroups={effectiveEventGroups}
                    selectedEventId={selectedEventId}
                    videoHeadTimeS={videoPlaybackSessionTimeS}
                    onSelectEvent={timeInteraction.setSelectedEventId}
                  />
                ) : (
                  <SignalWindowChart
                    activeBookmarkId={activeBookmarkId}
                    bookmarks={sortedBookmarks}
                    data={displayedWindowData}
                    durationS={durationS}
                    timeInteraction={timeInteraction}
                    visibleWindow={requestWindow}
                    visibleEventGroups={visibleEventGroups}
                    showMarks={showMarks}
                    synchronizedHoverTimeS={timeInteraction.hoverTimeS}
                    eventGroups={effectiveEventGroups}
                    selectedEventId={selectedEventId}
                    videoHeadTimeS={videoPlaybackSessionTimeS}
                    onHoverTimeChange={timeInteraction.setHoverTimeS}
                    onSelectEvent={timeInteraction.setSelectedEventId}
                  />
                )}
                {showEventDetails && (
                  <SelectedEventPanel
                    event={displayedWindowData.events.find((event) => event.eventId === selectedEventId) ?? null}
                    onClear={() => timeInteraction.setSelectedEventId(null)}
                    onZoom={timeInteraction.setWindow}
                  />
                )}
                {loadState.status === 'error' && (
                  <div className="signal-inspector-message warning">Could not update signals: {loadState.message}</div>
                )}
                {visibleWarnings.length > 0 && (
                  <div className="signal-inspector-message warning">
                    {visibleWarnings.slice(0, 3).join(' | ')}
                    {visibleWarnings.length > 3 ? ` | ${visibleWarnings.length - 3} more warning(s)` : ''}
                  </div>
                )}
              </>
            )}
          </div>
          {displayedWindowData && (
            <div className="signal-inspector-main-navigator">
              <SignalNavigator
                state={navigatorState}
                activeWindow={requestWindow}
                durationS={durationS}
                hideActiveWindowFill={videoScrollWithPlayback}
                pinnedTimeS={pinnedTimeS}
                onSelectWindow={timeInteraction.setWindow}
              />
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function BookmarkRenameInput({
  disabled,
  initialValue,
  onCancel,
  onCommit,
}: {
  disabled: boolean
  initialValue: string
  onCancel: () => void
  onCommit: (value: string) => void
}) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const skipBlurCommitRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    event.stopPropagation()
    if (event.key === 'Enter') {
      event.preventDefault()
      skipBlurCommitRef.current = true
      onCommit(value)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      skipBlurCommitRef.current = true
      onCancel()
    }
  }

  return (
    <input
      aria-label="Rename bookmark"
      className="signal-inspector-bookmark-rename"
      disabled={disabled}
      ref={inputRef}
      value={value}
      onBlur={() => {
        if (skipBlurCommitRef.current) {
          skipBlurCommitRef.current = false
          return
        }
        onCommit(value)
      }}
      onChange={(event) => setValue(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.stopPropagation()}
      onKeyDown={handleKeyDown}
      onPointerDown={(event) => event.stopPropagation()}
    />
  )
}

function SignalInspectorGpsPanel({
  activeWindow,
  collapsedAltitude,
  collapsedMap,
  cursorTimeS,
  dataSource,
  mapHeightPx,
  onMapHeightChange,
  onToggleAltitude,
  onToggleMap,
  session,
  videoHeadTimeS,
}: {
  activeWindow: { startS: number; endS: number }
  collapsedAltitude: boolean
  collapsedMap: boolean
  cursorTimeS: number | null
  dataSource: LibraryDataSource
  mapHeightPx: number
  onMapHeightChange: (heightPx: number) => void
  onToggleAltitude: () => void
  onToggleMap: () => void
  session: SessionRecord
  videoHeadTimeS: number | null
}) {
  const fallbackPointSet = useMemo(() => catalogGpsPointSet(session), [session])
  const mapResizeRef = useRef<{ pointerId: number; startClientY: number; startHeightPx: number } | null>(null)
  const [gpsState, setGpsState] = useState<GpsPanelState>(() => ({
    status: fallbackPointSet.present ? 'idle' : 'idle',
    message: fallbackPointSet.present ? 'GPS preview not loaded.' : 'No GPS path is available for this session.',
    pointSet: fallbackPointSet.present ? fallbackPointSet : null,
  }))
  const preferredSourceId = session.gpsSummary.preferredSourceId ?? session.gpsSummary.sources[0]?.sourceId ?? null

  useEffect(() => {
    let cancelled = false
    if (!dataSource.loadSessionGpsPoints) {
      if (fallbackPointSet.present) {
        setGpsState({
          status: 'ready',
          message: 'Using catalog GPS path; time-aligned highlight is not available.',
          pointSet: fallbackPointSet,
        })
      } else {
        setGpsState({
          status: 'idle',
          message: 'No GPS path is available for this session.',
          pointSet: null,
        })
      }
      return
    }

    setGpsState({
      status: 'loading',
      message: `Loading GPS points for ${session.name}...`,
      pointSet: fallbackPointSet.present ? fallbackPointSet : null,
    })
    dataSource
      .loadSessionGpsPoints(session, preferredSourceId)
      .then((pointSet) => {
        if (cancelled) {
          return
        }
        setGpsState({
          status: 'ready',
          message: gpsPanelStatusLine(pointSet),
          pointSet,
        })
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        setGpsState({
          status: 'error',
          message: error instanceof Error ? `Could not load GPS points: ${error.message}` : 'Could not load GPS points.',
          pointSet: fallbackPointSet.present ? fallbackPointSet : null,
        })
      })

    return () => {
      cancelled = true
    }
  }, [dataSource, fallbackPointSet, preferredSourceId, session])

  useEffect(() => {
    function handlePointerMove(event: globalThis.PointerEvent) {
      const drag = mapResizeRef.current
      if (!drag) {
        return
      }
      const nextHeight = drag.startHeightPx + event.clientY - drag.startClientY
      onMapHeightChange(clamp(nextHeight, SIGNAL_INSPECTOR_GPS_MAP_MIN_HEIGHT_PX, SIGNAL_INSPECTOR_GPS_MAP_MAX_HEIGHT_PX))
    }

    function handlePointerUp(event: globalThis.PointerEvent) {
      const drag = mapResizeRef.current
      if (!drag || event.pointerId !== drag.pointerId) {
        return
      }
      mapResizeRef.current = null
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [onMapHeightChange])

  const pointSet = gpsState.pointSet
  const fullPath = pointSet?.path ?? []
  const windowPath = useMemo(
    () => (pointSet ? gpsPathForWindow(pointSet.points, activeWindow) : []),
    [activeWindow.endS, activeWindow.startS, pointSet],
  )
  const cursorPosition = useMemo(
    () => (pointSet && cursorTimeS !== null ? gpsPositionAtTime(pointSet.points, cursorTimeS) : null),
    [cursorTimeS, pointSet],
  )
  const playbackPosition = useMemo(
    () => (pointSet && videoHeadTimeS !== null ? gpsPositionAtTime(pointSet.points, videoHeadTimeS) : null),
    [pointSet, videoHeadTimeS],
  )
  const mapCursorPosition =
    cursorTimeS !== null && videoHeadTimeS !== null && Math.abs(cursorTimeS - videoHeadTimeS) < 0.05
      ? null
      : cursorPosition
  const highlightPaths = useMemo<HighlightPathOverlay[]>(
    () =>
      windowPath.length >= 2
        ? [
            {
              id: 'signal-window',
              label: 'Signal window',
              path: windowPath,
              color: '#008c95',
              width: 4,
              opacity: 0.88,
            },
          ]
        : [],
    [windowPath],
  )
  const mapViewportStyle = { '--gps-map-height': `${mapHeightPx}px` } as CSSProperties

  function beginMapResize(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    mapResizeRef.current = {
      pointerId: event.pointerId,
      startClientY: event.clientY,
      startHeightPx: mapHeightPx,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  return (
    <>
      <section className="signal-inspector-card signal-inspector-gps-card">
        <div className="signal-inspector-card-header">
          <h3>
            GPS
            <InfoTip text="Shows the session GPS path and highlights the portion covered by the current signal window when time-aligned GPS points are available." />
          </h3>
          <div className="signal-inspector-card-actions">
            <GpsBadge summary={session.gpsSummary} />
            <button
              aria-label={collapsedMap ? 'Expand GPS' : 'Collapse GPS'}
              type="button"
              onClick={onToggleMap}
            >
              {collapsedMap ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
            </button>
          </div>
        </div>
        {!collapsedMap && (
          <div className="signal-inspector-resizable-viewport">
            {fullPath.length >= 2 ? (
              <div className="signal-inspector-gps-map" style={mapViewportStyle}>
                <MapRoutePreview
                  cursorPosition={mapCursorPosition}
                  highlightPaths={highlightPaths}
                  playbackPosition={playbackPosition}
                  primaryGpsPath={fullPath}
                  primarySession={session}
                />
              </div>
            ) : (
              <div className="signal-inspector-gps-empty" style={mapViewportStyle}>
                <MapIcon size={20} />
                <span>No GPS path is available for this session.</span>
              </div>
            )}
            <button
              aria-label="Resize GPS map"
              className="signal-inspector-vertical-resizer"
              type="button"
              onPointerDown={beginMapResize}
              title="Drag to resize GPS map"
            />
          </div>
        )}
      </section>
      <section className="signal-inspector-card signal-inspector-gps-card">
        <div className="signal-inspector-card-header">
          <h3>Altitude</h3>
          <div className="signal-inspector-card-actions">
            <button
              aria-label={collapsedAltitude ? 'Expand altitude' : 'Collapse altitude'}
              type="button"
              onClick={onToggleAltitude}
            >
              {collapsedAltitude ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
            </button>
          </div>
        </div>
        {!collapsedAltitude && <GpsAltitudeChart activeWindow={activeWindow} pointSet={pointSet} videoHeadTimeS={videoHeadTimeS} />}
      </section>
    </>
  )
}

function SignalInspectorVideoPanel({
  activeVideo,
  activeVideoId,
  activeWindow,
  canWrite,
  collapsed,
  durationS,
  message,
  onActiveVideoIdChange,
  onAddAttachment,
  onDeleteAttachment,
  onSettingsCollapsedChange,
  onSelectVideoFile,
  onScrubToCursorChange,
  onScrollWithPlaybackChange,
  onPlayFromPinnedTime,
  onSyncToPinnedTime,
  onTimeUpdate,
  onToggleCollapsed,
  onUpdateAttachment,
  onVideoHeightChange,
  scrollWithPlayback,
  scrubToCursor,
  pinnedTimeS,
  sessionStartedAt,
  settingsCollapsed,
  state,
  streamUrl,
  videoHeightPx,
  videoRef,
}: {
  activeVideo: SessionVideoAttachmentRecord | null
  activeVideoId: string
  activeWindow: { startS: number; endS: number }
  canWrite: boolean
  collapsed: boolean
  durationS: number
  message: string
  onActiveVideoIdChange: (attachmentId: string) => void
  onAddAttachment: (input: VideoAttachmentInput) => void
  onDeleteAttachment: (attachmentId: string) => void
  onSettingsCollapsedChange: (collapsed: boolean) => void
  onSelectVideoFile?: LibraryDataSource['selectLocalVideoFile']
  onScrubToCursorChange: (enabled: boolean) => void
  onScrollWithPlaybackChange: (enabled: boolean) => void
  onPlayFromPinnedTime: () => void
  onSyncToPinnedTime: () => void
  onTimeUpdate: () => void
  onToggleCollapsed: () => void
  onUpdateAttachment: (attachmentId: string, input: VideoAttachmentInput) => void
  onVideoHeightChange: (heightPx: number) => void
  scrollWithPlayback: boolean
  scrubToCursor: boolean
  pinnedTimeS: number | null
  sessionStartedAt: string
  settingsCollapsed: boolean
  state: VideoPanelState
  streamUrl: string
  videoHeightPx: number
  videoRef: RefObject<HTMLVideoElement | null>
}) {
  const data = videoStateData(state)
  const attachments = data?.attachments ?? []
  const [editingNewVideo, setEditingNewVideo] = useState(false)
  const [activeOffset, setActiveOffset] = useState('0')
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editCameraLabel, setEditCameraLabel] = useState('')
  const [editPath, setEditPath] = useState('')
  const [browseMessage, setBrowseMessage] = useState('')
  const autoNewArmedRef = useRef(false)
  const videoResizeRef = useRef<{ pointerId: number; startClientY: number; startHeightPx: number } | null>(null)

  useEffect(() => {
    if (editingNewVideo) {
      return
    }
    setActiveOffset(String(roundForInput(activeVideo?.sessionTimeAtVideoZeroS ?? 0)))
    setEditDisplayName(activeVideo?.displayName ?? '')
    setEditCameraLabel(activeVideo?.cameraLabel ?? '')
    setEditPath(activeVideo ? videoAttachmentPathValue(activeVideo) : '')
  }, [
    activeVideo?.attachmentId,
    activeVideo?.cameraLabel,
    activeVideo?.displayName,
    activeVideo?.libraryRelativePath,
    activeVideo?.path,
    activeVideo?.sessionRelativePath,
    activeVideo?.sessionTimeAtVideoZeroS,
    activeVideo?.workspaceRelativePath,
    editingNewVideo,
  ])

  useEffect(() => {
    if (state.status !== 'ready') {
      return
    }
    if (attachments.length === 0 && !editingNewVideo) {
      startNewAttachment(true)
      return
    }
    if (attachments.length > 0 && editingNewVideo && autoNewArmedRef.current) {
      autoNewArmedRef.current = false
      setEditingNewVideo(false)
    }
  }, [attachments.length, editingNewVideo, state.status])

  useEffect(() => {
    function handlePointerMove(event: globalThis.PointerEvent) {
      const drag = videoResizeRef.current
      if (!drag) {
        return
      }
      const nextHeight = drag.startHeightPx + event.clientY - drag.startClientY
      onVideoHeightChange(clamp(nextHeight, SIGNAL_INSPECTOR_VIDEO_MIN_HEIGHT_PX, SIGNAL_INSPECTOR_VIDEO_MAX_HEIGHT_PX))
    }

    function handlePointerUp(event: globalThis.PointerEvent) {
      const drag = videoResizeRef.current
      if (!drag || event.pointerId !== drag.pointerId) {
        return
      }
      videoResizeRef.current = null
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [onVideoHeightChange])

  const pristineForm = editingNewVideo
    ? {
        displayName: '',
        cameraLabel: '',
        path: '',
        offset: '0',
      }
    : {
        displayName: activeVideo?.displayName ?? '',
        cameraLabel: activeVideo?.cameraLabel ?? '',
        path: activeVideo ? videoAttachmentPathValue(activeVideo) : '',
        offset: String(roundForInput(activeVideo?.sessionTimeAtVideoZeroS ?? 0)),
      }
  const formDirty =
    editDisplayName !== pristineForm.displayName ||
    editCameraLabel !== pristineForm.cameraLabel ||
    editPath !== pristineForm.path ||
    activeOffset !== pristineForm.offset

  function startNewAttachment(autoArmed = false) {
    autoNewArmedRef.current = autoArmed
    setEditingNewVideo(true)
    setEditDisplayName('')
    setEditCameraLabel('')
    setEditPath('')
    setActiveOffset('0')
    setBrowseMessage('')
  }

  function saveAttachmentForm() {
    const input = {
      displayName: editDisplayName,
      cameraLabel: editCameraLabel,
      path: editPath,
      sessionTimeAtVideoZeroS: Number(activeOffset),
    }
    if (editingNewVideo) {
      onAddAttachment(input)
      setEditingNewVideo(false)
      return
    }
    if (activeVideo) {
      onUpdateAttachment(activeVideo.attachmentId, input)
    }
  }

  function nudgeVideoOffset(deltaS: number) {
    const current = Number(activeOffset)
    const nextOffset = roundForInput((Number.isFinite(current) ? current : 0) + deltaS)
    setActiveOffset(String(nextOffset))
    if (!activeVideo || editingNewVideo || !editPath.trim()) {
      return
    }
    onUpdateAttachment(activeVideo.attachmentId, {
      displayName: editDisplayName,
      cameraLabel: editCameraLabel,
      path: editPath,
      sessionTimeAtVideoZeroS: nextOffset,
    })
  }

  function beginVideoResize(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    videoResizeRef.current = {
      pointerId: event.pointerId,
      startClientY: event.clientY,
      startHeightPx: videoHeightPx,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  async function browseForVideo() {
    if (!onSelectVideoFile) {
      return
    }
    setBrowseMessage('Opening file picker...')
    try {
      const selection = await onSelectVideoFile()
      if (!selection.selected) {
        setBrowseMessage('')
        return
      }
      setEditPath(selection.workspaceRelativePath || selection.path)
      if (!editDisplayName.trim()) {
        setEditDisplayName(selection.displayName || selection.fileName || 'Session video')
      }
      const guessedOffsetS = videoOffsetGuessFromMedia(selection.mediaCreatedAtUnixS, sessionStartedAt)
      if (guessedOffsetS !== null) {
        setActiveOffset(String(guessedOffsetS))
      }
      const pathMessage = selection.workspaceRelativePath ? 'Selected workspace-relative video path.' : 'Selected absolute video path.'
      const offsetMessage = guessedOffsetS === null ? ' No media/session start-time match was available.' : ` Best-guess offset: ${guessedOffsetS}s.`
      setBrowseMessage(`${pathMessage}${offsetMessage}`)
    } catch (error) {
      setBrowseMessage(error instanceof Error ? `Could not browse for video: ${error.message}` : 'Could not browse for video.')
    }
  }

  const videoViewportStyle = { '--signal-inspector-video-height': `${videoHeightPx}px` } as CSSProperties

  return (
    <section className="signal-inspector-card signal-inspector-video-card">
      <div className="signal-inspector-card-header">
        <h3>
          Video
          <InfoTip text="Attach a local video to this session and synchronize playback using the session time at video zero." />
        </h3>
        <div className="signal-inspector-card-actions">
          <Film size={15} />
          <button
            aria-label={collapsed ? 'Expand video' : 'Collapse video'}
            type="button"
            onClick={onToggleCollapsed}
          >
            {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="signal-inspector-card-body">
          {state.status === 'loading' && <p>{state.message}</p>}
          {state.status === 'error' && <p className="signal-inspector-gps-status error">Could not load video attachments: {state.message}</p>}
          {attachments.length > 0 ? (
            <>
              <label className="signal-inspector-video-field">
                <span>Attachment</span>
                <select
                  value={activeVideoId || activeVideo?.attachmentId || ''}
                  onChange={(event) => {
                    setEditingNewVideo(false)
                    onActiveVideoIdChange(event.target.value)
                  }}
                >
                  {attachments.map((attachment) => (
                    <option key={attachment.attachmentId} value={attachment.attachmentId}>
                      {attachment.displayName || attachment.cameraLabel || attachment.attachmentId}
                    </option>
                  ))}
                </select>
              </label>
              {streamUrl ? (
                <div className="signal-inspector-resizable-viewport">
                  <video
                    className="signal-inspector-video-player"
                    controls
                    muted
                    onTimeUpdate={onTimeUpdate}
                    preload="metadata"
                    ref={videoRef}
                    src={streamUrl}
                    style={videoViewportStyle}
                  />
                  <button
                    aria-label="Resize video viewport"
                    className="signal-inspector-vertical-resizer"
                    type="button"
                    onPointerDown={beginVideoResize}
                    title="Drag to resize video"
                  />
                </div>
              ) : (
                <div className="signal-inspector-video-empty">No stream URL is available for this attachment.</div>
              )}
              <div className="signal-inspector-video-meta">
                <span>Window {formatTime(activeWindow.startS)}-{formatTime(activeWindow.endS)}</span>
                <span>Session {formatTime(0)}-{formatTime(durationS)}</span>
              </div>
              <div className="signal-inspector-video-runtime-controls">
                <div className="signal-inspector-video-runtime-column">
                  <label className="signal-inspector-video-checkbox">
                    <input
                      checked={scrubToCursor}
                      onChange={(event) => onScrubToCursorChange(event.target.checked)}
                      type="checkbox"
                    />
                    <span>Scrub video to chart cursor</span>
                  </label>
                  <label className="signal-inspector-video-checkbox">
                    <input
                      checked={scrollWithPlayback}
                      onChange={(event) => onScrollWithPlaybackChange(event.target.checked)}
                      type="checkbox"
                    />
                    <span>Scroll signals with video</span>
                  </label>
                </div>
                <div className="signal-inspector-video-runtime-column actions">
                  <button type="button" onClick={onPlayFromPinnedTime} disabled={!activeVideo || pinnedTimeS === null}>
                    <Play size={13} />
                    Play from pinned time
                  </button>
                  <button type="button" onClick={onSyncToPinnedTime} disabled={!canWrite || !activeVideo || pinnedTimeS === null}>
                    Sync to pinned time
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="signal-inspector-video-empty">No video attachments for this session.</div>
          )}
          {canWrite && (
            <div className="signal-inspector-video-settings">
              <div className="signal-inspector-subpanel-header">
                <strong>Video attachment controls</strong>
                <button
                  aria-label={settingsCollapsed ? 'Expand video attachment controls' : 'Collapse video attachment controls'}
                  type="button"
                  onClick={() => onSettingsCollapsedChange(!settingsCollapsed)}
                >
                  {settingsCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
                </button>
              </div>
              {!settingsCollapsed && (
                <div className="signal-inspector-video-form">
                  <h4>{editingNewVideo ? 'New video attachment' : activeVideo ? 'Selected video attachment' : 'Video attachment'}</h4>
                  <label>
                    <span>Name</span>
                    <input value={editDisplayName} onChange={(event) => setEditDisplayName(event.target.value)} placeholder="Session video" />
                  </label>
                  <label>
                    <span>Camera</span>
                    <input value={editCameraLabel} onChange={(event) => setEditCameraLabel(event.target.value)} placeholder="Helmet, bike, etc." />
                  </label>
                  <label>
                    <span>Video path</span>
                    <input value={editPath} onChange={(event) => setEditPath(event.target.value)} placeholder="video.mp4" />
                  </label>
                  {onSelectVideoFile && (
                    <button className="secondary" type="button" onClick={() => void browseForVideo()}>
                      Browse...
                    </button>
                  )}
                  {browseMessage && <p className="signal-inspector-video-inline-message">{browseMessage}</p>}
                  <div className="signal-inspector-video-offset-row">
                    <label>
                      <span>Video zero at session time (s)</span>
                      <input step={0.1} type="number" value={activeOffset} onChange={(event) => setActiveOffset(event.target.value)} />
                    </label>
                    <div className="signal-inspector-video-nudge-controls" aria-label="Nudge video sync offset">
                      <button type="button" onClick={() => nudgeVideoOffset(-1)} disabled={!activeVideo && !editingNewVideo} title="Nudge sync earlier by 1 second">
                        <ChevronsLeft size={13} />
                        <span>1s</span>
                      </button>
                      <button type="button" onClick={() => nudgeVideoOffset(-0.1)} disabled={!activeVideo && !editingNewVideo} title="Nudge sync earlier by 0.1 seconds">
                        <ChevronLeft size={13} />
                        <span>0.1</span>
                      </button>
                      <button type="button" onClick={() => nudgeVideoOffset(0.1)} disabled={!activeVideo && !editingNewVideo} title="Nudge sync later by 0.1 seconds">
                        <span>0.1</span>
                        <ChevronRight size={13} />
                      </button>
                      <button type="button" onClick={() => nudgeVideoOffset(1)} disabled={!activeVideo && !editingNewVideo} title="Nudge sync later by 1 second">
                        <span>1s</span>
                        <ChevronsRight size={13} />
                      </button>
                    </div>
                  </div>
                  <div className="signal-inspector-video-form-actions">
                    <button type="button" onClick={saveAttachmentForm} disabled={!formDirty || (!editingNewVideo && !activeVideo)}>
                      <Save size={14} />
                      Save
                    </button>
                    <button type="button" onClick={() => startNewAttachment()}>
                      New...
                    </button>
                    {activeVideo && !editingNewVideo && (
                      <button className="danger" type="button" onClick={() => onDeleteAttachment(activeVideo.attachmentId)}>
                        <Trash2 size={14} />
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          {message && <p className="signal-inspector-bookmark-message">{message}</p>}
          {!canWrite && attachments.length === 0 && state.status !== 'loading' && (
            <p className="signal-inspector-gps-status">Video attachment editing is unavailable in this context.</p>
          )}
        </div>
      )}
    </section>
  )
}

function GpsAltitudeChart({
  activeWindow,
  pointSet,
  videoHeadTimeS,
}: {
  activeWindow: { startS: number; endS: number }
  pointSet: SessionGpsPointSet | null
  videoHeadTimeS: number | null
}) {
  const samples = useMemo(() => gpsAltitudeSamplesForWindow(pointSet?.points ?? [], activeWindow), [activeWindow.endS, activeWindow.startS, pointSet])
  if (!pointSet?.present) {
    return <div className="signal-inspector-altitude-empty">No GPS altitude data.</div>
  }
  if (samples.length < 2) {
    return <div className="signal-inspector-altitude-empty">No altitude samples in window.</div>
  }

  const width = 420
  const height = 148
  const padding = { top: 14, right: 16, bottom: 38, left: 50 }
  const minTime = Math.min(activeWindow.startS, activeWindow.endS)
  const maxTime = Math.max(activeWindow.startS, activeWindow.endS)
  const elevations = samples.map((sample) => sample.elevationM)
  const minElevation = Math.min(...elevations)
  const maxElevation = Math.max(...elevations)
  const elevationStep = signalInspectorGridStep(maxElevation - minElevation, [5, 10, 20, 50, 100, 200], 3)
  const timeStep = signalInspectorGridStep(maxTime - minTime, [1, 2, 5, 10, 20, 30, 60, 120, 300], 3)
  const elevationDomain = signalInspectorGridDomain(minElevation, maxElevation, elevationStep)
  const timeDomain = signalInspectorGridDomain(minTime, maxTime, timeStep)
  const elevationTicks = signalInspectorGridTicks(elevationDomain.min, elevationDomain.max, elevationStep)
  const timeTicks = signalInspectorGridTicks(timeDomain.min, timeDomain.max, timeStep)
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const xForTime = (timeS: number) =>
    padding.left + ((timeS - timeDomain.min) / Math.max(1e-9, timeDomain.max - timeDomain.min)) * plotWidth
  const yForElevation = (elevationM: number) =>
    padding.top + (1 - (elevationM - elevationDomain.min) / Math.max(1e-9, elevationDomain.max - elevationDomain.min)) * plotHeight
  const path = samples
    .map((sample, index) => {
      const x = xForTime(sample.timeS)
      const y = yForElevation(sample.elevationM)
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
  const playbackMarker =
    videoHeadTimeS !== null && videoHeadTimeS >= timeDomain.min && videoHeadTimeS <= timeDomain.max
      ? {
          x: xForTime(videoHeadTimeS),
          y: yForElevation(interpolateGpsAltitude(samples, videoHeadTimeS)),
        }
      : null

  return (
    <div className="signal-inspector-altitude-chart">
      <svg aria-label="GPS altitude over selected signal window" viewBox={`0 0 ${width} ${height}`} role="img">
        {elevationTicks.map((tick) => {
          const y = yForElevation(tick)
          return (
            <g key={`elevation-${tick}`} className="signal-inspector-altitude-grid">
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
              <text x={padding.left - 7} y={y + 3} textAnchor="end">
                {Math.round(tick)}
              </text>
            </g>
          )
        })}
        {timeTicks.map((tick) => {
          const x = xForTime(tick)
          return (
            <g key={`time-${tick}`} className="signal-inspector-altitude-grid">
              <line x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} />
              <text x={x} y={height - padding.bottom + 16} textAnchor="middle">
                {formatTime(tick)}
              </text>
            </g>
          )
        })}
        <line className="signal-inspector-altitude-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
        <line className="signal-inspector-altitude-axis" x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
        <path className="signal-inspector-altitude-line" d={path} />
        {playbackMarker && (
          <g className="signal-inspector-altitude-playback-marker">
            <line x1={playbackMarker.x} x2={playbackMarker.x} y1={padding.top} y2={height - padding.bottom} />
            <circle cx={playbackMarker.x} cy={playbackMarker.y} r={4.4} />
          </g>
        )}
        <text className="signal-inspector-altitude-axis-title" x={(padding.left + width - padding.right) / 2} y={height - 3} textAnchor="middle">
          Time
        </text>
        <text
          className="signal-inspector-altitude-axis-title"
          x={15}
          y={(padding.top + height - padding.bottom) / 2}
          textAnchor="middle"
          transform={`rotate(-90 15 ${(padding.top + height - padding.bottom) / 2})`}
        >
          Altitude (m)
        </text>
      </svg>
    </div>
  )
}

function SignalWindowChart({
  activeBookmarkId,
  bookmarks,
  compact = false,
  data,
  durationS,
  eventGroups,
  height = 500,
  inlineLegend = false,
  externalHover = false,
  debugChartLabel,
  synchronizedHoverTimeS = null,
  selectedEventId,
  showFullSessionControl = true,
  showMarks,
  timeInteraction,
  videoHeadTimeS,
  visibleWindow,
  visibleEventGroups,
  onHoverTimeChange,
  onHoverDebug,
  onSelectEvent,
}: {
  activeBookmarkId: string | null
  bookmarks: SessionBookmarkRecord[]
  compact?: boolean
  data: TimeseriesWindowResponse
  durationS: number
  eventGroups: EventGroup[]
  height?: number
  inlineLegend?: boolean
  externalHover?: boolean
  debugChartLabel?: string
  synchronizedHoverTimeS?: number | null
  selectedEventId: string | null
  showFullSessionControl?: boolean
  showMarks: boolean
  timeInteraction: SessionTimeInteraction
  videoHeadTimeS: number | null
  visibleWindow: SessionTimeWindow
  visibleEventGroups: string[]
  onHoverTimeChange?: (timeS: number | null) => void
  onHoverDebug?: (event: HoverDebugEvent) => void
  onSelectEvent: (eventId: string | null) => void
}) {
  const chartFrameRef = useRef<HTMLDivElement | null>(null)
  const plotHostRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const timeInteractionRef = useRef(timeInteraction)
  const onHoverTimeChangeRef = useRef(onHoverTimeChange)
  const onHoverDebugRef = useRef(onHoverDebug)
  const suppressNextClickRef = useRef(false)
  const hostWidth = useElementWidth(plotHostRef)
  const [hover, setHover] = useState<HoverReadout | null>(null)
  const hoverFrameRef = useRef<number | null>(null)
  const pendingHoverRef = useRef<HoverReadout | null>(null)
  const [plotVersion, setPlotVersion] = useState(0)
  const chartModel = useMemo(() => buildSignalChartModel(data), [data])
  const plotWidth = boundedPlotWidth(hostWidth)
  const plotHeight = height
  const chartValues = chartSignalValues(chartModel.chartSignals)
  const selectedEventGroups = new Set(visibleEventGroups)
  const groupColorByKey = new Map(eventGroups.map((group) => [group.key, group.color]))
  const groupLaneByKey = new Map(eventGroups.map((group, index) => [group.key, index % 4]))
  const visibleEvents = data.events.filter((event) => selectedEventGroups.has(eventGroupKey(event)) && eventInWindow(event, visibleWindow))
  const visibleMarks = showMarks ? data.marks.filter((mark) => markInWindow(mark, visibleWindow)) : []
  const activeWindowStyle = signalWindowStyle(plotRef.current, timeInteraction.activeWindow, { hideWhenFullDomain: true })

  useEffect(() => {
    timeInteractionRef.current = timeInteraction
  }, [timeInteraction])

  useEffect(() => {
    onHoverTimeChangeRef.current = onHoverTimeChange
  }, [onHoverTimeChange])

  useEffect(() => {
    onHoverDebugRef.current = onHoverDebug
  }, [onHoverDebug])

  useEffect(
    () => () => {
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current)
      }
    },
    [],
  )

  useEffect(() => {
    if (
      !plotHostRef.current ||
      plotWidth < signalInspectorPlotToken('--signal-inspector-plot-min-width', 320) ||
      chartModel.times.length === 0 ||
      chartModel.chartSignals.length === 0 ||
      chartValues.length === 0
    ) {
      return
    }
    function scheduleHover(nextHover: HoverReadout | null) {
      pendingHoverRef.current = nextHover
      if (!externalHover) {
        onHoverTimeChangeRef.current?.(nextHover?.timeS ?? null)
      }
      if (hoverFrameRef.current !== null) {
        return
      }
      hoverFrameRef.current = window.requestAnimationFrame(() => {
        hoverFrameRef.current = null
        setHover(pendingHoverRef.current)
      })
    }
    plotHostRef.current.replaceChildren()
    const plot = new uPlot(
      signalUPlotOptions({
        model: chartModel,
        compact,
        debugChartLabel: debugChartLabel ?? chartModel.chartSignals[0]?.displayLabel ?? 'chart',
        width: plotWidth,
        height: plotHeight,
        enableHover: !externalHover,
        visibleWindow,
        onHoverDebug: (event) => onHoverDebugRef.current?.(event),
        onHover: scheduleHover,
      }),
      chartModel.alignedData,
      plotHostRef.current,
    )
    plotRef.current = plot
    const detachChartInteraction = attachSignalChartInteraction({
      chartFrameRef,
      model: chartModel,
      plot,
      suppressNextClickRef,
      timeInteractionRef,
    })
    setPlotVersion((version) => version + 1)
    return () => {
      detachChartInteraction()
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current)
        hoverFrameRef.current = null
        pendingHoverRef.current = null
      }
      plot.destroy()
      if (plotRef.current === plot) {
        plotRef.current = null
      }
    }
  }, [chartModel, chartValues.length, compact, externalHover, plotHeight, plotWidth])

  useEffect(() => {
    const plot = plotRef.current
    if (!plot) {
      return
    }
    plot.setScale('x', { min: visibleWindow.startS, max: visibleWindow.endS })
  }, [visibleWindow.endS, visibleWindow.startS])

  if (data.signals.length === 0 || chartModel.times.length === 0 || chartValues.length === 0) {
    return <div className="signal-inspector-message">No matching signal samples were returned for this window.</div>
  }

  const displayHover = onHoverTimeChange ? readoutForTime(chartModel, synchronizedHoverTimeS) : hover
  const displayHoverLeft = displayHover && plotRef.current ? plotValueX(plotRef.current, displayHover.timeS) : null
  const displayHoverIsVideoHead =
    displayHover !== null && videoHeadTimeS !== null && Math.abs(displayHover.timeS - videoHeadTimeS) < 0.05
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!externalHover || !plotRef.current || chartModel.times.length === 0) {
      return
    }
    const plot = plotRef.current
    const rect = plot.over.getBoundingClientRect()
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
      return
    }
    const rawLeft = event.clientX - rect.left
    const left = clamp(rawLeft, 0, rect.width)
    const rawTimeS = plot.posToVal(left, 'x')
    const domainStart = chartModel.times[0] ?? 0
    const domainEnd = chartModel.times.at(-1) ?? domainStart
    const timeS = clamp(rawTimeS, domainStart, domainEnd)
    const resolvedIndex = nearestTimeIndex(chartModel.times, timeS)
    onHoverDebugRef.current?.({
      chart: debugChartLabel ?? chartModel.chartSignals[0]?.displayLabel ?? 'chart',
      rawIndex: null,
      rawLeft,
      resolvedIndex,
      resolvedTimeS: resolvedIndex === null ? null : chartModel.times[resolvedIndex],
      action: 'hover',
      reason: 'dom-pointer',
      at: performance.now(),
    })
    onHoverTimeChangeRef.current?.(timeS)
  }

  return (
    <div className={`signal-inspector-chart-card${compact ? ' compact' : ''}${inlineLegend ? ' inline-legend' : ''}`}>
      <div className="signal-inspector-chart-frame" ref={chartFrameRef} onPointerMove={handlePointerMove}>
        {showFullSessionControl && (
          <button
            className="signal-inspector-full-session-control"
            type="button"
            onClick={() => timeInteraction.setWindow({ startS: 0, endS: durationS })}
          >
            <RefreshCcw size={14} />
            Full session
          </button>
        )}
        <div
          className="signal-inspector-uplot-host"
          ref={plotHostRef}
          style={{ height: plotHeight, minHeight: plotHeight }}
        />
        <SignalPlotOverlay
          activeBookmarkId={activeBookmarkId}
          bookmarks={bookmarks}
          eventGroups={eventGroups}
          groupColorByKey={groupColorByKey}
          groupLaneByKey={groupLaneByKey}
          marks={visibleMarks}
          onSelectEvent={onSelectEvent}
          pinnedTimeS={timeInteraction.pinnedTimeS}
          plot={plotRef.current}
          selectedEventId={selectedEventId}
          version={plotVersion}
          visibleEvents={visibleEvents}
        />
        {activeWindowStyle && <span aria-hidden="true" className="signal-inspector-active-window" style={activeWindowStyle} />}
        {displayHoverLeft !== null && (
          <span
            className={`signal-inspector-synced-hover-line${displayHoverIsVideoHead ? ' video-head' : ''}`}
            style={{ left: `${displayHoverLeft}px` }}
          />
        )}
        {displayHover && displayHoverLeft !== null && (
          <div className="signal-inspector-readout" style={{ left: `clamp(88px, ${displayHoverLeft}px, calc(100% - 88px))` }}>
            <strong>{formatTime(displayHover.timeS)}</strong>
            {displayHover.values.slice(0, 6).map((item) => (
              <span key={item.label}>
                <i style={{ background: item.color }} />
                {item.label}: {formatReadoutValue(item.value)}
                {item.unit ? ` ${item.unit}` : ''}
              </span>
            ))}
          </div>
        )}
        {inlineLegend && <SignalChartLegend chartModel={chartModel} marks={visibleMarks} />}
      </div>
      {!inlineLegend && <SignalChartLegend chartModel={chartModel} marks={visibleMarks} />}
    </div>
  )
}

function attachSignalChartInteraction({
  chartFrameRef,
  model,
  plot,
  suppressNextClickRef,
  timeInteractionRef,
}: {
  chartFrameRef: RefObject<HTMLDivElement | null>
  model: SignalChartModel
  plot: uPlot
  suppressNextClickRef: MutableRefObject<boolean>
  timeInteractionRef: MutableRefObject<SessionTimeInteraction>
}) {
  const previewElement = document.createElement('span')
  previewElement.className = 'signal-inspector-window-preview'
  previewElement.setAttribute('aria-hidden', 'true')
  chartFrameRef.current?.appendChild(previewElement)
  const timeFromClientX = (clientX: number) => {
    const rect = plot.over.getBoundingClientRect()
    const left = clamp(clientX - rect.left, 0, rect.width)
    const rawTimeS = plot.posToVal(left, 'x')
    const domainStart = model.times[0] ?? 0
    const domainEnd = model.times.at(-1) ?? domainStart
    return clamp(rawTimeS, domainStart, domainEnd)
  }
  const dragWidthPx = (drag: TimeWindowDrag, currentS: number) => {
    return Math.abs(plot.valToPos(currentS, 'x') - plot.valToPos(drag.startS, 'x'))
  }
  const hideWindowPreview = () => {
    previewElement.style.display = 'none'
  }
  const updateWindowPreview = (drag: TimeWindowDrag, currentS: number) => {
    const frame = chartFrameRef.current
    if (!frame || !previewElement.isConnected) {
      return
    }
    const width = dragWidthPx(drag, currentS)
    if (width < CHART_WINDOW_DRAG_THRESHOLD_PX) {
      hideWindowPreview()
      return
    }
    const frameRect = frame.getBoundingClientRect()
    const overRect = plot.over.getBoundingClientRect()
    const startX = plot.valToPos(drag.startS, 'x')
    const currentX = plot.valToPos(currentS, 'x')
    previewElement.style.display = 'block'
    previewElement.style.height = `${overRect.height}px`
    previewElement.style.left = `${overRect.left - frameRect.left + Math.min(startX, currentX)}px`
    previewElement.style.top = `${overRect.top - frameRect.top}px`
    previewElement.style.width = `${width}px`
  }
  const handlePointerDown = (event: globalThis.PointerEvent) => {
    if (event.button !== 0) {
      return
    }
    const startS = timeFromClientX(event.clientX)
    timeInteractionRef.current.beginWindowDrag(event.pointerId, startS)
    hideWindowPreview()
    try {
      plot.over.setPointerCapture(event.pointerId)
    } catch {
      // Pointer capture is an enhancement; uPlot still receives normal mouse events without it.
    }
  }
  const handlePointerMove = (event: globalThis.PointerEvent) => {
    const drag = timeInteractionRef.current.getWindowDrag()
    if (!drag || drag.pointerId !== event.pointerId) {
      return
    }
    const currentS = timeFromClientX(event.clientX)
    timeInteractionRef.current.updateWindowDrag(event.pointerId, currentS)
    updateWindowPreview(drag, currentS)
  }
  const handlePointerUp = (event: globalThis.PointerEvent) => {
    const drag = timeInteractionRef.current.getWindowDrag()
    if (!drag || drag.pointerId !== event.pointerId) {
      return
    }
    const endS = timeFromClientX(event.clientX)
    const dragWidth = dragWidthPx(drag, endS)
    if (dragWidth < CHART_WINDOW_DRAG_THRESHOLD_PX) {
      timeInteractionRef.current.cancelWindowDrag(event.pointerId)
      hideWindowPreview()
      return
    }
    suppressNextClickRef.current = true
    window.setTimeout(() => {
      suppressNextClickRef.current = false
    }, 0)
    hideWindowPreview()
    timeInteractionRef.current.commitWindowDrag(event.pointerId, endS)
  }
  const handlePointerCancel = (event: globalThis.PointerEvent) => {
    timeInteractionRef.current.cancelWindowDrag(event.pointerId)
    hideWindowPreview()
  }
  const handleClick = (event: globalThis.MouseEvent) => {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false
      event.preventDefault()
      event.stopPropagation()
      return
    }
    if (plot.select.width >= 4) {
      return
    }
    const pointS = timeFromClientX(event.clientX)
    timeInteractionRef.current.setPinnedTime(pointS)
  }

  plot.over.addEventListener('pointerdown', handlePointerDown)
  plot.over.addEventListener('pointermove', handlePointerMove)
  plot.over.addEventListener('pointerup', handlePointerUp)
  plot.over.addEventListener('pointercancel', handlePointerCancel)
  plot.over.addEventListener('lostpointercapture', handlePointerCancel)
  plot.over.addEventListener('click', handleClick)

  return () => {
    hideWindowPreview()
    previewElement.remove()
    plot.over.removeEventListener('pointerdown', handlePointerDown)
    plot.over.removeEventListener('pointermove', handlePointerMove)
    plot.over.removeEventListener('pointerup', handlePointerUp)
    plot.over.removeEventListener('pointercancel', handlePointerCancel)
    plot.over.removeEventListener('lostpointercapture', handlePointerCancel)
    plot.over.removeEventListener('click', handleClick)
  }
}

function SignalChartLegend({
  chartModel,
  marks,
}: {
  chartModel: SignalChartModel
  marks: TimeseriesWindowMark[]
}) {
  return (
    <div className="signal-inspector-legend">
      {chartModel.chartSignals.map((signal, index) => (
        <span key={signal.column}>
          <i style={{ background: SIGNAL_COLORS[(signal.originalIndex ?? index) % SIGNAL_COLORS.length] }} />
          {signal.displayLabel}
          {signal.unit ? ` (${signal.unit})` : ''}
          {signal.axisId !== 'primary' ? `, ${axisLabel(signal.axisId)} axis` : ''}
        </span>
      ))}
      {marks.length > 0 && (
        <span>
          <i className="signal-inspector-mark-swatch" />
          Logger marks ({marks.length})
        </span>
      )}
    </div>
  )
}

function SignalMultiChartStack({
  activeBookmarkId,
  bookmarks,
  data,
  durationS,
  eventGroups,
  selectedEventId,
  showMarks,
  timeInteraction,
  videoHeadTimeS,
  visibleWindow,
  visibleEventGroups,
  onSelectEvent,
}: {
  activeBookmarkId: string | null
  bookmarks: SessionBookmarkRecord[]
  data: TimeseriesWindowResponse
  durationS: number
  eventGroups: EventGroup[]
  selectedEventId: string | null
  showMarks: boolean
  timeInteraction: SessionTimeInteraction
  videoHeadTimeS: number | null
  visibleWindow: SessionTimeWindow
  visibleEventGroups: string[]
  onSelectEvent: (eventId: string | null) => void
}) {
  const [hoverDebugEvents, setHoverDebugEvents] = useState<HoverDebugEvent[]>([])
  const timeInteractionRef = useRef(timeInteraction)
  const pendingHoverDebugEventRef = useRef<HoverDebugEvent | null>(null)
  const pendingHoverTimeSRef = useRef<number | null>(null)
  const hoverDebugFrameRef = useRef<number | null>(null)
  const hoverTimeFrameRef = useRef<number | null>(null)
  const hoverClearTimerRef = useRef<number | null>(null)

  useEffect(() => {
    timeInteractionRef.current = timeInteraction
  }, [timeInteraction])

  const handleHoverTimeChange = (timeS: number | null) => {
    if (hoverClearTimerRef.current !== null) {
      window.clearTimeout(hoverClearTimerRef.current)
      hoverClearTimerRef.current = null
    }
    if (timeS === null) {
      hoverClearTimerRef.current = window.setTimeout(() => {
        hoverClearTimerRef.current = null
        timeInteractionRef.current.setHoverTimeS(null)
      }, 90)
      return
    }
    pendingHoverTimeSRef.current = timeS
    if (hoverTimeFrameRef.current !== null) {
      return
    }
    hoverTimeFrameRef.current = window.requestAnimationFrame(() => {
      hoverTimeFrameRef.current = null
      const nextTimeS = pendingHoverTimeSRef.current
      if (nextTimeS === null) {
        return
      }
      const current = timeInteractionRef.current.hoverTimeS
      if (current === null || Math.abs(current - nextTimeS) >= 0.001) {
        timeInteractionRef.current.setHoverTimeS(nextTimeS)
      }
    })
  }
  useEffect(
    () => () => {
      if (hoverClearTimerRef.current !== null) {
        window.clearTimeout(hoverClearTimerRef.current)
      }
      if (hoverTimeFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverTimeFrameRef.current)
      }
      if (hoverDebugFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverDebugFrameRef.current)
      }
    },
    [],
  )
  const handleHoverDebug = (event: HoverDebugEvent) => {
    pendingHoverDebugEventRef.current = event
    if (hoverDebugFrameRef.current !== null) {
      return
    }
    hoverDebugFrameRef.current = window.requestAnimationFrame(() => {
      hoverDebugFrameRef.current = null
      const next = pendingHoverDebugEventRef.current
      if (!next) {
        return
      }
      setHoverDebugEvents((events) => [next, ...events].slice(0, 10))
    })
  }
  const handleStackPointerLeave = () => {
    if (hoverClearTimerRef.current !== null) {
      window.clearTimeout(hoverClearTimerRef.current)
      hoverClearTimerRef.current = null
    }
    if (hoverTimeFrameRef.current !== null) {
      window.cancelAnimationFrame(hoverTimeFrameRef.current)
      hoverTimeFrameRef.current = null
    }
    pendingHoverTimeSRef.current = null
    timeInteractionRef.current.setHoverTimeS(null)
    handleHoverDebug({
      chart: 'stack',
      rawIndex: null,
      rawLeft: null,
      resolvedIndex: null,
      resolvedTimeS: null,
      action: 'leave',
      reason: 'stack-pointerleave',
      at: performance.now(),
    })
  }
  const signalWindows = useMemo(
    () => data.signals.map((signal) => timeseriesWindowForSignal(data, signal)),
    [data],
  )
  if (data.signals.length === 0) {
    return <div className="signal-inspector-message">No matching signal samples were returned for this window.</div>
  }
  return (
    <div className="signal-inspector-multi-stack" onPointerLeave={handleStackPointerLeave}>
      {SIGNAL_INSPECTOR_HOVER_DEBUG && <SignalHoverDebugPanel events={hoverDebugEvents} hoverTimeS={timeInteraction.hoverTimeS} />}
      {signalWindows.map((signalData, index) => {
        const signal = signalData.signals[0]
        if (!signal) {
          return null
        }
        const isFirstChart = index === 0
        return (
          <SignalWindowChart
            activeBookmarkId={activeBookmarkId}
            bookmarks={bookmarks}
            compact
            data={signalData}
            debugChartLabel={signal.displayName || signal.column}
            durationS={durationS}
            eventGroups={eventGroups}
            externalHover
            height={190}
            inlineLegend
            key={signal.column}
            selectedEventId={selectedEventId}
            showFullSessionControl={isFirstChart}
            showMarks={isFirstChart && showMarks}
            synchronizedHoverTimeS={timeInteraction.hoverTimeS}
            timeInteraction={timeInteraction}
            videoHeadTimeS={videoHeadTimeS}
            visibleWindow={visibleWindow}
            visibleEventGroups={isFirstChart ? visibleEventGroups : []}
            onHoverDebug={SIGNAL_INSPECTOR_HOVER_DEBUG ? handleHoverDebug : undefined}
            onHoverTimeChange={handleHoverTimeChange}
            onSelectEvent={onSelectEvent}
          />
        )
      })}
    </div>
  )
}

function SignalHoverDebugPanel({ events, hoverTimeS }: { events: HoverDebugEvent[]; hoverTimeS: number | null }) {
  return (
    <details className="signal-inspector-hover-debug" open>
      <summary>
        Hover debug
        <span>shared {hoverTimeS === null ? 'null' : `${hoverTimeS.toFixed(3)}s`}</span>
      </summary>
      {events.length === 0 ? (
        <div className="signal-inspector-hover-debug-empty">Move over a chart to sample cursor events.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Chart</th>
              <th>Action</th>
              <th>Reason</th>
              <th>idx</th>
              <th>left</th>
              <th>resolved</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event, index) => (
              <tr key={`${event.at}-${index}`}>
                <td>{event.chart}</td>
                <td>{event.action}</td>
                <td>{event.reason}</td>
                <td>{event.rawIndex ?? 'null'}</td>
                <td>{event.rawLeft === null ? 'null' : event.rawLeft.toFixed(1)}</td>
                <td>
                  {event.resolvedIndex === null || event.resolvedTimeS === null
                    ? 'null'
                    : `${event.resolvedIndex} / ${event.resolvedTimeS.toFixed(3)}s`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  )
}

function SignalPlotOverlay({
  activeBookmarkId,
  bookmarks,
  eventGroups,
  groupColorByKey,
  groupLaneByKey,
  marks,
  onSelectEvent,
  pinnedTimeS,
  plot,
  selectedEventId,
  version,
  visibleEvents,
}: {
  activeBookmarkId: string | null
  bookmarks: SessionBookmarkRecord[]
  eventGroups: EventGroup[]
  groupColorByKey: Map<string, string>
  groupLaneByKey: Map<string, number>
  marks: TimeseriesWindowMark[]
  onSelectEvent: (eventId: string | null) => void
  pinnedTimeS: number | null
  plot: uPlot | null
  selectedEventId: string | null
  version: number
  visibleEvents: TimeseriesWindowEvent[]
}) {
  void eventGroups
  void version
  if (!plot) {
    return null
  }
  const geometry = plotGeometry(plot)
  if (!geometry) {
    return null
  }
  const pinnedLeft = pinnedTimeS === null ? null : plotValueX(plot, pinnedTimeS)
  const showPinnedTime = pinnedLeft !== null && pinnedLeft >= geometry.left && pinnedLeft <= geometry.right
  return (
    <div className="signal-inspector-plot-overlay">
      {showPinnedTime && pinnedTimeS !== null && (
        <span
          aria-label={`Pinned time ${formatTime(pinnedTimeS)}`}
          className="signal-inspector-pinned-time"
          role="img"
          style={{
            height: `${geometry.height}px`,
            left: `${pinnedLeft}px`,
            top: `${geometry.top}px`,
          }}
          title={`Pinned time: ${formatTime(pinnedTimeS)}`}
        />
      )}
      {bookmarks.map((bookmark) => {
        const startS = bookmark.window.startS
        const endS = bookmark.window.endS
        if (!Number.isFinite(startS) || !Number.isFinite(endS)) {
          return null
        }
        const isPoint = nearlyEqual(startS, endS)
        const startLeft = plotValueX(plot, startS)
        const endLeft = plotValueX(plot, endS)
        const isActive = bookmark.id === activeBookmarkId
        if (isPoint) {
          if (startLeft === null) {
            return null
          }
          return (
            <span
              aria-label={`Bookmark ${bookmark.title} at ${formatTime(startS)}`}
              className={`signal-inspector-bookmark-point${isActive ? ' active' : ''}`}
              key={bookmark.id || `${bookmark.title}-${startS}`}
              role="img"
              style={{
                left: `${startLeft}px`,
                top: `${geometry.bottom + 27}px`,
              }}
              title={`${bookmark.title}: ${formatTime(startS)}`}
            />
          )
        }
        if (startLeft === null || endLeft === null) {
          return null
        }
        const left = Math.min(startLeft, endLeft)
        const width = Math.max(4, Math.abs(endLeft - startLeft))
        return (
          <span
            aria-label={`Bookmark ${bookmark.title} from ${formatTime(startS)} to ${formatTime(endS)}`}
            className={`signal-inspector-bookmark-window${isActive ? ' active' : ''}`}
            key={bookmark.id || `${bookmark.title}-${startS}-${endS}`}
            role="img"
            style={{
              left: `${left}px`,
              top: `${geometry.bottom + 25}px`,
              width: `${width}px`,
            }}
            title={`${bookmark.title}: ${formatTime(startS)}-${formatTime(endS)}`}
          />
        )
      })}
      {marks.map((mark) => {
        const left = plotValueX(plot, mark.timeS)
        if (left === null) {
          return null
        }
        return (
          <div
            aria-hidden="true"
            className="signal-inspector-uplot-mark"
            key={mark.markId || `${mark.displayName}-${mark.timeS}`}
            style={{
              height: `${geometry.height}px`,
              left: `${left}px`,
              top: `${geometry.top}px`,
            }}
            title={`${mark.displayName || 'Mark'} at ${formatTime(mark.timeS)}`}
          >
            <span>{mark.displayName || 'Mark'}</span>
          </div>
        )
      })}
      {visibleEvents.map((event, index) => {
        const timeS = event.peakTimeS ?? event.startS ?? event.endS
        if (typeof timeS !== 'number' || !Number.isFinite(timeS)) {
          return null
        }
        const left = plotValueX(plot, timeS)
        if (left === null) {
          return null
        }
        const key = eventGroupKey(event)
        const lane = groupLaneByKey.get(key) ?? 0
        return (
          <button
            aria-label={`${eventDisplayName(event)} at ${formatTime(timeS)}`}
            className={`signal-inspector-uplot-event${event.eventId === selectedEventId ? ' selected' : ''}`}
            key={`${event.eventId}-${index}`}
            onClick={(clickEvent) => {
              clickEvent.stopPropagation()
              onSelectEvent(event.eventId === selectedEventId ? null : event.eventId)
            }}
            style={{
              background: groupColorByKey.get(key) ?? '#b66a2c',
              left: `${left}px`,
              top: `${geometry.bottom + 12 + lane * 8}px`,
            }}
            title={`${eventDisplayName(event)}${event.end ? ` (${event.end})` : ''} at ${formatTime(timeS)}`}
            type="button"
          />
        )
      })}
    </div>
  )
}

function signalUPlotOptions({
  compact = false,
  debugChartLabel = 'chart',
  enableHover = true,
  height,
  model,
  onHover,
  onHoverDebug,
  visibleWindow,
  width,
}: {
  compact?: boolean
  debugChartLabel?: string
  enableHover?: boolean
  height: number
  model: SignalChartModel
  onHover: (hover: HoverReadout | null) => void
  onHoverDebug?: (event: HoverDebugEvent) => void
  visibleWindow: SessionTimeWindow
  width: number
}): uPlot.Options {
  const valuesByAxis = new Map(
    model.axisConfigs.map((axis) => [axis.id, chartSignalValues(model.chartSignals.filter((signal) => signal.axisId === axis.id))]),
  )
  const scales: uPlot.Scales = {
    x: { time: false, min: visibleWindow.startS, max: visibleWindow.endS },
  }
  for (const axis of model.axisConfigs) {
    scales[axis.id] = {
      range: axis.unit.key === '1' ? [0, 1] : paddedExtent(valuesByAxis.get(axis.id) ?? []),
    }
  }
  const axes: uPlot.Axis[] = [
    {
      scale: 'x',
      side: 2,
      values: (_plot, splits) => formatTimeAxisLabels(splits),
      stroke: '#5b6670',
      grid: { show: false },
      ticks: { stroke: '#9fb0ad', width: 1, size: 5 },
      font: '10px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
      labelFont: '11px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
      size: compact ? 24 : undefined,
    },
    ...model.axisConfigs.map((axis, index): uPlot.Axis => ({
      scale: axis.id,
      side: index === 0 ? 3 : 1,
      label: axis.unit.label,
      values: (_plot, splits) => splits.map((value) => formatAxisValue(value)),
      stroke: '#5b6670',
      grid: index === 0 ? { stroke: 'rgba(79, 116, 119, 0.15)', width: 1 } : { show: false },
      ticks: { stroke: '#9fb0ad', width: 1, size: 5 },
      size: compact ? 40 : index === 0 ? 52 : 48,
      font: '10px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
      labelFont: '11px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
    })),
  ]
  const series: uPlot.Series[] = [
    {},
    ...model.chartSignals.map((signal, index): uPlot.Series => ({
      label: signal.displayLabel,
      scale: signal.axisId,
      stroke: SIGNAL_COLORS[(signal.originalIndex ?? index) % SIGNAL_COLORS.length],
      width: 1.35,
      points: { show: false },
      spanGaps: false,
    })),
  ]
  return {
    width,
    height,
    class: 'signal-inspector-uplot',
    scales,
    axes,
    series,
    legend: { show: false },
    cursor: {
      x: true,
      y: false,
      drag: { x: false, y: false, setScale: false },
      points: { size: 5, width: 1 },
    },
    hooks: {
      setCursor: [
        (plot) => {
          if (!enableHover) {
            return
          }
          const rawIndex = typeof plot.cursor.idx === 'number' && Number.isFinite(plot.cursor.idx) ? plot.cursor.idx : null
          const rawLeft = typeof plot.cursor.left === 'number' && Number.isFinite(plot.cursor.left) ? plot.cursor.left : null
          const leftTimeS = rawLeft !== null ? plot.posToVal(rawLeft, 'x') : null
          let index =
            typeof leftTimeS === 'number' && Number.isFinite(leftTimeS)
              ? nearestTimeIndex(model.times, leftTimeS)
              : null
          let reason = index === null ? 'left-no-time' : 'left-authoritative'
          if ((index === null || index < 0 || index >= model.times.length) && rawIndex !== null) {
            index = rawIndex
            reason = 'idx-fallback'
          }
          if (index === null || index < 0 || index >= model.times.length) {
            onHoverDebug?.({
              chart: debugChartLabel,
              rawIndex,
              rawLeft,
              resolvedIndex: null,
              resolvedTimeS: null,
              action: 'clear',
              reason,
              at: performance.now(),
            })
            onHover(null)
            return
          }
          const timeS = model.times[index]
          onHoverDebug?.({
            chart: debugChartLabel,
            rawIndex,
            rawLeft,
            resolvedIndex: index,
            resolvedTimeS: timeS,
            action: 'hover',
            reason,
            at: performance.now(),
          })
          onHover({
            x: plot.valToPos(timeS, 'x'),
            timeS,
            values: model.chartSignals
              .map((signal, signalIndex) => ({
                label: signal.displayLabel,
                value: model.seriesValues[signalIndex]?.[index],
                unit: signal.unit,
                color: SIGNAL_COLORS[(signal.originalIndex ?? signalIndex) % SIGNAL_COLORS.length],
              }))
              .filter((item): item is HoverReadout['values'][number] => typeof item.value === 'number' && Number.isFinite(item.value)),
          })
        },
      ],
    },
  }
}

function SignalNavigator({
  state,
  activeWindow,
  durationS,
  hideActiveWindowFill,
  pinnedTimeS,
  onSelectWindow,
}: {
  state: LoadState
  activeWindow: { startS: number; endS: number }
  durationS: number
  hideActiveWindowFill: boolean
  pinnedTimeS: number | null
  onSelectWindow: (window: { startS: number; endS: number }) => void
}) {
  const plotHostRef = useRef<HTMLDivElement | null>(null)
  const previewRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const dragRef = useRef<NavigatorDrag | null>(null)
  const hostWidth = useElementWidth(plotHostRef, state.status)
  const [plotVersion, setPlotVersion] = useState(0)
  const data = state.status === 'ready' ? state.data : null
  const model = useMemo(() => (data ? buildSignalChartModel(data) : null), [data])
  const plotWidth = boundedPlotWidth(hostWidth)
  const plotHeight = 72
  const minWindowS = Math.max(0.1, durationS / 1000)

  useEffect(() => {
    if (
      !plotHostRef.current ||
      plotWidth < signalInspectorPlotToken('--signal-inspector-plot-min-width', 320) ||
      !model ||
      model.times.length === 0 ||
      model.chartSignals.length === 0
    ) {
      return
    }
    plotHostRef.current.replaceChildren()
    const plot = new uPlot(
      navigatorUPlotOptions({
        model,
        width: plotWidth,
        height: plotHeight,
      }),
      model.alignedData,
      plotHostRef.current,
    )
    plotRef.current = plot
    setPlotVersion((version) => version + 1)
    return () => {
      plot.destroy()
      if (plotRef.current === plot) {
        plotRef.current = null
      }
    }
  }, [model, plotHeight, plotWidth])

  useEffect(() => {
    setNavigatorPreview(previewRef.current, null, plotRef.current)
  }, [activeWindow.endS, activeWindow.startS, plotVersion])

  if (state.status === 'loading') {
    return <div className="signal-inspector-message">{state.message}</div>
  }
  if (state.status === 'error') {
    return <div className="signal-inspector-message warning">Could not load navigator: {state.message}</div>
  }
  if (state.status !== 'ready') {
    return <div className="signal-inspector-message">{state.message}</div>
  }
  if (!model || model.times.length === 0 || chartSignalValues(model.chartSignals).length === 0) {
    return <div className="signal-inspector-message">No displacement samples were returned for the full-session navigator.</div>
  }

  const activeStyle = navigatorWindowStyle(plotRef.current, activeWindow)
  const navigatorPlot = plotRef.current
  const pinnedLeft = pinnedTimeS === null || !navigatorPlot ? null : plotValueX(navigatorPlot, pinnedTimeS)

  function pointerTime(event: PointerEvent<HTMLElement>) {
    const plot = plotRef.current
    if (!plot) {
      return 0
    }
    const rect = plot.over.getBoundingClientRect()
    return clamp(plot.posToVal(event.clientX - rect.left, 'x'), 0, durationS)
  }

  function pointerX(event: PointerEvent<HTMLElement>) {
    const plot = plotRef.current
    if (!plot) {
      return 0
    }
    const geometry = plotGeometry(plot)
    if (!geometry) {
      return 0
    }
    return event.clientX - plot.root.getBoundingClientRect().left - geometry.left
  }

  function handlePointerDown(event: PointerEvent<HTMLElement>) {
    const plot = plotRef.current
    const geometry = plotGeometry(plot)
    if (!plot || !geometry) {
      return
    }
    event.preventDefault()
    const timeS = pointerTime(event)
    const viewX = pointerX(event)
    const activeStartS = clamp(activeWindow.startS, 0, durationS)
    const activeEndS = clamp(activeWindow.endS, 0, durationS)
    const activeStartX = plot.valToPos(activeStartS, 'x')
    const activeEndX = plot.valToPos(activeEndS, 'x')
    const activeSpan = Math.max(minWindowS, activeEndS - activeStartS)
    let startS = activeStartS
    let endS = activeEndS
    let mode: NavigatorDrag['mode'] = 'move'
    const handleTolerancePx = 13
    if (Math.abs(viewX - activeStartX) <= handleTolerancePx) {
      mode = 'start'
    } else if (Math.abs(viewX - activeEndX) <= handleTolerancePx) {
      mode = 'end'
    } else if (viewX >= Math.min(activeStartX, activeEndX) && viewX <= Math.max(activeStartX, activeEndX)) {
      mode = 'move'
    } else {
      startS = clamp(timeS - activeSpan / 2, 0, Math.max(0, durationS - activeSpan))
      endS = Math.min(durationS, startS + activeSpan)
      mode = 'move'
    }
    const drag: NavigatorDrag = { mode, originS: timeS, currentS: timeS, startS, endS }
    dragRef.current = drag
    setNavigatorPreview(previewRef.current, navigatorWindowFromDrag(drag, durationS, minWindowS), plot)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event: PointerEvent<HTMLElement>) {
    const drag = dragRef.current
    if (!drag) {
      return
    }
    event.preventDefault()
    const nextDrag = { ...drag, currentS: pointerTime(event) }
    dragRef.current = nextDrag
    setNavigatorPreview(previewRef.current, navigatorWindowFromDrag(nextDrag, durationS, minWindowS), plotRef.current)
  }

  function handlePointerUp(event: PointerEvent<HTMLElement>) {
    const drag = dragRef.current
    if (!drag) {
      return
    }
    event.preventDefault()
    const nextDrag = { ...drag, currentS: pointerTime(event) }
    dragRef.current = null
    setNavigatorPreview(previewRef.current, null, plotRef.current)
    onSelectWindow(navigatorWindowFromDrag(nextDrag, durationS, minWindowS))
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  function handlePointerCancel(event: PointerEvent<HTMLElement>) {
    dragRef.current = null
    setNavigatorPreview(previewRef.current, null, plotRef.current)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <section className="signal-inspector-navigator-card">
      <div className="signal-inspector-navigator-frame">
        <div className="signal-inspector-uplot-host signal-inspector-uplot-host-navigator" ref={plotHostRef} />
        <div
          className="signal-inspector-navigator-overlay"
          onPointerCancel={handlePointerCancel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          {activeStyle && (
            <div
              className={`signal-inspector-navigator-window${hideActiveWindowFill ? ' fill-hidden' : ''}`}
              style={activeStyle}
            >
              <span className="signal-inspector-navigator-handle start" />
              <span className="signal-inspector-navigator-handle end" />
            </div>
          )}
          {pinnedLeft !== null && pinnedTimeS !== null && (
            <span
              aria-label={`Pinned time ${formatTime(pinnedTimeS)}`}
              className="signal-inspector-navigator-pinned-time"
              style={{ left: `${pinnedLeft}px` }}
              title={`Pinned time: ${formatTime(pinnedTimeS)}`}
            />
          )}
          <div className="signal-inspector-navigator-preview" ref={previewRef} />
        </div>
      </div>
    </section>
  )
}

function navigatorUPlotOptions({
  height,
  model,
  width,
}: {
  height: number
  model: SignalChartModel
  width: number
}): uPlot.Options {
  const values = chartSignalValues(model.chartSignals)
  return {
    width,
    height,
    class: 'signal-inspector-uplot-navigator',
    scales: {
      x: { time: false, range: [0, model.times.at(-1) ?? 1] },
      primary: { range: paddedExtent(values) },
    },
    axes: [
      {
        scale: 'x',
        side: 2,
        values: (_plot, splits) => formatTimeAxisLabels(splits),
        stroke: '#5b6670',
        grid: { show: false },
        ticks: { stroke: '#9fb0ad', width: 1, size: 4 },
        font: '10px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
        size: 22,
      },
      { scale: 'primary', side: 3, show: false },
    ],
    series: [
      {},
      ...model.chartSignals.map((signal, index): uPlot.Series => ({
        label: signal.displayLabel,
        scale: 'primary',
        stroke: SIGNAL_COLORS[(signal.originalIndex ?? index) % SIGNAL_COLORS.length],
        width: 0.95,
        points: { show: false },
        spanGaps: false,
      })),
    ],
    legend: { show: false },
    cursor: {
      show: false,
      drag: { x: false, y: false, setScale: false },
    },
  }
}

function navigatorWindowStyle(plot: uPlot | null, window: { startS: number; endS: number }) {
  return signalWindowStyle(plot, window)
}

function signalWindowStyle(
  plot: uPlot | null,
  window: { startS: number; endS: number },
  options: { hideWhenFullDomain?: boolean } = {},
) {
  const geometry = plotGeometry(plot)
  if (!plot || !geometry) {
    return null
  }
  const xScale = plot.scales.x as { min?: number; max?: number }
  const domainStart = typeof xScale.min === 'number' && Number.isFinite(xScale.min) ? xScale.min : 0
  const domainEnd = typeof xScale.max === 'number' && Number.isFinite(xScale.max) ? xScale.max : Math.max(domainStart, window.endS)
  const requestedStartS = Math.min(window.startS, window.endS)
  const requestedEndS = Math.max(window.startS, window.endS)
  if (requestedEndS <= domainStart || requestedStartS >= domainEnd) {
    return null
  }
  const startS = clamp(requestedStartS, domainStart, domainEnd)
  const endS = clamp(requestedEndS, domainStart, domainEnd)
  const epsilon = Math.max(0.001, (domainEnd - domainStart) / 1000)
  if (
    options.hideWhenFullDomain &&
    Math.abs(startS - domainStart) <= epsilon &&
    Math.abs(endS - domainEnd) <= epsilon
  ) {
    return null
  }
  if (endS - startS <= 0) {
    return null
  }
  const startX = geometry.left + plot.valToPos(startS, 'x')
  const endX = geometry.left + plot.valToPos(endS, 'x')
  return {
    left: `${Math.min(startX, endX)}px`,
    top: `${geometry.top}px`,
    width: `${Math.max(2, Math.abs(endX - startX))}px`,
    height: `${geometry.height}px`,
  }
}

function setNavigatorPreview(
  element: HTMLDivElement | null,
  window: { startS: number; endS: number } | null,
  plot: uPlot | null,
) {
  if (!element) {
    return
  }
  const style = window ? navigatorWindowStyle(plot, window) : null
  if (!style) {
    element.style.display = 'none'
    return
  }
  element.style.display = 'block'
  element.style.left = style.left
  element.style.top = style.top
  element.style.width = style.width
  element.style.height = style.height
}

function SelectedEventPanel({
  event,
  onClear,
  onZoom,
}: {
  event: TimeseriesWindowEvent | null
  onClear: () => void
  onZoom: (window: { startS: number; endS: number }) => void
}) {
  if (!event) {
    return (
      <div className="signal-inspector-event-detail empty">
        <span>No event selected.</span>
        <InfoTip text="Click an event marker to inspect its timing. Dense event groups remain hidden until selected in the Events list." />
      </div>
    )
  }
  const eventStartS = event.startS ?? event.peakTimeS ?? event.endS ?? 0
  const eventEndS = event.endS ?? event.peakTimeS ?? event.startS ?? eventStartS
  const zoomPaddingS = Math.max(1, (eventEndS - eventStartS) * 2, 2)
  const metricEntries = eventMetricEntries(event.metrics)
  return (
    <section className="signal-inspector-event-detail">
      <div>
        <strong>{eventDisplayName(event)}</strong>
        <span>{event.end ? `${event.end} end` : 'all ends'}</span>
      </div>
      <dl>
        <dt>Start</dt>
        <dd>{event.startS !== null ? formatTime(event.startS) : 'unknown'}</dd>
        <dt>Peak</dt>
        <dd>{event.peakTimeS !== null ? formatTime(event.peakTimeS) : 'unknown'}</dd>
        <dt>End</dt>
        <dd>{event.endS !== null ? formatTime(event.endS) : 'unknown'}</dd>
        <dt>ID</dt>
        <dd>{event.eventId || 'unknown'}</dd>
      </dl>
      {metricEntries.length > 0 && (
        <div className="signal-inspector-event-metrics">
          <span>Metrics</span>
          <dl>
            {metricEntries.map(([name, value]) => (
              <Fragment key={name}>
                <dt>{formatMetricName(name)}</dt>
                <dd>{formatEventMetricValue(value)}</dd>
              </Fragment>
            ))}
          </dl>
        </div>
      )}
      <div className="signal-inspector-event-actions">
        <button
          type="button"
          onClick={() =>
            onZoom({
              startS: Math.max(0, eventStartS - zoomPaddingS),
              endS: Math.max(eventStartS + 0.2, eventEndS + zoomPaddingS),
            })
          }
        >
          Zoom to event
        </button>
        <button type="button" onClick={onClear}>
          Clear
        </button>
      </div>
    </section>
  )
}

function inspectorSignalOptions(session: SessionRecord): SessionSignalSummary[] {
  const signals = session.availableSignals ?? []
  const seen = new Set<string>()
  return signals
    .filter((signal) => signal.column && !seen.has(signal.column))
    .map((signal) => {
      seen.add(signal.column)
      return signal
    })
}

function defaultSignalColumns(signals: SessionSignalSummary[]) {
  const primary = signals.filter((signal) => signal.processingRole === 'primary_analysis')
  const source = primary.length ? primary : signals
  const wheelDisplacement = primary.filter(isWheelDisplacementSignal)
  const fallbackWheelDisplacement = wheelDisplacement.length ? wheelDisplacement : signals.filter(isWheelDisplacementSignal)
  const displacement = fallbackWheelDisplacement.length ? fallbackWheelDisplacement : source.filter(isDisplacementSignal)
  const preferred = displacement.length ? preferEngineeringDisplacementSignals(displacement) : source
  const defaults = preferred.slice(0, 4).map((signal) => signal.column)
  const speedSignal = signals.find(isWorldSpeedSignal)
  if (speedSignal && !defaults.includes(speedSignal.column)) {
    defaults.push(speedSignal.column)
  }
  return defaults
}

function preferEngineeringDisplacementSignals(signals: SessionSignalSummary[]) {
  const groups = new Map<string, SessionSignalSummary[]>()
  for (const signal of signals) {
    const key = displacementPreferenceKey(signal)
    groups.set(key, [...(groups.get(key) ?? []), signal])
  }

  return Array.from(groups.values())
    .map((group) => group.find(isEngineeringUnitDisplacement) ?? group[0])
    .sort((a, b) => signalEndRank(a) - signalEndRank(b) || a.column.localeCompare(b.column))
}

function displacementPreferenceKey(signal: SessionSignalSummary) {
  const end = normalizeSignalText(signal.end) || inferEndFromText(signal.column) || inferEndFromText(signal.displayName)
  return end ? `end:${end}` : `column:${signal.column}`
}

function isDisplacementSignal(signal: SessionSignalSummary) {
  const text = normalizeSignalText([signal.quantity, signal.displayName, signal.column].join(' '))
  return text.includes('disp') || text.includes('travel')
}

function isWheelDisplacementSignal(signal: SessionSignalSummary) {
  return isDisplacementSignal(signal) && normalizeSignalText(signal.domain) === 'wheel'
}

function isEngineeringUnitDisplacement(signal: SessionSignalSummary) {
  const unit = normalizeSignalText(signal.unit)
  const text = normalizeSignalText([signal.quantity, signal.displayName, signal.column].join(' '))
  if (!unit || ['1', 'ratio', 'norm', 'normalized', 'normalised', '%', 'percent', 'percentage'].includes(unit)) {
    return false
  }
  return !text.includes('normalized') && !text.includes('normalised') && !text.includes('disp_norm')
}

function isWorldSpeedSignal(signal: SessionSignalSummary) {
  const domain = normalizeSignalText(signal.domain)
  const quantity = normalizeSignalText(signal.quantity)
  const unit = signalUnitKey(signal)
  const text = normalizeSignalText([signal.displayName, signal.column, signal.kind, signal.sensor].join(' '))
  const worldish = ['world', 'gps', 'position', 'route'].includes(domain) || text.includes('gps') || text.includes('world')
  const speedish = ['speed', 'velocity', 'vel'].includes(quantity) || text.includes('speed')
  return worldish && speedish && ['mm/sec', 'm/sec', 'km/h', 'other:mph'].includes(unit)
}

function inferEndFromText(value: unknown) {
  const text = normalizeSignalText(value)
  if (text.includes('front')) {
    return 'front'
  }
  if (text.includes('rear')) {
    return 'rear'
  }
  return ''
}

function normalizeSignalText(value: unknown) {
  if (typeof value === 'string') {
    return value.trim().toLowerCase()
  }
  if (value === null || value === undefined) {
    return ''
  }
  return String(value).trim().toLowerCase()
}

function catalogGpsPointSet(session: SessionRecord): SessionGpsPointSet {
  return {
    present: session.gps.length > 0,
    sourceId: session.gpsSummary.preferredSourceId ?? session.gpsSummary.sources[0]?.sourceId ?? '',
    sourceKind: session.gpsSummary.preferredSourceKind ?? 'unknown',
    streamName: session.gpsSummary.sources[0]?.streamName ?? '',
    samplingMode: 'catalog',
    sourcePoints: session.gpsSummary.positionPointCount,
    returnedPoints: session.gps.length,
    maxPoints: session.gps.length,
    stride: null,
    sourceSelectionMethod: session.gpsSummary.sourceSelectionMethod,
    points: session.gps.map(([longitude, latitude]) => ({
      timeS: null,
      longitude,
      latitude,
      elevationM: null,
    })),
    path: session.gps.map(([longitude, latitude]) => [longitude, latitude] as GeoPosition),
    warnings: [...session.gpsSummary.warnings],
  }
}

function gpsPanelStatusLine(pointSet: SessionGpsPointSet) {
  if (!pointSet.present || pointSet.returnedPoints === 0) {
    return 'No GPS points returned for this session.'
  }
  const source = pointSet.sourceId || pointSet.sourceKind || 'GPS'
  const timedPointCount = pointSet.points.filter((point) => typeof point.timeS === 'number' && Number.isFinite(point.timeS)).length
  const timing = timedPointCount ? `${timedPointCount} timed` : 'no timed points'
  const stride = pointSet.stride && pointSet.stride > 1 ? `, stride ${pointSet.stride}` : ''
  return `${source}: ${pointSet.returnedPoints} of ${pointSet.sourcePoints} points, ${timing}${stride}.`
}

function makeVideoAttachmentId() {
  return `video-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function videoAttachmentPathValue(attachment: SessionVideoAttachmentRecord) {
  if (attachment.workspaceRelativePath) {
    return attachment.workspaceRelativePath
  }
  if (attachment.sessionRelativePath) {
    return attachment.sessionRelativePath
  }
  if (attachment.libraryRelativePath) {
    return attachment.libraryRelativePath
  }
  return attachment.path || attachment.uri || ''
}

function isAbsoluteLocalPath(value: string) {
  const text = value.trim()
  return /^[a-zA-Z]:[\\/]/.test(text) || text.startsWith('\\\\') || text.startsWith('/') || text.startsWith('file:')
}

function videoOffsetGuessFromMedia(mediaCreatedAtUnixS: number | null, sessionStartedAt: string) {
  if (mediaCreatedAtUnixS === null || !Number.isFinite(mediaCreatedAtUnixS)) {
    return null
  }
  const sessionStartedAtMs = Date.parse(sessionStartedAt)
  if (!Number.isFinite(sessionStartedAtMs)) {
    return null
  }
  return roundForInput(sessionStartedAtMs / 1000 - mediaCreatedAtUnixS)
}

function gpsPositionAtTime(points: SessionGpsPoint[], timeS: number): GeoPosition | null {
  if (!Number.isFinite(timeS)) {
    return null
  }
  const timedPoints = points
    .filter(
      (point) =>
        typeof point.timeS === 'number' &&
        Number.isFinite(point.timeS) &&
        Number.isFinite(point.longitude) &&
        Number.isFinite(point.latitude),
    )
    .sort((a, b) => (a.timeS ?? 0) - (b.timeS ?? 0))
  if (timedPoints.length === 0) {
    return null
  }
  if (timeS <= (timedPoints[0].timeS ?? 0)) {
    return gpsPositionFromPoint(timedPoints[0])
  }
  const lastPoint = timedPoints[timedPoints.length - 1]
  if (timeS >= (lastPoint.timeS ?? 0)) {
    return gpsPositionFromPoint(lastPoint)
  }
  for (let index = 1; index < timedPoints.length; index += 1) {
    const before = timedPoints[index - 1]
    const after = timedPoints[index]
    const beforeTimeS = before.timeS ?? 0
    const afterTimeS = after.timeS ?? beforeTimeS
    if (timeS > afterTimeS) {
      continue
    }
    if (afterTimeS <= beforeTimeS) {
      return gpsPositionFromPoint(after)
    }
    const fraction = clamp((timeS - beforeTimeS) / (afterTimeS - beforeTimeS), 0, 1)
    const elevationM =
      before.elevationM !== null &&
      after.elevationM !== null &&
      Number.isFinite(before.elevationM) &&
      Number.isFinite(after.elevationM)
        ? before.elevationM + (after.elevationM - before.elevationM) * fraction
        : null
    return elevationM === null
      ? [
          before.longitude + (after.longitude - before.longitude) * fraction,
          before.latitude + (after.latitude - before.latitude) * fraction,
        ]
      : [
          before.longitude + (after.longitude - before.longitude) * fraction,
          before.latitude + (after.latitude - before.latitude) * fraction,
          elevationM,
        ]
  }
  return null
}

function gpsPositionFromPoint(point: SessionGpsPoint): GeoPosition {
  return point.elevationM !== null && Number.isFinite(point.elevationM)
    ? [point.longitude, point.latitude, point.elevationM]
    : [point.longitude, point.latitude]
}

function gpsPathForWindow(points: SessionGpsPoint[], window: { startS: number; endS: number }) {
  const timedPoints = points
    .filter(
      (point) =>
        typeof point.timeS === 'number' &&
        Number.isFinite(point.timeS) &&
        Number.isFinite(point.longitude) &&
        Number.isFinite(point.latitude),
    )
    .sort((a, b) => (a.timeS ?? 0) - (b.timeS ?? 0))
  if (timedPoints.length < 2) {
    return []
  }
  const startS = Math.min(window.startS, window.endS)
  const endS = Math.max(window.startS, window.endS)
  const firstInside = timedPoints.findIndex((point) => (point.timeS ?? Number.NEGATIVE_INFINITY) >= startS)
  let lastInside = -1
  for (let index = timedPoints.length - 1; index >= 0; index -= 1) {
    if ((timedPoints[index].timeS ?? Number.POSITIVE_INFINITY) <= endS) {
      lastInside = index
      break
    }
  }
  if (firstInside < 0 || lastInside < 0 || firstInside > lastInside) {
    return []
  }
  const from = Math.max(0, firstInside - 1)
  const to = Math.min(timedPoints.length - 1, lastInside + 1)
  return timedPoints.slice(from, to + 1).map((point) =>
    point.elevationM !== null && Number.isFinite(point.elevationM)
      ? ([point.longitude, point.latitude, point.elevationM] as GeoPosition)
      : ([point.longitude, point.latitude] as GeoPosition),
  )
}

function gpsAltitudeSamplesForWindow(points: SessionGpsPoint[], window: { startS: number; endS: number }) {
  const startS = Math.min(window.startS, window.endS)
  const endS = Math.max(window.startS, window.endS)
  return points
    .filter(
      (point) =>
        typeof point.timeS === 'number' &&
        Number.isFinite(point.timeS) &&
        typeof point.elevationM === 'number' &&
        Number.isFinite(point.elevationM) &&
        point.timeS >= startS &&
        point.timeS <= endS,
    )
    .map((point) => ({ timeS: point.timeS as number, elevationM: point.elevationM as number }))
    .sort((a, b) => a.timeS - b.timeS)
}

function signalInspectorGridStep(span: number, candidates: number[], minimumGridlines = 3) {
  const safeSpan = Math.max(0, span)
  return [...candidates].reverse().find((candidate) => safeSpan / candidate >= minimumGridlines) ?? candidates[0]
}

function signalInspectorGridDomain(minValue: number, maxValue: number, step: number) {
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
    return { min: 0, max: step * 4 }
  }
  let min = Math.floor(minValue / step) * step
  let max = Math.ceil(maxValue / step) * step
  if (max <= min) {
    max = min + step * 4
  }
  while ((max - min) / step < 3) {
    max += step
  }
  return { min, max }
}

function signalInspectorGridTicks(min: number, max: number, step: number) {
  const ticks: number[] = []
  const start = Math.ceil(min / step) * step
  for (let value = start; value <= max + step * 0.001; value += step) {
    ticks.push(roundForInput(value))
  }
  return ticks
}

function interpolateGpsAltitude(samples: Array<{ timeS: number; elevationM: number }>, timeS: number) {
  if (!samples.length) {
    return 0
  }
  const sorted = [...samples].sort((a, b) => a.timeS - b.timeS)
  if (timeS <= sorted[0].timeS) {
    return sorted[0].elevationM
  }
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1]
    const next = sorted[index]
    if (timeS <= next.timeS) {
      const fraction = (timeS - previous.timeS) / Math.max(1e-9, next.timeS - previous.timeS)
      return previous.elevationM + (next.elevationM - previous.elevationM) * fraction
    }
  }
  return sorted[sorted.length - 1].elevationM
}

function timeseriesWindowForSignal(
  data: TimeseriesWindowResponse,
  signal: TimeseriesWindowResponse['signals'][number],
): TimeseriesWindowResponse {
  return {
    ...data,
    signals: [signal],
  }
}

function loadStoredChartMode(): SignalInspectorChartMode {
  if (typeof window === 'undefined') {
    return 'multi'
  }
  const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_CHART_MODE_STORAGE_KEY)
  return raw === 'single' || raw === 'multi' ? raw : 'multi'
}

function storeChartMode(mode: SignalInspectorChartMode) {
  if (typeof window === 'undefined') {
    return
  }
  window.localStorage.setItem(SIGNAL_INSPECTOR_CHART_MODE_STORAGE_KEY, mode)
}

function defaultViewPreferences(): SignalInspectorViewPreferences {
  return {
    sidebarOpen: true,
    controlsOpen: false,
    sidebarWidthPx: 380,
    collapsedSidebarPanels: {
      bookmarks: false,
      gpsMap: false,
      gpsAltitude: false,
      video: false,
    },
    gpsMapHeightPx: 184,
    videoHeightPx: 190,
    showEventDetails: false,
    videoSettingsCollapsed: true,
    videoScrollWithPlayback: false,
  }
}

function loadStoredViewPreferences(): SignalInspectorViewPreferences {
  const defaults = defaultViewPreferences()
  if (typeof window === 'undefined') {
    return defaults
  }
  try {
    const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_VIEW_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return defaults
    }
    const collapsedPanels =
      parsed.collapsedSidebarPanels && typeof parsed.collapsedSidebarPanels === 'object' && !Array.isArray(parsed.collapsedSidebarPanels)
        ? parsed.collapsedSidebarPanels
        : {}
    return {
      sidebarOpen: typeof parsed.sidebarOpen === 'boolean' ? parsed.sidebarOpen : defaults.sidebarOpen,
      controlsOpen: typeof parsed.controlsOpen === 'boolean' ? parsed.controlsOpen : defaults.controlsOpen,
      sidebarWidthPx:
        typeof parsed.sidebarWidthPx === 'number'
          ? clamp(parsed.sidebarWidthPx, SIGNAL_INSPECTOR_SIDEBAR_MIN_WIDTH_PX, SIGNAL_INSPECTOR_SIDEBAR_MAX_WIDTH_PX)
          : defaults.sidebarWidthPx,
      collapsedSidebarPanels: {
        bookmarks: typeof collapsedPanels.bookmarks === 'boolean' ? collapsedPanels.bookmarks : defaults.collapsedSidebarPanels.bookmarks,
        gpsMap: typeof collapsedPanels.gpsMap === 'boolean' ? collapsedPanels.gpsMap : defaults.collapsedSidebarPanels.gpsMap,
        gpsAltitude:
          typeof collapsedPanels.gpsAltitude === 'boolean' ? collapsedPanels.gpsAltitude : defaults.collapsedSidebarPanels.gpsAltitude,
        video: typeof collapsedPanels.video === 'boolean' ? collapsedPanels.video : defaults.collapsedSidebarPanels.video,
      },
      gpsMapHeightPx:
        typeof parsed.gpsMapHeightPx === 'number'
          ? clamp(parsed.gpsMapHeightPx, SIGNAL_INSPECTOR_GPS_MAP_MIN_HEIGHT_PX, SIGNAL_INSPECTOR_GPS_MAP_MAX_HEIGHT_PX)
          : defaults.gpsMapHeightPx,
      videoHeightPx:
        typeof parsed.videoHeightPx === 'number'
          ? clamp(parsed.videoHeightPx, SIGNAL_INSPECTOR_VIDEO_MIN_HEIGHT_PX, SIGNAL_INSPECTOR_VIDEO_MAX_HEIGHT_PX)
          : defaults.videoHeightPx,
      showEventDetails: typeof parsed.showEventDetails === 'boolean' ? parsed.showEventDetails : defaults.showEventDetails,
      videoSettingsCollapsed:
        typeof parsed.videoSettingsCollapsed === 'boolean' ? parsed.videoSettingsCollapsed : defaults.videoSettingsCollapsed,
      videoScrollWithPlayback:
        typeof parsed.videoScrollWithPlayback === 'boolean' ? parsed.videoScrollWithPlayback : defaults.videoScrollWithPlayback,
    }
  } catch {
    return defaults
  }
}

function storeViewPreferences(preferences: SignalInspectorViewPreferences) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(SIGNAL_INSPECTOR_VIEW_STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Ignore preference write failures; the inspector should remain usable.
  }
}

function loadStoredSignalColumns(session: SessionRecord, availableColumns: Set<string>) {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_SESSION_COLUMNS_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    const columns = Array.isArray(parsed?.[signalInspectorSessionPreferenceKey(session)])
      ? parsed[signalInspectorSessionPreferenceKey(session)]
      : null
    const validColumns = columns?.filter((column: unknown): column is string => typeof column === 'string' && availableColumns.has(column)) ?? []
    return validColumns.length > 0 ? validColumns : null
  } catch {
    return null
  }
}

function storeSignalColumns(session: SessionRecord, columns: string[]) {
  if (typeof window === 'undefined' || columns.length === 0) {
    return
  }
  try {
    const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_SESSION_COLUMNS_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    const preferences = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? { ...parsed } : {}
    preferences[signalInspectorSessionPreferenceKey(session)] = columns
    window.localStorage.setItem(SIGNAL_INSPECTOR_SESSION_COLUMNS_STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Ignore preference write failures; the inspector should remain usable.
  }
}

function loadStoredPinnedTime(session: SessionRecord, durationS: number) {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_SESSION_PINNED_TIME_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    const value = parsed?.[signalInspectorSessionPreferenceKey(session)]
    return typeof value === 'number' && Number.isFinite(value) ? sanitizeWindowBoundary(value, durationS) : null
  } catch {
    return null
  }
}

function storePinnedTime(session: SessionRecord, pinnedTimeS: number | null) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    const raw = window.localStorage.getItem(SIGNAL_INSPECTOR_SESSION_PINNED_TIME_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    const preferences = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? { ...parsed } : {}
    const key = signalInspectorSessionPreferenceKey(session)
    if (pinnedTimeS === null) {
      delete preferences[key]
    } else {
      preferences[key] = pinnedTimeS
    }
    window.localStorage.setItem(SIGNAL_INSPECTOR_SESSION_PINNED_TIME_STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Ignore preference write failures; the inspector should remain usable.
  }
}

function signalWindowRequestSignature(session: SessionRecord, selectedColumns: string[], buffered: boolean) {
  return `${session.libraryId}::${session.sessionKey}::${buffered ? 'buffered' : 'exact'}::${selectedColumns.join('|')}`
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

function signalInspectorSessionPreferenceKey(session: SessionRecord) {
  return `${session.libraryId}::${session.sessionKey}`
}

function useElementWidth(ref: RefObject<HTMLElement | null>, observeKey?: unknown) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element) {
      return
    }
    const setNextWidth = (rawWidth: number) => {
      const nextWidth = Math.max(0, Math.floor(rawWidth))
      setWidth((current) => (current === nextWidth ? current : nextWidth))
    }
    setNextWidth(element.getBoundingClientRect().width)
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      setNextWidth(entry?.contentRect.width ?? element.getBoundingClientRect().width)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [observeKey, ref])
  return width
}

function boundedPlotWidth(measuredWidth: number) {
  if (!Number.isFinite(measuredWidth) || measuredWidth <= 0) {
    return 0
  }
  const maxWidth = signalInspectorPlotToken('--signal-inspector-plot-max-width', 1800)
  return Math.floor(Math.max(0, Math.min(measuredWidth, maxWidth)))
}

function signalInspectorPlotToken(name: string, fallback: number) {
  if (typeof window === 'undefined' || !window.document?.documentElement) {
    return fallback
  }
  const value = window.getComputedStyle(window.document.documentElement).getPropertyValue(name).trim()
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function duplicateAwareSignalLabels<T extends Pick<SessionSignalSummary, 'column' | 'displayName' | 'motionSourceId' | 'sensor'>>(
  signals: T[],
) {
  const baseLabels = signals.map((signal) => signal.displayName || signal.column)
  const counts = new Map<string, number>()
  for (const label of baseLabels) {
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return signals.map((signal, index) => {
    const label = baseLabels[index]
    if ((counts.get(label) ?? 0) <= 1) {
      return label
    }
    const sourceId = signal.motionSourceId?.trim() || signal.sensor?.trim()
    return sourceId ? `${label} (${sourceId})` : label
  })
}

function buildSignalChartModel(data: TimeseriesWindowResponse): SignalChartModel {
  const displaySignals = data.signals.map(chartDisplaySignal)
  const axisUnits = chooseAxisUnits(displaySignals)
  const axisConfigs = axisUnits.map(
    (unit, index): AxisConfig => ({
      id: index === 0 ? 'primary' : `axis-${index + 1}`,
      unit,
      side: index === 0 ? 'left' : 'right',
      offset: index === 0 ? 0 : (index - 1) * 52,
    }),
  )
  const axisIdByUnitKey = new Map(axisConfigs.map((axis) => [axis.unit.key, axis.id]))
  const chartSignalsBase = displaySignals
    .map((signal, originalIndex) => {
      const unitKey = signalUnitKey(signal)
      const axisId = axisIdByUnitKey.get(unitKey)
      return axisId ? { ...signal, axisId, displayLabel: signal.displayName || signal.column, originalIndex, unitKey } : null
    })
    .filter((signal): signal is ChartSignal => signal !== null)
  const signalLabels = duplicateAwareSignalLabels(chartSignalsBase)
  const chartSignals = chartSignalsBase.map((signal, index) => ({ ...signal, displayLabel: signalLabels[index] }))
  const times: number[] = []
  const seriesValues = chartSignals.map((): Array<number | null> => [])
  for (let index = 0; index < data.time.values.length; index += 1) {
    const timeS = data.time.values[index]
    if (typeof timeS !== 'number' || !Number.isFinite(timeS)) {
      continue
    }
    times.push(timeS)
    chartSignals.forEach((signal, signalIndex) => {
      const value = signal.values[index]
      seriesValues[signalIndex].push(typeof value === 'number' && Number.isFinite(value) ? value : null)
    })
  }
  return {
    axisConfigs,
    chartSignals,
    alignedData: [times, ...seriesValues],
    times,
    seriesValues,
  }
}

function readoutForTime(model: SignalChartModel, timeS: number | null | undefined): HoverReadout | null {
  if (timeS === null || timeS === undefined || !Number.isFinite(timeS) || model.times.length === 0) {
    return null
  }
  const index = nearestTimeIndex(model.times, timeS)
  if (index === null) {
    return null
  }
  return {
    x: 0,
    timeS: model.times[index],
    values: model.chartSignals
      .map((signal, signalIndex) => ({
        label: signal.displayLabel,
        value: model.seriesValues[signalIndex]?.[index],
        unit: signal.unit,
        color: SIGNAL_COLORS[(signal.originalIndex ?? signalIndex) % SIGNAL_COLORS.length],
      }))
      .filter((item): item is HoverReadout['values'][number] => typeof item.value === 'number' && Number.isFinite(item.value)),
  }
}

function nearestTimeIndex(times: number[], timeS: number) {
  if (times.length === 0) {
    return null
  }
  let lo = 0
  let hi = times.length - 1
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2)
    if (times[mid] < timeS) {
      lo = mid + 1
    } else {
      hi = mid
    }
  }
  if (lo === 0) {
    return 0
  }
  const prev = lo - 1
  return Math.abs(times[lo] - timeS) < Math.abs(times[prev] - timeS) ? lo : prev
}

function chartDisplaySignal(signal: TimeseriesWindowResponse['signals'][number]): TimeseriesWindowResponse['signals'][number] {
  if (!isWorldSpeedSignal(signal)) {
    return signal
  }
  const compactUnit = normalizeSignalText(signal.unit).replace(/\s+/g, '')
  if (['km/h', 'kph', 'kmh'].includes(compactUnit)) {
    return { ...signal, unit: 'km/h' }
  }
  if (['m/s', 'm/sec', 'mpersec', 'mpersecond', 'ms-1', 'ms^-1'].includes(compactUnit)) {
    return {
      ...signal,
      unit: 'km/h',
      values: signal.values.map((value) => (typeof value === 'number' && Number.isFinite(value) ? value * 3.6 : value)),
    }
  }
  return signal
}

function plotGeometry(plot: uPlot | null) {
  if (!plot) {
    return null
  }
  const rootRect = plot.root.getBoundingClientRect()
  const overRect = plot.over.getBoundingClientRect()
  const left = overRect.left - rootRect.left
  const top = overRect.top - rootRect.top
  const width = plot.over.offsetWidth
  const height = plot.over.offsetHeight
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
  }
}

function plotValueX(plot: uPlot, value: number) {
  if (!Number.isFinite(value)) {
    return null
  }
  const geometry = plotGeometry(plot)
  if (!geometry) {
    return null
  }
  return geometry.left + plot.valToPos(value, 'x')
}

function signalEndRank(signal: SessionSignalSummary) {
  const end = normalizeSignalText(signal.end) || inferEndFromText(signal.column) || inferEndFromText(signal.displayName)
  if (end === 'front') {
    return 0
  }
  if (end === 'rear') {
    return 1
  }
  return 2
}

function chooseAxisUnits(signals: SessionSignalSummary[]): UnitChoice[] {
  const seen = new Set<string>()
  return signals
    .map(signalUnitKey)
    .filter((key) => {
      if (seen.has(key)) {
        return false
      }
      seen.add(key)
      return true
    })
    .sort((a, b) => unitPreferenceRank(a) - unitPreferenceRank(b))
    .map((key) => ({ key, label: unitLabelForKey(key) }))
}

function signalUnitKey(signal: SessionSignalSummary) {
  const raw = normalizeSignalText(signal.unit)
  const compact = raw.replace(/\s+/g, '')
  if (compact === 'mm') {
    return 'mm'
  }
  if (['mm/s', 'mm/sec', 'mmpersec', 'mmpersecond', 'mms-1', 'mms^-1'].includes(compact)) {
    return 'mm/sec'
  }
  if (['km/h', 'kph', 'kmh'].includes(compact)) {
    return 'km/h'
  }
  if (['m/s', 'm/sec', 'mpersec', 'mpersecond', 'ms-1', 'ms^-1'].includes(compact)) {
    return 'm/sec'
  }
  if (['1', 'ratio', 'norm', 'normalized', 'normalised'].includes(compact)) {
    return '1'
  }
  if (!compact || compact === 'count' || compact === 'counts') {
    return 'counts'
  }
  return `other:${raw}`
}

function unitPreferenceRank(key: string) {
  if (key === 'mm') {
    return 0
  }
  if (key === 'mm/sec') {
    return 1
  }
  if (key === 'km/h') {
    return 2
  }
  if (key === '1') {
    return 3
  }
  if (key === 'counts') {
    return 4
  }
  return 5
}

function unitLabelForKey(key: string) {
  if (key === 'mm') {
    return 'mm'
  }
  if (key === 'mm/sec') {
    return 'mm/sec'
  }
  if (key === 'km/h') {
    return 'km/h'
  }
  if (key === 'm/sec') {
    return 'm/s'
  }
  if (key === '1') {
    return '1'
  }
  if (key === 'counts') {
    return 'counts'
  }
  return key.replace(/^other:/, '') || 'value'
}

function chartSignalValues(signals: Array<{ values: Array<number | null> }>) {
  return signals.flatMap((signal) =>
    signal.values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)),
  )
}

function paddedExtent(values: number[]): [number, number] {
  const extent = d3.extent(values)
  const min = extent[0] ?? 0
  const max = extent[1] ?? 1
  if (min === max) {
    return [min - 1, max + 1]
  }
  const padding = (max - min) * 0.08
  return [min - padding, max + padding]
}

function axisLabel(axisId: AxisId) {
  if (axisId === 'primary') {
    return 'primary'
  }
  const match = /^axis-(\d+)$/.exec(axisId)
  const index = match ? Number(match[1]) : NaN
  if (index === 2) {
    return 'secondary'
  }
  if (index === 3) {
    return 'tertiary'
  }
  if (index === 4) {
    return 'quaternary'
  }
  return Number.isFinite(index) ? `axis ${index}` : axisId
}

function navigatorWindowFromDrag(drag: NavigatorDrag, durationS: number, minWindowS: number) {
  const startS = sanitizeWindowBoundary(drag.startS, durationS)
  const endS = sanitizeWindowBoundary(drag.endS, durationS)
  const span = Math.max(minWindowS, endS - startS)
  if (drag.mode === 'start') {
    const start = clamp(drag.currentS, 0, Math.max(0, endS - minWindowS))
    return { startS: start, endS: Math.max(start + minWindowS, endS) }
  }
  if (drag.mode === 'end') {
    const end = clamp(drag.currentS, Math.min(durationS, startS + minWindowS), durationS)
    return { startS: Math.min(startS, end - minWindowS), endS: end }
  }
  const delta = drag.currentS - drag.originS
  const nextStart = clamp(startS + delta, 0, Math.max(0, durationS - span))
  return { startS: nextStart, endS: Math.min(durationS, nextStart + span) }
}

function groupEvents(events: TimeseriesWindowEvent[]): EventGroup[] {
  const counts = new Map<string, { label: string; count: number }>()
  for (const event of events) {
    const key = eventGroupKey(event)
    const current = counts.get(key)
    if (current) {
      current.count += 1
    } else {
      counts.set(key, { label: eventGroupLabel(event), count: 1 })
    }
  }
  return Array.from(counts.entries())
    .map(([key, value], index) => ({
      key,
      label: value.label,
      count: value.count,
      dense: value.count > DENSE_EVENT_CUTOFF,
      color: EVENT_COLORS[index % EVENT_COLORS.length],
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

function eventGroupKey(event: TimeseriesWindowEvent) {
  return `${event.eventType || event.displayName}|||${event.end || 'all'}`
}

function eventGroupLabel(event: TimeseriesWindowEvent) {
  const base = eventDisplayName(event)
  return event.end ? `${base} (${event.end})` : base
}

function eventDisplayName(event: TimeseriesWindowEvent) {
  const raw = event.eventType || event.displayName || 'event'
  const withoutSuffix = (event.eventType ? raw : raw.replace(/\b(front|rear|wheel)\b/gi, '')).replace(/_all$/i, '')
  return withoutSuffix
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(' ')
}

function markInWindow(mark: TimeseriesWindowMark, window: SessionTimeWindow) {
  return Number.isFinite(mark.timeS) && mark.timeS >= window.startS && mark.timeS <= window.endS
}

function eventInWindow(event: TimeseriesWindowEvent, window: SessionTimeWindow) {
  const eventStartS = event.startS ?? event.peakTimeS ?? event.endS
  const eventEndS = event.endS ?? event.peakTimeS ?? event.startS
  if (!Number.isFinite(eventStartS) || !Number.isFinite(eventEndS)) {
    return false
  }
  return Math.max(eventStartS as number, window.startS) <= Math.min(eventEndS as number, window.endS)
}

function timeseriesDataCoverage(data: TimeseriesWindowResponse | undefined): SessionTimeWindow | null {
  if (!data) {
    return null
  }
  const startS = data.window.returnedStartS ?? data.window.requestedStartS ?? data.time.values.find((value) => typeof value === 'number') ?? null
  const endS =
    data.window.returnedEndS ??
    data.window.requestedEndS ??
    [...data.time.values].reverse().find((value) => typeof value === 'number') ??
    null
  if (typeof startS !== 'number' || typeof endS !== 'number' || !Number.isFinite(startS) || !Number.isFinite(endS) || endS <= startS) {
    return null
  }
  return { startS, endS }
}

function timeseriesDataMeetsResolution(data: TimeseriesWindowResponse | undefined, targetPoints: number) {
  if (!data) {
    return false
  }
  return data.sampling.mode === 'raw' || data.sampling.targetPoints >= targetPoints
}

function timeseriesDataMatchesSelectedSignals(
  data: TimeseriesWindowResponse | undefined,
  selectedColumns: readonly string[],
) {
  if (!data) {
    return false
  }
  const requestedColumns = new Set(selectedColumns)
  const returnedColumns = new Set(data.signals.map((signal) => signal.column))
  return (
    requestedColumns.size === selectedColumns.length &&
    returnedColumns.size === data.signals.length &&
    returnedColumns.size === requestedColumns.size &&
    [...requestedColumns].every((column) => returnedColumns.has(column))
  )
}

function windowContains(container: SessionTimeWindow, child: SessionTimeWindow, toleranceS = 0.05) {
  return container.startS <= child.startS + toleranceS && container.endS >= child.endS - toleranceS
}

function windowHasPlaybackRunway(container: SessionTimeWindow, visibleWindow: SessionTimeWindow, durationS: number) {
  if (!windowContains(container, visibleWindow)) {
    return false
  }
  const visibleSpanS = Math.max(0.1, visibleWindow.endS - visibleWindow.startS)
  const runwayS = playbackBufferRunwayS(visibleSpanS)
  const hasLeftRunway = visibleWindow.startS <= runwayS || container.startS <= visibleWindow.startS - runwayS
  const hasRightRunway = visibleWindow.endS >= durationS - runwayS || container.endS >= visibleWindow.endS + runwayS
  return hasLeftRunway && hasRightRunway
}

function playbackBufferRunwayS(visibleSpanS: number) {
  return Math.min(30, Math.max(8, visibleSpanS * 1.5))
}

function bufferedSignalFetchWindow(visibleWindow: SessionTimeWindow, durationS: number) {
  const visibleSpanS = Math.max(0.1, visibleWindow.endS - visibleWindow.startS)
  const bufferSpanS = Math.min(
    durationS,
    Math.max(
      SIGNAL_INSPECTOR_VIDEO_BUFFER_MIN_SPAN_S,
      Math.min(SIGNAL_INSPECTOR_VIDEO_BUFFER_MAX_SPAN_S, visibleSpanS * SIGNAL_INSPECTOR_VIDEO_BUFFER_MULTIPLIER),
    ),
  )
  const centerS = (visibleWindow.startS + visibleWindow.endS) / 2
  const maxStartS = Math.max(0, durationS - bufferSpanS)
  const startS = clamp(centerS - bufferSpanS / 2, 0, maxStartS)
  return { startS, endS: Math.min(durationS, startS + bufferSpanS) }
}

function signalWindowTargetPoints(visibleWindow: SessionTimeWindow, fetchWindow: SessionTimeWindow) {
  const visibleSpanS = Math.max(0.1, visibleWindow.endS - visibleWindow.startS)
  const fetchSpanS = Math.max(visibleSpanS, fetchWindow.endS - fetchWindow.startS)
  let visibleTarget = TARGET_POINTS
  if (visibleSpanS <= SIGNAL_INSPECTOR_SHORT_WINDOW_DETAIL_SPAN_S) {
    visibleTarget = SIGNAL_INSPECTOR_SHORT_WINDOW_TARGET_POINTS
  } else if (visibleSpanS <= SIGNAL_INSPECTOR_MEDIUM_WINDOW_DETAIL_SPAN_S) {
    visibleTarget = SIGNAL_INSPECTOR_MEDIUM_WINDOW_TARGET_POINTS
  }
  const scaledTarget = Math.ceil(visibleTarget * (fetchSpanS / visibleSpanS))
  return Math.max(2, Math.min(SIGNAL_INSPECTOR_MAX_TARGET_POINTS, scaledTarget))
}

function sanitizeWindow(startS: number, endS: number, durationS: number) {
  const start = sanitizeWindowBoundary(Math.min(startS, endS), durationS)
  const end = sanitizeWindowBoundary(Math.max(startS, endS), durationS)
  if (end <= start) {
    return { startS: Math.max(0, start - 0.1), endS: Math.min(durationS, start + 0.1) }
  }
  return { startS: start, endS: end }
}

function midpointOfWindow(window: SessionTimeWindow) {
  return roundForInput((window.startS + window.endS) / 2)
}

function sanitizeWindowBoundary(value: number, durationS: number) {
  return Math.max(0, Math.min(durationS, Number.isFinite(value) ? value : 0))
}

function visibleWindowWarnings(warnings: string[], window: { startS: number; endS: number }, durationS: number) {
  return warnings.filter((warning) => {
    if (warning === 'requested_window_starts_before_session' && window.startS <= 0.05) {
      return false
    }
    if (warning === 'requested_window_ends_after_session' && window.endS >= durationS - 0.05) {
      return false
    }
    return true
  })
}

function nearlyEqual(a: number, b: number) {
  return Math.abs(a - b) < 0.01
}

function sameStringSet(a: string[], b: string[]) {
  if (a.length !== b.length) {
    return false
  }
  const bSet = new Set(b)
  return a.every((value) => bSet.has(value))
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function roundForInput(value: number) {
  return Math.round(value * 10) / 10
}

function formatTime(value: number) {
  return formatTimeAxisValue(value, 1)
}

function formatTimeAxisLabels(values: number[]) {
  const finiteValues = values.filter((value) => Number.isFinite(value))
  for (let decimals = 0; decimals <= 6; decimals += 1) {
    const labels = values.map((value) => formatTimeAxisValue(value, decimals))
    const finiteLabels = finiteValues.map((value) => formatTimeAxisValue(value, decimals))
    if (new Set(finiteLabels).size === finiteLabels.length) {
      return labels
    }
  }
  return values.map((value) => formatTimeAxisValue(value, 6))
}

function formatTimeAxisValue(value: number, decimals: number) {
  if (!Number.isFinite(value)) {
    return '0:00'
  }
  const sign = value < 0 ? '-' : ''
  const factor = 10 ** decimals
  const roundedTotal = Math.round(Math.abs(value) * factor) / factor
  const minutes = Math.floor(roundedTotal / 60)
  const seconds = roundedTotal - minutes * 60
  if (decimals === 0) {
    return `${sign}${minutes}:${String(Math.round(seconds)).padStart(2, '0')}`
  }
  const secondsText = seconds.toFixed(decimals).padStart(3 + decimals, '0')
  return `${sign}${minutes}:${secondsText}`
}

function formatBookmarkWindow(window: { startS: number; endS: number }) {
  if (nearlyEqual(window.startS, window.endS)) {
    return `Point ${formatTime(window.startS)}`
  }
  return `${formatTime(window.startS)} - ${formatTime(window.endS)}`
}

function formatAxisValue(value: number) {
  if (Math.abs(value) >= 1000) {
    return d3.format('~s')(value)
  }
  return d3.format('~g')(value)
}

function formatReadoutValue(value: number) {
  const abs = Math.abs(value)
  if (abs >= 1000) {
    return d3.format(',.0f')(value)
  }
  if (abs >= 100) {
    return d3.format(',.1f')(value)
  }
  if (abs >= 10) {
    return d3.format(',.2f')(value)
  }
  return d3.format(',.3f')(value)
}

function eventMetricEntries(metrics: Record<string, unknown> | undefined) {
  if (!metrics) {
    return []
  }
  return Object.entries(metrics)
    .filter(([, value]) => {
      if (value === null || value === undefined) {
        return false
      }
      if (typeof value === 'number') {
        return Number.isFinite(value)
      }
      if (typeof value === 'string') {
        return value.trim().length > 0
      }
      return typeof value === 'boolean'
    })
    .sort(([left], [right]) => left.localeCompare(right))
}

function formatMetricName(name: string) {
  return name
    .replace(/^m_/, '')
    .replace(/^d_/, '')
    .replace(/_/g, ' ')
}

function formatEventMetricValue(value: unknown) {
  if (typeof value === 'number') {
    return formatReadoutValue(value)
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no'
  }
  return String(value)
}
