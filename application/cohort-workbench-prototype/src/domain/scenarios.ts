import type { ScenarioCriterion, ScenarioPredicate, ScenarioRecord } from './types'

const GROUP_OPERATORS = new Set(['and', 'or'])
const NUMERIC_OPERATORS = new Set(['lt', 'lte', 'gt', 'gte'])
const RANGE_OPERATORS = new Set(['between', 'outside'])
const VALUE_OPERATORS = new Set(['eq', 'in'])
const MAX_CRITERIA = 4

export function emptyScenario(): ScenarioRecord {
  return {
    displayName: '',
    description: '',
    category: '',
    predicate: {
      criterionId: 'criterion-1',
      series: { streamName: 'spatial_context', column: 'twistiness_rad_per_m' },
      op: 'gte',
      value: 0.04,
    },
    episodePolicy: {
      minimumDurationS: 0,
      minimumDistanceM: null,
      bridgeGapS: 0,
      bridgeGapM: null,
    },
    eligibilityPolicy: { activity: 'require_active' },
  }
}

export function cloneScenario(scenario: ScenarioRecord): ScenarioRecord {
  return structuredClone(scenario)
}

export function scratchScenario(scenario: ScenarioRecord): ScenarioRecord {
  const copy = cloneScenario(scenario)
  delete copy.id
  delete copy.revision
  delete copy.provenance
  return copy
}

export function scenarioDefinitionJson(scenario: ScenarioRecord) {
  return JSON.stringify({
    predicate: predicateToJson(scenario.predicate),
    episode_policy: {
      minimum_duration_s: scenario.episodePolicy.minimumDurationS,
      minimum_distance_m: scenario.episodePolicy.minimumDistanceM,
      bridge_gap_s: scenario.episodePolicy.bridgeGapS,
      bridge_gap_m: scenario.episodePolicy.bridgeGapM,
    },
    eligibility_policy: { activity: scenario.eligibilityPolicy.activity },
  }, null, 2)
}

export function scenarioFromDefinitionJson(
  text: string,
  metadata: Pick<ScenarioRecord, 'displayName' | 'description' | 'category'>,
  previous?: ScenarioRecord,
): ScenarioRecord {
  const value = JSON.parse(text) as unknown
  const root = objectValue(value, 'Scenario definition')
  const seenCriteria = new Set<string>()
  const criterionCount = { value: 0 }
  const predicate = predicateFromJson(root.predicate, 'predicate', seenCriteria, criterionCount)
  if (criterionCount.value > MAX_CRITERIA) {
    throw new Error(`A Scenario may contain at most ${MAX_CRITERIA} criteria.`)
  }
  const episode = optionalObjectValue(root.episode_policy, 'episode_policy')
  const eligibility = optionalObjectValue(root.eligibility_policy, 'eligibility_policy')
  const activity = eligibility.activity === undefined ? 'require_active' : requiredText(eligibility.activity, 'eligibility_policy.activity')
  if (activity !== 'require_active' && activity !== 'ignore') {
    throw new Error('eligibility_policy.activity must be "require_active" or "ignore".')
  }
  return {
    ...(previous ?? {}),
    displayName: requiredText(metadata.displayName, 'Name'),
    description: metadata.description.trim(),
    category: metadata.category.trim(),
    predicate,
    episodePolicy: {
      minimumDurationS: optionalNonNegativeNumber(episode.minimum_duration_s, 'episode_policy.minimum_duration_s', 0) as number,
      minimumDistanceM: optionalNonNegativeNumber(episode.minimum_distance_m, 'episode_policy.minimum_distance_m', null),
      bridgeGapS: optionalNonNegativeNumber(episode.bridge_gap_s, 'episode_policy.bridge_gap_s', 0) as number,
      bridgeGapM: optionalNonNegativeNumber(episode.bridge_gap_m, 'episode_policy.bridge_gap_m', null),
    },
    eligibilityPolicy: { activity },
  }
}

function predicateToJson(predicate: ScenarioPredicate): Record<string, unknown> {
  if ('children' in predicate) {
    return { op: predicate.op, children: predicate.children.map(predicateToJson) }
  }
  return {
    criterion_id: predicate.criterionId,
    series: {
      stream_name: predicate.series.streamName,
      ...(predicate.series.column ? { column: predicate.series.column } : {}),
      ...(predicate.series.selector ? { selector: predicate.series.selector } : {}),
    },
    op: predicate.op,
    ...(predicate.value !== undefined ? { value: predicate.value } : {}),
    ...(predicate.range
      ? {
          range: {
            lower: predicate.range.lower,
            upper: predicate.range.upper,
            include_lower: predicate.range.includeLower,
            include_upper: predicate.range.includeUpper,
          },
        }
      : {}),
  }
}

function predicateFromJson(
  value: unknown,
  path: string,
  seenCriteria: Set<string>,
  criterionCount: { value: number },
): ScenarioPredicate {
  const item = objectValue(value, path)
  const op = requiredText(item.op, `${path}.op`)
  if (GROUP_OPERATORS.has(op)) {
    if (!Array.isArray(item.children) || item.children.length === 0) {
      throw new Error(`${path}.children must be a non-empty array.`)
    }
    return {
      op: op as 'and' | 'or',
      children: item.children.map((child, index) => predicateFromJson(child, `${path}.children[${index}]`, seenCriteria, criterionCount)),
    }
  }
  const supported = NUMERIC_OPERATORS.has(op) || RANGE_OPERATORS.has(op) || VALUE_OPERATORS.has(op) || op === 'present'
  if (!supported) {
    throw new Error(`${path}.op is not supported.`)
  }
  const criterionId = requiredText(item.criterion_id, `${path}.criterion_id`)
  if (seenCriteria.has(criterionId)) {
    throw new Error(`criterion_id "${criterionId}" is duplicated.`)
  }
  seenCriteria.add(criterionId)
  criterionCount.value += 1
  const seriesValue = objectValue(item.series, `${path}.series`)
  const streamName = requiredText(seriesValue.stream_name, `${path}.series.stream_name`)
  const column = optionalText(seriesValue.column)
  const selector = isObject(seriesValue.selector) && Object.keys(seriesValue.selector).length > 0 ? { ...seriesValue.selector } : undefined
  if (Boolean(column) === Boolean(selector)) {
    throw new Error(`${path}.series must specify exactly one of column or selector.`)
  }
  const criterion: ScenarioCriterion = {
    criterionId,
    series: { streamName, ...(column ? { column } : {}), ...(selector ? { selector } : {}) },
    op: op as ScenarioCriterion['op'],
  }
  if (RANGE_OPERATORS.has(op)) {
    const range = objectValue(item.range, `${path}.range`)
    const lower = finiteNumber(range.lower, `${path}.range.lower`)
    const upper = finiteNumber(range.upper, `${path}.range.upper`)
    if (lower > upper) {
      throw new Error(`${path}.range.lower must not exceed range.upper.`)
    }
    criterion.range = {
      lower,
      upper,
      includeLower: range.include_lower !== false,
      includeUpper: range.include_upper !== false,
    }
  } else if (op !== 'present') {
    if (!('value' in item)) {
      throw new Error(`${path}.value is required.`)
    }
    if (NUMERIC_OPERATORS.has(op)) {
      criterion.value = finiteNumber(item.value, `${path}.value`)
    } else if (op === 'in') {
      if (!Array.isArray(item.value)) {
        throw new Error(`${path}.value must be an array for "in".`)
      }
      criterion.value = item.value
    } else {
      criterion.value = item.value
    }
  }
  return criterion
}

function optionalNonNegativeNumber(value: unknown, path: string, fallback: number | null) {
  if (value === undefined) {
    return fallback
  }
  if (value === null) {
    if (fallback === null) {
      return null
    }
    throw new Error(`${path} must be a finite non-negative number.`)
  }
  const number = finiteNumber(value, path)
  if (number < 0) {
    throw new Error(`${path} must be non-negative.`)
  }
  return number
}

function finiteNumber(value: unknown, path: string) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number.`)
  }
  return value
}

function requiredText(value: unknown, path: string) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${path} is required.`)
  }
  return value.trim()
}

function optionalText(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function objectValue(value: unknown, path: string): Record<string, unknown> {
  if (!isObject(value)) {
    throw new Error(`${path} must be a JSON object.`)
  }
  return value
}

function optionalObjectValue(value: unknown, path: string): Record<string, unknown> {
  return value === undefined ? {} : objectValue(value, path)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
