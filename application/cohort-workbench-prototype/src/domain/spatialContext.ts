import type { SpatialContextWindowResponse } from './types'

export function spatialDistanceAxis(distances: Array<number | null>) {
  const maximumDistance = Math.max(
    0,
    ...distances.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)),
  )
  const step = distanceGridStep(maximumDistance)
  const max = Math.max(step * 4, Math.ceil(maximumDistance / step) * step)
  return { min: 0, max, step, ticks: gridTicks(0, max, step) }
}

export function nearestSpatialDistance(distances: Array<number | null>, target: number) {
  let nearest: number | null = null
  let nearestDelta = Number.POSITIVE_INFINITY
  distances.forEach((distance) => {
    if (typeof distance !== 'number' || !Number.isFinite(distance)) return
    const delta = Math.abs(distance - target)
    if (delta < nearestDelta) {
      nearest = distance
      nearestDelta = delta
    }
  })
  return nearest
}

export function spatialDistanceForTime(data: SpatialContextWindowResponse, timeS: number) {
  const times = data.timeMapping.values
  const distances = data.distance.values
  for (let index = 1; index < times.length; index += 1) {
    const before = times[index - 1]
    const after = times[index]
    const beforeDistance = distances[index - 1]
    const afterDistance = distances[index]
    if (
      typeof before !== 'number' ||
      typeof after !== 'number' ||
      typeof beforeDistance !== 'number' ||
      typeof afterDistance !== 'number' ||
      after <= before ||
      timeS < before ||
      timeS > after
    ) continue
    const fraction = (timeS - before) / (after - before)
    return beforeDistance + fraction * (afterDistance - beforeDistance)
  }
  return null
}

export function spatialTimeAtDistance(data: SpatialContextWindowResponse, distanceM: number) {
  let nearestIndex = -1
  let nearestDelta = Number.POSITIVE_INFINITY
  data.distance.values.forEach((distance, index) => {
    if (typeof distance !== 'number' || !Number.isFinite(distance)) return
    const delta = Math.abs(distance - distanceM)
    if (delta < nearestDelta) {
      nearestIndex = index
      nearestDelta = delta
    }
  })
  const timeS = data.timeMapping.values[nearestIndex]
  return typeof timeS === 'number' && Number.isFinite(timeS) ? timeS : null
}

function distanceGridStep(span: number) {
  const candidates = [100, 200, 500, 1000, 2000]
  return [...candidates].reverse().find((candidate) => span / candidate >= 3) ?? candidates[0]
}

function gridTicks(minimum: number, maximum: number, step: number) {
  const ticks: number[] = []
  const start = Math.ceil(minimum / step) * step
  for (let value = start; value <= maximum + step * 0.001; value += step) {
    ticks.push(Math.round(value * 1e9) / 1e9)
  }
  return ticks
}
