import { useEffect, useState, type CSSProperties, type PointerEvent } from 'react'
import { gpsSourceLabel } from '../domain/geospatial'
import type { SessionGpsPointSet, SessionRecord, TrackRecord } from '../domain/types'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { MapRoutePreview } from './MapRoutePreview'

type LoadState =
  | { status: 'idle'; message: string }
  | { status: 'loading'; message: string }
  | { status: 'loaded'; message: string }
  | { status: 'error'; message: string }

type RequestState = {
  sessionKey: string
  pointSet: SessionGpsPointSet | null
  loadState: LoadState
}

const DEFAULT_MAP_HEIGHT = 292
const COMPACT_MAP_HEIGHT = 240
const MIN_MAP_HEIGHT = 220
const MAX_MAP_HEIGHT = 720

export function GpsRoutePreview({
  session,
  dataSource,
  selectedTracks,
  currentTracks,
  compact = false,
}: {
  session: SessionRecord | null
  dataSource: LibraryDataSource
  selectedTracks: TrackRecord[]
  currentTracks: TrackRecord[]
  compact?: boolean
}) {
  const sessionKey = session ? `${session.libraryId}|||${session.sessionKey}` : ''
  const [requestState, setRequestState] = useState<RequestState | null>(null)
  const [mapHeight, setMapHeight] = useState(compact ? COMPACT_MAP_HEIGHT : DEFAULT_MAP_HEIGHT)
  const hasLoadedCurrentSession = requestState?.sessionKey === sessionKey

  useEffect(() => {
    if (!session || !dataSource.loadSessionGpsPoints) {
      return
    }

    let cancelled = false
    Promise.resolve()
      .then(() => {
        if (!cancelled) {
          setRequestState({
            sessionKey,
            pointSet: null,
            loadState: { status: 'loading', message: `Loading GPS points for ${session.name}...` },
          })
        }
        return dataSource.loadSessionGpsPoints?.(session)
      })
      .then((loadedPointSet) => {
        if (cancelled || !loadedPointSet) {
          return
        }
        setRequestState({
          sessionKey,
          pointSet: loadedPointSet,
          loadState: {
            status: 'loaded',
            message: gpsPointSetStatusLine(loadedPointSet),
          },
        })
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        const message = error instanceof Error ? error.message : String(error)
        setRequestState({
          sessionKey,
          pointSet: gpsPointSetFromSession(session),
          loadState: { status: 'error', message: `GPS points unavailable: ${message}` },
        })
      })

    return () => {
      cancelled = true
    }
  }, [dataSource, session, sessionKey])

  const fallbackPointSet = session ? gpsPointSetFromSession(session) : null
  const pointSet = hasLoadedCurrentSession
    ? requestState?.pointSet
    : dataSource.loadSessionGpsPoints
      ? null
      : fallbackPointSet
  const loadState: LoadState = !session
    ? { status: 'idle', message: 'Select a session to load GPS points.' }
    : hasLoadedCurrentSession
      ? requestState.loadState
      : dataSource.loadSessionGpsPoints
        ? { status: 'loading', message: `Loading GPS points for ${session.name}...` }
        : { status: 'loaded', message: 'Using catalog GPS path.' }
  const path = pointSet?.path ?? session?.gps ?? []

  function startMapResize(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = mapHeight
    const pointerId = event.pointerId
    const target = event.currentTarget
    target.setPointerCapture(pointerId)

    function handlePointerMove(moveEvent: globalThis.PointerEvent) {
      const nextHeight = clamp(startHeight + moveEvent.clientY - startY, MIN_MAP_HEIGHT, MAX_MAP_HEIGHT)
      setMapHeight(nextHeight)
    }

    function stopResize() {
      target.releasePointerCapture(pointerId)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopResize)
      window.removeEventListener('pointercancel', stopResize)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopResize)
    window.addEventListener('pointercancel', stopResize)
  }

  const mapFrameStyle = {
    '--gps-map-height': `${mapHeight}px`,
  } as CSSProperties

  return (
    <div className={`gps-route-shell${compact ? ' compact' : ''}`}>
      <div className="gps-map-resize-frame" style={mapFrameStyle}>
        <MapRoutePreview
          primarySession={session}
          primaryGpsPath={path}
          selectedTracks={selectedTracks}
          currentTracks={currentTracks}
        />
        <button
          aria-label="Resize GPS map vertically"
          className="gps-map-resize-handle"
          onPointerDown={startMapResize}
          type="button"
        >
          <span />
        </button>
      </div>
      <div className={`gps-route-status ${loadState.status}`}>
        <strong>{loadStateLabel(loadState.status)}</strong>
        <span>{loadState.message}</span>
        {pointSet?.warnings.length ? <span>{pointSet.warnings.join(', ')}</span> : null}
      </div>
    </div>
  )
}

function gpsPointSetStatusLine(pointSet: SessionGpsPointSet) {
  if (!pointSet.present || pointSet.returnedPoints === 0) {
    return 'No GPS points returned for this session.'
  }
  const source = pointSet.sourceId
    ? `${gpsSourceLabel(pointSet.sourceKind)} (${pointSet.sourceId})`
    : gpsSourceLabel(pointSet.sourceKind)
  const stride = pointSet.stride && pointSet.stride > 1 ? `, stride ${pointSet.stride}` : ''
  return `${source}: ${pointSet.returnedPoints} of ${pointSet.sourcePoints} points${stride}.`
}

function gpsPointSetFromSession(session: SessionRecord): SessionGpsPointSet {
  return {
    present: session.gps.length > 0,
    sourceId: session.gpsSummary.sources[0]?.sourceId ?? '',
    sourceKind: session.gpsSummary.preferredSource ?? 'unknown',
    streamName: session.gpsSummary.sources[0]?.streamName ?? '',
    samplingMode: 'catalog',
    sourcePoints: session.gpsSummary.positionPointCount,
    returnedPoints: session.gps.length,
    maxPoints: session.gps.length,
    stride: null,
    points: session.gps.map(([longitude, latitude], index) => ({
      timeS: index,
      longitude,
      latitude,
      elevationM: null,
    })),
    path: session.gps.map(([longitude, latitude]) => [longitude, latitude] as [number, number]),
    warnings: [...session.gpsSummary.warnings],
  }
}

function loadStateLabel(status: LoadState['status']) {
  if (status === 'loading') {
    return 'Loading'
  }
  if (status === 'error') {
    return 'Fallback'
  }
  if (status === 'loaded') {
    return 'GPS'
  }
  return 'Idle'
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}
