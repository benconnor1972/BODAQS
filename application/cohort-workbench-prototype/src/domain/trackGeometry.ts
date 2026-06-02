const EARTH_RADIUS_M = 6371000

export function routeLengthM(points: Array<[number, number]>) {
  let total = 0
  for (let index = 1; index < points.length; index += 1) {
    total += distanceM(points[index - 1], points[index])
  }
  return total
}

export function pointAtStationM(points: Array<[number, number]>, stationM: number): [number, number] {
  if (points.length === 0) {
    return [0, 0]
  }
  if (points.length === 1 || stationM <= 0) {
    return points[0]
  }

  let travelledM = 0
  for (let index = 1; index < points.length; index += 1) {
    const start = points[index - 1]
    const end = points[index]
    const segmentM = distanceM(start, end)
    if (travelledM + segmentM >= stationM) {
      const ratio = segmentM > 0 ? (stationM - travelledM) / segmentM : 0
      return [
        start[0] + (end[0] - start[0]) * ratio,
        start[1] + (end[1] - start[1]) * ratio,
      ]
    }
    travelledM += segmentM
  }

  return points[points.length - 1]
}

function distanceM(start: [number, number], end: [number, number]) {
  const lon1 = toRadians(start[0])
  const lat1 = toRadians(start[1])
  const lon2 = toRadians(end[0])
  const lat2 = toRadians(end[1])
  const dLat = lat2 - lat1
  const dLon = lon2 - lon1
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function toRadians(value: number) {
  return (value * Math.PI) / 180
}
