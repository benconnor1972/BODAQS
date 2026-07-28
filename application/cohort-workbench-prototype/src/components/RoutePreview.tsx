import { Map } from 'lucide-react'
import { projectPaths } from '../domain/routes'
import type { GeoPosition, SessionRecord, TrackRecord } from '../domain/types'

export function RoutePreview({
  primarySession,
  primaryGpsPath,
  selectedTracks,
  currentTracks,
}: {
  primarySession: SessionRecord | null
  primaryGpsPath?: GeoPosition[]
  selectedTracks: TrackRecord[]
  currentTracks: TrackRecord[]
}) {
  const primaryPoints = primaryGpsPath ?? primarySession?.gps ?? []
  const allPaths = [
    ...(primarySession && primaryPoints.length
      ? [{ id: 'primary', points: primaryPoints, color: '#25333d', width: 4 }]
      : []),
    ...selectedTracks.map((track) => ({
      id: `selected-${track.id}`,
      points: track.points,
      color: '#2f7d6d',
      width: 3,
    })),
    ...currentTracks.map((track) => ({
      id: `current-${track.id}`,
      points: track.points,
      color: '#b66a2c',
      width: 2,
    })),
  ]
  const trackpointOverlays = [
    ...selectedTracks.map((track) => ({
      id: `selected-trackpoints-${track.id}`,
      points: track.trackpoints.map((trackpoint) => trackpoint.position),
      color: '#2f7d6d',
      width: 0,
    })),
    ...currentTracks.map((track) => ({
      id: `current-trackpoints-${track.id}`,
      points: track.trackpoints.map((trackpoint) => trackpoint.position),
      color: '#b66a2c',
      width: 0,
    })),
  ]
  const allPoints = [...allPaths, ...trackpointOverlays].flatMap((path) => path.points)

  if (allPoints.length === 0) {
    return (
      <div className="map-empty">
        <Map size={24} />
        <span>Select a session or track to preview GPS context.</span>
      </div>
    )
  }

  const projected = projectPaths([...allPaths, ...trackpointOverlays])
  const projectedPaths = projected.filter((path) => path.width > 0)
  const projectedTrackpoints = projected.filter((path) => path.width === 0)
  return (
    <svg className="route-preview" viewBox="0 0 320 260" role="img" aria-label="GPS route preview">
      <rect x="0" y="0" width="320" height="260" rx="8" />
      <g className="map-grid">
        {[40, 90, 140, 190, 240, 290].map((x) => (
          <line x1={x} x2={x} y1="20" y2="240" key={`x-${x}`} />
        ))}
        {[40, 90, 140, 190, 240].map((y) => (
          <line x1="20" x2="300" y1={y} y2={y} key={`y-${y}`} />
        ))}
      </g>
      {projectedPaths.map((path) => (
        <polyline
          fill="none"
          stroke={path.color}
          strokeWidth={path.width}
          points={path.points.map(([x, y]) => `${x},${y}`).join(' ')}
          key={path.id}
        />
      ))}
      {projectedPaths.flatMap((path) =>
        path.points.map(([x, y], index) => (
          <circle cx={x} cy={y} r={index === 0 ? 5 : 3.5} fill={path.color} key={`${path.id}-${index}`} />
        )),
      )}
      {projectedTrackpoints.flatMap((path) =>
        path.points.map(([x, y], index) => (
          <g className="trackpoint-marker" key={`${path.id}-${index}`}>
            <line x1={x - 13} x2={x + 13} y1={y + 9} y2={y - 9} stroke={path.color} />
            <circle cx={x} cy={y} r="5.5" fill="#fffaf0" stroke={path.color} />
            <text x={x + 8} y={y - 8}>
              {index + 1}
            </text>
          </g>
        )),
      )}
    </svg>
  )
}
