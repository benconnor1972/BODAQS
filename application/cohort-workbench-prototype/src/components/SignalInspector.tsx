import { useEffect, useMemo, useRef, useState, type PointerEvent, type RefObject } from 'react'
import * as d3 from 'd3'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { ChevronLeft, ChevronRight, Map as MapIcon, RefreshCcw, Save, SkipBack, SkipForward, Trash2 } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { gpsSourceDisplay } from '../domain/geospatial'
import { sessionToStudyRef } from '../domain/studySets'
import { InfoTip } from './Common'
import { MapRoutePreview, type HighlightPathOverlay } from './MapRoutePreview'
import { GpsBadge } from './StatusBadges'
import type {
  SessionRecord,
  SessionBookmarkRecord,
  SessionGpsPoint,
  SessionGpsPointSet,
  SessionSignalSummary,
  TimeseriesWindowEvent,
  TimeseriesWindowMark,
  TimeseriesWindowResponse,
} from '../domain/types'

const TARGET_POINTS = 1800
const NAVIGATOR_POINTS = 900
const DENSE_EVENT_CUTOFF = 50
const SIGNAL_COLORS = ['#008c95', '#101820', '#2d5f64', '#b88a43', '#6f7b80', '#9aa7a3']
const EVENT_COLORS = ['#b66a2c', '#4d70a8', '#8a5a7b', '#6f7e2e', '#c46f58', '#2f7d6d']

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

type NavigatorDrag = {
  mode: 'start' | 'end' | 'move'
  originS: number
  currentS: number
  startS: number
  endS: number
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

function loadStateData(state: LoadState) {
  return state.status === 'ready' || state.status === 'loading' || state.status === 'error' ? state.data : undefined
}

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
  const initialColumns = useMemo(() => defaultSignalColumns(signalOptions), [signalOptions])
  const [selectedColumns, setSelectedColumns] = useState<string[]>(initialColumns)
  const [windowStartS, setWindowStartS] = useState(() => sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS))
  const [windowEndS, setWindowEndS] = useState(() => sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS))
  const [bookmarks, setBookmarks] = useState<SessionBookmarkRecord[]>([])
  const [activeBookmarkId, setActiveBookmarkId] = useState<string | null>(null)
  const [bookmarkTitle, setBookmarkTitle] = useState('')
  const [bookmarkPointS, setBookmarkPointS] = useState(() =>
    roundForInput((sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS) + sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS)) / 2),
  )
  const [bookmarkMessage, setBookmarkMessage] = useState('')
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [showMarks, setShowMarks] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [controlsOpen, setControlsOpen] = useState(false)
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
  const eventGroupsInitializedRef = useRef(false)

  useEffect(() => {
    setSelectedColumns(defaultSignalColumns(signalOptions))
    setWindowStartS(sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS))
    setWindowEndS(sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS))
    setActiveBookmarkId(null)
    setBookmarkTitle('')
    setBookmarkPointS(
      roundForInput(
        (sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS) +
          sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS)) /
          2,
      ),
    )
    setBookmarkMessage('')
    setSelectedEventId(null)
    setShowMarks(true)
    setEventGroups([])
    setVisibleEventGroups([])
    eventGroupsInitializedRef.current = false
  }, [durationS, initialWindow?.endS, initialWindow?.startS, session.sessionKey, signalOptions])

  const requestWindow = sanitizeWindow(windowStartS, windowEndS, durationS)
  const displayedWindowData = loadStateData(loadState)
  const visibleWarnings = displayedWindowData
    ? visibleWindowWarnings(displayedWindowData.warnings, requestWindow, durationS)
    : []
  const bookmarkWindow = {
    startS: sanitizeWindowBoundary(windowStartS, durationS),
    endS: sanitizeWindowBoundary(windowEndS, durationS),
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
    async function loadWindow() {
      if (selectedColumns.length === 0) {
        setLoadState({ status: 'idle', message: 'Select one or more signals to inspect.' })
        return
      }
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
          window: requestWindow,
          resolution: { targetPoints: TARGET_POINTS },
          includeEvents: true,
          includeMarks: true,
        })
        if (!cancelled) {
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
    }

    void loadWindow()
    return () => {
      cancelled = true
    }
  }, [dataSource, requestWindow.endS, requestWindow.startS, selectedColumns, session])

  const markCount = displayedWindowData?.marks.length ?? 0

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
          setVisibleEventGroups([])
          eventGroupsInitializedRef.current = false
        }
      }
    }

    void loadFullSessionEvents()
    return () => {
      cancelled = true
    }
  }, [dataSource, durationS, eventSignalColumn, session.libraryId, session.sessionKey])

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
      setSelectedEventId(null)
      return
    }
    setSelectedEventId((current) =>
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

  async function saveBookmark(kind: 'window' | 'point') {
    const pointS = sanitizeWindowBoundary(bookmarkPointS, durationS)
    const window =
      kind === 'point'
        ? { startS: pointS, endS: pointS }
        : { startS: requestWindow.startS, endS: requestWindow.endS }
    const title =
      bookmarkTitle.trim() ||
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
      setBookmarkTitle('')
      setBookmarkMessage('')
      onBookmarksChanged?.(session)
    } catch (error) {
      setBookmarkMessage(error instanceof Error ? `Could not save bookmark: ${error.message}` : 'Could not save bookmark.')
    }
  }

  function applyBookmark(bookmark: SessionBookmarkRecord) {
    setWindowStartS(sanitizeWindowBoundary(bookmark.window.startS, durationS))
    setWindowEndS(sanitizeWindowBoundary(bookmark.window.endS, durationS))
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

  return (
    <div className="signal-inspector">
      <div
        className={`signal-inspector-layout${sidebarOpen ? '' : ' sidebar-collapsed'}${
          controlsOpen ? '' : ' controls-collapsed'
        }`}
      >
        {sidebarOpen ? (
        <aside className="signal-inspector-sidebar">
          <section className="signal-inspector-card">
            <div className="signal-inspector-card-header">
              <h3>
                Bookmarks
                <InfoTip text="Save bookmarks to return to windows or exact points while inspecting this session." />
              </h3>
              <div className="signal-inspector-card-actions">
                <small>{sortedBookmarks.length} saved</small>
                <button aria-label="Collapse bookmarks and GPS" type="button" onClick={() => setSidebarOpen(false)}>
                  <ChevronLeft size={15} />
                </button>
              </div>
            </div>
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
                aria-label="Bookmark point in seconds"
                min={0}
                max={durationS}
                step={0.1}
                type="number"
                value={roundForInput(bookmarkPointS)}
                onChange={(event) => setBookmarkPointS(Number(event.target.value))}
              />
              <button type="button" onClick={() => saveBookmark('point')} disabled={selectedColumns.length === 0}>
                Save point
              </button>
            </div>
            {bookmarkMessage && <p className="signal-inspector-bookmark-message">{bookmarkMessage}</p>}
            {sortedBookmarks.length === 0 ? (
              <p>No bookmarks yet.</p>
            ) : (
              <div className="signal-inspector-bookmark-list">
                {sortedBookmarks.map((bookmark) => (
                  <div className={bookmark.id === activeBookmarkId ? 'active' : ''} key={bookmark.id}>
                    <button type="button" onClick={() => applyBookmark(bookmark)}>
                      <strong>{bookmark.title}</strong>
                      <small>
                        {formatBookmarkWindow(bookmark.window)}
                      </small>
                    </button>
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
          </section>
          <SignalInspectorGpsPanel
            activeWindow={requestWindow}
            dataSource={dataSource}
            session={session}
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
            <span>Bookmarks / GPS</span>
          </button>
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
              {eventGroups.length === 0 ? (
                <p>No event overlays returned for this session.</p>
              ) : eventGroups.map((group) => (
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
          {loadState.status === 'loading' && !displayedWindowData && <div className="signal-inspector-message">{loadState.message}</div>}
          {loadState.status === 'error' && !displayedWindowData && (
            <div className="signal-inspector-message warning">Could not load signals: {loadState.message}</div>
          )}
          {loadState.status === 'idle' && <div className="signal-inspector-message">{loadState.message}</div>}
          {displayedWindowData && (
            <>
              {loadState.status === 'loading' && <div className="signal-inspector-update-pill">{loadState.message}</div>}
              <SignalWindowChart
                data={displayedWindowData}
                durationS={durationS}
                visibleEventGroups={visibleEventGroups}
                showMarks={showMarks}
                eventGroups={eventGroups}
                selectedEventId={selectedEventId}
                onSelectEvent={setSelectedEventId}
                onSelectWindow={(window) => {
                  setWindowStartS(window.startS)
                  setWindowEndS(window.endS)
                  setBookmarkPointS(roundForInput((window.startS + window.endS) / 2))
                }}
              />
              <SignalNavigator
                state={navigatorState}
                activeWindow={requestWindow}
                durationS={durationS}
                onSelectWindow={(window) => {
                  setWindowStartS(window.startS)
                  setWindowEndS(window.endS)
                  setBookmarkPointS(roundForInput((window.startS + window.endS) / 2))
                }}
              />
              <SelectedEventPanel
                event={displayedWindowData.events.find((event) => event.eventId === selectedEventId) ?? null}
                onClear={() => setSelectedEventId(null)}
                onZoom={(window) => {
                  setWindowStartS(window.startS)
                  setWindowEndS(window.endS)
                  setBookmarkPointS(roundForInput((window.startS + window.endS) / 2))
                }}
              />
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
        </section>
      </div>
    </div>
  )
}

function SignalInspectorGpsPanel({
  activeWindow,
  dataSource,
  session,
}: {
  activeWindow: { startS: number; endS: number }
  dataSource: LibraryDataSource
  session: SessionRecord
}) {
  const fallbackPointSet = useMemo(() => catalogGpsPointSet(session), [session])
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

  const pointSet = gpsState.pointSet
  const fullPath = pointSet?.path ?? []
  const windowPath = useMemo(
    () => (pointSet ? gpsPathForWindow(pointSet.points, activeWindow) : []),
    [activeWindow.endS, activeWindow.startS, pointSet],
  )
  const highlightPaths = useMemo<HighlightPathOverlay[]>(
    () =>
      windowPath.length >= 2
        ? [
            {
              id: 'signal-window',
              label: 'Signal window',
              path: windowPath,
              color: '#008c95',
              width: 7,
              opacity: 0.95,
            },
          ]
        : [],
    [windowPath],
  )
  const timedPointCount = pointSet?.points.filter((point) => typeof point.timeS === 'number' && Number.isFinite(point.timeS)).length ?? 0

  return (
    <section className="signal-inspector-card signal-inspector-gps-card">
      <div className="signal-inspector-card-header">
        <h3>
          GPS
          <InfoTip text="Shows the session GPS path and highlights the portion covered by the current signal window when time-aligned GPS points are available." />
        </h3>
        <GpsBadge summary={session.gpsSummary} />
      </div>
      {fullPath.length >= 2 ? (
        <div className="signal-inspector-gps-map">
          <MapRoutePreview
            currentTracks={[]}
            highlightPaths={highlightPaths}
            primaryGpsPath={fullPath}
            primarySession={session}
            selectedTracks={[]}
          />
        </div>
      ) : (
        <div className="signal-inspector-gps-empty">
          <MapIcon size={20} />
          <span>No GPS path is available for this session.</span>
        </div>
      )}
      <dl className="signal-inspector-gps-summary">
        <dt>Source</dt>
        <dd>{gpsSourceDisplay(session.gpsSummary.preferredSourceKind, session.gpsSummary.preferredSourceId)}</dd>
        <dt>Points</dt>
        <dd>{pointSet ? `${pointSet.returnedPoints} returned` : 'none'}</dd>
        <dt>Window</dt>
        <dd>{highlightPaths.length ? `${windowPath.length} GPS points` : timedPointCount ? 'No GPS points in window' : 'No timed GPS points'}</dd>
      </dl>
    </section>
  )
}

function SignalWindowChart({
  data,
  durationS,
  eventGroups,
  selectedEventId,
  showMarks,
  visibleEventGroups,
  onSelectEvent,
  onSelectWindow,
}: {
  data: TimeseriesWindowResponse
  durationS: number
  eventGroups: EventGroup[]
  selectedEventId: string | null
  showMarks: boolean
  visibleEventGroups: string[]
  onSelectEvent: (eventId: string | null) => void
  onSelectWindow: (window: { startS: number; endS: number }) => void
}) {
  const plotHostRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const onSelectWindowRef = useRef(onSelectWindow)
  const hostWidth = useElementWidth(plotHostRef)
  const [hover, setHover] = useState<HoverReadout | null>(null)
  const hoverFrameRef = useRef<number | null>(null)
  const pendingHoverRef = useRef<HoverReadout | null>(null)
  const [plotVersion, setPlotVersion] = useState(0)
  const chartModel = useMemo(() => buildSignalChartModel(data), [data])
  const plotWidth = boundedPlotWidth(hostWidth)
  const plotHeight = 500
  const chartValues = chartSignalValues(chartModel.chartSignals)
  const selectedEventGroups = new Set(visibleEventGroups)
  const groupColorByKey = new Map(eventGroups.map((group) => [group.key, group.color]))
  const groupLaneByKey = new Map(eventGroups.map((group, index) => [group.key, index % 4]))
  const visibleEvents = data.events.filter((event) => selectedEventGroups.has(eventGroupKey(event)))
  const xDomain = d3.extent(chartModel.times)
  const visibleMarks = showMarks ? data.marks.filter((mark) => markInDomain(mark, xDomain)) : []

  useEffect(() => {
    onSelectWindowRef.current = onSelectWindow
  }, [onSelectWindow])

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
        width: plotWidth,
        height: plotHeight,
        onHover: scheduleHover,
        onSelectWindow: (window) => onSelectWindowRef.current(window),
      }),
      chartModel.alignedData,
      plotHostRef.current,
    )
    plotRef.current = plot
    const handleMouseLeave = () => scheduleHover(null)
    plot.over.addEventListener('mouseleave', handleMouseLeave)
    setPlotVersion((version) => version + 1)
    return () => {
      plot.over.removeEventListener('mouseleave', handleMouseLeave)
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
  }, [chartModel, chartValues.length, plotHeight, plotWidth])

  if (data.signals.length === 0 || chartModel.times.length === 0 || chartValues.length === 0) {
    return <div className="signal-inspector-message">No matching signal samples were returned for this window.</div>
  }

  return (
    <div className="signal-inspector-chart-card">
      <div className="signal-inspector-chart-frame">
        <button
          className="signal-inspector-full-session-control"
          type="button"
          onClick={() => onSelectWindow({ startS: 0, endS: durationS })}
        >
          <RefreshCcw size={14} />
          Full session
        </button>
        <div className="signal-inspector-uplot-host" ref={plotHostRef} />
        <SignalPlotOverlay
          eventGroups={eventGroups}
          groupColorByKey={groupColorByKey}
          groupLaneByKey={groupLaneByKey}
          marks={visibleMarks}
          onSelectEvent={onSelectEvent}
          plot={plotRef.current}
          selectedEventId={selectedEventId}
          version={plotVersion}
          visibleEvents={visibleEvents}
        />
        {hover && (
          <div className="signal-inspector-readout">
            <strong>{formatTime(hover.timeS)}</strong>
            {hover.values.slice(0, 6).map((item) => (
              <span key={item.label}>
                <i style={{ background: item.color }} />
                {item.label}: {formatReadoutValue(item.value)}
                {item.unit ? ` ${item.unit}` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="signal-inspector-legend">
        {chartModel.chartSignals.map((signal, index) => (
          <span key={signal.column}>
            <i style={{ background: SIGNAL_COLORS[(signal.originalIndex ?? index) % SIGNAL_COLORS.length] }} />
            {signal.displayLabel}
            {signal.unit ? ` (${signal.unit})` : ''}
            {signal.axisId !== 'primary' ? `, ${axisLabel(signal.axisId)} axis` : ''}
          </span>
        ))}
        {visibleMarks.length > 0 && (
          <span>
            <i className="signal-inspector-mark-swatch" />
            Logger marks ({visibleMarks.length})
          </span>
        )}
      </div>
    </div>
  )
}

function SignalPlotOverlay({
  eventGroups,
  groupColorByKey,
  groupLaneByKey,
  marks,
  onSelectEvent,
  plot,
  selectedEventId,
  version,
  visibleEvents,
}: {
  eventGroups: EventGroup[]
  groupColorByKey: Map<string, string>
  groupLaneByKey: Map<string, number>
  marks: TimeseriesWindowMark[]
  onSelectEvent: (eventId: string | null) => void
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
  return (
    <div className="signal-inspector-plot-overlay">
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
          />
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
  height,
  model,
  onHover,
  onSelectWindow,
  width,
}: {
  height: number
  model: SignalChartModel
  onHover: (hover: HoverReadout | null) => void
  onSelectWindow: (window: { startS: number; endS: number }) => void
  width: number
}): uPlot.Options {
  const valuesByAxis = new Map(
    model.axisConfigs.map((axis) => [axis.id, chartSignalValues(model.chartSignals.filter((signal) => signal.axisId === axis.id))]),
  )
  const scales: uPlot.Scales = {
    x: { time: false },
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
      label: 'Time (s)',
      values: (_plot, splits) => splits.map((value) => formatTime(value)),
      stroke: '#5b6670',
      grid: { show: false },
      ticks: { stroke: '#9fb0ad', width: 1, size: 5 },
      font: '10px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
      labelFont: '11px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
    },
    ...model.axisConfigs.map((axis, index): uPlot.Axis => ({
      scale: axis.id,
      side: index === 0 ? 3 : 1,
      label: axis.unit.label,
      values: (_plot, splits) => splits.map((value) => formatAxisValue(value)),
      stroke: '#5b6670',
      grid: index === 0 ? { stroke: 'rgba(79, 116, 119, 0.15)', width: 1 } : { show: false },
      ticks: { stroke: '#9fb0ad', width: 1, size: 5 },
      size: index === 0 ? 52 : 48,
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
      drag: { x: true, y: false, setScale: false },
      points: { size: 5, width: 1 },
    },
    hooks: {
      setCursor: [
        (plot) => {
          const index = plot.cursor.idx
          if (index === null || index === undefined || index < 0 || index >= model.times.length) {
            onHover(null)
            return
          }
          const timeS = model.times[index]
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
      setSelect: [
        (plot) => {
          if (plot.select.width < 4) {
            return
          }
          const startS = plot.posToVal(plot.select.left, 'x')
          const endS = plot.posToVal(plot.select.left + plot.select.width, 'x')
          const nextStartS = Math.max(0, Math.min(startS, endS))
          const nextEndS = Math.min(Math.max(startS, endS), model.times.at(-1) ?? Math.max(startS, endS))
          if (nextEndS - nextStartS >= 0.1) {
            onSelectWindow({ startS: nextStartS, endS: nextEndS })
          }
          plot.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false)
        },
      ],
    },
  }
}

function SignalNavigator({
  state,
  activeWindow,
  durationS,
  onSelectWindow,
}: {
  state: LoadState
  activeWindow: { startS: number; endS: number }
  durationS: number
  onSelectWindow: (window: { startS: number; endS: number }) => void
}) {
  const plotHostRef = useRef<HTMLDivElement | null>(null)
  const previewRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const dragRef = useRef<NavigatorDrag | null>(null)
  const hostWidth = useElementWidth(plotHostRef)
  const [plotVersion, setPlotVersion] = useState(0)
  const data = state.status === 'ready' ? state.data : null
  const model = useMemo(() => (data ? buildSignalChartModel(data) : null), [data])
  const plotWidth = boundedPlotWidth(hostWidth)
  const plotHeight = 108
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
            <div className="signal-inspector-navigator-window" style={activeStyle}>
              <span className="signal-inspector-navigator-handle start" />
              <span className="signal-inspector-navigator-handle end" />
            </div>
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
        values: (_plot, splits) => splits.map((value) => formatTime(value)),
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
  const geometry = plotGeometry(plot)
  if (!plot || !geometry) {
    return null
  }
  const xScale = plot.scales.x as { min?: number; max?: number }
  const domainStart = typeof xScale.min === 'number' && Number.isFinite(xScale.min) ? xScale.min : 0
  const domainEnd = typeof xScale.max === 'number' && Number.isFinite(xScale.max) ? xScale.max : Math.max(domainStart, window.endS)
  const startS = clamp(window.startS, domainStart, domainEnd)
  const endS = clamp(window.endS, domainStart, domainEnd)
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
  return preferred.slice(0, 4).map((signal) => signal.column)
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
    path: session.gps.map(([longitude, latitude]) => [longitude, latitude] as [number, number]),
    warnings: [...session.gpsSummary.warnings],
  }
}

function gpsPanelStatusLine(pointSet: SessionGpsPointSet) {
  if (!pointSet.present || pointSet.returnedPoints === 0) {
    return 'No GPS points returned for this session.'
  }
  const source = gpsSourceDisplay(pointSet.sourceKind, pointSet.sourceId)
  const timedPointCount = pointSet.points.filter((point) => typeof point.timeS === 'number' && Number.isFinite(point.timeS)).length
  const timing = timedPointCount ? `${timedPointCount} timed` : 'no timed points'
  const stride = pointSet.stride && pointSet.stride > 1 ? `, stride ${pointSet.stride}` : ''
  return `${source}: ${pointSet.returnedPoints} of ${pointSet.sourcePoints} points, ${timing}${stride}.`
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
  return timedPoints.slice(from, to + 1).map((point) => [point.longitude, point.latitude] as [number, number])
}

function useElementWidth(ref: RefObject<HTMLElement | null>) {
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
  }, [ref])
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
  const axisUnits = chooseAxisUnits(data.signals)
  const axisConfigs = axisUnits.map(
    (unit, index): AxisConfig => ({
      id: index === 0 ? 'primary' : `axis-${index + 1}`,
      unit,
      side: index === 0 ? 'left' : 'right',
      offset: index === 0 ? 0 : (index - 1) * 52,
    }),
  )
  const axisIdByUnitKey = new Map(axisConfigs.map((axis) => [axis.unit.key, axis.id]))
  const chartSignalsBase = data.signals
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
  if (key === '1') {
    return 2
  }
  if (key === 'counts') {
    return 3
  }
  return 4
}

function unitLabelForKey(key: string) {
  if (key === 'mm') {
    return 'mm'
  }
  if (key === 'mm/sec') {
    return 'mm/sec'
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

function markInDomain(mark: TimeseriesWindowMark, domain: [number | undefined, number | undefined]) {
  if (!Number.isFinite(mark.timeS)) {
    return false
  }
  const start = domain[0] ?? Number.NEGATIVE_INFINITY
  const end = domain[1] ?? Number.POSITIVE_INFINITY
  return mark.timeS >= start && mark.timeS <= end
}

function sanitizeWindow(startS: number, endS: number, durationS: number) {
  const start = sanitizeWindowBoundary(Math.min(startS, endS), durationS)
  const end = sanitizeWindowBoundary(Math.max(startS, endS), durationS)
  if (end <= start) {
    return { startS: Math.max(0, start - 0.1), endS: Math.min(durationS, start + 0.1) }
  }
  return { startS: start, endS: end }
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
  if (!Number.isFinite(value)) {
    return '0:00'
  }
  const minutes = Math.floor(value / 60)
  const seconds = Math.round(value % 60)
  return `${minutes}:${String(seconds).padStart(2, '0')}`
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
