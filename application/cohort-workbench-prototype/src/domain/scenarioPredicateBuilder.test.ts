import { describe, expect, it } from 'vitest'
import { defaultScenarioCondition, scenarioBuilderFromPredicate, scenarioPredicateFromBuilder } from './scenarioPredicateBuilder'
import type { ScenarioPredicate } from './types'

describe('semantic scenario predicates', () => {
  it('round trips mixed explicit and semantic criteria, ranges and extra metadata', () => {
    const predicate: ScenarioPredicate = { op: 'or', children: [
      { criterionId: 'speed', series: { streamName: 'gps_logger', column: 'speed_mps' }, op: 'gt', value: 3 },
      { criterionId: 'wheel', series: { streamName: 'primary', selector: { domain: 'wheel', quantity: 'disp_norm', end: 'rear', unit: '1', control: 'custom' } }, op: 'between', range: { lower: 0.5, upper: 1, includeLower: false, includeUpper: true } },
    ] }
    const original = structuredClone(predicate)
    const builder = scenarioBuilderFromPredicate(predicate)!
    expect(builder.conditions[1].seriesKey).toBe('meaning')
    expect(scenarioPredicateFromBuilder(builder)).toEqual(predicate)
    expect(predicate).toEqual(original)
  })

  it('requires a nonempty meaning and serializes no concrete column', () => {
    const condition = { ...defaultScenarioCondition(1), seriesKey: 'meaning', selector: {} }
    expect(() => scenarioPredicateFromBuilder({ join: 'and', conditions: [condition] })).toThrow(/meaning attribute/)
    const result = scenarioPredicateFromBuilder({ join: 'and', conditions: [{ ...condition, selector: { domain: 'wheel', end: 'rear' } }] })
    expect(result).toMatchObject({ series: { selector: { domain: 'wheel', end: 'rear' } } })
    expect('children' in result ? result : result.series).not.toHaveProperty('column')
  })

  it('leaves unsupported selector formats and categorical operators in Advanced JSON', () => {
    expect(scenarioBuilderFromPredicate({ criterionId: 'a', series: { streamName: 'primary', selector: { flag: true } }, op: 'gt', value: 1 })).toBeNull()
    expect(scenarioBuilderFromPredicate({ criterionId: 'a', series: { streamName: 'primary', selector: { kind: 'qc' } }, op: 'present' })).toBeNull()
  })
})
