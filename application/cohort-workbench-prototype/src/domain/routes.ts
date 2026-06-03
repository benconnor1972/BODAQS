export type RoutePath = {
  id: string
  points: Array<[number, number]>
  color: string
  width: number
}

export function projectPaths(paths: RoutePath[]) {
  const allPoints = paths.flatMap((path) => path.points)
  const xs = allPoints.map(([x]) => x)
  const ys = allPoints.map(([, y]) => y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
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
