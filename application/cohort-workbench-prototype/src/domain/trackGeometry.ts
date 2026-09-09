import type { GeoPosition } from './types'

const EARTH_RADIUS_M = 6371000

export function routeLengthM(points: GeoPosition[]) {
  let total = 0
  for (let index = 1; index < points.length; index += 1) {
    total += distanceM(points[index - 1], points[index])
  }
  return total
}

export function routeStationsM(points: GeoPosition[]) {
  const stations = [0]
  let total = 0
  for (let index = 1; index < points.length; index += 1) {
    total += distanceM(points[index - 1], points[index])
    stations.push(total)
  }
  return stations
}

export function pointAtStationM(points: GeoPosition[], stationM: number): GeoPosition {
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
      const longitude = start[0] + (end[0] - start[0]) * ratio
      const latitude = start[1] + (end[1] - start[1]) * ratio
      const startElevation = start[2]
      const endElevation = end[2]
      if (Number.isFinite(startElevation) && Number.isFinite(endElevation)) {
        return [longitude, latitude, (startElevation as number) + (((endElevation as number) - (startElevation as number)) * ratio)]
      }
      return [longitude, latitude]
    }
    travelledM += segmentM
  }

  return points[points.length - 1]
}

export type RouteSectorReplacement = {
  points: GeoPosition[]
  lengthM: number
  startStationM: number
  endStationM: number
  replacementStartStationM: number
  replacementEndStationM: number
  removedLengthM: number
  replacementLengthM: number
  stationDeltaM: number
}

export function replaceRouteSectorWithConnector(
  points: GeoPosition[],
  startStationM: number,
  endStationM: number,
): RouteSectorReplacement | null {
  if (points.length < 2) {
    return null
  }
  const stations = routeStationsM(points)
  const originalLengthM = stations[stations.length - 1] ?? 0
  const startM = Math.max(0, Math.min(originalLengthM, startStationM))
  const endM = Math.max(0, Math.min(originalLengthM, endStationM))
  if (!Number.isFinite(startM) || !Number.isFinite(endM) || endM - startM <= 1e-6) {
    return null
  }

  const startPosition = pointAtStationM(points, startM)
  const endPosition = pointAtStationM(points, endM)
  const replacementPoints: GeoPosition[] = []
  points.forEach((position, index) => {
    if ((stations[index] ?? 0) < startM) {
      replacementPoints.push(copyPosition(position))
    }
  })
  replacementPoints.push(copyPosition(startPosition))
  const prefix = dedupeAdjacentPositions(replacementPoints)
  const replacementStartStationM = routeLengthM(prefix)
  replacementPoints.push(copyPosition(endPosition))
  const connector = dedupeAdjacentPositions(replacementPoints)
  const replacementEndStationM = routeLengthM(connector)
  points.forEach((position, index) => {
    if ((stations[index] ?? 0) > endM) {
      replacementPoints.push(copyPosition(position))
    }
  })
  const deduplicated = dedupeAdjacentPositions(replacementPoints)
  if (deduplicated.length < 2) {
    return null
  }
  const removedLengthM = endM - startM
  const replacementLengthM = distanceM(startPosition, endPosition)
  const lengthM = routeLengthM(deduplicated)
  return {
    points: deduplicated,
    lengthM,
    startStationM: startM,
    endStationM: endM,
    replacementStartStationM,
    replacementEndStationM,
    removedLengthM,
    replacementLengthM,
    stationDeltaM: lengthM - originalLengthM,
  }
}

export function stationAfterSectorReplacement(
  stationM: number,
  replacement: Pick<
    RouteSectorReplacement,
    | 'startStationM'
    | 'endStationM'
    | 'replacementStartStationM'
    | 'replacementEndStationM'
    | 'stationDeltaM'
  >,
) {
  if (stationM < replacement.startStationM) {
    return stationM
  }
  if (stationM > replacement.endStationM) {
    return stationM + replacement.stationDeltaM
  }
  const fraction = (stationM - replacement.startStationM) /
    (replacement.endStationM - replacement.startStationM)
  return replacement.replacementStartStationM +
    fraction * (replacement.replacementEndStationM - replacement.replacementStartStationM)
}

function distanceM(start: GeoPosition, end: GeoPosition) {
  const lon1 = toRadians(start[0])
  const lat1 = toRadians(start[1])
  const lon2 = toRadians(end[0])
  const lat2 = toRadians(end[1])
  const dLat = lat2 - lat1
  const dLon = lon2 - lon1
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return EARTH_RADIUS_M * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function dedupeAdjacentPositions(points: GeoPosition[]) {
  const out: GeoPosition[] = []
  points.forEach((position) => {
    const previous = out[out.length - 1]
    if (previous && Math.abs(previous[0] - position[0]) < 1e-12 && Math.abs(previous[1] - position[1]) < 1e-12) {
      return
    }
    out.push(copyPosition(position))
  })
  return out
}

function copyPosition(position: GeoPosition): GeoPosition {
  return Number.isFinite(position[2]) ? [position[0], position[1], position[2] as number] : [position[0], position[1]]
}

function toRadians(value: number) {
  return (value * Math.PI) / 180
}
