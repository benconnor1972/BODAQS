import type { GeoPosition } from './types'

const EARTH_RADIUS_M = 6371000

export type RouteGeometryDenoisingConfig = {
  enabled: boolean
  estimator: 'local_polynomial'
  windowM: number
  polynomialOrder: number
  fitWeighting: 'uniform' | 'tricube'
  robustIterations: number
  robustTuningConstant: number
}

export const DEFAULT_ROUTE_GEOMETRY_DENOISING: RouteGeometryDenoisingConfig = {
  enabled: true,
  estimator: 'local_polynomial',
  windowM: 20,
  polynomialOrder: 2,
  fitWeighting: 'tricube',
  robustIterations: 2,
  robustTuningConstant: 4.685,
}

export function denoiseRouteGeometry(
  points: GeoPosition[],
  overrides: Partial<RouteGeometryDenoisingConfig> = {},
): GeoPosition[] {
  const config = { ...DEFAULT_ROUTE_GEOMETRY_DENOISING, ...overrides }
  const source = dedupeAdjacentPositions(points)
  if (!config.enabled || source.length < 3 || config.windowM <= 0) {
    return source
  }

  const stations = routeStationsM(source)
  const latitudeRadians = source.map((position) => toRadians(position[1]))
  const longitudeRadians = source.map((position) => toRadians(position[0]))
  const latitudeOrigin = median(latitudeRadians)
  const longitudeOrigin = longitudeRadians[0]
  const latitudeStart = latitudeRadians[0]
  const longitudeScale = EARTH_RADIUS_M * Math.cos(latitudeOrigin)
  if (!Number.isFinite(longitudeScale) || Math.abs(longitudeScale) < 1e-9) {
    return source
  }
  const x = longitudeRadians.map((longitude) => (longitude - longitudeOrigin) * longitudeScale)
  const y = latitudeRadians.map((latitude) => (latitude - latitudeStart) * EARTH_RADIUS_M)
  const fittedX = new Array<number>(source.length)
  const fittedY = new Array<number>(source.length)
  const radiusM = config.windowM / 2
  const order = Math.max(1, Math.min(5, Math.trunc(config.polynomialOrder)))
  let left = 0
  let right = 0

  for (let index = 0; index < source.length; index += 1) {
    const centreM = stations[index]
    while (left < source.length && stations[left] < centreM - radiusM) {
      left += 1
    }
    right = Math.max(right, left)
    while (right < source.length && stations[right] <= centreM + radiusM) {
      right += 1
    }
    const offsets = stations.slice(left, right).map((stationM) => (stationM - centreM) / radiusM)
    const localX = x.slice(left, right)
    const localY = y.slice(left, right)
    const minimumPoints = order + 1
    if (offsets.length < minimumPoints) {
      fittedX[index] = x[index]
      fittedY[index] = y[index]
      continue
    }
    const baseWeights = offsets.map((offset) =>
      config.fitWeighting === 'tricube' ? (1 - Math.min(Math.abs(offset), 1) ** 3) ** 3 : 1,
    )
    const coefficients = robustLocalPolynomial(
      offsets,
      localX,
      localY,
      baseWeights,
      order,
      Math.max(0, Math.trunc(config.robustIterations)),
      config.robustTuningConstant,
    )
    fittedX[index] = coefficients?.x[0] ?? x[index]
    fittedY[index] = coefficients?.y[0] ?? y[index]
  }

  return source.map((position, index) => {
    const longitude = toDegrees((fittedX[index] / longitudeScale) + longitudeOrigin)
    const latitude = toDegrees((fittedY[index] / EARTH_RADIUS_M) + latitudeStart)
    return Number.isFinite(position[2]) ? [longitude, latitude, position[2] as number] : [longitude, latitude]
  })
}

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

function robustLocalPolynomial(
  offsets: number[],
  x: number[],
  y: number[],
  baseWeights: number[],
  order: number,
  robustIterations: number,
  robustTuningConstant: number,
) {
  let weights = [...baseWeights]
  let coefficientsX: number[] | null = null
  let coefficientsY: number[] | null = null
  for (let iteration = 0; iteration <= robustIterations; iteration += 1) {
    coefficientsX = weightedPolynomialFit(offsets, x, weights, order)
    coefficientsY = weightedPolynomialFit(offsets, y, weights, order)
    if (!coefficientsX || !coefficientsY || iteration === robustIterations) {
      break
    }
    const residualX = x.map((value, index) => value - evaluatePolynomial(coefficientsX as number[], offsets[index]))
    const residualY = y.map((value, index) => value - evaluatePolynomial(coefficientsY as number[], offsets[index]))
    const centreX = median(residualX)
    const centreY = median(residualY)
    const radialResiduals = residualX.map((value, index) =>
      Math.hypot(value - centreX, residualY[index] - centreY),
    )
    const scale = 1.4826 * median(radialResiduals)
    if (!Number.isFinite(scale) || scale <= 1e-9 || robustTuningConstant <= 0) {
      break
    }
    weights = baseWeights.map((weight, index) => {
      const scaledResidual = radialResiduals[index] / (robustTuningConstant * scale)
      const robustWeight = scaledResidual < 1 ? (1 - scaledResidual ** 2) ** 2 : 0
      return weight * robustWeight
    })
  }
  return coefficientsX && coefficientsY ? { x: coefficientsX, y: coefficientsY } : null
}

function weightedPolynomialFit(
  offsets: number[],
  values: number[],
  weights: number[],
  order: number,
): number[] | null {
  const size = order + 1
  const matrix = Array.from({ length: size }, () => new Array<number>(size).fill(0))
  const vector = new Array<number>(size).fill(0)
  let positiveWeightCount = 0
  for (let row = 0; row < offsets.length; row += 1) {
    const weight = weights[row]
    if (!Number.isFinite(weight) || weight <= 0 || !Number.isFinite(values[row])) {
      continue
    }
    positiveWeightCount += 1
    const powers = new Array<number>((2 * order) + 1).fill(1)
    for (let power = 1; power < powers.length; power += 1) {
      powers[power] = powers[power - 1] * offsets[row]
    }
    for (let column = 0; column < size; column += 1) {
      vector[column] += weight * values[row] * powers[column]
      for (let other = 0; other < size; other += 1) {
        matrix[column][other] += weight * powers[column + other]
      }
    }
  }
  return positiveWeightCount >= size ? solveLinearSystem(matrix, vector) : null
}

function solveLinearSystem(matrix: number[][], vector: number[]): number[] | null {
  const size = vector.length
  const augmented = matrix.map((row, index) => [...row, vector[index]])
  for (let column = 0; column < size; column += 1) {
    let pivot = column
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(augmented[row][column]) > Math.abs(augmented[pivot][column])) {
        pivot = row
      }
    }
    if (!Number.isFinite(augmented[pivot][column]) || Math.abs(augmented[pivot][column]) <= 1e-12) {
      return null
    }
    ;[augmented[column], augmented[pivot]] = [augmented[pivot], augmented[column]]
    const divisor = augmented[column][column]
    for (let entry = column; entry <= size; entry += 1) {
      augmented[column][entry] /= divisor
    }
    for (let row = 0; row < size; row += 1) {
      if (row === column) {
        continue
      }
      const factor = augmented[row][column]
      for (let entry = column; entry <= size; entry += 1) {
        augmented[row][entry] -= factor * augmented[column][entry]
      }
    }
  }
  const result = augmented.map((row) => row[size])
  return result.every(Number.isFinite) ? result : null
}

function evaluatePolynomial(coefficients: number[], value: number) {
  return coefficients.reduceRight((total, coefficient) => (total * value) + coefficient, 0)
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

function median(values: number[]) {
  if (values.length === 0) {
    return Number.NaN
  }
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
}

function toRadians(value: number) {
  return (value * Math.PI) / 180
}

function toDegrees(value: number) {
  return (value * 180) / Math.PI
}
