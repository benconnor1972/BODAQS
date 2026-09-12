import type { ScenarioCriterion, ScenarioPredicate } from './types'

export const MAX_SCENARIO_CRITERIA = 4

export type ScenarioNumericOperator = 'lt' | 'lte' | 'gt' | 'gte' | 'between' | 'outside'
export type ScenarioBuilderJoin = 'and' | 'or'

export type ScenarioSeriesDefinition = {
  key: string
  label: string
  streamName: string
  column: string
  unit: string
  defaultValue: number
}

export type ScenarioBuilderCondition = {
  editorId: string
  criterionId: string
  seriesKey: string
  streamName: string
  column: string
  op: ScenarioNumericOperator
  value: string
  lower: string
  upper: string
  includeLower: boolean
  includeUpper: boolean
}

export type ScenarioPredicateBuilderState = {
  join: ScenarioBuilderJoin
  conditions: ScenarioBuilderCondition[]
}

export const scenarioSeriesDefinitions: ScenarioSeriesDefinition[] = [
  { key: 'altitude', label: 'Altitude', streamName: 'spatial_context', column: 'altitude_m', unit: 'm', defaultValue: 100 },
  { key: 'gradient', label: 'Gradient', streamName: 'spatial_context', column: 'gradient_fraction', unit: 'fraction', defaultValue: -0.1 },
  { key: 'twistiness', label: 'Twistiness', streamName: 'spatial_context', column: 'twistiness_rad_per_m', unit: 'rad/m', defaultValue: 0.04 },
  { key: 'front_activity', label: 'Front suspension activity', streamName: 'spatial_context', column: 'front_suspension_activity', unit: 'm/m', defaultValue: 0.02 },
  { key: 'rear_activity', label: 'Rear suspension activity', streamName: 'spatial_context', column: 'rear_suspension_activity', unit: 'm/m', defaultValue: 0.02 },
  { key: 'combined_activity', label: 'Combined suspension activity', streamName: 'spatial_context', column: 'combined_suspension_activity', unit: 'm/m', defaultValue: 0.02 },
  { key: 'gps_speed', label: 'GPS speed', streamName: 'gps_logger', column: 'speed_mps', unit: 'm/s', defaultValue: 2 },
]

export const scenarioOperatorLabels: Record<ScenarioNumericOperator, string> = {
  lt: 'Less than',
  lte: 'At most',
  gt: 'Greater than',
  gte: 'At least',
  between: 'Between',
  outside: 'Outside',
}

let nextEditorIdValue = 1

export function scenarioBuilderFromPredicate(predicate: ScenarioPredicate): ScenarioPredicateBuilderState | null {
  const leaves = 'children' in predicate ? predicate.children : [predicate]
  if ('children' in predicate && leaves.some((child) => 'children' in child)) return null
  const conditions = leaves.map((leaf) => conditionFromCriterion(leaf as ScenarioCriterion))
  if (conditions.some((condition) => condition === null) || conditions.length === 0 || conditions.length > MAX_SCENARIO_CRITERIA) return null
  return {
    join: 'children' in predicate ? predicate.op : 'and',
    conditions: conditions as ScenarioBuilderCondition[],
  }
}

export function scenarioPredicateFromBuilder(builder: ScenarioPredicateBuilderState): ScenarioPredicate {
  if (builder.conditions.length === 0 || builder.conditions.length > MAX_SCENARIO_CRITERIA) {
    throw new Error('A Scenario must contain between one and four criteria.')
  }
  const ids = new Set<string>()
  const children = builder.conditions.map((condition, index): ScenarioCriterion => {
    const criterionId = condition.criterionId.trim() || `criterion-${index + 1}`
    const uniqueId = ids.has(criterionId) ? `${criterionId}-${index + 1}` : criterionId
    ids.add(uniqueId)
    if (!condition.streamName.trim() || !condition.column.trim()) throw new Error(`Criterion ${index + 1} requires a stream and column.`)
    const criterion: ScenarioCriterion = {
      criterionId: uniqueId,
      series: { streamName: condition.streamName.trim(), column: condition.column.trim() },
      op: condition.op,
    }
    if (condition.op === 'between' || condition.op === 'outside') {
      const lower = finiteInput(condition.lower, `Criterion ${index + 1} lower bound`)
      const upper = finiteInput(condition.upper, `Criterion ${index + 1} upper bound`)
      if (lower > upper) throw new Error(`Criterion ${index + 1} lower bound must not exceed its upper bound.`)
      criterion.range = { lower, upper, includeLower: condition.includeLower, includeUpper: condition.includeUpper }
    } else {
      criterion.value = finiteInput(condition.value, `Criterion ${index + 1} value`)
    }
    return criterion
  })
  return children.length === 1 ? children[0] : { op: builder.join, children }
}

export function defaultScenarioCondition(index: number): ScenarioBuilderCondition {
  const definition = scenarioSeriesDefinitions[2]
  return {
    editorId: nextEditorId(),
    criterionId: `criterion-${index}`,
    seriesKey: definition.key,
    streamName: definition.streamName,
    column: definition.column,
    op: 'gte',
    value: String(definition.defaultValue),
    lower: '0',
    upper: String(definition.defaultValue),
    includeLower: true,
    includeUpper: true,
  }
}

function conditionFromCriterion(criterion: ScenarioCriterion): ScenarioBuilderCondition | null {
  if (!criterion.series.column || criterion.series.selector) return null
  if (!['lt', 'lte', 'gt', 'gte', 'between', 'outside'].includes(criterion.op)) return null
  const definition = scenarioSeriesDefinitions.find((item) => item.streamName === criterion.series.streamName && item.column === criterion.series.column)
  return {
    editorId: nextEditorId(),
    criterionId: criterion.criterionId,
    seriesKey: definition?.key ?? 'custom',
    streamName: criterion.series.streamName,
    column: criterion.series.column,
    op: criterion.op as ScenarioNumericOperator,
    value: String(criterion.value ?? definition?.defaultValue ?? 0),
    lower: String(criterion.range?.lower ?? 0),
    upper: String(criterion.range?.upper ?? 1),
    includeLower: criterion.range?.includeLower ?? true,
    includeUpper: criterion.range?.includeUpper ?? true,
  }
}

function finiteInput(value: string, label: string) {
  const number = Number(value)
  if (!value.trim() || !Number.isFinite(number)) throw new Error(`${label} must be a finite number.`)
  return number
}

function nextEditorId() {
  return `scenario-condition-${nextEditorIdValue++}`
}
