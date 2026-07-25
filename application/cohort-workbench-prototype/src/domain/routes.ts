import type { GeoPosition } from './types'

export type RoutePath = {
  id: string
  points: GeoPosition[]
  color: string
  width: number
}

export function projectPaths(paths: RoutePath[]) {
  const allPoints = paths.flatMap((path) => path.points)
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const [x, y] of allPoints) {
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
  }
  if (allPoints.length === 0) {
    return paths
  }
  const xSpan = maxX - minX || 1
  const ySpan = maxY - minY || 1

  return paths.map((path) => ({
    ...path,
    points: path.points.map(
      ([x, y]) =>
        [
          24 + ((x - minX) / xSpan) * 272,
          236 - ((y - minY) / ySpan) * 212,
        ] as [number, number],
    ),
  }))
}
