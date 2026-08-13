import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Mountain } from 'lucide-react'
import { IconButton, InfoTip } from './Common'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { gpsSourceDisplay, gpsSourceLabel } from '../domain/geospatial'
import { routeStationsM } from '../domain/trackGeometry'
import type { GeoPosition, SessionGpsPointSet, SessionRecord } from '../domain/types'

type AltitudeLoadState =
  | { status: 'idle'; message: string; pointSet: SessionGpsPointSet | null }
  | { status: 'loading'; message: string; pointSet: SessionGpsPointSet | null }
  | { status: 'ready'; message: string; pointSet: SessionGpsPointSet }
  | { status: 'error'; message: string; pointSet: SessionGpsPointSet | null }

type AltitudeSample = {
  distanceM: number
  elevationM: number
}

export function SessionAltitudePreview({
  collapsed,
  dataSource,
  onToggleCollapsed,
  session,
}: {
  collapsed: boolean
  dataSource: LibraryDataSource
  onToggleCollapsed: () => void
  session: SessionRecord | null
}) {
  const preferredSourceId = session?.gpsSummary.preferredSourceId ?? session?.gpsSummary.sources[0]?.sourceId ?? null
  const [loadState, setLoadState] = useState<AltitudeLoadState>({
    status: 'idle',
    message: 'Select a session to preview altitude.',
    pointSet: null,
  })

  useEffect(() => {
    let cancelled = false
    if (!session) {
      setLoadState({ status: 'idle', message: 'Select a session to preview altitude.', pointSet: null })
      return
    }
    if (!dataSource.loadSessionGpsPoints) {
      setLoadState({ status: 'idle', message: 'Altitude preview requires time-aligned GPS points.', pointSet: null })
      return
    }
    setLoadState((current) => ({
      status: 'loading',
      message: `Loading altitude for ${session.name}...`,
      pointSet: current.pointSet,
    }))
    dataSource
      .loadSessionGpsPoints(session, preferredSourceId)
      .then((pointSet) => {
        if (cancelled) {
          return
        }
        setLoadState({
          status: 'ready',
          message: altitudePointSetStatusLine(pointSet),
          pointSet,
        })
      })
      .catch((error) => {
        if (cancelled) {
          return
        }
        setLoadState({
          status: 'error',
          message: error instanceof Error ? error.message : String(error),
          pointSet: null,
        })
      })
    return () => {
      cancelled = true
    }
  }, [dataSource, preferredSourceId, session])

  const samples = useMemo(() => altitudeSamplesForSessionGps(loadState.pointSet), [loadState.pointSet])
  const hasAltitude = samples.length >= 2
  const sourceLabel = loadState.pointSet?.sourceId
    ? gpsSourceDisplay(loadState.pointSet.sourceKind, loadState.pointSet.sourceId)
    : loadState.pointSet
      ? gpsSourceLabel(loadState.pointSet.sourceKind)
      : 'No altitude'

  return (
    <section className={`module session-altitude-module collapsible-module${collapsed ? ' collapsed' : ''}`}>
      <div className="module-header">
        <h2 className="module-heading">
          <Mountain size={16} aria-hidden="true" />
          Altitude Profile
          <InfoTip text="Preview the selected session GPS altitude against distance from the session start." />
        </h2>
        <div className="module-header-actions">
          <span className="module-header-count">{session ? sourceLabel : 'No primary session'}</span>
          <IconButton
            label={collapsed ? 'Expand Altitude Profile' : 'Collapse Altitude Profile'}
            onClick={onToggleCollapsed}
            icon={collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          />
        </div>
      </div>
      {!collapsed && (
        <>
          {hasAltitude ? (
            <LibraryAltitudeChart samples={samples} />
          ) : (
            <div className="session-altitude-empty">
              {loadState.status === 'loading'
                ? loadState.message
                : session
                  ? 'No GPS altitude data is available for this session.'
                  : loadState.message}
            </div>
          )}
          <div className={`session-altitude-status ${loadState.status}`}>
            <strong>{altitudeStatusLabel(loadState.status)}</strong>
            <span>{loadState.message}</span>
            {loadState.pointSet?.warnings.length ? <span>{loadState.pointSet.warnings.join(', ')}</span> : null}
          </div>
        </>
      )}
    </section>
  )
}

function LibraryAltitudeChart({ samples }: { samples: AltitudeSample[] }) {
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

  return (
    <svg className="library-altitude-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Selected session altitude profile">
      {elevationTicks.map((tick) => {
        const y = yForElevation(tick)
        return (
          <g key={`elevation-${tick}`} className="library-altitude-grid">
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
          <g key={`distance-${tick}`} className="library-altitude-grid">
            <line x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} />
            <text x={x} y={height - padding.bottom + 16} textAnchor="middle">
              {formatDistanceTick(tick)}
            </text>
          </g>
        )
      })}
      <line className="library-altitude-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
      <line className="library-altitude-axis" x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
      <path className="library-altitude-line" d={path} />
      <text className="library-altitude-axis-title" x={(padding.left + width - padding.right) / 2} y={height - 3} textAnchor="middle">
        Distance from start
      </text>
      <text
        className="library-altitude-axis-title"
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

function altitudePointSetStatusLine(pointSet: SessionGpsPointSet) {
  if (!pointSet.present || pointSet.returnedPoints === 0) {
    return 'No GPS points returned for this session.'
  }
  const source = pointSet.sourceId
    ? gpsSourceDisplay(pointSet.sourceKind, pointSet.sourceId)
    : gpsSourceLabel(pointSet.sourceKind)
  const altitudeCount = pointSet.points.filter((point) => point.elevationM !== null && Number.isFinite(point.elevationM)).length
  return `${source}: ${altitudeCount} altitude point${altitudeCount === 1 ? '' : 's'} available.`
}

function altitudeStatusLabel(status: AltitudeLoadState['status']) {
  if (status === 'loading') {
    return 'Loading'
  }
  if (status === 'error') {
    return 'Unavailable'
  }
  if (status === 'ready') {
    return 'Altitude'
  }
  return 'Idle'
}

function gridStep(span: number, candidates: number[], minimumGridlines = 3) {
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
  while ((max - min) / step < 3) {
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
