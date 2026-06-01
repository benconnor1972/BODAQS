import { Map } from 'lucide-react'
import { projectPaths } from '../domain/routes'
import type { SessionRecord, TrackRecord } from '../domain/types'

export function RoutePreview({
  primarySession,
  selectedTracks,
  currentTracks,
}: {
  primarySession: SessionRecord | null
  selectedTracks: TrackRecord[]
  currentTracks: TrackRecord[]
}) {
  const allPaths = [
    ...(primarySession ? [{ id: 'primary', points: primarySession.gps, color: '#25333d', width: 4 }] : []),
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
  const allPoints = allPaths.flatMap((path) => path.points)

  if (allPoints.length === 0) {
    return (
      <div className="map-empty">
        <Map size={24} />
        <span>Select a session or track to preview GPS context.</span>
      </div>
    )
  }

  const projected = projectPaths(allPaths)
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
      {projected.map((path) => (
        <polyline
          fill="none"
          stroke={path.color}
          strokeWidth={path.width}
          points={path.points.map(([x, y]) => `${x},${y}`).join(' ')}
          key={path.id}
        />
      ))}
      {projected.flatMap((path) =>
        path.points.map(([x, y], index) => (
          <circle cx={x} cy={y} r={index === 0 ? 5 : 3.5} fill={path.color} key={`${path.id}-${index}`} />
        )),
      )}
    </svg>
  )
}
