import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import * as d3 from 'd3'
import { RefreshCcw, Save, SkipBack, SkipForward, Trash2 } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionToStudyRef } from '../domain/studySets'
import type {
  SessionRecord,
  SessionSignalSummary,
  TimeseriesWindowEvent,
  TimeseriesWindowMark,
  TimeseriesWindowResponse,
} from '../domain/types'

const TARGET_POINTS = 1800
const DENSE_EVENT_CUTOFF = 50
const SIGNAL_COLORS = ['#008c95', '#101820', '#2d5f64', '#b88a43', '#6f7b80', '#9aa7a3']
const EVENT_COLORS = ['#b66a2c', '#4d70a8', '#8a5a7b', '#6f7e2e', '#c46f58', '#2f7d6d']

type LoadState =
  | { status: 'idle'; message: string }
  | { status: 'loading'; message: string }
  | { status: 'ready'; message: string; data: TimeseriesWindowResponse }
  | { status: 'error'; message: string }

type EventGroup = {
  key: string
  label: string
  count: number
  dense: boolean
  color: string
}

type SignalInspectorBookmark = {
  id: string
  title: string
  window: {
    startS: number
    endS: number
  }
  signalColumns: string[]
  createdAtUtc: string
  updatedAtUtc: string
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

type DragSelection = {
  originS: number
  currentS: number
}

export function SignalInspector({
  session,
  dataSource,
  initialWindow = null,
}: {
  session: SessionRecord
  dataSource: LibraryDataSource
  initialWindow?: { startS: number; endS: number } | null
}) {
  const durationS = Math.max(1, session.gpsSummary.sessionDurationS || session.durationMin * 60 || 1)
  const signalOptions = useMemo(() => inspectorSignalOptions(session), [session])
  const signalOptionColumns = useMemo(() => new Set(signalOptions.map((signal) => signal.column)), [signalOptions])
  const initialColumns = useMemo(() => defaultSignalColumns(signalOptions), [signalOptions])
  const [selectedColumns, setSelectedColumns] = useState<string[]>(initialColumns)
  const [windowStartS, setWindowStartS] = useState(() => sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS))
  const [windowEndS, setWindowEndS] = useState(() => sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS))
  const [bookmarks, setBookmarks] = useState<SignalInspectorBookmark[]>(() => loadSignalInspectorBookmarks(session))
  const [activeBookmarkId, setActiveBookmarkId] = useState<string | null>(null)
  const [bookmarkTitle, setBookmarkTitle] = useState('')
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [showMarks, setShowMarks] = useState(true)
  const [loadState, setLoadState] = useState<LoadState>({
    status: 'idle',
    message: signalOptions.length ? 'Choose signals to inspect.' : 'No signal catalog is available for this session.',
  })
  const [visibleEventGroups, setVisibleEventGroups] = useState<string[]>([])

  useEffect(() => {
    setSelectedColumns(defaultSignalColumns(signalOptions))
    setWindowStartS(sanitizeWindowBoundary(initialWindow?.startS ?? 0, durationS))
    setWindowEndS(sanitizeWindowBoundary(initialWindow?.endS ?? durationS, durationS))
    setBookmarks(loadSignalInspectorBookmarks(session))
    setActiveBookmarkId(null)
    setBookmarkTitle('')
    setSelectedEventId(null)
    setShowMarks(true)
  }, [durationS, initialWindow?.endS, initialWindow?.startS, session.sessionKey, signalOptions])

  const requestWindow = sanitizeWindow(windowStartS, windowEndS, durationS)
  const sortedBookmarks = useMemo(
    () => [...bookmarks].sort((a, b) => a.window.startS - b.window.startS || a.title.localeCompare(b.title)),
    [bookmarks],
  )
  const activeBookmarkIndex = activeBookmarkId
    ? sortedBookmarks.findIndex((bookmark) => bookmark.id === activeBookmarkId)
    : -1

  useEffect(() => {
    let cancelled = false
    async function loadWindow() {
      if (selectedColumns.length === 0) {
        setLoadState({ status: 'idle', message: 'Select one or more signals to inspect.' })
        return
      }
      setLoadState({ status: 'loading', message: 'Loading signal window...' })
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
          setLoadState({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        }
      }
    }

    void loadWindow()
    return () => {
      cancelled = true
    }
  }, [dataSource, requestWindow.endS, requestWindow.startS, selectedColumns, session])

  const eventGroups = useMemo(
    () => (loadState.status === 'ready' ? groupEvents(loadState.data.events) : []),
    [loadState],
  )
  const markCount = loadState.status === 'ready' ? loadState.data.marks.length : 0
  const eventGroupKey = eventGroups.map((group) => `${group.key}:${group.count}`).join('|')

  useEffect(() => {
    setVisibleEventGroups(eventGroups.filter((group) => !group.dense).map((group) => group.key))
  }, [eventGroupKey])

  useEffect(() => {
    if (loadState.status !== 'ready') {
      setSelectedEventId(null)
      return
    }
    setSelectedEventId((current) =>
      current && loadState.data.events.some((event) => event.eventId === current) ? current : null,
    )
  }, [loadState])

  useEffect(() => {
    setActiveBookmarkId((current) => {
      const bookmark = current ? bookmarks.find((candidate) => candidate.id === current) : null
      if (
        bookmark &&
        nearlyEqual(bookmark.window.startS, requestWindow.startS) &&
        nearlyEqual(bookmark.window.endS, requestWindow.endS) &&
        sameStringSet(bookmark.signalColumns, selectedColumns)
      ) {
        return current
      }
      return null
    })
  }, [bookmarks, requestWindow.endS, requestWindow.startS, selectedColumns])

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

  function resetWindow() {
    setWindowStartS(0)
    setWindowEndS(durationS)
  }

  function saveWindow() {
    const now = new Date().toISOString()
    const title = bookmarkTitle.trim() || `Window ${formatTime(requestWindow.startS)}-${formatTime(requestWindow.endS)}`
    const bookmark: SignalInspectorBookmark = {
      id: `siw-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      title,
      window: requestWindow,
      signalColumns: [...selectedColumns],
      createdAtUtc: now,
      updatedAtUtc: now,
    }
    const nextBookmarks = [...bookmarks, bookmark]
    setBookmarks(nextBookmarks)
    persistSignalInspectorBookmarks(session, nextBookmarks)
    setActiveBookmarkId(bookmark.id)
    setBookmarkTitle('')
  }

  function applyBookmark(bookmark: SignalInspectorBookmark) {
    setWindowStartS(sanitizeWindowBoundary(bookmark.window.startS, durationS))
    setWindowEndS(sanitizeWindowBoundary(bookmark.window.endS, durationS))
    const restoredColumns = bookmark.signalColumns.filter((column) => signalOptionColumns.has(column))
    if (restoredColumns.length > 0) {
      setSelectedColumns(restoredColumns)
    }
    setActiveBookmarkId(bookmark.id)
  }

  function deleteBookmark(bookmarkId: string) {
    const nextBookmarks = bookmarks.filter((bookmark) => bookmark.id !== bookmarkId)
    setBookmarks(nextBookmarks)
    persistSignalInspectorBookmarks(session, nextBookmarks)
    setActiveBookmarkId((current) => (current === bookmarkId ? null : current))
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
      <section className="signal-inspector-toolbar">
        <div className="signal-inspector-window-controls">
          <label>
            Start (s)
            <input
              min={0}
              max={durationS}
              step={0.1}
              type="number"
              value={roundForInput(requestWindow.startS)}
              onChange={(event) => setWindowStartS(Number(event.target.value))}
            />
          </label>
          <label>
            End (s)
            <input
              min={0}
              max={durationS}
              step={0.1}
              type="number"
              value={roundForInput(requestWindow.endS)}
              onChange={(event) => setWindowEndS(Number(event.target.value))}
            />
          </label>
          <button type="button" onClick={resetWindow} disabled={requestWindow.startS === 0 && requestWindow.endS === durationS}>
            <RefreshCcw size={14} />
            Full session
          </button>
          <button type="button" onClick={() => goToAdjacentBookmark(-1)} disabled={sortedBookmarks.length === 0}>
            <SkipBack size={14} />
            Previous
          </button>
          <button type="button" onClick={() => goToAdjacentBookmark(1)} disabled={sortedBookmarks.length === 0}>
            <SkipForward size={14} />
            Next
          </button>
        </div>
        <div className="signal-inspector-status">
          {formatTime(requestWindow.startS)} to {formatTime(requestWindow.endS)} / {formatTime(durationS)}
        </div>
      </section>

      <div className="signal-inspector-layout">
        <aside className="signal-inspector-sidebar">
          <section className="signal-inspector-card">
            <div className="signal-inspector-card-header">
              <h3>Saved windows</h3>
              <small>{sortedBookmarks.length} saved</small>
            </div>
            <div className="signal-inspector-save-row">
              <input
                type="text"
                value={bookmarkTitle}
                onChange={(event) => setBookmarkTitle(event.target.value)}
                placeholder={`Window ${formatTime(requestWindow.startS)}-${formatTime(requestWindow.endS)}`}
              />
              <button type="button" onClick={saveWindow} disabled={selectedColumns.length === 0}>
                <Save size={14} />
                Save
              </button>
            </div>
            {sortedBookmarks.length === 0 ? (
              <p>Save a window to return to it quickly while inspecting this session.</p>
            ) : (
              <div className="signal-inspector-bookmark-list">
                {sortedBookmarks.map((bookmark) => (
                  <div className={bookmark.id === activeBookmarkId ? 'active' : ''} key={bookmark.id}>
                    <button type="button" onClick={() => applyBookmark(bookmark)}>
                      <strong>{bookmark.title}</strong>
                      <small>
                        {formatTime(bookmark.window.startS)} - {formatTime(bookmark.window.endS)}
                      </small>
                    </button>
                    <button
                      aria-label={`Delete saved window ${bookmark.title}`}
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
          </section>

          <section className="signal-inspector-card">
            <h3>Signals</h3>
            {signalOptions.length === 0 ? (
              <p>No signal catalog is available for this session.</p>
            ) : (
              <div className="signal-inspector-check-list">
                {signalOptions.map((signal) => (
                  <label key={signal.column}>
                    <input
                      checked={selectedColumns.includes(signal.column)}
                      onChange={() => toggleColumn(signal.column)}
                      type="checkbox"
                    />
                    <span>
                      <strong>{signal.displayName || signal.column}</strong>
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
                <p>No event overlays returned for this window.</p>
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
                        {group.dense ? `, hidden by default above ${DENSE_EVENT_CUTOFF}` : ''}
                      </small>
                    </span>
                  </label>
                ))
              }
            </div>
          </section>
        </aside>

        <section className="signal-inspector-main">
          {loadState.status === 'loading' && <div className="signal-inspector-message">{loadState.message}</div>}
          {loadState.status === 'error' && (
            <div className="signal-inspector-message warning">Could not load signals: {loadState.message}</div>
          )}
          {loadState.status === 'idle' && <div className="signal-inspector-message">{loadState.message}</div>}
          {loadState.status === 'ready' && (
            <>
              <SignalWindowChart
                data={loadState.data}
                visibleEventGroups={visibleEventGroups}
                showMarks={showMarks}
                eventGroups={eventGroups}
                selectedEventId={selectedEventId}
                onSelectEvent={setSelectedEventId}
                onSelectWindow={(window) => {
                  setWindowStartS(window.startS)
                  setWindowEndS(window.endS)
                }}
              />
              <SelectedEventPanel
                event={loadState.data.events.find((event) => event.eventId === selectedEventId) ?? null}
                onClear={() => setSelectedEventId(null)}
                onZoom={(window) => {
                  setWindowStartS(window.startS)
                  setWindowEndS(window.endS)
                }}
              />
              {loadState.data.warnings.length > 0 && (
                <div className="signal-inspector-message warning">
                  {loadState.data.warnings.slice(0, 3).join(' | ')}
                  {loadState.data.warnings.length > 3 ? ` | ${loadState.data.warnings.length - 3} more warning(s)` : ''}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}

function SignalWindowChart({
  data,
  eventGroups,
  selectedEventId,
  showMarks,
  visibleEventGroups,
  onSelectEvent,
  onSelectWindow,
}: {
  data: TimeseriesWindowResponse
  eventGroups: EventGroup[]
  selectedEventId: string | null
  showMarks: boolean
  visibleEventGroups: string[]
  onSelectEvent: (eventId: string | null) => void
  onSelectWindow: (window: { startS: number; endS: number }) => void
}) {
  const width = 1040
  const height = 470
  const margin = { top: 18, right: 24, bottom: 42, left: 58 }
  const plotLeft = margin.left
  const plotRight = width - margin.right
  const plotTop = margin.top
  const plotBottom = height - margin.bottom
  const plotWidth = plotRight - plotLeft
  const plotHeight = plotBottom - plotTop
  const [hover, setHover] = useState<HoverReadout | null>(null)
  const [drag, setDrag] = useState<DragSelection | null>(null)
  const dragRef = useRef<DragSelection | null>(null)
  const hoverFrameRef = useRef<number | null>(null)
  const pendingHoverRef = useRef<HoverReadout | null>(null)
  const dragFrameRef = useRef<number | null>(null)
  const pendingDragRef = useRef<DragSelection | null>(null)
  const timeValues = data.time.values
  const finiteTimes = timeValues.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const xDomain = d3.extent(finiteTimes)
  const signalValues = data.signals.flatMap((signal) =>
    signal.values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)),
  )
  const valueExtent = d3.extent(signalValues)
  const yPadding = valueExtent[0] === valueExtent[1] ? 1 : ((valueExtent[1] ?? 1) - (valueExtent[0] ?? 0)) * 0.08
  const x = d3
    .scaleLinear()
    .domain([xDomain[0] ?? 0, xDomain[1] ?? 1])
    .range([margin.left, width - margin.right])
  const y = d3
    .scaleLinear()
    .domain([(valueExtent[0] ?? 0) - yPadding, (valueExtent[1] ?? 1) + yPadding])
    .nice()
    .range([height - margin.bottom, margin.top])
  const line = d3
    .line<{ timeS: number | null; value: number | null }>()
    .defined((point) => typeof point.timeS === 'number' && typeof point.value === 'number')
    .x((point) => x(point.timeS ?? 0))
    .y((point) => y(point.value ?? 0))
    .curve(d3.curveMonotoneX)
  const selectedEventGroups = new Set(visibleEventGroups)
  const groupColorByKey = new Map(eventGroups.map((group) => [group.key, group.color]))
  const visibleEvents = data.events.filter((event) => selectedEventGroups.has(eventGroupKey(event)))
  const visibleMarks = showMarks ? data.marks.filter((mark) => markInDomain(mark, xDomain)) : []
  const unitLabel = chartUnitLabel(data.signals)
  const minWindowS = Math.max(0.1, ((xDomain[1] ?? 1) - (xDomain[0] ?? 0)) / 500)
  const dragWindow = drag
    ? sanitizeWindow(drag.originS, drag.currentS, xDomain[1] ?? Math.max(drag.originS, drag.currentS))
    : null
  const dragStartX = dragWindow ? x(dragWindow.startS) : 0
  const dragEndX = dragWindow ? x(dragWindow.endS) : 0

  useEffect(
    () => () => {
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current)
      }
      if (dragFrameRef.current !== null) {
        window.cancelAnimationFrame(dragFrameRef.current)
      }
    },
    [],
  )

  if (data.signals.length === 0 || finiteTimes.length === 0 || signalValues.length === 0) {
    return <div className="signal-inspector-message">No matching signal samples were returned for this window.</div>
  }

  function pointerViewX(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    return ((event.clientX - bounds.left) / Math.max(1, bounds.width)) * width
  }

  function pointerTime(event: PointerEvent<SVGSVGElement>) {
    return clamp(x.invert(pointerViewX(event)), xDomain[0] ?? 0, xDomain[1] ?? 1)
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

  function scheduleDrag(nextDrag: DragSelection | null) {
    pendingDragRef.current = nextDrag
    if (dragFrameRef.current !== null) {
      return
    }
    dragFrameRef.current = window.requestAnimationFrame(() => {
      dragFrameRef.current = null
      setDrag(pendingDragRef.current)
    })
  }

  function updateHover(event: PointerEvent<SVGSVGElement>) {
    const timeS = pointerTime(event)
    const index = nearestTimeIndex(timeValues, timeS)
    if (index < 0) {
      scheduleHover(null)
      return
    }
    const actualTime = timeValues[index]
    if (typeof actualTime !== 'number' || !Number.isFinite(actualTime)) {
      scheduleHover(null)
      return
    }
    scheduleHover({
      x: x(actualTime),
      timeS: actualTime,
      values: data.signals
        .map((signal, signalIndex) => ({
          label: signal.displayName || signal.column,
          value: signal.values[index],
          unit: signal.unit,
          color: SIGNAL_COLORS[signalIndex % SIGNAL_COLORS.length],
        }))
        .filter((item): item is HoverReadout['values'][number] => typeof item.value === 'number' && Number.isFinite(item.value)),
    })
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    const viewX = pointerViewX(event)
    if (viewX < plotLeft || viewX > plotRight) {
      return
    }
    event.preventDefault()
    const timeS = pointerTime(event)
    const nextDrag = { originS: timeS, currentS: timeS }
    dragRef.current = nextDrag
    scheduleDrag(nextDrag)
    event.currentTarget.setPointerCapture(event.pointerId)
    updateHover(event)
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const activeDrag = dragRef.current
    if (activeDrag) {
      event.preventDefault()
      const nextDrag = { ...activeDrag, currentS: pointerTime(event) }
      dragRef.current = nextDrag
      scheduleDrag(nextDrag)
      return
    }
    updateHover(event)
  }

  function handlePointerUp(event: PointerEvent<SVGSVGElement>) {
    const activeDrag = dragRef.current
    if (!activeDrag) {
      return
    }
    event.preventDefault()
    const endS = pointerTime(event)
    const nextStartS = Math.min(activeDrag.originS, endS)
    const nextEndS = Math.max(activeDrag.originS, endS)
    if (nextEndS - nextStartS >= minWindowS) {
      onSelectWindow({ startS: nextStartS, endS: nextEndS })
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragRef.current = null
    scheduleDrag(null)
    updateHover(event)
  }

  function handlePointerCancel(event: PointerEvent<SVGSVGElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragRef.current = null
    scheduleDrag(null)
  }

  return (
    <div className="signal-inspector-chart-card">
      <div className="signal-inspector-chart-hint">Drag across the chart to inspect a narrower time window. Move the pointer to read the nearest sample.</div>
      <div className="signal-inspector-chart-frame">
        <svg
          className={`signal-inspector-chart${drag ? ' selecting' : ''}`}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Signal time series"
          onPointerCancel={handlePointerCancel}
          onPointerDown={handlePointerDown}
          onPointerLeave={() => {
            if (!dragRef.current) {
              scheduleHover(null)
            }
          }}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <rect
            className="signal-inspector-interaction-layer"
            x={plotLeft}
            y={plotTop}
            width={plotWidth}
            height={plotHeight}
          />
          <line className="signal-inspector-axis" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
          <line className="signal-inspector-axis" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
          {x.ticks(10).map((tick) => (
            <g key={`x-${tick}`}>
              <line className="signal-inspector-tick" x1={x(tick)} x2={x(tick)} y1={height - margin.bottom} y2={height - margin.bottom + 4} />
              <text className="signal-inspector-axis-label" x={x(tick)} y={height - 14} textAnchor="middle">
                {formatTime(tick)}
              </text>
            </g>
          ))}
          {y.ticks(7).map((tick) => (
            <g key={`y-${tick}`}>
              <line className="signal-inspector-grid-line" x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} />
              <text className="signal-inspector-axis-label" x={margin.left - 8} y={y(tick) + 4} textAnchor="end">
                {formatAxisValue(tick)}
              </text>
            </g>
          ))}
          {visibleEvents.map((event, index) => {
            const timeS = event.peakTimeS ?? event.startS ?? event.endS
            if (typeof timeS !== 'number' || !Number.isFinite(timeS)) {
              return null
            }
            const key = eventGroupKey(event)
            return (
              <line
                className={`signal-inspector-event-marker${event.eventId === selectedEventId ? ' selected' : ''}`}
                key={`${event.eventId}-${index}`}
                stroke={groupColorByKey.get(key) ?? '#b66a2c'}
                x1={x(timeS)}
                x2={x(timeS)}
                y1={margin.top}
                y2={height - margin.bottom}
                onClick={(clickEvent) => {
                  clickEvent.stopPropagation()
                  onSelectEvent(event.eventId === selectedEventId ? null : event.eventId)
                }}
              >
                <title>
                  {event.displayName || event.eventType}
                  {event.end ? ` (${event.end})` : ''} at {formatTime(timeS)}
                </title>
              </line>
            )
          })}
          {visibleMarks.map((mark) => {
            const markX = x(mark.timeS)
            return (
              <g className="signal-inspector-mark-marker" key={mark.markId || `${mark.displayName}-${mark.timeS}`} transform={`translate(${markX} 0)`}>
                <line className="signal-inspector-mark-guide" x1={0} x2={0} y1={plotTop} y2={plotBottom} />
                <line className="signal-inspector-mark-cross" x1={-5} x2={5} y1={plotTop + 10} y2={plotTop + 20} />
                <line className="signal-inspector-mark-cross" x1={-5} x2={5} y1={plotTop + 20} y2={plotTop + 10} />
                <title>
                  {mark.displayName || 'Mark'} at {formatTime(mark.timeS)}
                </title>
              </g>
            )
          })}
          {dragWindow && (
            <rect
              className="signal-inspector-selection"
              x={Math.min(dragStartX, dragEndX)}
              y={plotTop}
              width={Math.max(1, Math.abs(dragEndX - dragStartX))}
              height={plotHeight}
            />
          )}
          {data.signals.map((signal, index) => {
            const points = timeValues.map((timeS, pointIndex) => ({ timeS, value: signal.values[pointIndex] ?? null }))
            const path = line(points)
            return path ? (
              <path
                className="signal-inspector-line"
                d={path}
                key={signal.column}
                stroke={SIGNAL_COLORS[index % SIGNAL_COLORS.length]}
              >
                <title>{signal.displayName || signal.column}</title>
              </path>
            ) : null
          })}
        {hover && (
          <>
            <line className="signal-inspector-hover-line" x1={hover.x} x2={hover.x} y1={plotTop} y2={plotBottom} />
            <circle className="signal-inspector-hover-point" cx={hover.x} cy={plotTop + 8} r={3.5} />
          </>
        )}
          <text className="signal-inspector-axis-title" x={(width + margin.left - margin.right) / 2} y={height - 3} textAnchor="middle">
            Time (s)
          </text>
          <text
            className="signal-inspector-axis-title"
            textAnchor="middle"
            transform={`translate(16 ${(height + margin.top - margin.bottom) / 2}) rotate(-90)`}
          >
            {unitLabel}
          </text>
        </svg>
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
        {data.signals.map((signal, index) => (
          <span key={signal.column}>
            <i style={{ background: SIGNAL_COLORS[index % SIGNAL_COLORS.length] }} />
            {signal.displayName || signal.column}
            {signal.unit ? ` (${signal.unit})` : ''}
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
        Click an event marker to inspect its timing. Dense event groups remain hidden until selected in the Events list.
      </div>
    )
  }
  const eventStartS = event.startS ?? event.peakTimeS ?? event.endS ?? 0
  const eventEndS = event.endS ?? event.peakTimeS ?? event.startS ?? eventStartS
  const zoomPaddingS = Math.max(1, (eventEndS - eventStartS) * 2, 2)
  return (
    <section className="signal-inspector-event-detail">
      <div>
        <strong>{event.displayName || event.eventType || 'Event'}</strong>
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
  const displacement = source.filter(isDisplacementSignal)
  const preferred = displacement.length ? preferEngineeringDisplacementSignals(displacement) : source
  return preferred.slice(0, 4).map((signal) => signal.column)
}

function preferEngineeringDisplacementSignals(signals: SessionSignalSummary[]) {
  const groups = new Map<string, SessionSignalSummary[]>()
  for (const signal of signals) {
    const key = displacementPreferenceKey(signal)
    groups.set(key, [...(groups.get(key) ?? []), signal])
  }

  const selected = Array.from(groups.values()).map((group) => group.find(isEngineeringUnitDisplacement) ?? group[0])
  const selectedColumns = new Set(selected.map((signal) => signal.column))
  const engineeringRemainders = signals.filter(
    (signal) => !selectedColumns.has(signal.column) && isEngineeringUnitDisplacement(signal),
  )
  const otherRemainders = signals.filter((signal) => !selectedColumns.has(signal.column) && !isEngineeringUnitDisplacement(signal))
  return [...selected, ...engineeringRemainders, ...otherRemainders]
}

function displacementPreferenceKey(signal: SessionSignalSummary) {
  const end = normalizeSignalText(signal.end) || inferEndFromText(signal.column) || inferEndFromText(signal.displayName)
  return end ? `end:${end}` : `column:${signal.column}`
}

function isDisplacementSignal(signal: SessionSignalSummary) {
  const text = normalizeSignalText([signal.quantity, signal.displayName, signal.column].join(' '))
  return text.includes('disp') || text.includes('travel')
}

function isEngineeringUnitDisplacement(signal: SessionSignalSummary) {
  const unit = normalizeSignalText(signal.unit)
  const text = normalizeSignalText([signal.quantity, signal.displayName, signal.column].join(' '))
  if (!unit || ['1', 'ratio', 'norm', 'normalized', 'normalised', '%', 'percent', 'percentage'].includes(unit)) {
    return false
  }
  return !text.includes('normalized') && !text.includes('normalised') && !text.includes('disp_norm')
}

function inferEndFromText(value: string) {
  const text = normalizeSignalText(value)
  if (text.includes('front')) {
    return 'front'
  }
  if (text.includes('rear')) {
    return 'rear'
  }
  return ''
}

function normalizeSignalText(value: string) {
  return value.trim().toLowerCase()
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
  const base = event.displayName || event.eventType || 'event'
  return event.end ? `${base} (${event.end})` : base
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

function loadSignalInspectorBookmarks(session: SessionRecord): SignalInspectorBookmark[] {
  if (typeof window === 'undefined') {
    return []
  }
  try {
    const raw = window.localStorage.getItem(signalInspectorBookmarkStorageKey(session))
    if (!raw) {
      return []
    }
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed.filter(isSignalInspectorBookmark)
  } catch {
    return []
  }
}

function persistSignalInspectorBookmarks(session: SessionRecord, bookmarks: SignalInspectorBookmark[]) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(signalInspectorBookmarkStorageKey(session), JSON.stringify(bookmarks))
  } catch {
    // Local saved windows are a convenience only; failure should not block inspection.
  }
}

function signalInspectorBookmarkStorageKey(session: SessionRecord) {
  return `bodaqs.signal-inspector.windows.v1:${session.libraryId}:${session.sessionKey}`
}

function isSignalInspectorBookmark(value: unknown): value is SignalInspectorBookmark {
  if (!value || typeof value !== 'object') {
    return false
  }
  const candidate = value as SignalInspectorBookmark
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.title === 'string' &&
    typeof candidate.window?.startS === 'number' &&
    typeof candidate.window?.endS === 'number' &&
    Array.isArray(candidate.signalColumns)
  )
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

function nearestTimeIndex(values: Array<number | null>, target: number) {
  let bestIndex = -1
  let bestDistance = Number.POSITIVE_INFINITY
  values.forEach((value, index) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return
    }
    const distance = Math.abs(value - target)
    if (distance < bestDistance) {
      bestDistance = distance
      bestIndex = index
    }
  })
  return bestIndex
}

function chartUnitLabel(signals: SessionSignalSummary[]) {
  const units = Array.from(new Set(signals.map((signal) => signal.unit).filter(Boolean)))
  if (units.length === 1) {
    return units[0]
  }
  if (units.length > 1) {
    return 'mixed units'
  }
  return 'value'
}
